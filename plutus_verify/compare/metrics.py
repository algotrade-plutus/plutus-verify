"""Metric comparison: locate the actual value, apply tolerance, emit verdict."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

from plutus_verify.compare.llm_match import (
    MetricMatchClient,
    MetricMatchRequest,
    eyeball_metrics,
)
from plutus_verify.extract.plan import ExpectedMetric, Locate, Tolerance


@dataclass(frozen=True)
class MetricSources:
    """The artifacts produced by a completed step, available for metric lookup."""

    stdout: str
    file_root: Path


@dataclass(frozen=True)
class MetricComparison:
    name: str
    expected: float
    actual: Optional[float]
    tolerance: Tolerance
    pass_: bool
    unverifiable_reason: Optional[str] = None


# ---------- tolerance engine ----------


def within_tolerance(expected, actual, tol: Tolerance) -> bool:
    # Categorical values (e.g., "equal" for stock_weight_option) only work
    # with kind="exact"; numeric tolerance against a string is meaningless.
    if isinstance(expected, str) or isinstance(actual, str):
        if tol.kind == "exact":
            return str(actual).strip() == str(expected).strip()
        return False
    delta = abs(actual - expected)
    if tol.kind == "exact":
        # IEEE 754: 0.475 != 0.47500000000000003 even though both came from the
        # same decimal source. For "exact" we accept tiny float drift; integers
        # still compare cleanly because relative tolerance of 0 catches them.
        import math
        return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
    if tol.kind == "absolute":
        return delta <= tol.value
    if tol.kind == "relative":
        if expected == 0:
            # divide-by-zero: degrade to absolute with the same value
            return delta <= tol.value if actual == 0 else False
        return delta / abs(expected) <= tol.value
    raise ValueError(f"unknown tolerance kind: {tol.kind}")


# ---------- locate dispatch ----------


def compare_step_metrics(
    metrics: list[ExpectedMetric],
    sources: MetricSources,
    *,
    match_client: Optional[MetricMatchClient] = None,
) -> list[MetricComparison]:
    """Compare a step's metrics, batching LLM-eyeballing into one call.

    Two passes:
      1. Deterministic locate per metric. Anything that succeeds is final.
      2. For stdout-based metrics that failed step 1, ONE LLM call with all of
         them packed together (saves re-sending the full stdout per metric).
    """
    results: list[Optional[MetricComparison]] = []
    llm_pending: list[ExpectedMetric] = []
    llm_pending_idx: list[int] = []
    llm_pending_locate_errors: list[str] = []

    for i, m in enumerate(metrics):
        try:
            actual = _locate(m.locate, sources)
            results.append(
                MetricComparison(
                    name=m.name,
                    expected=m.value,
                    actual=actual,
                    tolerance=m.tolerance,
                    pass_=within_tolerance(m.value, actual, m.tolerance),
                )
            )
        except _LocateError as exc:
            results.append(None)  # placeholder
            if match_client is not None and m.locate.kind == "stdout_table":
                llm_pending.append(m)
                llm_pending_idx.append(i)
                llm_pending_locate_errors.append(str(exc))
            else:
                results[i] = MetricComparison(
                    name=m.name,
                    expected=m.value,
                    actual=None,
                    tolerance=m.tolerance,
                    pass_=False,
                    unverifiable_reason=str(exc),
                )

    if llm_pending:
        requests = [
            MetricMatchRequest(name=m.name, expected_approx=m.value) for m in llm_pending
        ]
        try:
            llm_actuals = eyeball_metrics(
                metrics=requests, stdout=sources.stdout, client=match_client
            )
        except Exception as exc:
            llm_actuals = {m.name: None for m in llm_pending}
            # All LLM-pending entries get unverifiable; record the failure
            for j, (m, locate_err) in enumerate(zip(llm_pending, llm_pending_locate_errors)):
                results[llm_pending_idx[j]] = MetricComparison(
                    name=m.name,
                    expected=m.value,
                    actual=None,
                    tolerance=m.tolerance,
                    pass_=False,
                    unverifiable_reason=(
                        f"deterministic locate failed ({locate_err}); "
                        f"LLM eyeball errored: {exc}"
                    ),
                )
            return [r for r in results]  # type: ignore[return-value]

        for j, m in enumerate(llm_pending):
            actual = llm_actuals.get(m.name)
            idx = llm_pending_idx[j]
            if actual is None:
                results[idx] = MetricComparison(
                    name=m.name,
                    expected=m.value,
                    actual=None,
                    tolerance=m.tolerance,
                    pass_=False,
                    unverifiable_reason=(
                        f"deterministic locate failed ({llm_pending_locate_errors[j]}); "
                        "LLM eyeball also returned no value"
                    ),
                )
            else:
                results[idx] = MetricComparison(
                    name=m.name,
                    expected=m.value,
                    actual=actual,
                    tolerance=m.tolerance,
                    pass_=within_tolerance(m.value, actual, m.tolerance),
                )

    return [r for r in results]  # type: ignore[return-value]


def compare_metric(
    expected: ExpectedMetric,
    sources: MetricSources,
    *,
    match_client: Optional[MetricMatchClient] = None,
) -> MetricComparison:
    """Locate the value produced at runtime and compare to the expected value.

    Tries the deterministic ``locate`` directive first. If that fails AND a
    ``match_client`` is provided, falls back to LLM-eyeballing on the stdout —
    useful when the README's claimed format differs from what the script
    actually emits (markdown table vs free text). The LLM is a smart parser;
    the tolerance check still runs deterministically.
    """
    try:
        actual = _locate(expected.locate, sources)
    except _LocateError as exc:
        # Fall back to LLM-eyeballing if available AND we're looking in stdout.
        # (json_file / file_regex failures are not about format drift — the
        # file is structured; if we can't find it, the LLM won't either.)
        if match_client is not None and expected.locate.kind == "stdout_table":
            llm_actuals = eyeball_metrics(
                metrics=[MetricMatchRequest(name=expected.name, expected_approx=expected.value)],
                stdout=sources.stdout,
                client=match_client,
            )
            actual = llm_actuals.get(expected.name)
            if actual is None:
                return MetricComparison(
                    name=expected.name,
                    expected=expected.value,
                    actual=None,
                    tolerance=expected.tolerance,
                    pass_=False,
                    unverifiable_reason=(
                        f"deterministic locate failed ({exc}); "
                        "LLM eyeball also returned no value"
                    ),
                )
            return MetricComparison(
                name=expected.name,
                expected=expected.value,
                actual=actual,
                tolerance=expected.tolerance,
                pass_=within_tolerance(expected.value, actual, expected.tolerance),
            )
        return MetricComparison(
            name=expected.name,
            expected=expected.value,
            actual=None,
            tolerance=expected.tolerance,
            pass_=False,
            unverifiable_reason=str(exc),
        )

    return MetricComparison(
        name=expected.name,
        expected=expected.value,
        actual=actual,
        tolerance=expected.tolerance,
        pass_=within_tolerance(expected.value, actual, expected.tolerance),
    )


class _LocateError(RuntimeError):
    pass


def _locate(loc: Locate, sources: MetricSources) -> float:
    if loc.kind == "stdout_table":
        return _locate_stdout_table(loc, sources.stdout)
    if loc.kind == "json_file":
        return _locate_json_file(loc, sources.file_root)
    if loc.kind == "file_regex":
        return _locate_file_regex(loc, sources.file_root)
    raise _LocateError(f"unknown locate kind: {loc.kind}")


# ---------- stdout_table ----------


_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


def _split_table_row(line: str) -> Optional[list[str]]:
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return None
    return [cell.strip() for cell in m.group(1).split("|")]


def _locate_stdout_table(loc: Locate, stdout: str) -> float:
    if loc.row is None or loc.col is None:
        raise _LocateError("stdout_table locate requires both 'row' and 'col'")
    target = loc.row.strip().casefold()
    for line in stdout.splitlines():
        cells = _split_table_row(line)
        if not cells:
            continue
        if cells[0].casefold().startswith(target):
            if loc.col >= len(cells):
                raise _LocateError(f"col {loc.col} out of range for row '{loc.row}'")
            raw = cells[loc.col]
            try:
                return float(raw)
            except ValueError as exc:
                raise _LocateError(
                    f"cell at row '{loc.row}' col {loc.col} not numeric: {raw!r}"
                ) from exc
    raise _LocateError(f"row '{loc.row}' not found in stdout table")


# ---------- json_file ----------


def _locate_json_file(loc: Locate, root: Path) -> "float | str":
    if not loc.path or not loc.jsonpath:
        raise _LocateError("json_file locate requires 'path' and 'jsonpath'")
    p = root / loc.path
    if not p.exists():
        raise _LocateError(f"file not found: {loc.path}")
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise _LocateError(f"invalid JSON in {loc.path}: {exc.msg}") from exc
    try:
        expr = jsonpath_parse(loc.jsonpath)
    except JsonPathParserError as exc:
        raise _LocateError(f"invalid jsonpath {loc.jsonpath!r}: {exc}") from exc
    matches = expr.find(data)
    if not matches:
        raise _LocateError(f"jsonpath {loc.jsonpath!r} matched nothing in {loc.path}")
    val = matches[0].value
    # Numeric values get returned as float for tolerance math. Strings pass
    # through verbatim — Plutus repos occasionally use categorical params
    # (e.g., "stock_weight_option": "equal") that should compare with exact
    # tolerance, not as numbers.
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, str):
        return val
    raise _LocateError(f"value at {loc.jsonpath} has unsupported type {type(val).__name__}: {val!r}")


# ---------- file_regex ----------


def _locate_file_regex(loc: Locate, root: Path) -> float:
    if not loc.path or not loc.pattern:
        raise _LocateError("file_regex locate requires 'path' and 'pattern'")
    p = root / loc.path
    if not p.exists():
        raise _LocateError(f"file not found: {loc.path}")
    try:
        rx = re.compile(loc.pattern)
    except re.error as exc:
        raise _LocateError(f"invalid regex: {exc}") from exc
    m = rx.search(p.read_text())
    if not m:
        raise _LocateError(f"regex did not match in {loc.path}")
    try:
        raw = m.group("value")
    except IndexError as exc:
        raise _LocateError("regex must contain a (?P<value>...) named group") from exc
    try:
        return float(raw)
    except ValueError as exc:
        raise _LocateError(f"matched value {raw!r} is not numeric") from exc

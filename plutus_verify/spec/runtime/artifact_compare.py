"""Comparators for v2 expected artifacts.

Three kinds, each dispatched on ``Artifact.compare``:
  - json_numeric_tolerance: deep-walk JSON; numeric values within relative
    tolerance (default 5%); non-numeric must be byte-equal.
  - byte_exact: file bytes identical.
  - visual_similarity: delegates to existing chart-similarity vision client.

Existence semantics differ by kind. ``byte_exact`` and
``json_numeric_tolerance`` are deterministic — a missing reference file
is a real failure. ``visual_similarity`` is opt-in along two axes
(snapshot existence and vision-client wiring); missing either is a
non-blocking skip surfaced through ``CompareResult.skipped``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

from plutus_verify.util.json_io import load_json

from plutus_verify.spec.manifest import Artifact

DEFAULT_RELATIVE_TOLERANCE = 0.05


@dataclass(frozen=True)
class CompareResult:
    ok: bool
    kind: str
    detail: str = ""
    path: str = ""
    skipped: bool = False


def compare_artifact(
    ref: Artifact,
    *,
    expected_path: Path,
    produced_path: Path,
    vision_client: Optional[Any],
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> CompareResult:
    if ref.compare == "byte_exact":
        result = _byte_exact(expected_path, produced_path)
    elif ref.compare == "json_numeric_tolerance":
        result = _json_numeric(expected_path, produced_path, relative_tolerance)
    elif ref.compare == "visual_similarity":
        result = _visual_similarity(ref, expected_path, produced_path, vision_client)
    else:
        result = CompareResult(ok=False, kind=ref.compare, detail=f"unknown compare kind: {ref.compare}")
    return replace(result, path=ref.path)


def _byte_exact(expected: Path, produced: Path) -> CompareResult:
    if not expected.exists():
        return CompareResult(ok=False, kind="byte_exact", detail=f"expected file not found: {expected}")
    if not produced.exists():
        return CompareResult(ok=False, kind="byte_exact", detail=f"produced file not found: {produced}")
    if expected.read_bytes() == produced.read_bytes():
        return CompareResult(ok=True, kind="byte_exact")
    return CompareResult(ok=False, kind="byte_exact", detail=f"bytes differ ({expected.name} vs {produced.name})")


def _json_numeric(expected: Path, produced: Path, tol: float) -> CompareResult:
    if not expected.exists():
        return CompareResult(ok=False, kind="json_numeric_tolerance", detail=f"expected file not found: {expected}")
    if not produced.exists():
        return CompareResult(ok=False, kind="json_numeric_tolerance", detail=f"produced file not found: {produced}")
    try:
        exp = load_json(expected)
        prod = load_json(produced)
    except json.JSONDecodeError as e:
        return CompareResult(ok=False, kind="json_numeric_tolerance", detail=f"invalid JSON: {e}")
    diffs: list[str] = []
    _walk(exp, prod, "", tol, diffs)
    if diffs:
        return CompareResult(
            ok=False, kind="json_numeric_tolerance", detail="; ".join(diffs[:5])
        )
    return CompareResult(ok=True, kind="json_numeric_tolerance")


def _walk(exp: Any, prod: Any, path: str, tol: float, diffs: list[str]) -> None:
    if isinstance(exp, dict) and isinstance(prod, dict):
        for k in exp:
            sub = f"{path}.{k}" if path else k
            if k not in prod:
                diffs.append(f"missing key {sub}")
                continue
            _walk(exp[k], prod[k], sub, tol, diffs)
        return
    if isinstance(exp, list) and isinstance(prod, list):
        if len(exp) != len(prod):
            diffs.append(f"{path} length {len(prod)} != expected {len(exp)}")
            return
        for i, (e, p) in enumerate(zip(exp, prod)):
            _walk(e, p, f"{path}[{i}]", tol, diffs)
        return
    if isinstance(exp, bool) or isinstance(prod, bool):
        if exp != prod:
            diffs.append(f"{path}: {prod!r} != {exp!r}")
        return
    if isinstance(exp, (int, float)) and isinstance(prod, (int, float)):
        if exp == 0:
            if abs(prod) > tol:
                diffs.append(f"{path}: {prod} not within ±{tol} of 0")
            return
        if abs(prod - exp) / abs(exp) > tol:
            diffs.append(f"{path}: {prod} not within ±{tol * 100:.0f}% of {exp}")
        return
    if exp != prod:
        diffs.append(f"{path}: {prod!r} != {exp!r}")


def _visual_similarity(
    ref: Artifact,
    expected: Path,
    produced: Path,
    vision_client: Optional[Any],
) -> CompareResult:
    # Visual checks are opt-in along two axes: a reference image must
    # exist (`plutus snapshot`) AND a vision client must be configured
    # (`--visual-check`). Missing either is a non-blocking skip, not a
    # failure — symmetric to keep the contract from 0.2.5 consistent.
    if not expected.exists():
        return CompareResult(
            ok=True,
            kind="visual_similarity",
            skipped=True,
            detail=f"skipped (no reference at {expected}; run `plutus snapshot` to enable)",
        )
    if not produced.exists():
        return CompareResult(
            ok=False,
            kind="visual_similarity",
            detail=f"produced file not found: {produced}",
        )
    if vision_client is None:
        return CompareResult(
            ok=True,
            kind="visual_similarity",
            skipped=True,
            detail="skipped (no vision client configured; pass --visual-check to enable)",
        )
    threshold = ref.threshold or 0.7
    try:
        match = vision_client.match(
            reference_image_path=expected,
            produced_image_path=produced,
            threshold=threshold,
        )
    except Exception as exc:  # noqa: BLE001
        return CompareResult(ok=False, kind="visual_similarity", detail=str(exc))
    if getattr(match, "match", False):
        return CompareResult(ok=True, kind="visual_similarity", detail=getattr(match, "reason", ""))
    return CompareResult(
        ok=False,
        kind="visual_similarity",
        detail=f"score={getattr(match, 'score', 'n/a')}: {getattr(match, 'reason', '')}",
    )

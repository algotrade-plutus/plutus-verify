"""Native v2 pipeline: build → execute → compare, consuming a Manifest directly.

No adapter to v1 plumbing. Mirrors the v1 pipeline shape but consumes
``plutus_verify.spec.manifest.Manifest`` end-to-end. Designed to be called from
``run_pipeline`` when ``.plutus/manifest.yaml`` is present.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.spec.manifest import Manifest, Step
from plutus_verify.spec.runtime.data_resolver import (
    DataSource,
    DataTierResult,
    default_downloader,
    resolve_data_tiers,
)
from plutus_verify.spec.runtime.dockerfile_gen import generate_dockerfile
from plutus_verify.spec.runtime.preflight import (
    PreflightError,
    assert_inputs_present,
    assert_outputs_present,
)
from plutus_verify.spec.runtime.refcompare import (
    CompareResult,
    compare_reference_output,
)


@dataclass
class StepRuntimeResult:
    step_id: str
    exit_code: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    skipped_reason: Optional[str] = None
    preflight_error: Optional[str] = None


@dataclass
class HeadlineResult:
    name: str
    ok: bool
    actual: Any
    expected: Any
    detail: str = ""


@dataclass
class V2RuntimeResult:
    image: str
    data_tier_used: str
    step_results: dict[str, StepRuntimeResult] = field(default_factory=dict)
    headline_results: dict[str, dict[str, HeadlineResult]] = field(default_factory=dict)
    reference_results: dict[str, list[CompareResult]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


ImageBuilder = Callable[[str, Path], str]  # (dockerfile_text, repo_path) -> image_tag
Runner = Any  # duck-typed: .run(image=, command=, cwd=, network=, timeout_seconds=, env=)


def run_v2_pipeline(
    manifest: Manifest,
    *,
    repo_path: Path,
    image_builder: ImageBuilder,
    runner: Runner,
    vision_client: Optional[Any],
    secrets: dict[str, str],
    downloader: Optional[Callable[[DataSource, Path], bool]] = None,
    force_data_tier: Optional[str] = None,
    expected_dir: Optional[Path] = None,
) -> V2RuntimeResult:
    dockerfile = generate_dockerfile(manifest.env, secrets=manifest.secrets)
    image = image_builder(dockerfile, repo_path)

    tier = resolve_data_tiers(
        manifest,
        repo_path=repo_path,
        downloader=downloader or default_downloader,
        force_tier=force_data_tier,
    )

    result = V2RuntimeResult(image=image, data_tier_used=tier.tier_used)
    result.notes.extend(tier.notes)

    expected_root = expected_dir or (repo_path / ".plutus" / "expected")

    for step in _topo_sort(manifest.steps):
        sr = _run_step(
            step,
            image=image,
            repo_path=repo_path,
            runner=runner,
            secrets=secrets,
            satisfied=tier.satisfied,
        )
        result.step_results[step.id] = sr

    for er in manifest.expected:
        result.headline_results[er.step_id] = _compare_headlines(er, repo_path)
        result.reference_results[er.step_id] = _compare_refs(
            er, repo_path, expected_root, vision_client
        )

    return result


def _topo_sort(steps: tuple[Step, ...]) -> list[Step]:
    by_id = {s.id: s for s in steps}
    out: list[Step] = []
    seen: set[str] = set()

    def visit(sid: str) -> None:
        if sid in seen:
            return
        for dep in by_id[sid].depends_on:
            if dep in by_id:
                visit(dep)
        seen.add(sid)
        out.append(by_id[sid])

    for s in steps:
        visit(s.id)
    return out


def _run_step(
    step: Step,
    *,
    image: str,
    repo_path: Path,
    runner: Runner,
    secrets: dict[str, str],
    satisfied: frozenset[str],
) -> StepRuntimeResult:
    if step.id in satisfied:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=0,
            duration_seconds=0.0,
            skipped_reason="satisfied_by_data_source",
        )
    try:
        assert_inputs_present(step, repo_path)
    except PreflightError as exc:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=-1,
            duration_seconds=0.0,
            preflight_error=str(exc),
        )
    if not step.command:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=-1,
            duration_seconds=0.0,
            preflight_error=f"step '{step.id}' has no command and is not satisfied by a data source",
        )

    exec_result = runner.run(
        image=image,
        command=step.command,
        cwd=repo_path,
        network=step.network,
        timeout_seconds=step.timeout_seconds,
        env=secrets,
    )
    sr = StepRuntimeResult(
        step_id=step.id,
        exit_code=getattr(exec_result, "exit_code", -1),
        duration_seconds=getattr(exec_result, "duration_seconds", 0.0),
        stdout=getattr(exec_result, "stdout", ""),
        stderr=getattr(exec_result, "stderr", ""),
    )
    if sr.exit_code == 0:
        try:
            assert_outputs_present(step, repo_path)
        except PreflightError as exc:
            sr.preflight_error = str(exc)
    return sr


def _compare_headlines(er, repo_path: Path) -> dict[str, "HeadlineResult"]:
    out: dict[str, HeadlineResult] = {}
    for h in er.headlines:
        try:
            actual = _locate_value(h.locate, repo_path)
            ok, detail = _within_tolerance(actual, h.value, h.tolerance)
            out[h.name] = HeadlineResult(name=h.name, ok=ok, actual=actual, expected=h.value, detail=detail)
        except Exception as exc:  # noqa: BLE001
            out[h.name] = HeadlineResult(
                name=h.name, ok=False, actual=None, expected=h.value, detail=str(exc)
            )
    return out


def _locate_value(locate, repo_path: Path) -> Any:
    if locate.kind == "json_file" and locate.path and locate.jsonpath:
        from jsonpath_ng import parse as _parse_jsonpath

        data = json.loads((repo_path / locate.path).read_text())
        expr = _parse_jsonpath(locate.jsonpath)
        matches = [m.value for m in expr.find(data)]
        if not matches:
            raise KeyError(f"no match for jsonpath {locate.jsonpath} in {locate.path}")
        return matches[0]
    raise NotImplementedError(f"locate kind {locate.kind} not supported in Plan 2")


def _within_tolerance(actual: Any, expected: Any, tol) -> tuple[bool, str]:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if tol.kind == "exact":
            return actual == expected, "" if actual == expected else f"{actual} != {expected}"
        if tol.kind == "absolute":
            ok = abs(actual - expected) <= tol.value
            return ok, "" if ok else f"|{actual} - {expected}| > {tol.value}"
        # relative
        if expected == 0:
            ok = abs(actual) <= tol.value
        else:
            ok = abs(actual - expected) / abs(expected) <= tol.value
        return ok, "" if ok else f"{actual} not within ±{tol.value * 100:.0f}% of {expected}"
    return actual == expected, "" if actual == expected else f"{actual!r} != {expected!r}"


def _compare_refs(er, repo_path: Path, expected_root: Path, vision_client) -> list[CompareResult]:
    out: list[CompareResult] = []
    for r in er.reference_outputs:
        expected_path = expected_root / er.step_id / r.path
        produced_path = repo_path / r.path
        out.append(
            compare_reference_output(
                r,
                expected_path=expected_path,
                produced_path=produced_path,
                vision_client=vision_client,
            )
        )
    return out

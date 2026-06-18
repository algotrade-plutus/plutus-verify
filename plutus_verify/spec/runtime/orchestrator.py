"""Native v2 pipeline: build → execute → compare, consuming a Manifest directly.

No adapter to v1 plumbing. Mirrors the v1 pipeline shape but consumes
``plutus_verify.spec.manifest.Manifest`` end-to-end. Designed to be called from
``run_pipeline`` when ``.plutus/manifest.yaml`` is present.
"""
from __future__ import annotations

import tempfile
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
from plutus_verify.spec.runtime.sdk_bundle import (
    SdkBundleError,
    ensure_plutus_wheel,
)
from plutus_verify.spec.runtime.staging import (
    extract_outputs,
    populate_staging,
)
from plutus_verify.spec.runtime.preflight import (
    PreflightError,
    assert_inputs_present,
    assert_outputs_present,
)
from plutus_verify.spec.runtime.artifact_compare import (
    CompareResult,
    compare_artifact,
)
from plutus_verify.spec.runtime.results import (
    MalformedResultsError,
    MissingResultsError,
    load_results,
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
class ExpectedMetricResult:
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
    metric_results: dict[str, dict[str, ExpectedMetricResult]] = field(default_factory=dict)
    artifact_results: dict[str, list[CompareResult]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # True iff the env is restored from a committed lockfile (env.manager == 'uv'
    # with a lockfile). When False the env is re-resolved at build time and may
    # drift — surfaced as a deprecation note now, a soft fail in a future release.
    env_reproducible: bool = True


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
    # Docker mounts and build contexts require absolute paths; the relative
    # paths users typically pass on the CLI break `-v` and `docker build`.
    repo_path = repo_path.resolve()

    # NOTE: stale-results-dir cleanup is performed by scaffold_check (the
    # CLI wrapper), not here. Direct callers of run_v2_pipeline (tests,
    # programmatic users) manage that themselves.

    # Stage the SDK wheel into the Docker build context so the generated image
    # can `import plutus_verify`. Scripts whose steps declare `expected.metrics`
    # WILL `import plutus_verify` (to call `pv.step(...).metric(...)`), so a
    # bundling failure for those manifests is fatal — silently building an
    # image without the SDK produces ModuleNotFoundError at script-run time
    # which then surfaces as a step failure with no obvious cause. Manifests
    # with no expected metrics (scripts that hand-roll JSON or just verify
    # outputs) get the previous graceful-degrade behavior.
    sdk_required = any(er.metrics for er in manifest.expected)
    sdk_wheel_basename: Optional[str] = None
    _sdk_bundle_error: Optional[str] = None
    try:
        build_ctx = repo_path / ".plutus" / "build"
        wheel = ensure_plutus_wheel(build_ctx)
        sdk_wheel_basename = wheel.name
    except SdkBundleError as exc:
        if sdk_required:
            raise SdkBundleError(
                f"cannot bundle plutus-verify into image and the manifest "
                f"declares scripts that need the SDK (expected.metrics is "
                f"non-empty). Refusing to build a degraded image. "
                f"Underlying error: {exc}"
            ) from exc
        sdk_wheel_basename = None
        _sdk_bundle_error = str(exc)

    dockerfile = generate_dockerfile(
        manifest.env,
        secrets=manifest.secrets,
        sdk_wheel_basename=sdk_wheel_basename,
    )
    image = image_builder(dockerfile, repo_path)

    tier = resolve_data_tiers(
        manifest,
        repo_path=repo_path,
        downloader=downloader or default_downloader,
        force_tier=force_data_tier,
    )

    env_reproducible = manifest.env.manager == "uv" and bool(manifest.env.lockfile)
    result = V2RuntimeResult(
        image=image,
        data_tier_used=tier.tier_used,
        env_reproducible=env_reproducible,
    )
    result.notes.extend(tier.notes)
    if not env_reproducible:
        result.notes.append(
            "DEPRECATION: environment is not reproducibly locked "
            "(env.manager != 'uv' or no env.lockfile). Dependencies are "
            "re-resolved at build time, so results may not reproduce. Pin with "
            "uv + a committed lockfile. This will become a soft fail (exit 1) in "
            "a future release."
        )
    if _sdk_bundle_error is not None:
        result.notes.append(f"SDK wheel not staged: {_sdk_bundle_error}")
    elif sdk_wheel_basename is not None:
        result.notes.append(f"SDK wheel staged: {sdk_wheel_basename}")

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
        result.metric_results[er.step_id] = _compare_metrics(
            er, repo_path, result.step_results
        )
        result.artifact_results[er.step_id] = _compare_artifacts(
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
    if step.verification_mode == "artifact_check":
        # Don't execute — just verify the declared outputs exist (e.g., a
        # shipped optimized_parameter.json).
        sr = StepRuntimeResult(
            step_id=step.id,
            exit_code=0,
            duration_seconds=0.0,
            skipped_reason="artifact_check (no execution; outputs verified by preflight)",
        )
        try:
            assert_outputs_present(step, repo_path)
        except PreflightError as exc:
            sr.preflight_error = str(exc)
            sr.exit_code = -1
        return sr

    if not step.command:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=-1,
            duration_seconds=0.0,
            preflight_error=f"step '{step.id}' has no command and is not satisfied by a data source",
        )

    with tempfile.TemporaryDirectory(prefix=f"plutus-stage-{step.id}-") as staging_str:
        staging = Path(staging_str)
        populate_staging(repo_path, staging, step)
        exec_result = runner.run(
            image=image,
            command=step.command,
            cwd=staging,
            network=step.network,
            timeout_seconds=step.timeout_seconds,
            env=secrets,
        )
        extract_outputs(staging, repo_path, step)
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


def _compare_metrics(
    er, repo_path: Path, step_results: dict[str, StepRuntimeResult]
) -> dict[str, "ExpectedMetricResult"]:
    """Compare expected metrics against metrics in <repo>/.plutus/run/<step_id>/results.json.

    Reads the results.json the step's SDK-instrumented script wrote, builds a
    name → value lookup, and compares each expected metric. Locator dispatch
    is gone — metrics are identified by canonical snake_case name only.

    If the step itself failed (non-zero exit, or a preflight error), the
    metric comparisons are suppressed and each declared metric is reported
    as failed-due-to-step-failure. This prevents the verifier from comparing
    against a stale results.json from a prior run and reporting "ok" for a
    step whose actual run produced nothing.
    """
    sr = step_results.get(er.step_id)
    if sr is not None and (sr.exit_code != 0 or sr.preflight_error):
        reason = (
            f"preflight error: {sr.preflight_error}"
            if sr.preflight_error
            else f"step exited {sr.exit_code}"
        )
        detail = f"step '{er.step_id}' failed ({reason}); metric not evaluated"
        return {
            h.name: ExpectedMetricResult(
                name=h.name, ok=False, actual=None, expected=h.value, detail=detail
            )
            for h in er.metrics
        }

    try:
        results = load_results(repo_path, step_id=er.step_id)
    except MissingResultsError as exc:
        detail = f"results.json missing: {exc}"
        return {
            h.name: ExpectedMetricResult(
                name=h.name, ok=False, actual=None, expected=h.value, detail=detail
            )
            for h in er.metrics
        }
    except MalformedResultsError as exc:
        detail = f"results.json malformed: {exc}"
        return {
            h.name: ExpectedMetricResult(
                name=h.name, ok=False, actual=None, expected=h.value, detail=detail
            )
            for h in er.metrics
        }

    metrics_by_name = {m.name: m for m in results.metrics}
    out: dict[str, ExpectedMetricResult] = {}
    for h in er.metrics:
        m = metrics_by_name.get(h.name)
        if m is None:
            out[h.name] = ExpectedMetricResult(
                name=h.name,
                ok=False,
                actual=None,
                expected=h.value,
                detail=f"metric '{h.name}' not produced in results.json",
            )
            continue
        ok, detail = _within_tolerance(m.value, h.value, h.tolerance)
        out[h.name] = ExpectedMetricResult(
            name=h.name, ok=ok, actual=m.value, expected=h.value, detail=detail
        )
    return out


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


def _compare_artifacts(er, repo_path: Path, expected_root: Path, vision_client) -> list[CompareResult]:
    out: list[CompareResult] = []
    for r in er.artifacts:
        expected_path = expected_root / er.step_id / r.path
        produced_path = repo_path / r.path
        out.append(
            compare_artifact(
                r,
                expected_path=expected_path,
                produced_path=produced_path,
                vision_client=vision_client,
            )
        )
    return out

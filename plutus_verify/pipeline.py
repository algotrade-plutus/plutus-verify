"""Pipeline orchestrator: wires every stage end-to-end with injectable adapters.

CLI -> ``run_pipeline`` -> ingest -> extract -> build -> execute -> compare -> report.

Adapters (git, LLM, builder, runner, vision) are passed in by the caller, so
the same pipeline serves the real CLI and the tests.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from plutus_verify import __version__
from plutus_verify.util.json_io import load_json, save_json
from plutus_verify.compare.charts import VisionClient, compare_charts
from plutus_verify.compare.llm_match import MetricMatchClient
from plutus_verify.compare.metrics import MetricSources, compare_metric, compare_step_metrics
from plutus_verify.compare.rubric import (
    ExecOutcome,
    OverallReport,
    StepReport,
    StepVerdict,
    aggregate_overall,
    aggregate_step,
)
from plutus_verify.config import Config
from plutus_verify.execute import ExecResult, Runner, run_plan
from plutus_verify.extract import LLMClient, extract_plan
from plutus_verify.extract.plan import ExtractedPlan, parse_plan
from plutus_verify.extract.validator import validate_plan
from plutus_verify.ingest import IngestResult, ingest, resume_existing_run
from plutus_verify.report import (
    Finding,
    FindingKind,
    FindingSeverity,
    RunMeta,
    StageOutcome,
    TrailEntry,
    outcome_from_counts,
    write_reports,
)
from plutus_verify.spec.runtime import V2RuntimeResult, run_v2_pipeline
from plutus_verify.util.progress import NullProgress, Progress


class Builder(Protocol):
    def build(self, *, repo_path: Path, commit_sha: str) -> Any:
        """Return either a str image tag or a BuildResult-shape with adjustments."""
        ...


@dataclass
class PipelineInputs:
    source: str
    out_dir: Path
    config: Config
    secrets_path: Optional[Path] = None
    ref: Optional[str] = None
    skip_clone: bool = False
    auto_fetch: bool = False
    """If True, attempt to download data for steps with a manual_download
    alternative whose expected_layout files aren't present on disk."""
    charts_enabled: bool = True
    prefer_data_path: Optional[str] = None
    extract_only: bool = False
    resume_from: Optional[str] = None  # "extract"|"build"|"execute"|"compare"|"report"
    # C2 — resume / pre-loaded artifacts
    pre_loaded_plan: Optional[ExtractedPlan] = None
    """If set, skip the extract stage and use this plan instead."""
    pre_built_image: Optional[str] = None
    """If set, skip the build stage and use this image tag instead."""
    resume_existing: bool = False
    """If True, load ingest state from ``out_dir/meta.json`` (no fresh clone)
    and load plan from ``out_dir/plan.json`` if present (no fresh extract).
    """
    progress: Optional[Progress] = None
    """If set, the pipeline tees stage/substep events to this emitter. Pass
    ``None`` (default) for a silent run (tests, batch mode)."""


@dataclass
class PipelineResult:
    plan: ExtractedPlan
    overall: Optional[OverallReport]
    meta: RunMeta
    out_dir: Path
    verification_trail: list[TrailEntry] = field(default_factory=list)


_STAGE_ORDER = ("ingest", "extract", "build", "execute", "compare", "report")


def _should_skip(resume_from: Optional[str], stage: str) -> bool:
    if not resume_from:
        return False
    return _STAGE_ORDER.index(stage) < _STAGE_ORDER.index(resume_from)


def _parse_secrets_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _plan_to_dict(plan: ExtractedPlan) -> dict[str, Any]:
    """Round-trip a parsed plan back to a dict for persistence."""
    return _asdict_with_tuples(plan)


def _asdict_with_tuples(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _asdict_with_tuples(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: _asdict_with_tuples(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_asdict_with_tuples(v) for v in obj]
    return obj


def _apply_artifact_only_override(plan: ExtractedPlan, ids: list[str]) -> ExtractedPlan:
    """Force the given step ids into verification_mode='artifact_check'."""
    if not ids:
        return plan
    new_steps = tuple(
        dataclasses.replace(s, verification_mode="artifact_check") if s.id in ids else s
        for s in plan.steps
    )
    return dataclasses.replace(plan, steps=new_steps)


def _build_nine_step_coverage(plan: ExtractedPlan) -> dict[str, dict[str, Any]]:
    return {
        k: {
            "present": v.present,
            "section_heading": v.section_heading,
            "confidence": v.confidence,
        }
        for k, v in plan.nine_step_mapping.items()
    }


def run_pipeline(
    inputs: PipelineInputs,
    *,
    git_runner: Callable[..., str] = None,  # type: ignore[assignment]
    llm_client: LLMClient,
    builder: Builder,
    runner: Runner,
    vision: VisionClient,
    match_client: Optional[MetricMatchClient] = None,
) -> PipelineResult:
    inputs.out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    progress: Progress = inputs.progress or NullProgress()
    trail: list[TrailEntry] = []
    stage_start = start

    # ---------- ingest ----------
    progress.stage("ingest", f"source: {inputs.source}")
    if inputs.resume_existing and (inputs.out_dir / "meta.json").exists():
        ing: IngestResult = resume_existing_run(inputs.out_dir)
        ingest_outcome = "skipped"
        ingest_summary = f"reused existing run dir at {inputs.out_dir}"
    else:
        ingest_kwargs: dict[str, Any] = {}
        if git_runner is not None:
            ingest_kwargs["git_runner"] = git_runner
        ing = ingest(
            inputs.source,
            run_dir=inputs.out_dir,
            ref=inputs.ref,
            skip_clone=inputs.skip_clone,
            **ingest_kwargs,
        )
        ingest_outcome = "ok"
        ingest_summary = f"cloned {ing.commit_sha[:7]} ({ing.branch})"
    progress.stage("ingest", f"{ingest_summary}  ({time.monotonic() - stage_start:.1f}s)")
    trail.append(
        TrailEntry(
            stage="ingest",
            outcome=ingest_outcome,
            duration_seconds=time.monotonic() - stage_start,
            summary=ingest_summary,
            artifacts=["meta.json"],
        )
    )
    stage_start = time.monotonic()

    # ---------- extract ----------
    plan_path = inputs.out_dir / "plan.json"
    extract_outcome: str
    extract_summary: str
    extract_artifacts: list[str] = []
    _spec_manifest = None  # set when .plutus/manifest.yaml is present (v2 native path)
    spec_path = ing.repo_path / ".plutus" / "manifest.yaml"
    if spec_path.exists():
        from plutus_verify.spec.adapter import to_extracted_plan
        from plutus_verify.spec.loader import load_manifest

        try:
            manifest = load_manifest(ing.repo_path)
        except Exception as exc:
            progress.error("extract", f"v2 spec load failed: {exc}")
            raise
        _spec_manifest = manifest  # stash for native v2 routing below
        plan = to_extracted_plan(manifest)
        plan = _apply_artifact_only_override(plan, inputs.config.overrides.artifact_only_steps)
        save_json(_plan_to_dict(plan), plan_path)
        n_steps = len(plan.steps)
        n_metrics = sum(len(er.metrics) for er in plan.expected_results)
        n_charts = sum(len(er.charts) for er in plan.expected_results)
        extract_outcome = "ok"
        extract_summary = (
            f"v2 spec — {n_steps} steps, {n_metrics} metrics, {n_charts} charts"
        )
        progress.stage(
            "extract",
            f"loaded .plutus/manifest.yaml — {extract_summary}  "
            f"({time.monotonic() - stage_start:.1f}s)",
        )
        extract_artifacts = ["plan.json", "manifest.yaml"]
    elif inputs.pre_loaded_plan is not None:
        plan = inputs.pre_loaded_plan
        # Persist so the re-run is auditable
        if not plan_path.exists():
            save_json(_plan_to_dict(plan), plan_path)
        progress.stage("extract", "skipped (pre-loaded plan provided)")
        extract_outcome = "skipped"
        extract_summary = "used pre-loaded plan.json"
        extract_artifacts = ["plan.json"]
    elif inputs.resume_existing and plan_path.exists():
        plan = parse_plan(load_json(plan_path))
        progress.stage("extract", "skipped (using existing plan.json from out_dir)")
        extract_outcome = "skipped"
        extract_summary = "reused existing plan.json"
        extract_artifacts = ["plan.json"]
    elif _should_skip(inputs.resume_from, "extract") and plan_path.exists():
        plan = parse_plan(load_json(plan_path))
        progress.stage("extract", "skipped (resume-from past extract)")
        extract_outcome = "skipped"
        extract_summary = "reused existing plan.json"
        extract_artifacts = ["plan.json"]
    else:
        plan, extract_summary = _run_extract_via_llm(
            ing=ing,
            inputs=inputs,
            llm_client=llm_client,
            plan_path=plan_path,
            progress=progress,
            stage_start=stage_start,
        )
        extract_outcome = "ok"
        extract_artifacts = ["plan.json", "extract_call_*.txt"]
    trail.append(
        TrailEntry(
            stage="extract",
            outcome=extract_outcome,
            duration_seconds=time.monotonic() - stage_start,
            summary=extract_summary,
            artifacts=extract_artifacts,
        )
    )
    stage_start = time.monotonic()

    meta = RunMeta(
        repo_name=plan.repo.name or Path(inputs.source).stem,
        git_url=inputs.source,
        commit_sha=ing.commit_sha,
        branch=ing.branch,
        run_id=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%MZ"),
        duration_seconds=0,
        plutus_verify_version=__version__,
    )

    if inputs.extract_only:
        progress.stage("report", f"extract-only complete — see {plan_path}")
        return PipelineResult(
            plan=plan,
            overall=None,
            meta=meta,
            out_dir=inputs.out_dir,
            verification_trail=trail,
        )

    # ---------- v2 native runtime (bypasses build/execute/compare/report stages) ----------
    if _spec_manifest is not None:
        return _run_v2_native_path(
            inputs=inputs,
            ing=ing,
            plan=plan,
            manifest=_spec_manifest,
            meta=meta,
            trail=trail,
            stage_start=stage_start,
            start=start,
            progress=progress,
            builder=builder,
            runner=runner,
            vision=vision,
        )

    # ---------- build ----------
    build_adjustments: list[Any] = []
    build_artifacts_dir = inputs.out_dir / "build"
    if inputs.pre_built_image is not None:
        image = inputs.pre_built_image
        progress.stage("build", f"skipped (using pre-built image {image})")
        build_outcome = "skipped"
        build_summary = f"reused image {image}"
        build_artifacts: list[str] = []
    else:
        progress.stage("build", "target image: python:3.13-slim (auto-fixing)")
        try:
            built = _invoke_builder(
                builder,
                repo_path=ing.repo_path,
                commit_sha=ing.commit_sha,
                progress=progress,
                artifacts_dir=build_artifacts_dir,
            )
        except Exception as exc:
            progress.error("build", f"{type(exc).__name__}: {exc}")
            raise
        # Allow builders to return either an image tag or a BuildResult-shape.
        if isinstance(built, str):
            image = built
            build_artifacts = []
        else:
            image = built.image
            build_adjustments = list(getattr(built, "adjustments", ()) or ())
            build_artifacts = (
                ["build/attempt_*.log", "build/attempt_*.fixers.json"]
                if build_artifacts_dir.exists()
                else []
            )
        build_outcome = "ok"
        build_summary = (
            f"image {image}"
            + (
                f" ({len(build_adjustments)} adjustment(s) applied)"
                if build_adjustments
                else ""
            )
        )
        progress.stage(
            "build",
            f"{build_summary}  ({time.monotonic() - stage_start:.1f}s)",
        )
    trail.append(
        TrailEntry(
            stage="build",
            outcome=build_outcome,
            duration_seconds=time.monotonic() - stage_start,
            summary=build_summary,
            artifacts=build_artifacts,
        )
    )
    stage_start = time.monotonic()

    # ---------- auto-fetch (opt-in) ----------
    fetch_findings: list[Finding] = []
    if inputs.auto_fetch:
        progress.stage("fetch", "auto-fetching missing manual_download alternatives")
        fetch_findings = _auto_fetch_missing_data(plan, ing.repo_path)
        n_ok = sum(1 for f in fetch_findings if f.kind == FindingKind.DATA_AUTO_FETCHED)
        n_fail = sum(1 for f in fetch_findings if f.kind == FindingKind.DATA_FETCH_FAILED)
        fetch_summary = f"{n_ok} fetched, {n_fail} failed"
        progress.stage(
            "fetch", f"{fetch_summary}  ({time.monotonic() - stage_start:.1f}s)"
        )
        fetch_outcome = outcome_from_counts(ok=n_ok, failed=n_fail)
    else:
        progress.stage("fetch", "skipped (use --auto-fetch to enable)")
        fetch_outcome = "skipped"
        fetch_summary = "no --auto-fetch"
    trail.append(
        TrailEntry(
            stage="fetch",
            outcome=fetch_outcome,
            duration_seconds=time.monotonic() - stage_start,
            summary=fetch_summary,
            artifacts=[],
        )
    )
    stage_start = time.monotonic()

    # ---------- execute ----------
    progress.stage("execute", f"{len(plan.steps)} step(s) to run")
    secrets = _parse_secrets_file(inputs.secrets_path) if inputs.secrets_path else {}
    execute_artifacts_dir = inputs.out_dir / "execute"
    exec_outputs: dict[str, ExecResult] = run_plan(
        plan,
        image=image,
        repo_path=ing.repo_path,
        runner=runner,
        available_secrets=secrets,
        prefer_data_path=inputs.prefer_data_path,
        manual_download_resolver=_manual_download_present(ing.repo_path),
        progress=progress,
        artifacts_dir=execute_artifacts_dir,
    )
    n_ran = sum(
        1
        for r in exec_outputs.values()
        if r.outcome == ExecOutcome.OK and r.alternative_used != "artifact_check"
    )
    n_skipped = sum(1 for r in exec_outputs.values() if r.outcome == ExecOutcome.SKIPPED)
    n_failed = sum(
        1
        for r in exec_outputs.values()
        if r.outcome in (ExecOutcome.FAILED, ExecOutcome.TIMEOUT)
    )
    execute_summary = f"{n_ran} ran, {n_skipped} skipped, {n_failed} failed"
    progress.stage(
        "execute", f"{execute_summary}  ({time.monotonic() - stage_start:.1f}s)"
    )
    execute_outcome = (
        "failed" if n_failed else ("partial" if n_skipped and not n_ran else "ok")
    )
    trail.append(
        TrailEntry(
            stage="execute",
            outcome=execute_outcome,
            duration_seconds=time.monotonic() - stage_start,
            summary=execute_summary,
            artifacts=(
                ["execute/<step_id>.{stdout,stderr,meta.json}"]
                if execute_artifacts_dir.exists()
                else []
            ),
        )
    )
    stage_start = time.monotonic()

    # ---------- compare ----------
    overall, step_reports = _run_compare_stage(
        plan=plan,
        exec_outputs=exec_outputs,
        repo_path=ing.repo_path,
        vision=vision,
        match_client=match_client,
        chart_match_threshold=inputs.config.charts.match_threshold,
        charts_enabled=inputs.charts_enabled,
        progress=progress,
        stage_start=stage_start,
        trail=trail,
    )
    stage_start = time.monotonic()

    # ---------- findings ----------
    findings = _build_findings(
        fetch_findings=fetch_findings,
        build_adjustments=build_adjustments,
        step_reports=step_reports,
    )

    # ---------- report ----------
    meta = dataclasses.replace(meta, duration_seconds=int(time.monotonic() - start))
    progress.stage("report", f"verdict: {overall.verdict.value} (exit {overall.exit_code})")
    # Pre-add the report trail entry so the rendered report includes itself.
    trail.append(
        TrailEntry(
            stage="report",
            outcome="ok",
            duration_seconds=time.monotonic() - stage_start,
            summary=f"verdict: {overall.verdict.value}",
            artifacts=["report.md", "report.json", "run.log"],
        )
    )
    report_paths = write_reports(
        out_dir=inputs.out_dir,
        overall=overall,
        meta=meta,
        extraction_notes=list(plan.extraction_notes),
        nine_step_coverage=_build_nine_step_coverage(plan),
        findings=findings,
        verification_trail=trail,
    )
    progress.stage(
        "report",
        f"written: {report_paths[1]}  {report_paths[0]}  {inputs.out_dir / 'run.log'}",
    )

    return PipelineResult(
        plan=plan,
        overall=overall,
        meta=meta,
        out_dir=inputs.out_dir,
        verification_trail=trail,
    )


_BUILD_KIND_MAP = {
    "encoding": FindingKind.BUILD_ENCODING,
    "missing_dep": FindingKind.BUILD_MISSING_DEP,
    "incomplete_dep": FindingKind.BUILD_INCOMPLETE_DEP,
    "apt_dev_header": FindingKind.BUILD_INCOMPLETE_DEP,
    "pin_version": FindingKind.BUILD_INCOMPLETE_DEP,
    "give_up": FindingKind.BUILD_UPSTREAM_BROKEN,
}


def _build_findings(
    *,
    fetch_findings: list[Finding],
    build_adjustments: list[Any],
    step_reports: list[StepReport],
) -> list[Finding]:
    """Aggregate auto-fetch / build / execute / metric findings into one list."""
    findings: list[Finding] = list(fetch_findings)
    for adj in build_adjustments:
        findings.append(
            Finding(
                severity=FindingSeverity.NOTE,
                kind=_BUILD_KIND_MAP.get(adj.kind, FindingKind.BUILD_MISSING_DEP),
                step="(build)",
                summary=f"[{adj.phase}] {adj.description}",
            )
        )
    for sr in step_reports:
        if sr.exec_outcome.value in ("failed", "timeout") and sr.required:
            findings.append(
                Finding(
                    severity=FindingSeverity.BLOCKER,
                    kind=FindingKind.EXEC_FAILED,
                    step=sr.step_id,
                    summary=f"step {sr.step_id} {sr.exec_outcome.value}",
                )
            )
        for m in sr.metrics:
            if m.pass_:
                continue
            if m.unverifiable_reason:
                findings.append(
                    Finding(
                        severity=FindingSeverity.PARTIAL,
                        kind=FindingKind.METRIC_UNVERIFIABLE,
                        step=sr.step_id,
                        summary=f"{m.name}: {m.unverifiable_reason}",
                    )
                )
            else:
                actual_str = "—" if m.actual is None else f"{m.actual:g}"
                findings.append(
                    Finding(
                        severity=FindingSeverity.PARTIAL,
                        kind=FindingKind.METRIC_DRIFT,
                        step=sr.step_id,
                        summary=(
                            f"{m.name} drifted from README "
                            f"({m.expected:g} expected vs {actual_str})"
                        ),
                    )
                )
    return findings


def _run_extract_via_llm(
    *,
    ing: IngestResult,
    inputs: PipelineInputs,
    llm_client: LLMClient,
    plan_path: Path,
    progress: Progress,
    stage_start: float,
) -> tuple[ExtractedPlan, str]:
    """Drive the 4-call LLM extraction + validator + persist plan.json.

    Returns ``(plan, summary)``; raises on extract failure (caller logs).
    """
    readme_text = ing.readme_path.read_text()
    progress.stage("extract", "generating plan via 4 LLM calls")

    retry_counts: dict[str, int] = {}

    def _save_attempt(label: str, raw: str, err: Exception | None) -> None:
        tag = "ok" if err is None else type(err).__name__
        (inputs.out_dir / f"extract_{label}_{tag}.txt").write_text(raw)
        if err is not None:
            (inputs.out_dir / f"extract_{label}_{tag}.err").write_text(str(err))
        # Label is shaped "call_2_steps_attempt_1" — pull out the call number +
        # element name for the readable progress hint.
        try:
            call_num = label.split("_")[1]
            element = label.split("_")[2]
        except IndexError:
            call_num, element = "?", label
        if err is None:
            progress.substep("extract", f"call {int(call_num) + 1}/4 {element}: ok")
        else:
            retry_counts[element] = retry_counts.get(element, 0) + 1
            msg = str(err).splitlines()[0] if str(err) else type(err).__name__
            if len(msg) > 120:
                msg = msg[:117] + "..."
            progress.substep(
                "extract",
                f"call {int(call_num) + 1}/4 {element}: retry "
                f"{retry_counts[element]} — {type(err).__name__}: {msg}",
            )

    try:
        plan = extract_plan(
            readme_text,
            llm_client,
            temperature=inputs.config.llm.temperature,
            max_retries=inputs.config.llm.max_retries,
            first_attempt_idle_seconds=float(
                getattr(inputs.config.llm, "first_attempt_timeout_seconds", 180)
            ),
            retry_idle_seconds=float(inputs.config.llm.timeout_seconds),
            on_attempt=_save_attempt,
        )
    except Exception as exc:
        progress.error("extract", f"{type(exc).__name__}: {exc}")
        raise
    plan = _apply_artifact_only_override(plan, inputs.config.overrides.artifact_only_steps)
    # Validator: only the deterministic Phase 1 runs in production. Phase 2
    # (LLM second pass) had a tendency to hallucinate no-op corrections; it
    # was disabled in Iteration 4. The Phase 2 code stays in the validator
    # module (and its tests) as a safety net for repos we haven't seen yet.
    plan, validator_fixes = validate_plan(
        plan,
        readme_text=readme_text,
        repo_path=ing.repo_path,
        llm_client=None,
    )
    if validator_fixes:
        save_json(validator_fixes, inputs.out_dir / "validator_fixes.json")
        progress.substep(
            "extract",
            f"validator applied {len(validator_fixes)} fix(es) to plan",
        )
    save_json(_plan_to_dict(plan), plan_path)
    n_steps = len(plan.steps)
    n_metrics = sum(len(er.metrics) for er in plan.expected_results)
    n_charts = sum(len(er.charts) for er in plan.expected_results)
    n_retries = sum(retry_counts.values())
    summary = (
        f"{n_steps} steps, {n_metrics} metrics, {n_charts} charts"
        + (f" ({n_retries} retry)" if n_retries else "")
    )
    progress.stage(
        "extract",
        f"plan.json written — {summary}  ({time.monotonic() - stage_start:.1f}s)",
    )
    return plan, summary


def _run_compare_stage(
    *,
    plan: ExtractedPlan,
    exec_outputs: dict[str, ExecResult],
    repo_path: Path,
    vision: VisionClient,
    match_client: Optional[MetricMatchClient],
    chart_match_threshold: float,
    charts_enabled: bool,
    progress: Progress,
    stage_start: float,
    trail: list[TrailEntry],
) -> tuple[OverallReport, list[StepReport]]:
    """Run the compare stage: per-step metric + chart comparison, then aggregate.

    Mutates ``trail`` by appending the compare TrailEntry.
    """
    n_metrics_total = sum(len(er.metrics) for er in plan.expected_results)
    n_charts_total = sum(len(er.charts) for er in plan.expected_results)
    progress.stage(
        "compare",
        f"{n_metrics_total} metric(s), {n_charts_total} chart(s)",
    )
    step_reports: list[StepReport] = []
    er_by_step = {er.step_id: er for er in plan.expected_results}
    n_metrics_pass = 0
    n_metrics_fail = 0
    n_charts_pass = 0
    n_charts_fail = 0
    for step in plan.steps:
        result = exec_outputs[step.id]
        er = er_by_step.get(step.id)
        sources = MetricSources(stdout=result.stdout, file_root=repo_path)
        metric_comparisons = (
            compare_step_metrics(list(er.metrics), sources, match_client=match_client)
            if er
            else []
        )
        chart_verdicts = (
            compare_charts(
                list(er.charts),
                repo_root=repo_path,
                vision=vision,
                match_threshold=chart_match_threshold,
                enabled=charts_enabled,
            )
            if er
            else []
        )
        step_reports.append(
            aggregate_step(
                step_id=step.id,
                required=step.required,
                exec_outcome=result.outcome,
                metrics=metric_comparisons,
                charts=chart_verdicts,
                verification_mode=step.verification_mode,
            )
        )

        n_m_pass = sum(1 for m in metric_comparisons if m.pass_)
        n_c_pass = sum(1 for c in chart_verdicts if c.verdict == "match")
        n_metrics_pass += n_m_pass
        n_metrics_fail += len(metric_comparisons) - n_m_pass
        n_charts_pass += n_c_pass
        n_charts_fail += len(chart_verdicts) - n_c_pass
        if metric_comparisons or chart_verdicts:
            parts = []
            if metric_comparisons:
                parts.append(f"metrics {n_m_pass}/{len(metric_comparisons)} pass")
            if chart_verdicts:
                parts.append(f"charts {n_c_pass}/{len(chart_verdicts)} pass")
            progress.substep("compare", f"{step.id}: {', '.join(parts)}")

    overall = aggregate_overall(step_reports)
    compare_summary = (
        f"metrics {n_metrics_pass}/{n_metrics_pass + n_metrics_fail} pass, "
        f"charts {n_charts_pass}/{n_charts_pass + n_charts_fail} pass"
    )
    progress.stage(
        "compare", f"{compare_summary}  ({time.monotonic() - stage_start:.1f}s)"
    )
    trail.append(
        TrailEntry(
            stage="compare",
            outcome="ok" if not (n_metrics_fail or n_charts_fail) else "partial",
            duration_seconds=time.monotonic() - stage_start,
            summary=compare_summary,
            artifacts=[],
        )
    )
    return overall, step_reports


def _run_v2_native_path(
    *,
    inputs: PipelineInputs,
    ing: IngestResult,
    plan: ExtractedPlan,
    manifest: Any,
    meta: RunMeta,
    trail: list[TrailEntry],
    stage_start: float,
    start: float,
    progress: Progress,
    builder: Builder,
    runner: Runner,
    vision: VisionClient,
) -> "PipelineResult":
    """Native v2 path: build+execute+compare via run_v2_pipeline, then write a
    minimal report synthesized from V2RuntimeResult.

    TODO(plan2-task6-report-synthesis): v2 run's report.md/json currently lists
    no per-step metrics or charts, and nine_step_coverage is always empty. Wire
    ExpectedMetricResult into MetricComparison and translate manifest.nine_step_coverage
    into the report. Not a regression (v2 routing is correct) — just a fidelity gap.
    """
    # Image builder adapter: the v2 orchestrator expects
    # image_builder(dockerfile_text, repo_path) -> image_tag.
    # The injected `builder` follows the v1 protocol (.build(repo_path, commit_sha)).
    # We bridge them here so the real docker build wiring (Plan 3) can supply a
    # proper v2-aware builder later.
    def _image_builder(dockerfile_text: str, repo_path: Any) -> str:
        # TODO(plan2-task6-report-synthesis): v2 run's report.md/json currently lists
        # no per-step metrics or charts, and nine_step_coverage is always empty. Wire
        # ExpectedMetricResult into MetricComparison and translate manifest.nine_step_coverage
        # into the report. Not a regression (v2 routing is correct) — just a fidelity gap.
        result = _invoke_builder(
            builder,
            repo_path=ing.repo_path,
            commit_sha=ing.commit_sha,
            progress=progress,
            artifacts_dir=inputs.out_dir / "build",
        )
        if isinstance(result, str):
            return result
        return result.image

    secrets = _parse_secrets_file(inputs.secrets_path) if inputs.secrets_path else {}

    # -- run the native v2 pipeline --
    progress.stage("build", "v2 native: building image")
    progress.stage("execute", "v2 native: running steps")
    try:
        v2_result: V2RuntimeResult = run_v2_pipeline(
            manifest,
            repo_path=ing.repo_path,
            image_builder=_image_builder,
            runner=runner,
            vision_client=vision,
            secrets=secrets,
        )
    except Exception as exc:
        progress.error("execute", f"v2 pipeline failed: {exc}")
        raise

    # -- synthesize trail entries for build / fetch / execute / compare --
    trail.append(TrailEntry(
        stage="build",
        outcome="ok",
        duration_seconds=0.0,
        summary=f"v2 image: {v2_result.image}",
        artifacts=[],
    ))
    trail.append(TrailEntry(
        stage="fetch",
        outcome="ok",
        duration_seconds=0.0,
        summary=f"data tier: {v2_result.data_tier_used}",
        artifacts=[],
    ))

    n_ran = sum(
        1 for sr in v2_result.step_results.values()
        if sr.exit_code == 0 and sr.skipped_reason is None
    )
    n_skipped = sum(
        1 for sr in v2_result.step_results.values()
        if sr.skipped_reason is not None
    )
    n_failed = sum(
        1 for sr in v2_result.step_results.values()
        if sr.exit_code != 0 and sr.skipped_reason is None
    )
    trail.append(TrailEntry(
        stage="execute",
        outcome="failed" if n_failed else ("partial" if n_skipped and not n_ran else "ok"),
        duration_seconds=sum(
            sr.duration_seconds for sr in v2_result.step_results.values()
        ),
        summary=f"{n_ran} ran, {n_skipped} skipped, {n_failed} failed",
        artifacts=[],
    ))

    # -- synthesize step reports for the overall verdict --
    step_reports: list[StepReport] = []
    for step in manifest.steps:
        sr = v2_result.step_results.get(step.id)
        if sr is None:
            exec_outcome = ExecOutcome.SKIPPED
        elif sr.skipped_reason is not None:
            exec_outcome = ExecOutcome.OK
        elif sr.exit_code == 0 and sr.preflight_error is None:
            exec_outcome = ExecOutcome.OK
        elif sr.exit_code != 0:
            exec_outcome = ExecOutcome.FAILED
        else:
            exec_outcome = ExecOutcome.OK  # ran but had preflight warning

        step_reports.append(aggregate_step(
            step_id=step.id,
            required=step.required,
            exec_outcome=exec_outcome,
            metrics=[],   # TODO(plan2-task6-report-synthesis): v2 run's report.md/json currently lists no per-step metrics or charts, and nine_step_coverage is always empty. Wire ExpectedMetricResult into MetricComparison and translate manifest.nine_step_coverage into the report. Not a regression (v2 routing is correct) — just a fidelity gap.
            charts=[],    # TODO(plan2-task6-report-synthesis): v2 run's report.md/json currently lists no per-step metrics or charts, and nine_step_coverage is always empty. Wire ExpectedMetricResult into MetricComparison and translate manifest.nine_step_coverage into the report. Not a regression (v2 routing is correct) — just a fidelity gap.
        ))

    overall = aggregate_overall(step_reports)

    n_hl_pass = sum(
        1
        for step_hl in v2_result.metric_results.values()
        for hr in step_hl.values()
        if hr.ok
    )
    n_hl_fail = sum(
        1
        for step_hl in v2_result.metric_results.values()
        for hr in step_hl.values()
        if not hr.ok
    )
    compare_summary = f"metrics {n_hl_pass} pass / {n_hl_fail} fail (v2)"
    trail.append(TrailEntry(
        stage="compare",
        outcome="ok" if not n_hl_fail else "partial",
        duration_seconds=0.0,
        summary=compare_summary,
        artifacts=[],
    ))

    # -- write reports --
    meta = dataclasses.replace(meta, duration_seconds=int(time.monotonic() - start))
    progress.stage("report", f"verdict: {overall.verdict.value} (exit {overall.exit_code})")
    trail.append(TrailEntry(
        stage="report",
        outcome="ok",
        duration_seconds=time.monotonic() - stage_start,
        summary=f"verdict: {overall.verdict.value} [v2]",
        artifacts=["report.md", "report.json"],
    ))
    write_reports(
        out_dir=inputs.out_dir,
        overall=overall,
        meta=meta,
        extraction_notes=[],
        nine_step_coverage={},  # TODO(plan2-task6-report-synthesis): v2 run's report.md/json currently lists no per-step metrics or charts, and nine_step_coverage is always empty. Wire ExpectedMetricResult into MetricComparison and translate manifest.nine_step_coverage into the report. Not a regression (v2 routing is correct) — just a fidelity gap.
        findings=[],
        verification_trail=trail,
    )

    return PipelineResult(
        plan=plan,
        overall=overall,
        meta=meta,
        out_dir=inputs.out_dir,
        verification_trail=trail,
    )


def _invoke_builder(
    builder: "Builder",
    *,
    repo_path: Path,
    commit_sha: str,
    progress: Progress,
    artifacts_dir: Path,
) -> Any:
    """Call ``builder.build(...)``, passing progress + artifacts_dir if accepted.

    Test stubs implement a minimal signature; the real builder accepts the
    observability kwargs. ``TypeError`` falls back to the minimal signature.
    """
    try:
        return builder.build(
            repo_path=repo_path,
            commit_sha=commit_sha,
            progress=progress,
            artifacts_dir=artifacts_dir,
        )
    except TypeError:
        return builder.build(repo_path=repo_path, commit_sha=commit_sha)


def _auto_fetch_missing_data(plan: ExtractedPlan, repo_path: Path) -> list[Finding]:
    """For each step with a manual_download alternative whose data isn't on
    disk, attempt the download. One Finding emitted per attempt.

    NOTE-severity for successful fetches; BLOCKER for fetches that failed
    despite being attempted. URL hosts we don't know how to handle are not
    treated as findings — the executor will surface the missing data as its
    own EXEC_FAILED finding if no other alternative is viable.
    """
    from plutus_verify.fetch import FetchResult, FetchSkipped, fetch_manual_download

    findings: list[Finding] = []
    for step in plan.steps:
        if not step.alternatives:
            continue
        for alt in step.alternatives:
            if alt.kind != "manual_download":
                continue
            if not alt.expected_layout:
                continue
            # Already present? Nothing to do.
            if all((repo_path / p).exists() for p in alt.expected_layout):
                continue
            outcome = fetch_manual_download(alt, repo_path=repo_path)
            if isinstance(outcome, FetchSkipped):
                continue  # unknown host — executor will report the data-missing error
            if outcome.ok:
                findings.append(
                    Finding(
                        severity=FindingSeverity.NOTE,
                        kind=FindingKind.DATA_AUTO_FETCHED,
                        step=step.id,
                        summary=f"fetched data via {alt.label!r}: {outcome.message}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        severity=FindingSeverity.BLOCKER,
                        kind=FindingKind.DATA_FETCH_FAILED,
                        step=step.id,
                        summary=f"auto-fetch failed for {alt.label!r}: {outcome.message}",
                    )
                )
    return findings


def _manual_download_present(repo_path: Path):
    """Closure: given a manual_download alternative, check if its expected
    layout files/directories exist under the repo. Used to skip the credentialed
    fallback when the manual data is already present.

    Supports glob patterns (``database/*.csv``) — Plutus repos sometimes
    declare layout as a wildcard rather than enumerating each file.
    """
    from plutus_verify.fetch import _layout_entry_present

    def check(alt) -> bool:
        if not alt.expected_layout:
            return False
        return all(_layout_entry_present(repo_path, p) for p in alt.expected_layout)

    return check

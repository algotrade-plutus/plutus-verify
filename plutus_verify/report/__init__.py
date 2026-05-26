"""Report writers: JSON (machine) + Markdown (reviewer)."""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

StageOutcome = Literal["ok", "skipped", "failed", "partial"]


def outcome_from_counts(*, ok: int, failed: int) -> StageOutcome:
    """Pick a stage outcome from per-item counts.

    ``failed`` dominates: any failure makes the stage failed. Otherwise ``ok``
    iff at least one item succeeded, else ``skipped`` (e.g., no work to do).
    Use ``"partial"`` only when the caller has explicit partial semantics — it
    is not derivable from counts alone.
    """
    if failed:
        return "failed"
    if ok:
        return "ok"
    return "skipped"

from plutus_verify.util.json_io import save_json

from plutus_verify.compare.metrics import MetricComparison
from plutus_verify.compare.rubric import (
    ChartVerdict,
    OverallReport,
    StepReport,
    StepVerdict,
)


@dataclass(frozen=True)
class TrailEntry:
    """One entry in the per-stage verification trail.

    Built by the pipeline at each stage boundary and rendered into the
    ``Verification Trail`` section of ``report.md`` + the
    ``verification_trail`` array in ``report.json``.
    """

    stage: str            # "ingest" | "extract" | "build" | "fetch" | "execute" | "compare" | "report"
    outcome: StageOutcome
    duration_seconds: float
    summary: str
    artifacts: list[str] = field(default_factory=list)


_TRAIL_OUTCOME_BADGE = {
    "ok": "✓",
    "skipped": "—",
    "partial": "⚠️",
    "failed": "❌",
}


class FindingSeverity(enum.IntEnum):
    """Lower value = higher severity (sorts blocker → partial → note)."""
    BLOCKER = 0
    PARTIAL = 1
    NOTE = 2


class FindingKind(str, enum.Enum):
    BUILD_ENCODING = "build_encoding"
    BUILD_MISSING_DEP = "build_missing_dep"
    BUILD_INCOMPLETE_DEP = "build_incomplete_dep"
    BUILD_UPSTREAM_BROKEN = "build_upstream_broken"
    EXEC_NETWORK_AT_IMPORT = "exec_network_at_import"
    EXEC_FAILED = "exec_failed"
    METRIC_DRIFT = "metric_drift"
    METRIC_UNVERIFIABLE = "metric_unverifiable"
    PLAN_DEFECT = "plan_defect"
    DATA_AUTO_FETCHED = "data_auto_fetched"
    DATA_FETCH_FAILED = "data_fetch_failed"


_SEVERITY_BADGE = {
    FindingSeverity.BLOCKER: "❌",
    FindingSeverity.PARTIAL: "⚠️",
    FindingSeverity.NOTE: "ℹ️",
}


def _fmt_metric(v) -> str:
    """Render a metric value (numeric or categorical) for the markdown table."""
    if isinstance(v, (int, float)):
        return f"{v:g}"
    return str(v)


@dataclass(frozen=True)
class Finding:
    severity: FindingSeverity
    kind: FindingKind
    step: str           # step id or "(build)" / "(plan)"
    summary: str

NINE_STEP_LABELS = {
    "step_1_hypothesis": "Hypothesis",
    "step_2_data_collection": "Data Collection",
    "step_3_data_processing": "Data Processing",
    "step_4_in_sample": "In-sample Backtesting",
    "step_5_optimization": "Optimization",
    "step_6_out_of_sample": "Out-of-sample Backtesting",
    "step_7_paper_trading": "Paper Trading",
}

VERDICT_BADGE = {
    StepVerdict.REPRODUCED: "✅",
    StepVerdict.PARTIAL: "⚠️",
    StepVerdict.FAILED: "❌",
    StepVerdict.SKIPPED: "⏭",
}


@dataclass(frozen=True)
class RunMeta:
    repo_name: str
    git_url: str
    commit_sha: str
    branch: str
    run_id: str
    duration_seconds: int
    plutus_verify_version: str


def write_reports(
    *,
    out_dir: Path,
    overall: OverallReport,
    meta: RunMeta,
    extraction_notes: list[str],
    nine_step_coverage: dict[str, dict[str, Any]],
    findings: Optional[list[Finding]] = None,
    verification_trail: Optional[list[TrailEntry]] = None,
) -> tuple[Path, Path]:
    """Write ``report.json`` and ``report.md`` under ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"

    ordered_findings = sorted(findings or [], key=lambda f: (f.severity, f.kind.value))
    trail = list(verification_trail or [])
    payload = _build_json_payload(
        overall, meta, extraction_notes, nine_step_coverage, ordered_findings, trail
    )
    save_json(payload, json_path)
    md_path.write_text(
        _render_markdown(
            overall, meta, extraction_notes, nine_step_coverage, ordered_findings, trail
        )
    )
    return json_path, md_path


# ---------- JSON ----------


def _build_json_payload(
    overall: OverallReport,
    meta: RunMeta,
    extraction_notes: list[str],
    nine_step_coverage: dict[str, dict[str, Any]],
    findings: list[Finding],
    verification_trail: list[TrailEntry],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "verdict": overall.verdict.value,
        "exit_code": overall.exit_code,
        "repo": {
            "name": meta.repo_name,
            "git_url": meta.git_url,
            "commit_sha": meta.commit_sha,
            "branch": meta.branch,
        },
        "run": {
            "run_id": meta.run_id,
            "duration_seconds": meta.duration_seconds,
            "plutus_verify_version": meta.plutus_verify_version,
        },
        "findings": [
            {
                "severity": f.severity.name.lower(),
                "kind": f.kind.value,
                "step": f.step,
                "summary": f.summary,
            }
            for f in findings
        ],
        "verification_trail": [
            {
                "stage": t.stage,
                "outcome": t.outcome,
                "duration_seconds": round(t.duration_seconds, 2),
                "summary": t.summary,
                "artifacts": list(t.artifacts),
            }
            for t in verification_trail
        ],
        "nine_step_coverage": nine_step_coverage,
        "steps": [_serialize_step(s) for s in overall.steps],
        "extraction_notes": extraction_notes,
    }


def _serialize_step(s: StepReport) -> dict[str, Any]:
    return {
        "step_id": s.step_id,
        "required": s.required,
        "verdict": s.verdict.value,
        "exec_outcome": s.exec_outcome.value,
        "low_confidence": s.low_confidence,
        "verification_mode": getattr(s, "verification_mode", "execute"),
        "metrics": [_serialize_metric(m) for m in s.metrics],
        "charts": [_serialize_chart(c) for c in s.charts],
    }


def _serialize_metric(m: MetricComparison) -> dict[str, Any]:
    return {
        "name": m.name,
        "expected": m.expected,
        "actual": m.actual,
        "tolerance": {"kind": m.tolerance.kind, "value": m.tolerance.value},
        "pass": m.pass_,
        "unverifiable_reason": m.unverifiable_reason,
    }


def _serialize_chart(c: ChartVerdict) -> dict[str, Any]:
    return {
        "name": c.name,
        "produced_path": c.produced_path,
        "verdict": c.verdict,
        "confidence": c.confidence,
        "rationale": c.rationale,
    }


# ---------- Markdown ----------


def _render_markdown(
    overall: OverallReport,
    meta: RunMeta,
    extraction_notes: list[str],
    nine_step_coverage: dict[str, dict[str, Any]],
    findings: list[Finding],
    verification_trail: list[TrailEntry],
) -> str:
    badge = VERDICT_BADGE[overall.verdict]
    lines: list[str] = []
    lines.append(
        f"# Plutus Verification Report — {meta.repo_name} @ {meta.commit_sha[:7]}"
    )
    lines.append("")
    n_total = sum(1 for s in overall.steps if s.required)
    n_done = sum(
        1 for s in overall.steps if s.required and s.verdict == StepVerdict.REPRODUCED
    )
    lines.append(
        f"**Verdict:** {badge} {overall.verdict.value}  "
        f"({n_done}/{n_total} required steps reproduced)"
    )
    lines.append(
        f"**Run:** {meta.run_id} · {meta.duration_seconds}s · "
        f"plutus-verify v{meta.plutus_verify_version}"
    )
    lines.append(f"**Source:** {meta.git_url} @ `{meta.commit_sha[:12]}` ({meta.branch})")
    lines.append("")

    if findings:
        lines.append("## Findings")
        lines.append("")
        lines.append("| # | Severity | Kind | Step | Summary |")
        lines.append("|--:|:--------:|------|------|---------|")
        for i, f in enumerate(findings, start=1):
            badge = _SEVERITY_BADGE[f.severity]
            lines.append(f"| {i} | {badge} {f.severity.name.lower()} | `{f.kind.value}` | `{f.step}` | {f.summary} |")
        lines.append("")

    if verification_trail:
        lines.append("## Verification Trail")
        lines.append("")
        lines.append("| Stage | Outcome | Duration | Summary | Artifacts |")
        lines.append("|-------|---------|---------:|---------|-----------|")
        for t in verification_trail:
            badge = _TRAIL_OUTCOME_BADGE.get(t.outcome, t.outcome)
            dur = f"{t.duration_seconds:.1f}s"
            artifacts = ", ".join(f"`{a}`" for a in t.artifacts) if t.artifacts else "—"
            lines.append(
                f"| {t.stage} | {badge} {t.outcome} | {dur} | {t.summary} | {artifacts} |"
            )
        lines.append("")
        lines.append("Full chronological log: `run.log`.")
        lines.append("")

    if nine_step_coverage:
        lines.append("## 9-Step Coverage")
        lines.append("")
        lines.append("| Step | Section in README | Coverage | Notes |")
        lines.append("|-----:|--------------------|:--------:|-------|")
        for i, key in enumerate(NINE_STEP_LABELS, start=1):
            entry = nine_step_coverage.get(key, {})
            present = entry.get("present", False)
            heading = entry.get("section_heading") or "(not present)"
            coverage = "✅" if present else "⚠️ missing"
            note = entry.get("note", "")
            lines.append(f"| {i} | {heading} | {coverage} | {note} |")
        lines.append("")

    lines.append("## Per-Step Detail")
    lines.append("")
    for s in overall.steps:
        lines.extend(_render_step(s))
        lines.append("")

    if extraction_notes:
        lines.append("## Extraction Notes (LLM)")
        for n in extraction_notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_step(s: StepReport) -> list[str]:
    badge = VERDICT_BADGE[s.verdict]
    out: list[str] = []
    out.append(f"### {s.step_id}  {badge} {s.verdict.value}")
    mode_note = ""
    if getattr(s, "verification_mode", "execute") == "artifact_check":
        mode_note = " · mode: `artifact_check` (committed artifact verified, not re-run)"
    out.append(f"exec: `{s.exec_outcome.value}` · required: {s.required}{mode_note}")
    if s.metrics:
        out.append("")
        out.append("| Metric | Expected | Actual | Tolerance | ✓ |")
        out.append("|--------|---------:|-------:|:---------:|:-:|")
        for m in s.metrics:
            actual = "—" if m.actual is None else _fmt_metric(m.actual)
            mark = "✅" if m.pass_ else "❌"
            tol = f"{m.tolerance.kind} {m.tolerance.value:g}"
            reason = (
                f" ({m.unverifiable_reason})" if m.unverifiable_reason else ""
            )
            out.append(
                f"| {m.name} | {_fmt_metric(m.expected)} | {actual} | {tol} | {mark}{reason} |"
            )
    if s.charts:
        out.append("")
        out.append("Charts:")
        for c in s.charts:
            conf = f" · conf {c.confidence:.2f}" if c.confidence is not None else ""
            mark = "✅" if c.verdict == "match" else ("⚠️" if c.verdict == "partial" else "❌")
            rat = f" — {c.rationale}" if c.rationale else ""
            out.append(f"- {c.name} ({c.produced_path}) — {mark} {c.verdict}{conf}{rat}")
    return out

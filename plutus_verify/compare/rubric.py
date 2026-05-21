"""Rubric: per-step verdicts + overall exit code.

See docs/plan/ §"Rubric → exit code".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from plutus_verify.compare.metrics import MetricComparison


class StepVerdict(str, Enum):
    REPRODUCED = "reproduced"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ExecOutcome(str, Enum):
    OK = "ok"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ChartVerdict:
    name: str
    produced_path: str
    verdict: str  # "match" | "partial" | "mismatch" | "missing_file" | "skipped"
    confidence: Optional[float] = None
    rationale: Optional[str] = None


@dataclass(frozen=True)
class StepReport:
    step_id: str
    required: bool
    verdict: StepVerdict
    metrics: list[MetricComparison]
    charts: list[ChartVerdict]
    exec_outcome: ExecOutcome
    low_confidence: bool = False
    verification_mode: str = "execute"


@dataclass(frozen=True)
class OverallReport:
    verdict: StepVerdict
    exit_code: int
    steps: list[StepReport] = field(default_factory=list)


def aggregate_step(
    *,
    step_id: str,
    required: bool,
    exec_outcome: ExecOutcome,
    metrics: list[MetricComparison],
    charts: list[ChartVerdict],
    low_confidence: bool = False,
    verification_mode: str = "execute",
) -> StepReport:
    if exec_outcome in (ExecOutcome.FAILED, ExecOutcome.TIMEOUT):
        verdict = StepVerdict.FAILED
    elif exec_outcome == ExecOutcome.SKIPPED:
        verdict = StepVerdict.SKIPPED
    else:
        # exec was clean. Drill into metrics + charts.
        if any(c.verdict in ("missing_file", "mismatch") for c in charts):
            verdict = StepVerdict.FAILED
        elif any(not m.pass_ for m in metrics) or any(
            c.verdict == "partial" for c in charts
        ):
            verdict = StepVerdict.PARTIAL
        else:
            verdict = StepVerdict.REPRODUCED

    return StepReport(
        step_id=step_id,
        required=required,
        verdict=verdict,
        metrics=metrics,
        charts=charts,
        exec_outcome=exec_outcome,
        low_confidence=low_confidence,
        verification_mode=verification_mode,
    )


def aggregate_overall(steps: list[StepReport]) -> OverallReport:
    required = [s for s in steps if s.required]
    if any(s.verdict == StepVerdict.FAILED for s in required):
        return OverallReport(StepVerdict.FAILED, 2, steps)
    if any(s.verdict == StepVerdict.PARTIAL for s in required):
        return OverallReport(StepVerdict.PARTIAL, 1, steps)
    return OverallReport(StepVerdict.REPRODUCED, 0, steps)

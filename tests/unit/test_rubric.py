"""Tests for the rubric: per-step verdicts + overall exit code."""
import pytest

from plutus_verify.compare.metrics import MetricComparison
from plutus_verify.compare.rubric import (
    ChartVerdict,
    ExecOutcome,
    StepVerdict,
    StepReport,
    aggregate_overall,
    aggregate_step,
)
from plutus_verify.extract.plan import Tolerance


def _ok_metric(name: str = "m") -> MetricComparison:
    return MetricComparison(
        name=name,
        expected=1.0,
        actual=1.0,
        tolerance=Tolerance(kind="relative", value=0.05),
        pass_=True,
    )


def _bad_metric(name: str = "m") -> MetricComparison:
    return MetricComparison(
        name=name,
        expected=1.0,
        actual=2.0,
        tolerance=Tolerance(kind="relative", value=0.05),
        pass_=False,
    )


def _unverifiable_metric(name: str = "m") -> MetricComparison:
    return MetricComparison(
        name=name,
        expected=1.0,
        actual=None,
        tolerance=Tolerance(kind="relative", value=0.05),
        pass_=False,
        unverifiable_reason="missing file",
    )


# ---------- per-step verdict ----------


def test_step_reproduced_when_clean_exit_and_all_metrics_and_charts_pass():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.OK,
        metrics=[_ok_metric("a"), _ok_metric("b")],
        charts=[ChartVerdict(name="x", produced_path="x.svg", verdict="match", confidence=0.9)],
    )
    assert isinstance(sr, StepReport)
    assert sr.verdict == StepVerdict.REPRODUCED


def test_step_partial_when_one_metric_out_of_tolerance():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.OK,
        metrics=[_ok_metric(), _bad_metric()],
        charts=[],
    )
    assert sr.verdict == StepVerdict.PARTIAL


def test_step_partial_when_chart_partial():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.OK,
        metrics=[_ok_metric()],
        charts=[ChartVerdict(name="x", produced_path="x.svg", verdict="partial", confidence=0.8)],
    )
    assert sr.verdict == StepVerdict.PARTIAL


def test_step_partial_when_metric_unverifiable():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.OK,
        metrics=[_unverifiable_metric()],
        charts=[],
    )
    assert sr.verdict == StepVerdict.PARTIAL


def test_step_failed_when_exec_failed():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.FAILED,
        metrics=[_ok_metric()],
        charts=[],
    )
    assert sr.verdict == StepVerdict.FAILED


def test_step_failed_when_exec_timeout():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.TIMEOUT,
        metrics=[],
        charts=[],
    )
    assert sr.verdict == StepVerdict.FAILED


def test_step_failed_when_expected_chart_file_missing():
    sr = aggregate_step(
        step_id="step",
        required=True,
        exec_outcome=ExecOutcome.OK,
        metrics=[],
        charts=[ChartVerdict(name="x", produced_path="x.svg", verdict="missing_file")],
    )
    assert sr.verdict == StepVerdict.FAILED


def test_step_skipped_when_optional_and_exec_skipped():
    sr = aggregate_step(
        step_id="optional",
        required=False,
        exec_outcome=ExecOutcome.SKIPPED,
        metrics=[],
        charts=[],
    )
    assert sr.verdict == StepVerdict.SKIPPED


# ---------- overall ----------


def test_overall_exit_zero_when_all_required_reproduced():
    steps = [
        StepReport("s1", True, StepVerdict.REPRODUCED, [], [], ExecOutcome.OK),
        StepReport("s2", True, StepVerdict.REPRODUCED, [], [], ExecOutcome.OK),
        StepReport("opt", False, StepVerdict.SKIPPED, [], [], ExecOutcome.SKIPPED),
    ]
    overall = aggregate_overall(steps)
    assert overall.exit_code == 0
    assert overall.verdict == StepVerdict.REPRODUCED


def test_overall_exit_one_when_required_partial():
    steps = [
        StepReport("s1", True, StepVerdict.REPRODUCED, [], [], ExecOutcome.OK),
        StepReport("s2", True, StepVerdict.PARTIAL, [], [], ExecOutcome.OK),
    ]
    overall = aggregate_overall(steps)
    assert overall.exit_code == 1
    assert overall.verdict == StepVerdict.PARTIAL


def test_overall_exit_two_when_required_failed():
    steps = [
        StepReport("s1", True, StepVerdict.REPRODUCED, [], [], ExecOutcome.OK),
        StepReport("s2", True, StepVerdict.FAILED, [], [], ExecOutcome.FAILED),
    ]
    overall = aggregate_overall(steps)
    assert overall.exit_code == 2
    assert overall.verdict == StepVerdict.FAILED


def test_overall_ignores_optional_failures():
    """An optional step that fails does not raise the exit code beyond what required steps say."""
    steps = [
        StepReport("s1", True, StepVerdict.REPRODUCED, [], [], ExecOutcome.OK),
        StepReport("opt", False, StepVerdict.FAILED, [], [], ExecOutcome.FAILED),
    ]
    overall = aggregate_overall(steps)
    assert overall.exit_code == 0

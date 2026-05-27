"""Tests for the report writers."""
import json
from pathlib import Path

from plutus_verify.compare.metrics import MetricComparison
from plutus_verify.compare.rubric import (
    ChartVerdict,
    ExecOutcome,
    OverallReport,
    StepReport,
    StepVerdict,
)
from plutus_verify.extract.plan import Tolerance
from plutus_verify.report import RunMeta, write_reports


def _sample_overall() -> OverallReport:
    metric = MetricComparison(
        name="sharpe_ratio",
        expected=0.9516,
        actual=0.9498,
        tolerance=Tolerance(kind="relative", value=0.05),
        pass_=True,
    )
    bad_metric = MetricComparison(
        name="annual_return",
        expected=17.10,
        actual=18.50,
        tolerance=Tolerance(kind="absolute", value=1.0),
        pass_=False,
    )
    s1 = StepReport(
        step_id="in_sample_backtest",
        required=True,
        verdict=StepVerdict.REPRODUCED,
        metrics=[metric],
        charts=[ChartVerdict(name="hpr", produced_path="result/backtest/hpr.svg", verdict="match", confidence=0.92)],
        exec_outcome=ExecOutcome.OK,
    )
    s2 = StepReport(
        step_id="out_of_sample",
        required=True,
        verdict=StepVerdict.PARTIAL,
        metrics=[bad_metric],
        charts=[ChartVerdict(name="drawdown", produced_path="result/optimization/drawdown.svg", verdict="partial", confidence=0.72)],
        exec_outcome=ExecOutcome.OK,
    )
    return OverallReport(verdict=StepVerdict.PARTIAL, exit_code=1, steps=[s1, s2])


def _meta() -> RunMeta:
    return RunMeta(
        repo_name="ProtoMarketMaker",
        git_url="https://github.com/algotrade-plutus/ProtoMarketMaker",
        commit_sha="abc1234567",
        branch="main",
        run_id="2026-05-15T10-21Z",
        duration_seconds=724,
        plutus_verify_version="0.2.6",
    )


def test_write_reports_creates_json_and_markdown(tmp_path: Path):
    json_path, md_path = write_reports(
        out_dir=tmp_path,
        overall=_sample_overall(),
        meta=_meta(),
        extraction_notes=["Step 3 not present"],
        nine_step_coverage={
            f"step_{i}_{name}": {"present": p, "section_heading": h}
            for i, (name, p, h) in enumerate(
                [
                    ("hypothesis", True, "Hypothesis"),
                    ("data_collection", True, "Data Collection"),
                    ("data_processing", False, None),
                    ("in_sample", True, "In-sample Backtesting"),
                    ("optimization", True, "Optimization"),
                    ("out_of_sample", True, "Out-of-sample Backtesting"),
                    ("paper_trading", False, None),
                ],
                start=1,
            )
        },
    )
    assert json_path.exists()
    assert md_path.exists()

    payload = json.loads(json_path.read_text())
    assert payload["verdict"] == "partial"
    assert payload["exit_code"] == 1
    assert payload["repo"]["name"] == "ProtoMarketMaker"
    assert len(payload["steps"]) == 2
    assert payload["steps"][1]["metrics"][0]["pass"] is False

    md = md_path.read_text()
    assert "ProtoMarketMaker" in md
    assert "abc1234567"[:7] in md
    assert "Sharpe Ratio" in md or "sharpe_ratio" in md
    assert "## 9-Step Coverage" in md
    assert "⚠️" in md  # partial badge


def test_findings_block_present_and_severity_sorted(tmp_path: Path):
    """Findings: blockers first, then partials, then notes."""
    from plutus_verify.report import Finding, FindingKind, FindingSeverity
    findings = [
        Finding(severity=FindingSeverity.NOTE, kind=FindingKind.BUILD_ENCODING,
                step="(build)", summary="auto-fixed UTF-16 BOM in requirements.txt"),
        Finding(severity=FindingSeverity.BLOCKER, kind=FindingKind.EXEC_FAILED,
                step="data_processing", summary="ImportError vnstock_ezchart.static"),
        Finding(severity=FindingSeverity.PARTIAL, kind=FindingKind.METRIC_DRIFT,
                step="out_of_sample", summary="OOS Sharpe drifted 26%"),
    ]
    json_path, md_path = write_reports(
        out_dir=tmp_path,
        overall=_sample_overall(),
        meta=_meta(),
        extraction_notes=[],
        nine_step_coverage={},
        findings=findings,
    )
    payload = json.loads(json_path.read_text())
    # JSON: findings list in severity order (blocker → partial → note)
    kinds = [f["kind"] for f in payload["findings"]]
    assert kinds[0] == "exec_failed"        # blocker
    assert kinds[1] == "metric_drift"        # partial
    assert kinds[2] == "build_encoding"      # note

    md = md_path.read_text()
    # MD: a Findings section appears above 9-step coverage
    assert "## Findings" in md
    finding_idx = md.index("## Findings")
    coverage_idx = md.index("## 9-Step Coverage") if "## 9-Step Coverage" in md else len(md)
    assert finding_idx < coverage_idx
    # All 3 findings render
    assert "vnstock_ezchart" in md
    assert "drifted" in md
    assert "BOM" in md


def test_verification_trail_section_renders(tmp_path: Path):
    """Verification Trail table appears in report.md with one row per stage."""
    from plutus_verify.report import TrailEntry
    trail = [
        TrailEntry(stage="ingest", outcome="ok", duration_seconds=0.8,
                   summary="cloned 7f8a3c1", artifacts=["meta.json"]),
        TrailEntry(stage="build", outcome="ok", duration_seconds=87.2,
                   summary="image plutus-run-x (2 adjustments)",
                   artifacts=["build/attempt_*.log"]),
        TrailEntry(stage="execute", outcome="partial", duration_seconds=42.0,
                   summary="2 ran, 1 skipped, 0 failed",
                   artifacts=["execute/<step>.{stdout,stderr,meta.json}"]),
    ]
    json_path, md_path = write_reports(
        out_dir=tmp_path,
        overall=_sample_overall(),
        meta=_meta(),
        extraction_notes=[],
        nine_step_coverage={},
        findings=[],
        verification_trail=trail,
    )
    md = md_path.read_text()
    assert "## Verification Trail" in md
    # Each stage row present
    assert "| ingest |" in md
    assert "| build |" in md
    assert "| execute |" in md
    # Outcome badges
    assert "ok" in md
    assert "partial" in md
    # Artifact references
    assert "`meta.json`" in md
    assert "Full chronological log: `run.log`." in md

    payload = json.loads(json_path.read_text())
    assert "verification_trail" in payload
    assert len(payload["verification_trail"]) == 3
    assert payload["verification_trail"][0]["stage"] == "ingest"
    assert payload["verification_trail"][1]["summary"].startswith("image")


def test_verification_trail_omitted_when_empty(tmp_path: Path):
    json_path, md_path = write_reports(
        out_dir=tmp_path,
        overall=_sample_overall(),
        meta=_meta(),
        extraction_notes=[],
        nine_step_coverage={},
        findings=[],
    )
    md = md_path.read_text()
    assert "## Verification Trail" not in md
    payload = json.loads(json_path.read_text())
    assert payload["verification_trail"] == []


def test_findings_omitted_when_empty(tmp_path: Path):
    """No findings → no Findings section in markdown."""
    json_path, md_path = write_reports(
        out_dir=tmp_path,
        overall=_sample_overall(),
        meta=_meta(),
        extraction_notes=[],
        nine_step_coverage={},
        findings=[],
    )
    md = md_path.read_text()
    assert "## Findings" not in md


def test_write_reports_handles_unverifiable_metric(tmp_path: Path):
    overall = OverallReport(
        verdict=StepVerdict.PARTIAL,
        exit_code=1,
        steps=[
            StepReport(
                step_id="opt",
                required=True,
                verdict=StepVerdict.PARTIAL,
                metrics=[
                    MetricComparison(
                        name="step",
                        expected=3.1,
                        actual=None,
                        tolerance=Tolerance(kind="absolute", value=0.5),
                        pass_=False,
                        unverifiable_reason="file not found: parameter/optimized_parameter.json",
                    )
                ],
                charts=[],
                exec_outcome=ExecOutcome.OK,
            )
        ],
    )
    json_path, md_path = write_reports(
        out_dir=tmp_path,
        overall=overall,
        meta=_meta(),
        extraction_notes=[],
        nine_step_coverage={},
    )
    payload = json.loads(json_path.read_text())
    assert payload["steps"][0]["metrics"][0]["actual"] is None
    assert (
        payload["steps"][0]["metrics"][0]["unverifiable_reason"]
        == "file not found: parameter/optimized_parameter.json"
    )
    md = md_path.read_text()
    assert "unverifiable" in md.lower() or "not found" in md.lower()

"""Tests for the native v2 orchestrator."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.loader import load_manifest_from_yaml_text
from plutus_verify.spec.runtime.orchestrator import V2RuntimeResult, run_v2_pipeline


_YAML = """\
schema_version: "2.0"
repo: {name: T, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "echo data"
    outputs: ["data/raw/x"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo backtest"
    inputs: [data/raw]
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    headlines:
      - name: sharpe
        value: 0.85
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []
nine_step_coverage: {}
"""


def _stage_repo(tmp_path: Path):
    """Pre-create files the steps' inputs/outputs check expects."""
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "x").write_text("ok")
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.86}')


def test_runtime_runs_all_steps_and_compares_headlines(tmp_path):
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)
    image_builder = MagicMock(return_value="built-image-tag")
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1,
    )

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert isinstance(result, V2RuntimeResult)
    assert result.image == "built-image-tag"
    image_builder.assert_called_once()
    assert runner.run.call_count == 2  # data_collection + in_sample
    assert result.headline_results["in_sample"]["sharpe"].ok


def test_runtime_skips_steps_satisfied_by_data_source(tmp_path):
    _stage_repo(tmp_path)
    yaml = _YAML.replace(
        "data_sources: {processed: [], raw: []}",
        """data_sources:
  processed: []
  raw:
    - kind: github_release
      url: https://example.com/raw.tar.gz
      expected_layout: ["data/raw/x"]
      satisfies: [data_collection]""",
    )
    manifest = load_manifest_from_yaml_text(yaml)
    image_builder = MagicMock(return_value="img")
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
        downloader=lambda *a, **kw: True,  # pretend download succeeds
    )

    # data_collection skipped → only in_sample ran
    assert runner.run.call_count == 1
    assert result.data_tier_used == "raw"


def test_runtime_propagates_step_failure(tmp_path):
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)
    runner = MagicMock()
    # data_collection fails — in_sample should still be attempted? Per design,
    # downstream steps that declare it as depends_on skip. With no depends_on,
    # in_sample runs anyway. The orchestrator records the failure but does not
    # raise — it surfaces in `result.step_results`.
    runner.run.side_effect = [
        MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1),
        MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1),
    ]

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert result.step_results["data_collection"].exit_code == 1
    assert result.step_results["in_sample"].exit_code == 0


def test_runtime_preflight_failure_marks_step_skipped(tmp_path):
    """If input is missing AND not satisfied by a data source, step should
    surface a clear preflight error in step_results."""
    # in_sample needs data/raw but we don't pre-stage it
    manifest = load_manifest_from_yaml_text(_YAML)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    # data_collection has no inputs, runs OK; outputs missing → preflight failure post-run
    dc = result.step_results["data_collection"]
    assert dc.preflight_error is not None
    assert "missing output" in dc.preflight_error


_STDOUT_TABLE_YAML = """\
schema_version: "2.0"
repo: {name: T, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo backtest"
    outputs: ["result.txt"]
expected:
  - step_id: in_sample
    headlines:
      - name: Sharpe Ratio
        value: 0.95
        locate: {kind: stdout_table, row: "Sharpe Ratio", col: 1}
        tolerance: {kind: relative, value: 0.05}
      - name: MDD
        value: -0.20
        locate: {kind: stdout_table, row: "Maximum Drawdown (MDD)", col: 1}
        tolerance: {kind: absolute, value: 0.02}
    reference_outputs: []
nine_step_coverage: {}
"""


_SAMPLE_STDOUT_TABLE = """\
running backtest...

| Metric                 | Value                              |
|------------------------|------------------------------------|
| Sharpe Ratio           | 0.9516                             |
| Sortino Ratio          | 1.3490                             |
| Maximum Drawdown (MDD) | -0.2010                            |
"""


def test_runtime_stdout_table_locator_picks_up_metrics_from_step_stdout(tmp_path):
    """Headline metrics with locate.kind=stdout_table read from the matching
    step's captured stdout, not from any file in the repo."""
    (tmp_path / "result.txt").write_text("ok")
    manifest = load_manifest_from_yaml_text(_STDOUT_TABLE_YAML)
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout=_SAMPLE_STDOUT_TABLE, stderr="", duration_seconds=0.1,
    )

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    sharpe = result.headline_results["in_sample"]["Sharpe Ratio"]
    assert sharpe.actual == 0.9516
    assert sharpe.ok  # within ±5% of 0.95

    mdd = result.headline_results["in_sample"]["MDD"]
    assert mdd.actual == -0.2010
    assert mdd.ok  # within ±0.02 of -0.20


def test_runtime_stdout_table_missing_row_reports_failure(tmp_path):
    """Row not present in stdout → headline marked not-ok with diagnostic detail."""
    (tmp_path / "result.txt").write_text("ok")
    manifest = load_manifest_from_yaml_text(_STDOUT_TABLE_YAML)
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="no table here", stderr="", duration_seconds=0.1,
    )

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    sharpe = result.headline_results["in_sample"]["Sharpe Ratio"]
    assert not sharpe.ok
    assert "not found" in sharpe.detail.lower()

"""Tests for the native v2 orchestrator."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.sdk import step as pv_step
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

    # Pre-write the results.json that the (fake) script would have produced.
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("sharpe", 0.86, unit="ratio")

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
    hr = result.headline_results["in_sample"]["sharpe"]
    assert hr.ok is True
    assert hr.actual == 0.86
    assert hr.expected == 0.85


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


# --- Plan 6 / Task 4: headline comparison reads results.json by metric name ---


def _make_manifest_with_headlines(headlines_yaml: str) -> str:
    """Build a manifest YAML string with the given headlines block."""
    return f"""\
schema_version: "2.0"
repo: {{name: T, primary_language: python}}
env: {{base: python, python_version: "3.11", requirements_file: requirements.txt}}
secrets: []
data_sources: {{processed: [], raw: []}}
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
{headlines_yaml}
    reference_outputs: []
nine_step_coverage: {{}}
"""


def _runner_ok():
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )
    return runner


def test_headline_passes_when_results_json_value_matches_within_tolerance(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("sharpe_ratio", 0.95, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.headline_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is True
    assert hr.actual == 0.95
    assert hr.expected == 0.95


def test_headline_fails_when_results_json_value_outside_tolerance(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("sharpe_ratio", 0.80, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.headline_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is False
    assert hr.actual == 0.80
    assert hr.expected == 0.95
    assert "0.95" in hr.detail  # tolerance detail mentions the expected value


def test_missing_results_json_fails_every_headline(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
        "      - name: sortino_ratio\n"
        "        value: 1.10\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)
    # NOTE: no SDK call — results.json is absent

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hrs = result.headline_results["in_sample"]
    assert set(hrs.keys()) == {"sharpe_ratio", "sortino_ratio"}
    for name, hr in hrs.items():
        assert hr.ok is False
        assert hr.actual is None
        assert "results.json missing" in hr.detail


def test_metric_not_produced_fails_only_that_headline(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
        "      - name: sortino_ratio\n"
        "        value: 1.10\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    # Write only sharpe_ratio — sortino_ratio is absent.
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("sharpe_ratio", 0.95, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hrs = result.headline_results["in_sample"]
    assert hrs["sharpe_ratio"].ok is True
    assert hrs["sharpe_ratio"].actual == 0.95

    assert hrs["sortino_ratio"].ok is False
    assert hrs["sortino_ratio"].actual is None
    assert "not produced" in hrs["sortino_ratio"].detail
    assert "sortino_ratio" in hrs["sortino_ratio"].detail


def test_relative_tolerance_pass_within_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: sharpe_ratio\n"
        "        value: 1.0\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("sharpe_ratio", 1.04, unit="ratio")  # 4% off → within 5%

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.headline_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is True


def test_relative_tolerance_fail_outside_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: sharpe_ratio\n"
        "        value: 1.0\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("sharpe_ratio", 1.10, unit="ratio")  # 10% off → outside 5%

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.headline_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is False
    assert hr.actual == 1.10


def test_absolute_tolerance_pass_within_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: max_drawdown\n"
        "        value: -0.20\n"
        "        tolerance: {kind: absolute, value: 0.02}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("max_drawdown", -0.21, unit="ratio")  # |diff|=0.01 ≤ 0.02

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.headline_results["in_sample"]["max_drawdown"]
    assert hr.ok is True
    assert hr.actual == -0.21


def test_absolute_tolerance_fail_outside_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_headlines(
        "      - name: max_drawdown\n"
        "        value: -0.20\n"
        "        tolerance: {kind: absolute, value: 0.02}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.headline("max_drawdown", -0.25, unit="ratio")  # |diff|=0.05 > 0.02

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.headline_results["in_sample"]["max_drawdown"]
    assert hr.ok is False
    assert hr.actual == -0.25

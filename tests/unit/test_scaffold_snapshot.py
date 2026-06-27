"""Tests for `plutus snapshot`."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from plutus_verify.scaffold.init import scaffold_init
from plutus_verify.scaffold.snapshot import SnapshotResult, scaffold_snapshot
from plutus_verify.sdk import step as pv_step


def _stage_repo(tmp_path: Path, with_outputs: bool = True):
    scaffold_init(tmp_path)
    if with_outputs:
        (tmp_path / "out").mkdir(exist_ok=True)
        (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
        (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "raw" / "x.parquet").write_text("ok")
        (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "processed" / "x.parquet").write_text("ok")


def _read_metric_value(repo_path: Path, step_id: str, name: str) -> float:
    """Re-load the on-disk manifest and return the named metric value."""
    text = (repo_path / ".plutus" / "manifest.yaml").read_text()
    data = yaml.safe_load(text)
    for block in data["expected"]:
        if block["step_id"] == step_id:
            for h in block.get("metrics") or []:
                if h["name"] == name:
                    return h["value"]
    raise KeyError(f"no metric {name!r} for step {step_id!r}")


_TWO_STEP_MANIFEST = """\
schema_version: "2.0"

repo:
  name: demo
  primary_language: python

env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt

secrets: []

data_sources:
  processed: []
  raw: []

steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.in_sample"
    outputs: ["out/in.json"]
  - id: out_of_sample
    nine_step: step_6_out_of_sample
    required: true
    command: "python -m demo.out_of_sample"
    outputs: ["out/out.json"]

expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.0
        tolerance: {kind: relative, value: 0.05}
      - name: maximum_drawdown
        value: 0.0
        tolerance: {kind: relative, value: 0.05}
    artifacts: []
  - step_id: out_of_sample
    metrics:
      - name: sharpe_ratio
        value: 0.0
        tolerance: {kind: relative, value: 0.05}
      - name: maximum_drawdown
        value: 0.0
        tolerance: {kind: relative, value: 0.05}
    artifacts: []

nine_step_coverage:
  step_1_hypothesis: {present: true, section: "hyp"}
  step_2_data_preparation: {present: true, section: "dc"}
  step_3_forming_set_of_rules: {present: true, section: "dp"}
  step_4_in_sample: {present: true, section: "is"}
  step_5_optimization: {present: false, section: null}
  step_6_out_of_sample: {present: true, section: "oos"}
  step_7_paper_trading: {present: false, section: null}
"""


def test_snapshot_without_run_copies_existing_outputs(tmp_path: Path):
    _stage_repo(tmp_path)
    res = scaffold_snapshot(tmp_path, run_check_first=False)
    assert isinstance(res, SnapshotResult)
    expected_root = tmp_path / ".plutus" / "expected"
    assert (expected_root / "in_sample" / "out" / "metrics.json").exists()
    # The skeleton's data_* steps declare outputs ending in / (directory globs);
    # snapshot should copy whatever's there.
    assert res.files_copied >= 1


def test_snapshot_skips_missing_outputs_with_warning(tmp_path: Path):
    _stage_repo(tmp_path, with_outputs=False)
    res = scaffold_snapshot(tmp_path, run_check_first=False)
    # Nothing to copy → still returns, just files_copied=0 and notes mentions skipped
    assert res.files_copied == 0
    assert any("missing" in n.lower() for n in res.notes)


def test_snapshot_with_run_blesses_from_results_buffer_and_writes_result(tmp_path: Path):
    """L1+L2: snapshot runs in-container, harvests produced outputs to
    .plutus/results/, then blesses from there into both .plutus/expected/
    (groundtruth) and the working tree (human-facing result/)."""
    _stage_repo(tmp_path)

    def fake_run(**kwargs):
        # Simulate the in_sample container producing its declared output.
        c = Path(kwargs["cwd"])
        (c / "out").mkdir(parents=True, exist_ok=True)
        (c / "out" / "metrics.json").write_text('{"sharpe": 1.23}')
        return MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    runner = MagicMock()
    runner.run.side_effect = fake_run
    res = scaffold_snapshot(
        tmp_path,
        run_check_first=True,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    # check ran (image_builder called); snapshot copied from the results buffer
    assert res.check_result is not None
    assert res.files_copied >= 1
    # groundtruth blessed under .plutus/expected/<step>/
    assert (
        tmp_path / ".plutus" / "expected" / "in_sample" / "out" / "metrics.json"
    ).read_text() == '{"sharpe": 1.23}'
    # human-facing copy written into the working tree (result/ = declared path)
    assert (tmp_path / "out" / "metrics.json").read_text() == '{"sharpe": 1.23}'


def test_snapshot_with_run_aborts_on_check_failure(tmp_path: Path):
    """If `plutus check` fails (required step non-zero), snapshot should not
    overwrite reference outputs from a failing run."""
    _stage_repo(tmp_path)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1)

    with pytest.raises(RuntimeError, match="check failed"):
        scaffold_snapshot(
            tmp_path,
            run_check_first=True,
            image_builder=MagicMock(return_value="img"),
            runner=runner,
            vision_client=None,
            secrets={},
        )


def test_snapshot_updates_metric_values_from_results_json(tmp_path: Path):
    _stage_repo(tmp_path)
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.95, unit="ratio")

    res = scaffold_snapshot(tmp_path, run_check_first=False)
    assert res.metrics_updated == 1
    assert _read_metric_value(tmp_path, "in_sample", "sharpe_ratio") == 0.95


def test_snapshot_update_metric_values_false_skips_update(tmp_path: Path):
    _stage_repo(tmp_path)
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.95, unit="ratio")

    res = scaffold_snapshot(
        tmp_path, run_check_first=False, update_metric_values=False
    )
    assert res.metrics_updated == 0
    # Manifest's value: still the placeholder.
    assert _read_metric_value(tmp_path, "in_sample", "sharpe_ratio") == 0.0


def test_snapshot_missing_results_json_appends_note(tmp_path: Path):
    _stage_repo(tmp_path)
    # No results.json written for in_sample.
    res = scaffold_snapshot(tmp_path, run_check_first=False)
    assert res.metrics_updated == 0
    assert any(
        "results.json" in n and "in_sample" in n for n in res.notes
    ), f"expected a note mentioning results.json and in_sample, got: {res.notes}"


def test_snapshot_extra_metric_in_results_skipped_silently(tmp_path: Path):
    _stage_repo(tmp_path)
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.95, unit="ratio")
        r.metric("sortino_ratio", 1.20, unit="ratio")

    res = scaffold_snapshot(tmp_path, run_check_first=False)
    # Only sharpe was declared in the skeleton manifest; sortino is silently dropped.
    assert res.metrics_updated == 1
    assert not any("sortino" in n for n in res.notes), (
        f"snapshot should pre-filter to declared metrics, but got note about "
        f"sortino: {res.notes}"
    )
    assert _read_metric_value(tmp_path, "in_sample", "sharpe_ratio") == 0.95


def test_snapshot_update_artifacts_false_skips_copy(tmp_path: Path):
    _stage_repo(tmp_path)
    res = scaffold_snapshot(
        tmp_path, run_check_first=False, update_artifacts=False
    )
    assert res.files_copied == 0
    # The expected/<step>/ subdirectory tree should not have been created.
    expected_root = tmp_path / ".plutus" / "expected"
    # `scaffold_init` creates `.plutus/expected/` itself, but no per-step subdirs.
    assert not any(p.is_dir() for p in expected_root.iterdir()), (
        f"expected/ subtree should be empty when update_artifacts=False; "
        f"got: {list(expected_root.iterdir())}"
    )


def test_snapshot_both_flags_off_is_noop_on_disk(tmp_path: Path):
    _stage_repo(tmp_path)
    manifest_before = (tmp_path / ".plutus" / "manifest.yaml").read_text()

    res = scaffold_snapshot(
        tmp_path,
        run_check_first=False,
        update_artifacts=False,
        update_metric_values=False,
    )
    assert res.files_copied == 0
    assert res.metrics_updated == 0
    # Manifest text is byte-identical.
    manifest_after = (tmp_path / ".plutus" / "manifest.yaml").read_text()
    assert manifest_before == manifest_after
    # expected/ has no per-step subdirs.
    expected_root = tmp_path / ".plutus" / "expected"
    assert not any(p.is_dir() for p in expected_root.iterdir())


def test_snapshot_handles_multiple_steps_with_metrics(tmp_path: Path):
    scaffold_init(tmp_path)
    # Overwrite the manifest with our two-step variant.
    (tmp_path / ".plutus" / "manifest.yaml").write_text(_TWO_STEP_MANIFEST)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 1.10, unit="ratio")
        r.metric("maximum_drawdown", 0.18, unit="fraction")
    with pv_step("out_of_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.85, unit="ratio")
        r.metric("maximum_drawdown", 0.22, unit="fraction")

    res = scaffold_snapshot(tmp_path, run_check_first=False)
    assert res.metrics_updated == 4
    assert _read_metric_value(tmp_path, "in_sample", "sharpe_ratio") == 1.10
    assert _read_metric_value(tmp_path, "in_sample", "maximum_drawdown") == 0.18
    assert _read_metric_value(tmp_path, "out_of_sample", "sharpe_ratio") == 0.85
    assert _read_metric_value(tmp_path, "out_of_sample", "maximum_drawdown") == 0.22

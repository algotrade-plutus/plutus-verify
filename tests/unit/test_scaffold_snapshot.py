"""Tests for `plutus snapshot`."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.init import scaffold_init
from plutus_verify.scaffold.snapshot import SnapshotResult, scaffold_snapshot


def _stage_repo(tmp_path: Path, with_outputs: bool = True):
    scaffold_init(tmp_path)
    if with_outputs:
        (tmp_path / "out").mkdir(exist_ok=True)
        (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
        (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "raw" / "x.parquet").write_text("ok")
        (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "processed" / "x.parquet").write_text("ok")


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


def test_snapshot_with_run_runs_check_first(tmp_path: Path):
    _stage_repo(tmp_path)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
    res = scaffold_snapshot(
        tmp_path,
        run_check_first=True,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    # check ran (image_builder called); snapshot copied
    assert res.check_result is not None
    assert res.files_copied >= 1


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

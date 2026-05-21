"""Tests for `plutus check` (programmatic API)."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.check import CheckResult, scaffold_check
from plutus_verify.scaffold.init import scaffold_init


def test_check_returns_result_when_manifest_valid(tmp_path: Path):
    scaffold_init(tmp_path)
    # Pre-stage so the dummy run doesn't fail preflight
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="dummy-image"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert isinstance(res, CheckResult)
    assert res.runtime_result.image == "dummy-image"
    assert res.exit_code in (0, 1, 2)


def test_check_missing_manifest_raises(tmp_path: Path):
    from plutus_verify.spec.loader import ManifestLoadError

    with pytest.raises(ManifestLoadError):
        scaffold_check(
            tmp_path,
            image_builder=MagicMock(),
            runner=MagicMock(),
            vision_client=None,
            secrets={},
        )


def test_check_exit_code_zero_when_all_pass(tmp_path: Path):
    """All steps exit 0, headlines pass → exit 0."""
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert res.exit_code == 0


def test_check_exit_code_two_when_required_step_fails(tmp_path: Path):
    """A required step exits non-zero → exit 2."""
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1)
    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert res.exit_code == 2

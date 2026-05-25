"""Tests for `plutus check` (programmatic API)."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.check import CheckResult, scaffold_check
from plutus_verify.scaffold.init import scaffold_init
from plutus_verify.sdk import step as pv_step


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
    """All required steps exit 0 and the SDK-written results.json carries the
    expected metric value — `plutus check` returns exit 0.

    Note: scaffold_check wipes .plutus/run/ at the start, so the runner mock
    writes results.json DURING the run (mid-pipeline) rather than the test
    pre-staging it — that mirrors what a real container would do.
    """
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()

    def fake_run(**kwargs):
        # When the in_sample script runs, simulate it writing results.json
        # the same way an instrumented script with `pv.step` would.
        if "TODO_python_module_to_backtest" in kwargs.get("command", "") or "in_sample" in kwargs.get("command", ""):
            with pv_step("in_sample", repo_path=tmp_path) as r:
                r.metric("sharpe_ratio", 0.0, unit="ratio")
        return MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    runner.run.side_effect = fake_run
    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert res.exit_code == 0


def test_check_wipes_stale_run_dir_before_pipeline(tmp_path: Path):
    """A stale .plutus/run/<step>/results.json from a previous run must be
    wiped before this run, so the comparison phase reads only what THIS run
    produced. Prevents the stale-results false-positive class of bug.
    """
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    # Pre-stage a stale results.json that would match the manifest exactly.
    # Without the wipe, this would produce a false-positive "ok" even though
    # the (mock) container never actually ran our backtest.
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.0, unit="ratio")
    stale = tmp_path / ".plutus" / "run" / "in_sample" / "results.json"
    assert stale.exists()

    # Runner exits non-zero (script crashed) — and does NOT write a fresh
    # results.json. The wipe + skip-on-failed-step combo should report the
    # metric as not-evaluated, not as "ok" from the stale file.
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=1, stdout="", stderr="boom", duration_seconds=0.1
    )

    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert not stale.exists(), "stale results.json should have been wiped"
    # Exit 2 (required step failed); metric reports failure with the
    # "step failed" diagnostic, not a false "ok".
    assert res.exit_code == 2
    hr = res.runtime_result.metric_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is False
    assert "step 'in_sample' failed" in hr.detail


def test_check_exit_code_one_when_metric_missing(tmp_path: Path):
    """All required steps exit 0 but the SDK never wrote results.json — the
    metric comparison fails, surfacing a soft-fail (exit code 1)."""
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
    assert res.exit_code == 1


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

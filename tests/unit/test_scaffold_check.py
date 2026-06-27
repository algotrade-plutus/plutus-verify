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
        # Simulate a real container: write the steps' declared outputs into the
        # staging cwd so the orchestrator can harvest them to .plutus/results/.
        c = Path(kwargs["cwd"])
        (c / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (c / "data" / "processed" / "x.parquet").write_text("ok")
        (c / "out").mkdir(parents=True, exist_ok=True)
        (c / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
        # When the in_sample script runs, also write results.json the same way
        # an instrumented script with `pv.step` would.
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


def test_check_wipes_stale_results_buffer_before_pipeline(tmp_path: Path):
    """A stale .plutus/results/<step>/ artifact from a previous run must be
    wiped before this run, so the compare phase reads only what THIS run
    produced (symmetric to the .plutus/run/ wipe)."""
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    stale = tmp_path / ".plutus" / "results" / "in_sample" / "out" / "metrics.json"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"sharpe": 999}')

    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )
    scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert not stale.exists(), "stale .plutus/results/ should have been wiped"


def test_check_exit_code_one_when_metric_missing(tmp_path: Path):
    """All required steps exit 0 but the SDK never wrote results.json — the
    metric comparison fails, surfacing a soft-fail (exit code 1)."""
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()

    def fake_run(**kwargs):
        # Steps produce their declared outputs (so they pass the output check),
        # but the SDK never writes results.json — the metric comparison fails.
        c = Path(kwargs["cwd"])
        (c / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (c / "data" / "processed" / "x.parquet").write_text("ok")
        (c / "out").mkdir(parents=True, exist_ok=True)
        (c / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
        return MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    runner.run.side_effect = fake_run
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


def test_exit_code_warn_artifact_does_not_fail():
    """A WARN artifact (ok=False, skipped=True) must not flip exit code to 1.

    Direct test of the `_exit_code` helper so we don't have to drive
    the full Docker-mocked pipeline just to assert this rule.
    """
    from plutus_verify.scaffold.check import _exit_code
    from plutus_verify.spec.manifest import (
        DataSourceTiers,
        Env,
        Manifest,
        Repo,
        Step,
    )
    from plutus_verify.spec.runtime.artifact_compare import CompareResult
    from plutus_verify.spec.runtime.orchestrator import (
        StepRuntimeResult,
        V2RuntimeResult,
    )

    manifest = Manifest(
        schema_version="2.0",
        repo=Repo(name="t", primary_language="python"),
        env=Env(base="python", python_version="3.11", requirements_file="r.txt"),
        secrets=(),
        data_sources=DataSourceTiers(),
        steps=(Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),),
        expected=(),
    )
    runtime = V2RuntimeResult(image="img", data_tier_used="raw")
    runtime.step_results["in_sample"] = StepRuntimeResult(
        step_id="in_sample", exit_code=0, duration_seconds=0.1
    )
    runtime.artifact_results["in_sample"] = [
        CompareResult(
            ok=False,
            skipped=True,
            kind="byte_identical",
            path="result/hpr.svg",
            detail="bytes differ; pass --visual-check for LLM judgment",
        ),
    ]
    assert _exit_code(manifest, runtime) == 0, (
        "WARN (ok=False, skipped=True) must not promote exit code to 1"
    )

    # Sanity check: a true FAIL (ok=False, skipped=False) still flips to 1.
    runtime.artifact_results["in_sample"] = [
        CompareResult(
            ok=False,
            skipped=False,
            kind="byte_exact",
            path="result/data.csv",
            detail="bytes differ",
        ),
    ]
    assert _exit_code(manifest, runtime) == 1

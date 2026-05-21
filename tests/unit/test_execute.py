"""Tests for the execute stage: step DAG runner with an injectable Runner."""
import json
from pathlib import Path

import pytest

from plutus_verify.compare.rubric import ExecOutcome
from plutus_verify.execute import (
    ExecResult,
    Runner,
    run_plan,
)
from plutus_verify.extract.plan import Step, StepAlternative
from tests.unit.test_plan_schema import _minimal_valid_plan
from plutus_verify.extract.plan import parse_plan
from plutus_verify.util.progress import Progress


class _FakeRunner(Runner):
    """A scripted runner: dict of {command -> ExecResult}."""

    def __init__(self, scripted: dict[str, ExecResult]) -> None:
        self._scripted = scripted
        self.calls: list[tuple[str, str, str]] = []  # (image, command, network)

    def run(
        self,
        *,
        image: str,
        command: str,
        cwd: Path,
        network: str,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        self.calls.append((image, command, network))
        if command not in self._scripted:
            return ExecResult(
                exit_code=127,
                stdout="",
                stderr=f"command not scripted: {command}",
                duration_seconds=0.0,
                outcome=ExecOutcome.FAILED,
            )
        return self._scripted[command]


def _ok(stdout: str = "ok\n") -> ExecResult:
    return ExecResult(
        exit_code=0,
        stdout=stdout,
        stderr="",
        duration_seconds=1.0,
        outcome=ExecOutcome.OK,
    )


def _fail() -> ExecResult:
    return ExecResult(
        exit_code=1,
        stdout="",
        stderr="boom",
        duration_seconds=0.5,
        outcome=ExecOutcome.FAILED,
    )


def test_run_plan_executes_each_step_once(tmp_path: Path):
    plan = parse_plan(_minimal_valid_plan())
    runner = _FakeRunner({"python backtesting.py": _ok("| Sharpe Ratio | 0.95 |\n")})
    outputs = run_plan(plan, image="plutus-run-x", repo_path=tmp_path, runner=runner)
    assert len(runner.calls) == 1
    assert outputs["in_sample_backtest"].outcome == ExecOutcome.OK
    assert "Sharpe Ratio" in outputs["in_sample_backtest"].stdout


def test_run_plan_skips_dependents_when_dependency_fails(tmp_path: Path):
    """A failed step's dependents are marked SKIPPED, not executed."""
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"].insert(
        0,
        {
            "id": "preflight",
            "nine_step": "step_2_data_collection",
            "required": True,
            "command": "python prep.py",
            "network": "none",
            "timeout_seconds": 60,
        },
    )
    plan_dict["steps"][1]["depends_on"] = ["preflight"]
    plan = parse_plan(plan_dict)

    runner = _FakeRunner(
        {"python prep.py": _fail(), "python backtesting.py": _ok()}
    )
    outputs = run_plan(plan, image="img", repo_path=tmp_path, runner=runner)
    assert outputs["preflight"].outcome == ExecOutcome.FAILED
    assert outputs["in_sample_backtest"].outcome == ExecOutcome.SKIPPED
    # the skipped dependent never reached the runner
    assert all("backtesting.py" not in c[1] for c in runner.calls)


def test_run_plan_prefers_first_alternative_when_secrets_available(tmp_path: Path):
    """For a step with `alternatives`, pick the first whose secrets are satisfied."""
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"].insert(
        0,
        {
            "id": "data_collection",
            "nine_step": "step_2_data_collection",
            "required": False,
            "alternatives": [
                {
                    "label": "google_drive",
                    "kind": "manual_download",
                    "url": "https://drive.google.com/xyz",
                    "expected_layout": ["data/"],
                },
                {
                    "label": "db_loader",
                    "kind": "command",
                    "command": "python data_loader.py",
                    "needs_secrets": ["DB_NAME"],
                    "network": "bridge",
                    "timeout_seconds": 60,
                },
            ],
        },
    )
    plan_dict["steps"][1]["depends_on"] = ["data_collection"]
    plan = parse_plan(plan_dict)
    runner = _FakeRunner({"python backtesting.py": _ok()})
    outputs = run_plan(
        plan,
        image="img",
        repo_path=tmp_path,
        runner=runner,
        prefer_data_path="google_drive",
        manual_download_resolver=lambda alt: True,  # treat the manual data as already present
    )
    assert outputs["data_collection"].outcome == ExecOutcome.OK
    # The DB loader command should NOT have been called.
    assert all("data_loader" not in c[1] for c in runner.calls)


def test_run_plan_skips_runner_for_artifact_check_steps(tmp_path: Path):
    """A step with verification_mode=artifact_check is not executed; downstream
    compare runs against existing files in the repo."""
    plan_dict = _minimal_valid_plan()
    # Mark the existing in_sample step as artifact_check
    plan_dict["steps"][0]["verification_mode"] = "artifact_check"
    plan_dict["steps"][0]["command"] = None
    plan = parse_plan(plan_dict)

    runner = _FakeRunner({})  # no commands scripted; runner must not be called
    outputs = run_plan(plan, image="img", repo_path=tmp_path, runner=runner)
    assert outputs["in_sample_backtest"].outcome == ExecOutcome.OK
    assert outputs["in_sample_backtest"].alternative_used == "artifact_check"
    assert runner.calls == []


def test_run_plan_artifact_check_does_not_cascade_skip_downstream(tmp_path: Path):
    """A successful artifact_check step satisfies downstream depends_on edges."""
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"].insert(
        0,
        {
            "id": "optimization",
            "nine_step": "step_5_optimization",
            "required": True,
            "verification_mode": "artifact_check",
        },
    )
    plan_dict["steps"][1]["depends_on"] = ["optimization"]
    plan = parse_plan(plan_dict)

    runner = _FakeRunner({"python backtesting.py": _ok()})
    outputs = run_plan(plan, image="img", repo_path=tmp_path, runner=runner)
    assert outputs["optimization"].outcome == ExecOutcome.OK
    assert outputs["in_sample_backtest"].outcome == ExecOutcome.OK
    assert any("backtesting.py" in c[1] for c in runner.calls)


def test_run_plan_falls_back_to_db_loader_when_secrets_present(tmp_path: Path):
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"].insert(
        0,
        {
            "id": "data_collection",
            "nine_step": "step_2_data_collection",
            "required": True,
            "alternatives": [
                {
                    "label": "google_drive",
                    "kind": "manual_download",
                    "url": "https://drive/x",
                    "expected_layout": ["data/"],
                },
                {
                    "label": "db_loader",
                    "kind": "command",
                    "command": "python data_loader.py",
                    "needs_secrets": ["DB_NAME"],
                    "network": "bridge",
                    "timeout_seconds": 60,
                },
            ],
        },
    )
    plan_dict["steps"][1]["depends_on"] = ["data_collection"]
    plan = parse_plan(plan_dict)
    runner = _FakeRunner(
        {
            "python data_loader.py": _ok("data ready"),
            "python backtesting.py": _ok(),
        }
    )
    outputs = run_plan(
        plan,
        image="img",
        repo_path=tmp_path,
        runner=runner,
        available_secrets={"DB_NAME": "x"},
        manual_download_resolver=lambda alt: False,  # google drive absent
    )
    assert outputs["data_collection"].outcome == ExecOutcome.OK
    assert any("data_loader" in c[1] for c in runner.calls)


def test_run_plan_persists_per_step_artifacts(tmp_path: Path):
    """Each executed step writes <step>.{stdout,stderr,meta.json} into artifacts_dir."""
    plan = parse_plan(_minimal_valid_plan())
    runner = _FakeRunner({"python backtesting.py": _ok("hello world\n")})
    art = tmp_path / "execute"
    outputs = run_plan(
        plan,
        image="img",
        repo_path=tmp_path,
        runner=runner,
        artifacts_dir=art,
    )
    assert outputs["in_sample_backtest"].outcome == ExecOutcome.OK
    assert (art / "in_sample_backtest.stdout").read_text() == "hello world\n"
    assert (art / "in_sample_backtest.stderr").read_text() == ""
    meta = json.loads((art / "in_sample_backtest.meta.json").read_text())
    assert meta["step_id"] == "in_sample_backtest"
    assert meta["exit_code"] == 0
    assert meta["outcome"] == "ok"
    assert meta["command"] == "python backtesting.py"


def test_run_plan_emits_substep_per_step(tmp_path: Path):
    plan = parse_plan(_minimal_valid_plan())
    runner = _FakeRunner({"python backtesting.py": _ok()})
    progress = Progress(tmp_path / "run", stream=None)
    run_plan(
        plan,
        image="img",
        repo_path=tmp_path,
        runner=runner,
        progress=progress,
    )
    progress.close()
    log = (tmp_path / "run" / "run.log").read_text()
    assert "[execute]   in_sample_backtest: running" in log
    assert "[execute]   in_sample_backtest: ok" in log

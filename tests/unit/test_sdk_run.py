"""Tests for the SDK Run context manager + step() factory."""
from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

import pytest

import plutus_verify as pv
from plutus_verify.sdk import Run, step
from plutus_verify.sdk.schema import validate_results


def _results_path(repo: Path, step_id: str) -> Path:
    return repo / ".plutus" / "run" / step_id / "results.json"


def test_public_import_surface() -> None:
    assert pv.step is step
    assert pv.Run is Run


def test_basic_write_emits_canonical_results(tmp_path: Path) -> None:
    with step("in_sample_backtest", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.9517, unit="ratio")
        r.metric("maximum_drawdown", -0.20, unit="fraction")
        r.artifact("equity_curve", "result/backtest/hpr.svg", kind="chart")
        r.artifact("drawdown_chart", "result/backtest/drawdown.svg")
        r.metadata(seed=2025)

    path = _results_path(tmp_path, "in_sample_backtest")
    assert path.exists()
    payload = json.loads(path.read_text())

    # File must round-trip through the schema validator.
    validate_results(payload)

    assert payload["schema_version"] == "1.0"
    assert payload["step_id"] == "in_sample_backtest"
    assert {m["name"] for m in payload["metrics"]} == {"sharpe_ratio", "maximum_drawdown"}
    assert {a["name"] for a in payload["artifacts"]} == {"equity_curve", "drawdown_chart"}
    assert payload["metadata"]["seed"] == 2025


def test_default_artifact_kind_is_chart(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.artifact("a", "x.svg")
    payload = json.loads(_results_path(tmp_path, "s").read_text())
    assert payload["artifacts"][0]["kind"] == "chart"


def test_atomic_write_no_tmp_left_behind(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.metric("m", 1.0)
    out_dir = tmp_path / ".plutus" / "run" / "s"
    leftovers = [p for p in out_dir.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_exception_in_with_block_skips_write(tmp_path: Path) -> None:
    path = _results_path(tmp_path, "s")
    assert not path.exists()
    with pytest.raises(RuntimeError):
        with step("s", repo_path=tmp_path) as r:
            r.metric("m", 1.0)
            raise RuntimeError("user code blew up")
    assert not path.exists()


def test_duplicate_metric_name_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.metric("m", 1.0)
            r.metric("m", 2.0)


def test_duplicate_artifact_name_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.artifact("a", "x.svg")
            r.artifact("a", "y.svg")


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metric_value_raises(tmp_path: Path, bad_value: float) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.metric("m", bad_value)


def test_bad_unit_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.metric("m", 1.0, unit="percent")


def test_bad_artifact_kind_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.artifact("a", "x.pdf", kind="pdf")


@pytest.mark.parametrize("bad_name", ["SharpeRatio", "sharpe-ratio", "1sharpe", "_sharpe", ""])
def test_non_snake_case_metric_name_raises(tmp_path: Path, bad_name: str) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.metric(bad_name, 1.0)


@pytest.mark.parametrize("bad_name", ["EquityCurve", "equity-curve", "9chart"])
def test_non_snake_case_artifact_name_raises(tmp_path: Path, bad_name: str) -> None:
    with pytest.raises(ValueError):
        with step("s", repo_path=tmp_path) as r:
            r.artifact(bad_name, "x.svg")


def test_bad_step_id_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        with step("BadStepId", repo_path=tmp_path):
            pass


def test_metadata_kwargs_round_trip(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.metadata(seed=2025, notes="hello", count=3)
    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert md["seed"] == 2025
    assert md["notes"] == "hello"
    assert md["count"] == 3


def test_metadata_last_write_wins(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.metadata(seed=1)
        r.metadata(seed=2)
    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert md["seed"] == 2


def test_duration_seconds_auto_injected(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path):
        pass
    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert "duration_seconds" in md
    assert isinstance(md["duration_seconds"], (int, float))
    assert md["duration_seconds"] >= 0
    assert math.isfinite(md["duration_seconds"])


def test_user_duration_seconds_wins(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.metadata(duration_seconds=999.0)
    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert md["duration_seconds"] == 999.0


def test_git_commit_injected_when_repo_present(tmp_path: Path) -> None:
    # Configure a local repo with one commit so HEAD resolves without depending
    # on host git config.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "x").write_text("hello")
    subprocess.run(["git", "add", "x"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
        env={**os.environ, "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@t.test"},
    )

    with step("s", repo_path=tmp_path):
        pass

    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert "git_commit" in md
    assert isinstance(md["git_commit"], str)
    assert len(md["git_commit"]) == 7


def test_git_commit_absent_when_no_dot_git(tmp_path: Path) -> None:
    assert not (tmp_path / ".git").exists()
    with step("s", repo_path=tmp_path):
        pass
    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert "git_commit" not in md


def test_user_git_commit_wins(tmp_path: Path) -> None:
    # Even with .git present, user-provided value should override.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    with step("s", repo_path=tmp_path) as r:
        r.metadata(git_commit="deadbee")
    md = json.loads(_results_path(tmp_path, "s").read_text())["metadata"]
    assert md["git_commit"] == "deadbee"


def test_step_writes_inside_explicit_repo_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)  # cwd is NOT the repo we point at

    target = tmp_path / "repo"
    target.mkdir()
    with step("s", repo_path=target):
        pass

    assert _results_path(target, "s").exists()
    assert not (other / ".plutus").exists()


def test_step_walks_up_to_find_dot_plutus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".plutus").mkdir(parents=True)
    nested = repo / "src" / "deep"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    with step("s"):
        pass

    assert _results_path(repo, "s").exists()


def test_step_uses_cwd_when_no_dot_plutus_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with step("s"):
        pass
    assert _results_path(tmp_path, "s").exists()


def test_flush_can_be_called_explicitly(tmp_path: Path) -> None:
    r = Run("s", repo_path=tmp_path)
    r.__enter__()
    r.metric("m", 1.0)
    r.flush()
    assert _results_path(tmp_path, "s").exists()
    # __exit__ on success should be a no-op or re-flush idempotently; either
    # way, the file should remain.
    r.__exit__(None, None, None)
    assert _results_path(tmp_path, "s").exists()


def test_metric_value_accepts_ints(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.metric("trade_count", 42, unit="count")
    payload = json.loads(_results_path(tmp_path, "s").read_text())
    assert payload["metrics"][0]["value"] == 42


def test_artifact_path_accepts_pathlib(tmp_path: Path) -> None:
    with step("s", repo_path=tmp_path) as r:
        r.artifact("equity_curve", Path("result") / "x.svg", kind="chart")
    payload = json.loads(_results_path(tmp_path, "s").read_text())
    assert payload["artifacts"][0]["path"] == str(Path("result") / "x.svg")

"""Tests for `plutus bootstrap` CLI subcommand (Plan 9 Task 4)."""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from plutus_verify.__main__ import cli
from plutus_verify.sdk import step as pv_step


# ---------------------------------------------------------------------------
# Helpers (mirroring test_scaffold_bootstrap.py)
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Create an empty repo skeleton (so pv.step writes under tmp_path)."""
    (tmp_path / ".plutus").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_results(
    repo: Path,
    step_id: str,
    metrics: list[tuple[str, float, str]] | None = None,
    artifacts: list[tuple[str, str, str]] | None = None,
) -> None:
    metrics = metrics or []
    artifacts = artifacts or []
    with pv_step(step_id, repo_path=repo) as r:
        for name, value, unit in metrics:
            r.metric(name, value, unit=unit)
        for name, path, kind in artifacts:
            r.artifact(name, path, kind=kind)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_cli_bootstrap_help_mentions_force():
    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap", "--help"])
    assert result.exit_code == 0
    assert "--force" in result.output


def test_cli_bootstrap_success_prints_paths_and_next_hint(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.5, "ratio")]
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap", str(repo)])

    assert result.exit_code == 0, result.output
    assert "draft:" in result.output
    assert "guidance:" in result.output
    assert "Next:" in result.output
    assert "manifest_TODO.md" in result.output
    assert ".draft" in result.output
    assert "plutus check" in result.output

    assert (repo / ".plutus" / "manifest.yaml.draft").exists()
    assert (repo / ".plutus" / "manifest_TODO.md").exists()


def test_cli_bootstrap_error_exits_three(tmp_path: Path):
    repo = _make_repo(tmp_path)
    # No pv.step invocations → no results.json → BootstrapError

    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap", str(repo)])

    assert result.exit_code == 3
    assert "error:" in result.stderr
    assert "pv.step" in result.stderr


def test_cli_bootstrap_force_passes_through(tmp_path: Path):
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.5, "ratio")]
    )
    draft_path = repo / ".plutus" / "manifest.yaml.draft"
    draft_path.write_text("# stale draft\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["bootstrap", str(repo), "--force"])

    assert result.exit_code == 0, result.output
    text = draft_path.read_text()
    assert "stale draft" not in text
    assert "schema_version" in text

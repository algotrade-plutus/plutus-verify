"""Tests for `plutus snapshot` CLI subcommand (Plan 8 Task 3)."""
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from plutus_verify.__main__ import cli
from plutus_verify.scaffold.snapshot import SnapshotResult


def test_cli_snapshot_help_mentions_both_new_flags():
    runner = CliRunner()
    result = runner.invoke(cli, ["snapshot", "--help"])
    assert result.exit_code == 0
    assert "--no-artifacts" in result.output
    assert "--no-metrics" in result.output


def test_cli_snapshot_passes_no_metrics_to_scaffold(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, metrics_updated=0)
        result = runner.invoke(
            cli, ["snapshot", str(tmp_path), "--no-run", "--no-metrics"]
        )
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["update_metric_values"] is False
    assert kwargs["update_artifacts"] is True


def test_cli_snapshot_passes_no_artifacts_to_scaffold(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, metrics_updated=0)
        result = runner.invoke(
            cli, ["snapshot", str(tmp_path), "--no-run", "--no-artifacts"]
        )
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["update_artifacts"] is False
    assert kwargs["update_metric_values"] is True


def test_cli_snapshot_default_passes_both_true(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, metrics_updated=0)
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--no-run"])
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["update_artifacts"] is True
    assert kwargs["update_metric_values"] is True


def test_cli_snapshot_default_runs_in_container(tmp_path: Path):
    """Without --no-run, snapshot wires a real builder + runner and calls
    scaffold_snapshot with run_check_first=True (L1: no more --no-run hard block)."""
    runner = CliRunner()
    with patch(
        "plutus_verify.scaffold.snapshot.scaffold_snapshot"
    ) as mock_scaffold, patch(
        "plutus_verify.spec.runtime.make_image_builder"
    ) as mock_mib, patch(
        "plutus_verify.runner_docker.DockerRunner"
    ) as mock_dr:
        mock_scaffold.return_value = SnapshotResult(files_copied=1, metrics_updated=0)
        result = runner.invoke(cli, ["snapshot", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["run_check_first"] is True
    assert kwargs["image_builder"] is not None
    assert kwargs["runner"] is not None


def test_cli_snapshot_no_run_does_not_build(tmp_path: Path):
    """--no-run keeps the local-bytes opt-out: run_check_first=False, no builder."""
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, metrics_updated=0)
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--no-run"])
    assert result.exit_code == 0, result.output
    _, kwargs = mock_scaffold.call_args
    assert kwargs["run_check_first"] is False


def test_cli_snapshot_output_includes_metrics_updated(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(
            files_copied=5, metrics_updated=3
        )
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--no-run"])
    assert result.exit_code == 0, result.output
    assert "files copied: 5" in result.output
    assert "metrics updated: 3" in result.output

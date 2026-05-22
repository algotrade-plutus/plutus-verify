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
    assert "--no-reference-outputs" in result.output
    assert "--no-headlines" in result.output


def test_cli_snapshot_passes_no_headlines_to_scaffold(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, headlines_updated=0)
        result = runner.invoke(
            cli, ["snapshot", str(tmp_path), "--no-run", "--no-headlines"]
        )
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["update_headline_values"] is False
    assert kwargs["update_reference_outputs"] is True


def test_cli_snapshot_passes_no_reference_outputs_to_scaffold(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, headlines_updated=0)
        result = runner.invoke(
            cli, ["snapshot", str(tmp_path), "--no-run", "--no-reference-outputs"]
        )
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["update_reference_outputs"] is False
    assert kwargs["update_headline_values"] is True


def test_cli_snapshot_default_passes_both_true(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(files_copied=0, headlines_updated=0)
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--no-run"])
    assert result.exit_code == 0, result.output
    assert mock_scaffold.called
    _, kwargs = mock_scaffold.call_args
    assert kwargs["update_reference_outputs"] is True
    assert kwargs["update_headline_values"] is True


def test_cli_snapshot_output_includes_headlines_updated(tmp_path: Path):
    runner = CliRunner()
    with patch("plutus_verify.scaffold.snapshot.scaffold_snapshot") as mock_scaffold:
        mock_scaffold.return_value = SnapshotResult(
            files_copied=5, headlines_updated=3
        )
        result = runner.invoke(cli, ["snapshot", str(tmp_path), "--no-run"])
    assert result.exit_code == 0, result.output
    assert "files copied: 5" in result.output
    assert "headlines updated: 3" in result.output

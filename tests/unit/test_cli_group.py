"""Tests for the refactored CLI group."""
from pathlib import Path

from click.testing import CliRunner

from plutus_verify.__main__ import cli


def test_cli_has_init_subcommand():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "check" in result.output
    assert "snapshot" in result.output


def test_init_subcommand_creates_files(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".plutus" / "manifest.yaml").exists()


def test_check_subcommand_loads_manifest(tmp_path: Path, monkeypatch):
    """`plutus check` should load and validate the manifest, error if absent."""
    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])
    assert result.exit_code != 0
    assert "no .plutus/manifest.yaml" in result.output or "manifest" in result.output.lower()

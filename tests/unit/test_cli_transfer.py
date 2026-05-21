"""Tests for `plutus transfer` CLI subcommand."""
from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from plutus_verify.__main__ import cli


def test_transfer_subcommand_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "transfer" in result.output


def test_transfer_missing_readme_errors(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["transfer", str(tmp_path)])
    assert result.exit_code != 0
    assert "README" in result.output


def test_transfer_writes_draft(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("# Demo")

    from plutus_verify.extract.plan import EnvSetup, ExtractedPlan, NineStepEntry, Repo

    plan = ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="DemoCLI",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={
            f"step_{i}_{n}": NineStepEntry(present=False, section_heading=None, confidence=0.5)
            for i, n in enumerate(
                ["hypothesis", "data_collection", "data_processing", "in_sample", "optimization", "out_of_sample", "paper_trading"],
                start=1,
            )
        },
        steps=(),
        expected_results=(),
    )
    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )
    # The CLI builds its own llm_client; we patch the constructor to a no-op
    monkeypatch.setattr(
        "plutus_verify.__main__.OpenAICompatClient",
        lambda *a, **kw: MagicMock(),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["transfer", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".plutus" / "manifest.yaml.draft").exists()

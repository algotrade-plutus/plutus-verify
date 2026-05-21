"""Tests for `plutus transfer` programmatic API."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.transfer import (
    TransferError,
    TransferResult,
    scaffold_transfer,
)


def _write_readme(tmp_path: Path, content: str = "# Demo repo") -> None:
    (tmp_path / "README.md").write_text(content)


def test_transfer_writes_draft_manifest(tmp_path, monkeypatch):
    _write_readme(tmp_path)

    # Stub the extractor — return a minimal ExtractedPlan
    from plutus_verify.extract.plan import (
        EnvSetup,
        ExtractedPlan,
        NineStepEntry,
        Repo,
        Step,
    )

    plan = ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="Demo",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={
            f"step_{i}_{n}": NineStepEntry(present=True, section_heading=n, confidence=0.95)
            for i, n in enumerate(
                ["hypothesis", "data_collection", "data_processing", "in_sample", "optimization", "out_of_sample", "paper_trading"],
                start=1,
            )
        },
        steps=(
            Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="python a.py", produces=("out/m.json",)),
        ),
        expected_results=(),
    )

    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )

    res = scaffold_transfer(tmp_path, llm_client=MagicMock())

    draft_path = tmp_path / ".plutus" / "manifest.yaml.draft"
    assert draft_path.exists()
    assert "schema_version" in draft_path.read_text()
    assert isinstance(res, TransferResult)
    assert res.draft_path == draft_path


def test_transfer_does_not_overwrite_existing_manifest(tmp_path, monkeypatch):
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text("# already there\n")

    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: MagicMock(),
    )

    with pytest.raises(TransferError, match="manifest.yaml already exists"):
        scaffold_transfer(tmp_path, llm_client=MagicMock())


def test_transfer_missing_readme_raises(tmp_path):
    with pytest.raises(TransferError, match="README.md"):
        scaffold_transfer(tmp_path, llm_client=MagicMock())


def test_transfer_overwrites_existing_draft(tmp_path, monkeypatch):
    """A previous draft is replaced — that's the whole point of re-running transfer."""
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml.draft").write_text("# stale draft\n")

    from plutus_verify.extract.plan import EnvSetup, ExtractedPlan, NineStepEntry, Repo

    plan = ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="Fresh",
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

    scaffold_transfer(tmp_path, llm_client=MagicMock())
    content = (plutus / "manifest.yaml.draft").read_text()
    assert "Fresh" in content
    assert "stale draft" not in content

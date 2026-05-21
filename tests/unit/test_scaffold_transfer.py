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
    todo_path = tmp_path / ".plutus" / "instrument_TODO.md"
    assert draft_path.exists()
    assert todo_path.exists()
    assert "schema_version" in draft_path.read_text()
    assert "Instrumentation TODO" in todo_path.read_text()
    assert isinstance(res, TransferResult)
    assert res.draft_path == draft_path
    assert res.instrument_todo_path == todo_path


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


def _stub_plan(name: str = "Fresh"):
    from plutus_verify.extract.plan import EnvSetup, ExtractedPlan, NineStepEntry, Repo

    return ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name=name,
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


def test_transfer_overwrites_existing_draft(tmp_path, monkeypatch):
    """A previous draft (manifest only, no TODO) is replaced — re-running with no
    pre-existing instrument_TODO.md succeeds by default."""
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml.draft").write_text("# stale draft\n")

    plan = _stub_plan("Fresh")
    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )

    scaffold_transfer(tmp_path, llm_client=MagicMock())
    content = (plutus / "manifest.yaml.draft").read_text()
    assert "Fresh" in content
    assert "stale draft" not in content
    assert (plutus / "instrument_TODO.md").exists()


def test_transfer_refuses_to_overwrite_existing_instrument_todo(tmp_path, monkeypatch):
    """Without ``force=True``, an existing instrument_TODO.md must not be clobbered."""
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "instrument_TODO.md").write_text("# my hand-edited TODO\n")

    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: _stub_plan(),
    )

    with pytest.raises(TransferError, match="instrument_TODO.md already exists"):
        scaffold_transfer(tmp_path, llm_client=MagicMock())

    # Hand-edited content preserved
    assert (plutus / "instrument_TODO.md").read_text() == "# my hand-edited TODO\n"


def test_transfer_force_overwrites_both(tmp_path, monkeypatch):
    """``force=True`` replaces both the draft and the instrument_TODO.md."""
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml.draft").write_text("# stale draft\n")
    (plutus / "instrument_TODO.md").write_text("# stale TODO\n")

    plan = _stub_plan("Fresh")
    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )

    scaffold_transfer(tmp_path, llm_client=MagicMock(), force=True)
    assert "Fresh" in (plutus / "manifest.yaml.draft").read_text()
    assert "stale draft" not in (plutus / "manifest.yaml.draft").read_text()
    todo = (plutus / "instrument_TODO.md").read_text()
    assert "stale TODO" not in todo
    assert "Instrumentation TODO" in todo

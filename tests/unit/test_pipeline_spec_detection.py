"""Tests that pipeline.py uses the v2 spec when .plutus/manifest.yaml exists,
falling back to the LLM extractor otherwise.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.config import Config
from plutus_verify.extract.plan import ExtractedPlan
from plutus_verify.ingest import IngestResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline


_MIN_MANIFEST = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo hi"
    outputs: ["out/metrics.json"]
expected: []
nine_step_coverage: {}
"""


def _make_ingest_result(repo_path: Path, *, with_manifest: bool) -> IngestResult:
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "README.md").write_text("# Demo\nSee .plutus/.")
    if with_manifest:
        plutus = repo_path / ".plutus"
        plutus.mkdir()
        (plutus / "manifest.yaml").write_text(_MIN_MANIFEST)
    meta_path = repo_path.parent / "meta.json"
    meta_path.write_text("{}")
    return IngestResult(
        git_url=str(repo_path),
        repo_path=repo_path,
        readme_path=repo_path / "README.md",
        commit_sha="0" * 40,
        branch="main",
        meta_path=meta_path,
    )


def test_pipeline_uses_spec_when_dotplutus_present(tmp_path: Path, monkeypatch):
    """When .plutus/manifest.yaml exists, the LLM extractor must NOT be called."""
    repo_path = tmp_path / "repo"
    ingest_result = _make_ingest_result(repo_path, with_manifest=True)

    from plutus_verify import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest", lambda *a, **kw: ingest_result)

    llm_client = MagicMock()
    llm_client.complete.side_effect = AssertionError("LLM must not be called when spec exists")

    inputs = PipelineInputs(
        source=str(repo_path),
        out_dir=tmp_path / "out",
        config=Config(),
        skip_clone=True,
        extract_only=True,
    )
    result = run_pipeline(
        inputs,
        llm_client=llm_client,
        builder=MagicMock(),
        runner=MagicMock(),
        vision=MagicMock(),
    )
    assert isinstance(result.plan, ExtractedPlan)
    assert result.plan.repo.name == "Demo"
    llm_client.complete.assert_not_called()


def test_pipeline_falls_back_to_extract_when_no_dotplutus(tmp_path: Path, monkeypatch):
    """When .plutus/ is absent, the legacy extract path is used (verified by
    confirming the pre_loaded_plan branch was honored — that branch only runs
    when the spec branch does NOT short-circuit)."""
    from plutus_verify.extract.plan import EnvSetup, Repo as PlanRepo

    repo_path = tmp_path / "repo"
    ingest_result = _make_ingest_result(repo_path, with_manifest=False)

    from plutus_verify import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest", lambda *a, **kw: ingest_result)

    sentinel_plan = ExtractedPlan(
        schema_version="1.0",
        repo=PlanRepo(
            name="SentinelRepo",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={},
        steps=(),
        expected_results=(),
        extraction_notes=("from-sentinel",),
    )
    inputs = PipelineInputs(
        source=str(repo_path),
        out_dir=tmp_path / "out",
        config=Config(),
        skip_clone=True,
        extract_only=True,
        pre_loaded_plan=sentinel_plan,
    )
    result = run_pipeline(
        inputs,
        llm_client=MagicMock(),
        builder=MagicMock(),
        runner=MagicMock(),
        vision=MagicMock(),
    )
    assert "from-sentinel" in result.plan.extraction_notes
    assert result.plan.repo.name == "SentinelRepo"


def test_pipeline_propagates_invalid_manifest_error(tmp_path: Path, monkeypatch):
    """An invalid .plutus/manifest.yaml must surface as a pipeline error,
    not be silently swallowed or treated as a fallback to the LLM path."""
    from plutus_verify.spec.loader import ManifestLoadError

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "README.md").write_text("# bad")
    plutus = repo_path / ".plutus"
    plutus.mkdir()
    # schema_version is wrong — schema validation will reject it
    (plutus / "manifest.yaml").write_text(
        'schema_version: "9.99"\nrepo: {name: B, primary_language: python}\n'
    )
    meta_path = tmp_path / "meta.json"
    meta_path.write_text("{}")

    from plutus_verify import pipeline as pipeline_mod

    monkeypatch.setattr(
        pipeline_mod,
        "ingest",
        lambda *a, **kw: IngestResult(
            git_url=str(repo_path),
            repo_path=repo_path,
            readme_path=repo_path / "README.md",
            commit_sha="0" * 40,
            branch="main",
            meta_path=meta_path,
        ),
    )

    inputs = PipelineInputs(
        source=str(repo_path),
        out_dir=tmp_path / "out",
        config=Config(),
        skip_clone=True,
        extract_only=True,
    )
    with pytest.raises(ManifestLoadError):
        run_pipeline(
            inputs,
            llm_client=MagicMock(),
            builder=MagicMock(),
            runner=MagicMock(),
            vision=MagicMock(),
        )

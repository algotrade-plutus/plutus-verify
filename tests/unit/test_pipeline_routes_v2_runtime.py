"""When .plutus/manifest.yaml is present, the pipeline must use the native v2
runtime (no adapter, no LLM extract). Plan 2 routing test."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.config import Config
from plutus_verify.ingest import IngestResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline


_MIN = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
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


def test_pipeline_uses_native_v2_runtime_when_manifest_present(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# D")
    (repo / "out").mkdir()
    (repo / "out" / "metrics.json").write_text("{}")
    plutus = repo / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text(_MIN)

    from plutus_verify import pipeline as pmod

    monkeypatch.setattr(
        pmod, "ingest",
        lambda *a, **kw: IngestResult(
            git_url=str(repo), repo_path=repo, readme_path=repo / "README.md",
            commit_sha="0" * 40, branch="main", meta_path=tmp_path / "meta.json",
        ),
    )

    # Patch run_v2_pipeline to confirm it's called and to short-circuit
    sentinel = MagicMock()
    sentinel.image = "built-img"
    sentinel.data_tier_used = "code"
    sentinel.step_results = {}
    sentinel.headline_results = {}
    sentinel.reference_results = {}
    sentinel.notes = []
    fake_run_v2 = MagicMock(return_value=sentinel)
    monkeypatch.setattr(pmod, "run_v2_pipeline", fake_run_v2)

    llm = MagicMock()
    llm.complete.side_effect = AssertionError("LLM must not be called")

    inputs = PipelineInputs(
        source=str(repo), out_dir=tmp_path / "out", config=Config(),
        skip_clone=True,
    )
    result = run_pipeline(inputs, llm_client=llm, builder=MagicMock(), runner=MagicMock(), vision=MagicMock())

    fake_run_v2.assert_called_once()
    # Some sort of report should still be assembled — but the test only
    # checks routing here; the actual report-shape assertion is in the
    # integration test (Task 7).

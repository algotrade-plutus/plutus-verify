"""End-to-end test: pipeline ingests a fixture repo with .plutus/, runs through
the extract stage (loads + adapts the v2 manifest), and emits a plan.json
identical-in-shape to what the LLM extractor would have produced.

Does NOT exercise build/execute/compare — those need Docker. This test verifies
the spec→adapter→pipeline integration.
"""
from pathlib import Path
from unittest.mock import MagicMock

from plutus_verify.config import Config
from plutus_verify.ingest import IngestResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline


_FIXTURE = Path(__file__).parent / "fixtures" / "spec_v2_minimal"


def test_spec_e2e_extract_only(tmp_path: Path, monkeypatch):
    # Stub ingest to return the fixture repo unmodified
    from plutus_verify import pipeline as pipeline_mod

    fake_meta = tmp_path / "meta.json"
    fake_meta.write_text("{}")
    monkeypatch.setattr(
        pipeline_mod,
        "ingest",
        lambda *a, **kw: IngestResult(
            git_url=str(_FIXTURE),
            repo_path=_FIXTURE,
            readme_path=_FIXTURE / "README.md",
            commit_sha="0" * 40,
            branch="main",
            meta_path=fake_meta,
        ),
    )

    out = tmp_path / "out"
    inputs = PipelineInputs(
        source=str(_FIXTURE),
        out_dir=out,
        config=Config(),
        skip_clone=True,
        extract_only=True,
    )
    llm_client = MagicMock()
    llm_client.complete.side_effect = AssertionError("LLM must not be called")

    result = run_pipeline(
        inputs,
        llm_client=llm_client,
        builder=MagicMock(),
        runner=MagicMock(),
        vision=MagicMock(),
    )

    plan = result.plan
    assert plan.repo.name == "SpecV2Minimal"
    assert len(plan.steps) == 3
    step_ids = [s.id for s in plan.steps]
    assert step_ids == ["data_preparation", "forming_rules", "in_sample"]

    dc = plan.steps[0]
    assert dc.alternatives is not None and len(dc.alternatives) == 1
    assert dc.alternatives[0].kind == "manual_download"
    assert dc.alternatives[0].url == "https://example.com/raw.tar.gz"

    er = plan.expected_results[0]
    assert er.metrics[0].name == "sharpe_ratio"

    # plan.json was persisted
    assert (out / "plan.json").exists()
    llm_client.complete.assert_not_called()

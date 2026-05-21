"""End-to-end test of the native v2 runtime against the spec_v2_minimal fixture."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime import V2RuntimeResult, run_v2_pipeline


_FIXTURE = Path(__file__).parent / "fixtures" / "spec_v2_minimal"


def test_v2_runtime_end_to_end(tmp_path):
    manifest = load_manifest(_FIXTURE)

    # Copy fixture repo to tmp_path so the test can mutate output dirs
    import shutil
    work = tmp_path / "repo"
    shutil.copytree(_FIXTURE, work)

    # Pre-stage all outputs declared by steps (since we stub the runner)
    (work / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (work / "data" / "raw" / "x.parquet").write_text("ok")
    (work / "data" / "processed").mkdir(parents=True, exist_ok=True)
    (work / "data" / "processed" / "x.parquet").write_text("ok")
    (work / "out").mkdir(parents=True, exist_ok=True)
    (work / "out" / "metrics.json").write_text('{"sharpe": 0.86}')

    image_builder = MagicMock(return_value="fixture-image")
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=work,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
        downloader=lambda *a, **kw: False,  # no downloads — force code path
    )

    assert isinstance(result, V2RuntimeResult)
    assert result.image == "fixture-image"
    # data_tier_used is "raw" because the layout already exists (we pre-staged it)
    assert result.data_tier_used == "raw"
    # 3 steps in fixture, all should have an entry in step_results
    assert set(result.step_results.keys()) == {"data_collection", "data_processing", "in_sample"}
    # Headline comparison gets wired in Task 4 (results.json reader). For now we
    # only verify the orchestrator still returns a placeholder entry for the
    # configured headline.
    assert "sharpe_ratio" in result.headline_results["in_sample"]

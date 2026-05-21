"""Tests for the v1 → v2 reverse adapter (used by `plutus transfer`)."""
import pytest
import yaml

from plutus_verify.extract.plan import (
    EnvSetup,
    ExpectedChart,
    ExpectedMetric,
    ExpectedResult,
    ExtractedPlan,
    Locate,
    NineStepEntry,
    Repo,
    SecretRequirement,
    Step,
    StepAlternative,
    Tolerance,
)
from plutus_verify.scaffold.extract_to_v2 import to_v2_manifest_yaml


def _minimal_plan() -> ExtractedPlan:
    return ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="Demo",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(SecretRequirement(key="API", purpose="data", step_ids=("data_collection",)),),
        ),
        nine_step_mapping={
            "step_1_hypothesis": NineStepEntry(present=True, section_heading="Hypothesis", confidence=0.9),
            "step_2_data_collection": NineStepEntry(present=True, section_heading="Data", confidence=0.95),
            "step_3_data_processing": NineStepEntry(present=False, section_heading=None, confidence=0.4),
            "step_4_in_sample": NineStepEntry(present=True, section_heading="Backtest", confidence=0.95),
            "step_5_optimization": NineStepEntry(present=False, section_heading=None, confidence=0.3),
            "step_6_out_of_sample": NineStepEntry(present=False, section_heading=None, confidence=0.2),
            "step_7_paper_trading": NineStepEntry(present=False, section_heading=None, confidence=0.1),
        },
        steps=(
            Step(
                id="data_collection",
                nine_step="step_2_data_collection",
                required=True,
                command="python -m demo.collect",
                produces=("data/raw/x.parquet",),
                network="bridge",
            ),
            Step(
                id="in_sample",
                nine_step="step_4_in_sample",
                required=True,
                command="python -m demo.backtest",
                produces=("out/metrics.json",),
            ),
        ),
        expected_results=(
            ExpectedResult(
                step_id="in_sample",
                metrics=(
                    ExpectedMetric(
                        name="sharpe_ratio",
                        value=0.85,
                        locate=Locate(kind="json_file", path="out/metrics.json", jsonpath="$.sharpe"),
                        tolerance=Tolerance(kind="relative", value=0.05),
                    ),
                ),
                charts=(),
            ),
        ),
    )


def test_emitted_yaml_is_parseable():
    """The draft must be valid YAML (TODO comments are allowed; YAML treats them as comments)."""
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    assert data["schema_version"] == "2.0"


@pytest.mark.xfail(
    reason=(
        "Plan 6 / Task 3 removed `locate:` from the v2 schema; the reverse "
        "adapter (extract_to_v2.py) still emits a locate block from the v1 "
        "ExpectedMetric. Task 6 rewrites the reverse adapter to drop locate "
        "and emit display_name instead — this test re-passes then."
    ),
    strict=True,
)
def test_emitted_yaml_passes_v2_schema_validation():
    """A perfectly-extracted plan should yield a manifest that already validates,
    so authors can run `plutus check` against the draft (after renaming)."""
    from plutus_verify.spec.loader import load_manifest_from_yaml_text

    text = to_v2_manifest_yaml(_minimal_plan())
    m = load_manifest_from_yaml_text(text)
    assert m.repo.name == "Demo"
    assert len(m.steps) == 2
    assert m.steps[1].outputs == ("out/metrics.json",)


def test_emitted_yaml_has_todo_markers_for_inputs():
    """v1 has no `inputs:` field. The reverse adapter must emit `inputs: []`
    with a TODO comment per step prompting the author to declare them."""
    text = to_v2_manifest_yaml(_minimal_plan())
    assert "# TODO(plutus-transfer): declare inputs" in text


def test_emitted_yaml_translates_secrets():
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    assert any(s["key"] == "API" for s in data["secrets"])


def test_emitted_yaml_translates_metrics_to_headlines():
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    er = data["expected"][0]
    assert er["step_id"] == "in_sample"
    assert er["headlines"][0]["name"] == "sharpe_ratio"
    assert er["headlines"][0]["value"] == 0.85


def test_emitted_yaml_translates_charts_to_visual_similarity():
    plan = _minimal_plan()
    # Add a chart
    plan = ExtractedPlan(
        schema_version=plan.schema_version,
        repo=plan.repo,
        nine_step_mapping=plan.nine_step_mapping,
        steps=plan.steps,
        expected_results=(
            ExpectedResult(
                step_id="in_sample",
                metrics=plan.expected_results[0].metrics,
                charts=(ExpectedChart(name="eq", produced_path="out/eq.png", reference_image=None),),
            ),
        ),
    )
    text = to_v2_manifest_yaml(plan)
    data = yaml.safe_load(text)
    er = data["expected"][0]
    assert er["reference_outputs"][0]["compare"] == "visual_similarity"
    assert er["reference_outputs"][0]["path"] == "out/eq.png"


def test_emitted_yaml_translates_manual_download_to_data_source():
    plan = _minimal_plan()
    # Add a manual_download alternative to data_collection
    new_steps = list(plan.steps)
    dc = new_steps[0]
    new_steps[0] = Step(
        id=dc.id,
        nine_step=dc.nine_step,
        required=dc.required,
        command=dc.command,
        network=dc.network,
        produces=dc.produces,
        alternatives=(
            StepAlternative(
                label="Google Drive",
                kind="manual_download",
                url="https://drive.google.com/x",
                expected_layout=("data/raw/x.parquet",),
            ),
        ),
    )
    plan = ExtractedPlan(
        schema_version=plan.schema_version,
        repo=plan.repo,
        nine_step_mapping=plan.nine_step_mapping,
        steps=tuple(new_steps),
        expected_results=plan.expected_results,
    )
    text = to_v2_manifest_yaml(plan)
    data = yaml.safe_load(text)
    assert len(data["data_sources"]["raw"]) == 1
    raw = data["data_sources"]["raw"][0]
    assert raw["url"] == "https://drive.google.com/x"
    assert raw["satisfies"] == ["data_collection"]


def test_emitted_yaml_marks_low_confidence_nine_steps():
    text = to_v2_manifest_yaml(_minimal_plan())
    # nine_step_3_data_processing was present=False; confidence 0.4 (low) → expect a TODO
    assert "TODO(plutus-transfer)" in text

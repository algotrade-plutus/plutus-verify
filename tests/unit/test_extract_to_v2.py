"""Tests for the v1 → v2 reverse adapter (used by `plutus transfer`)."""
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
from plutus_verify.scaffold.extract_to_v2 import (
    instrument_todo_markdown,
    to_v2_manifest_yaml,
)


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


def test_emitted_yaml_translates_metrics_to_metrics():
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    er = data["expected"][0]
    assert er["step_id"] == "in_sample"
    assert er["metrics"][0]["name"] == "sharpe_ratio"
    assert er["metrics"][0]["value"] == 0.85


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


def _plan_with_metric(name: str, value) -> ExtractedPlan:
    base = _minimal_plan()
    return ExtractedPlan(
        schema_version=base.schema_version,
        repo=base.repo,
        nine_step_mapping=base.nine_step_mapping,
        steps=base.steps,
        expected_results=(
            ExpectedResult(
                step_id="in_sample",
                metrics=(
                    ExpectedMetric(
                        name=name,
                        value=value,
                        locate=Locate(kind="json_file", path="out/m.json", jsonpath="$.x"),
                        tolerance=Tolerance(kind="relative", value=0.05),
                    ),
                ),
                charts=(),
            ),
        ),
    )


def test_emitted_yaml_canonicalizes_metric_name_and_emits_display_name():
    text = to_v2_manifest_yaml(_plan_with_metric("Sharpe Ratio", 0.95))
    data = yaml.safe_load(text)
    metric = data["expected"][0]["metrics"][0]
    assert metric["name"] == "sharpe_ratio"
    assert metric["display_name"] == "Sharpe Ratio"
    assert metric["value"] == 0.95


def test_emitted_yaml_canonicalizes_complex_metric_name():
    text = to_v2_manifest_yaml(_plan_with_metric("Maximum Drawdown (MDD)", 0.12))
    data = yaml.safe_load(text)
    metric = data["expected"][0]["metrics"][0]
    assert metric["name"] == "maximum_drawdown_mdd"
    assert metric["display_name"] == "Maximum Drawdown (MDD)"


def test_emitted_yaml_unparseable_value_becomes_zero_with_todo():
    text = to_v2_manifest_yaml(_plan_with_metric("Some Metric", "abc"))
    # The TODO comment line must mention the original literal
    assert "TODO(plutus-transfer)" in text
    assert 'could not parse "abc" as float' in text
    data = yaml.safe_load(text)
    metric = data["expected"][0]["metrics"][0]
    assert metric["value"] == 0.0


def test_emitted_yaml_parses_stringified_float():
    text = to_v2_manifest_yaml(_plan_with_metric("hpr", "0.42"))
    data = yaml.safe_load(text)
    metric = data["expected"][0]["metrics"][0]
    assert metric["name"] == "hpr"
    assert metric["value"] == 0.42


def test_emitted_yaml_does_not_contain_locate():
    """Plan 6 removed `locate:` from v2 — the reverse adapter must not emit it."""
    text = to_v2_manifest_yaml(_minimal_plan())
    assert "locate:" not in text


def test_instrument_todo_markdown_lists_steps_with_metrics():
    plan = _minimal_plan()  # has one step (in_sample) with one metric (sharpe_ratio)
    md = instrument_todo_markdown(plan)
    # The step with a metric appears
    assert "in_sample" in md
    assert 'pv.step("in_sample")' in md
    assert "sharpe_ratio" in md
    # The step without metrics (data_collection) is omitted
    assert "data_collection" not in md


def test_instrument_todo_markdown_uses_canonical_names():
    plan = _plan_with_metric("Sharpe Ratio", 0.95)
    md = instrument_todo_markdown(plan)
    # Canonical snake_case is the literal passed to r.metric(...)
    assert 'r.metric("sharpe_ratio"' in md


def test_instrument_todo_markdown_includes_command_when_present():
    plan = _minimal_plan()
    md = instrument_todo_markdown(plan)
    assert "python -m demo.backtest" in md


def test_instrument_todo_markdown_empty_when_no_metrics():
    base = _minimal_plan()
    plan = ExtractedPlan(
        schema_version=base.schema_version,
        repo=base.repo,
        nine_step_mapping=base.nine_step_mapping,
        steps=base.steps,
        expected_results=(),
    )
    md = instrument_todo_markdown(plan)
    # Header is present but no step subsections (no concrete pv.step("...") block)
    assert "Instrumentation TODO" in md
    assert 'pv.step("' not in md
    assert "## Step `" not in md

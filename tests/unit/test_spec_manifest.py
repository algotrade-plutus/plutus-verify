"""Tests for the v2 Manifest dataclasses."""
from plutus_verify.spec.manifest import (
    DataSource,
    DataSourceTiers,
    Env,
    ExpectedBlock,
    Headline,
    Locate,
    Manifest,
    NineStepCoverage,
    ReferenceOutput,
    Repo,
    Secret,
    Step,
    Tolerance,
)


def test_manifest_minimal_construction():
    m = Manifest(
        schema_version="2.0",
        repo=Repo(name="Demo", primary_language="python"),
        env=Env(
            base="python",
            python_version="3.11",
            requirements_file="requirements.txt",
        ),
        secrets=(),
        data_sources=DataSourceTiers(),
        steps=(
            Step(
                id="in_sample",
                nine_step="step_4_in_sample",
                required=True,
                command="python -m demo.backtest",
                outputs=("out/metrics.json",),
            ),
        ),
        expected=(),
        nine_step_coverage={},
    )
    assert m.steps[0].id == "in_sample"
    assert m.env.base == "python"
    assert m.data_sources.processed == ()
    assert m.data_sources.raw == ()


def test_step_with_free_form_nine_step():
    s = Step(
        id="train_model",
        nine_step=None,
        label="Custom: train classifier",
        required=True,
        command="python -m demo.ml.train",
        outputs=("models/clf.pkl",),
    )
    assert s.nine_step is None
    assert s.label == "Custom: train classifier"


def test_data_source_satisfies_multiple_steps():
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/*.parquet",),
        satisfies=("data_collection", "data_processing"),
    )
    assert ds.satisfies == ("data_collection", "data_processing")


def test_headline_uses_locate_and_tolerance():
    h = Headline(
        name="sharpe_ratio",
        value=0.85,
        locate=Locate(kind="json_file", path="out/m.json", jsonpath="$.sharpe"),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    assert h.locate.kind == "json_file"
    assert h.tolerance.value == 0.05


def test_reference_output_with_threshold():
    r = ReferenceOutput(
        path="out/equity_curve.png",
        compare="visual_similarity",
        threshold=0.7,
    )
    assert r.compare == "visual_similarity"
    assert r.threshold == 0.7

"""Tests for spec.adapter: Manifest → ExtractedPlan bridge."""
from plutus_verify.spec.adapter import to_extracted_plan
from plutus_verify.spec.loader import load_manifest_from_yaml_text


_MIN = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets:
  - key: API
    purpose: testing
    used_by: [in_sample]
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.backtest"
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    headlines:
      - name: sharpe_ratio
        value: 0.85
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []
nine_step_coverage:
  step_4_in_sample: {present: true, section: "Backtest"}
"""


def test_adapter_returns_extracted_plan():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert hasattr(p, "schema_version")
    assert p.schema_version == "1.0"
    assert p.repo.name == "Demo"


def test_adapter_maps_env_to_requirements_txt():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert p.repo.env_setup.kind == "requirements_txt"
    assert p.repo.env_setup.path == "requirements.txt"
    assert p.repo.env_setup.python_version == "3.11"


def test_adapter_maps_secrets():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert len(p.repo.secrets_required) == 1
    assert p.repo.secrets_required[0].key == "API"
    assert p.repo.secrets_required[0].step_ids == ("in_sample",)


def test_adapter_maps_step_and_outputs_to_produces():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert len(p.steps) == 1
    s = p.steps[0]
    assert s.id == "in_sample"
    assert s.command == "python -m demo.backtest"
    assert s.produces == ("out/metrics.json",)


def test_adapter_maps_headlines_to_expected_metrics():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert len(p.expected_results) == 1
    er = p.expected_results[0]
    assert er.step_id == "in_sample"
    assert len(er.metrics) == 1
    assert er.metrics[0].name == "sharpe_ratio"
    assert er.metrics[0].value == 0.85
    assert er.metrics[0].locate.kind == "json_file"


def test_adapter_maps_nine_step_coverage_to_mapping():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    entry = p.nine_step_mapping["step_4_in_sample"]
    assert entry.present is True
    assert entry.section_heading == "Backtest"
    assert entry.confidence == 1.0


def test_adapter_translates_raw_data_source_to_alternative():
    yaml_text = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources:
  processed: []
  raw:
    - kind: github_release
      url: https://github.com/x/y/raw.tar.gz
      expected_layout: ["data/raw/*.parquet"]
      satisfies: [data_collection]
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge
    command: "python collect.py"
    outputs: ["data/raw/x.parquet"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python preprocess.py"
    outputs: ["data/processed/x.parquet"]
expected: []
nine_step_coverage: {}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    p = to_extracted_plan(m)
    dc = next(s for s in p.steps if s.id == "data_collection")
    assert dc.alternatives is not None
    assert len(dc.alternatives) == 1
    alt = dc.alternatives[0]
    assert alt.kind == "manual_download"
    assert alt.url == "https://github.com/x/y/raw.tar.gz"
    assert alt.expected_layout == ("data/raw/*.parquet",)


def test_adapter_free_form_step_gets_placeholder_nine_step():
    yaml_text = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: train
    nine_step: null
    label: ML train
    required: true
    command: "python train.py"
    outputs: ["models/clf.pkl"]
expected: []
nine_step_coverage: {}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    p = to_extracted_plan(m)
    s = p.steps[0]
    assert s.nine_step == "step_4_in_sample"  # placeholder
    assert any("free-form step 'train'" in note for note in p.extraction_notes)


def test_adapter_processed_data_source_logs_warning_in_notes():
    yaml_text = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources:
  processed:
    - kind: s3
      url: s3://x
      expected_layout: ["data/processed/*.parquet"]
      satisfies: [data_collection, data_processing]
  raw: []
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "python a.py"
    outputs: ["data/raw/x"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python b.py"
    outputs: ["data/processed/x"]
expected: []
nine_step_coverage: {}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    p = to_extracted_plan(m)
    notes_blob = " ".join(p.extraction_notes)
    assert "data_sources.processed" in notes_blob
    assert "Plan 2" in notes_blob

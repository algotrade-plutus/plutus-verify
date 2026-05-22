"""Tests for spec.loader: YAML/dict → Manifest."""
from pathlib import Path

import pytest

from plutus_verify.spec import Manifest, load_manifest
from plutus_verify.spec.loader import (
    ManifestLoadError,
    load_manifest_from_dict,
    load_manifest_from_yaml_text,
)


_MIN_YAML = """\
schema_version: "2.0"
repo:
  name: Demo
  primary_language: python
env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
secrets: []
data_sources:
  processed: []
  raw: []
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.backtest"
    outputs: ["out/metrics.json"]
expected: []
nine_step_coverage: {}
"""


def test_load_from_yaml_text_returns_manifest():
    m = load_manifest_from_yaml_text(_MIN_YAML)
    assert isinstance(m, Manifest)
    assert m.repo.name == "Demo"
    assert m.steps[0].id == "in_sample"
    assert m.steps[0].outputs == ("out/metrics.json",)


def test_load_from_dict_returns_manifest():
    import yaml

    data = yaml.safe_load(_MIN_YAML)
    m = load_manifest_from_dict(data)
    assert isinstance(m, Manifest)
    assert m.env.python_version == "3.11"


def test_load_from_path(tmp_path: Path):
    plutus_dir = tmp_path / ".plutus"
    plutus_dir.mkdir()
    (plutus_dir / "manifest.yaml").write_text(_MIN_YAML)
    m = load_manifest(tmp_path)
    assert m.repo.name == "Demo"


def test_load_missing_dotplutus_raises(tmp_path: Path):
    with pytest.raises(ManifestLoadError, match="no .plutus/manifest.yaml"):
        load_manifest(tmp_path)


def test_load_schema_violation_wraps_error(tmp_path: Path):
    bad = _MIN_YAML.replace('"2.0"', '"1.0"')
    with pytest.raises(ManifestLoadError, match="schema"):
        load_manifest_from_yaml_text(bad)


def test_load_full_manifest_with_all_features():
    yaml_text = """\
schema_version: "2.0"
repo:
  name: ProtoMM
  primary_language: python
env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
  os_packages: [build-essential]
  gpu_required: false
secrets:
  - key: TIINGO_API_KEY
    purpose: market data
    used_by: [data_collection]
data_sources:
  processed:
    - kind: google_drive
      url: https://drive.google.com/x
      expected_layout: ["data/processed/*.parquet"]
      satisfies: [data_collection, data_processing]
  raw:
    - kind: github_release
      url: https://github.com/x/y/releases/v1/raw.tar.gz
      expected_layout: ["data/raw/*.parquet"]
      satisfies: [data_collection]
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge
    command: "python -m proto_mm.data.collect"
    outputs: ["data/raw/*.parquet"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python -m proto_mm.data.preprocess"
    inputs: [data/raw]
    outputs: ["data/processed/*.parquet"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m proto_mm.backtest"
    inputs: [data/processed]
    outputs: ["out/metrics.json", "out/equity.png"]
  - id: train_model
    nine_step: null
    label: "Custom: train classifier"
    required: true
    command: "python -m proto_mm.ml.train"
    outputs: ["models/clf.pkl"]
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        display_name: "Sharpe Ratio"
        value: 0.85
        tolerance: {kind: relative, value: 0.05}
    reference_outputs:
      - path: "out/metrics.json"
        compare: json_numeric_tolerance
      - path: "out/equity.png"
        compare: visual_similarity
        threshold: 0.7
nine_step_coverage:
  step_1_hypothesis: {present: true, section: "1. Hypothesis"}
  step_2_data_collection: {present: true, section: "2. Data"}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    assert len(m.steps) == 4
    assert m.steps[3].nine_step is None
    assert m.steps[3].label == "Custom: train classifier"
    assert len(m.data_sources.processed) == 1
    assert m.data_sources.processed[0].satisfies == ("data_collection", "data_processing")
    assert m.expected[0].metrics[0].value == 0.85
    assert m.expected[0].metrics[0].display_name == "Sharpe Ratio"
    assert m.expected[0].reference_outputs[1].threshold == 0.7
    assert m.nine_step_coverage["step_1_hypothesis"].present is True


def test_load_metric_without_display_name_keeps_it_none():
    yaml_text = _MIN_YAML.replace(
        "expected: []",
        """expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.85
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []""",
    )
    m = load_manifest_from_yaml_text(yaml_text)
    h = m.expected[0].metrics[0]
    assert h.name == "sharpe_ratio"
    assert h.display_name is None

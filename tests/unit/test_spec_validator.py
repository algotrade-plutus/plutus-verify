"""Tests for the v2 manifest invariants that JSON-Schema can't express."""
import pytest

from plutus_verify.spec.loader import ManifestLoadError, load_manifest_from_yaml_text


_BASE = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps: %s
expected: []
nine_step_coverage: {}
"""


def _yaml(steps: str) -> str:
    return _BASE % steps


def test_data_collection_without_command_rejected():
    steps = """
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    outputs: ["data/raw/x.parquet"]
"""
    with pytest.raises(ManifestLoadError, match="data_collection.*command"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_data_processing_without_command_rejected():
    steps = """
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    outputs: ["data/processed/x.parquet"]
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "python collect.py"
    outputs: ["data/raw/x.parquet"]
"""
    with pytest.raises(ManifestLoadError, match="data_processing.*command"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_duplicate_step_ids_rejected():
    steps = """
  - id: same
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
  - id: same
    nine_step: step_6_out_of_sample
    required: true
    command: "echo b"
"""
    with pytest.raises(ManifestLoadError, match="duplicate step id"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_depends_on_unknown_step_rejected():
    steps = """
  - id: a
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
    depends_on: ["ghost"]
"""
    with pytest.raises(ManifestLoadError, match="depends_on.*ghost"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_expected_refers_to_unknown_step_rejected():
    yaml_text = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: a
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
expected:
  - step_id: ghost
    metrics: []
    artifacts: []
nine_step_coverage: {}
"""
    with pytest.raises(ManifestLoadError, match="expected.*ghost"):
        load_manifest_from_yaml_text(yaml_text)


def test_data_source_satisfies_unknown_step_rejected():
    yaml_text = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources:
  processed:
    - kind: s3
      url: s3://x
      expected_layout: ["data/processed/*.parquet"]
      satisfies: ["data_collection", "ghost"]
  raw: []
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "echo a"
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "echo b"
expected: []
nine_step_coverage: {}
"""
    with pytest.raises(ManifestLoadError, match="satisfies.*ghost"):
        load_manifest_from_yaml_text(yaml_text)


def test_secret_used_by_unknown_step_rejected():
    yaml_text = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets:
  - key: K
    used_by: [ghost]
data_sources: {processed: [], raw: []}
steps:
  - id: a
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
expected: []
nine_step_coverage: {}
"""
    with pytest.raises(ManifestLoadError, match="secret K.*used_by.*ghost"):
        load_manifest_from_yaml_text(yaml_text)

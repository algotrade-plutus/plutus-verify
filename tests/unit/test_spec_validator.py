"""Tests for the v2 manifest invariants that JSON-Schema can't express."""
from pathlib import Path

import pytest

from plutus_verify.spec.loader import (
    ManifestLoadError,
    load_manifest,
    load_manifest_from_yaml_text,
)


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


def test_data_preparation_without_command_rejected():
    steps = """
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    outputs: ["data/processed/x.parquet"]
"""
    with pytest.raises(ManifestLoadError, match="data_preparation.*command"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_legacy_data_ids_no_longer_require_command():
    # After the v2025 rename only `data_preparation` is special-cased. The old
    # `data_collection`/`data_processing` ids are ordinary steps now and may omit
    # a command (a free-form step with nine_step: null).
    steps = """
  - id: data_collection
    nine_step: null
    label: "legacy id, no longer a data step"
    required: true
    outputs: ["data/raw/x.parquet"]
"""
    m = load_manifest_from_yaml_text(_yaml(steps))
    assert m.steps[0].id == "data_collection"
    assert m.steps[0].command is None


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
      satisfies: ["data_preparation", "ghost"]
  raw: []
steps:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    command: "echo a"
  - id: in_sample
    nine_step: step_4_in_sample
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


# ---- env.install_project invariants ----

_INSTALL_PROJECT_MANIFEST = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", manager: %s, lockfile: uv.lock, install_project: true}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "pmm-backtest"
expected: []
nine_step_coverage: {}
"""


def test_install_project_requires_uv_manager():
    # manager: pip + install_project: true → clear error (uv-only capability).
    with pytest.raises(ManifestLoadError, match="install_project.*uv"):
        load_manifest_from_yaml_text(_INSTALL_PROJECT_MANIFEST % "pip")


def _write_repo(tmp_path: Path, *, with_pyproject: bool) -> Path:
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text(_INSTALL_PROJECT_MANIFEST % "uv")
    if with_pyproject:
        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    return tmp_path


def test_install_project_requires_pyproject_at_repo_root(tmp_path: Path):
    repo = _write_repo(tmp_path, with_pyproject=False)
    with pytest.raises(ManifestLoadError, match="install_project.*pyproject"):
        load_manifest(repo)


def test_install_project_ok_with_uv_lockfile_and_pyproject(tmp_path: Path):
    repo = _write_repo(tmp_path, with_pyproject=True)
    m = load_manifest(repo)
    assert m.env.install_project is True

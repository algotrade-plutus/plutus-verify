"""Templates emitted by `plutus init`."""
import yaml

from plutus_verify.scaffold.templates import MANIFEST_SKELETON, WORKFLOW_YAML


def test_manifest_skeleton_is_valid_yaml():
    data = yaml.safe_load(MANIFEST_SKELETON)
    assert isinstance(data, dict)
    assert data["schema_version"] == "2.0"
    assert "repo" in data
    assert "env" in data
    assert "steps" in data
    assert "expected" in data


def test_manifest_skeleton_has_todo_markers():
    # Skeleton must guide authors with TODO markers, not leave silent empty fields
    assert "TODO" in MANIFEST_SKELETON


def test_manifest_skeleton_loads_via_load_manifest_from_yaml_text():
    """The skeleton must pass schema validation as-is, so authors can run
    `plutus check` and get a useful error pointing at their TODOs (not a
    schema-violation cliff)."""
    from plutus_verify.spec.loader import load_manifest_from_yaml_text

    m = load_manifest_from_yaml_text(MANIFEST_SKELETON)
    assert m.schema_version == "2.0"


def test_workflow_yaml_is_valid_github_actions():
    data = yaml.safe_load(WORKFLOW_YAML)
    assert data["name"] == "plutus reproducibility"
    assert "on" in data or True in data  # PyYAML maps "on:" to True sometimes; just check structure
    assert "jobs" in data
    assert "check" in data["jobs"]

"""Tests for `plutus init`."""
from pathlib import Path

import pytest

from plutus_verify.scaffold.init import InitResult, scaffold_init


def test_init_creates_manifest_and_workflow(tmp_path: Path):
    res = scaffold_init(tmp_path)
    assert isinstance(res, InitResult)
    assert (tmp_path / ".plutus" / "manifest.yaml").exists()
    assert (tmp_path / ".github" / "workflows" / "plutus.yml").exists()
    assert (tmp_path / ".plutus" / "expected").is_dir()
    assert res.created_manifest is True
    assert res.created_workflow is True


def test_init_does_not_overwrite_existing_manifest(tmp_path: Path):
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text("# my custom manifest\n")
    res = scaffold_init(tmp_path)
    assert res.created_manifest is False
    assert (plutus / "manifest.yaml").read_text() == "# my custom manifest\n"


def test_init_does_not_overwrite_existing_workflow(tmp_path: Path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "plutus.yml").write_text("# custom workflow\n")
    res = scaffold_init(tmp_path)
    assert res.created_workflow is False


def test_init_force_overwrites(tmp_path: Path):
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text("# old\n")
    res = scaffold_init(tmp_path, force=True)
    assert res.created_manifest is True
    assert "schema_version" in (plutus / "manifest.yaml").read_text()


def test_init_skeleton_is_loadable(tmp_path: Path):
    """After init, the manifest must pass schema validation so `plutus check`
    has a sensible starting state."""
    scaffold_init(tmp_path)
    from plutus_verify.spec.loader import load_manifest

    m = load_manifest(tmp_path)
    assert m.schema_version == "2.0"


def test_init_writes_example_script(tmp_path: Path):
    """`plutus init` should drop a `.plutus/example_script.py` showing how to
    wire `pv.step(...)` into an author's reproducibility script."""
    scaffold_init(tmp_path)
    example = tmp_path / ".plutus" / "example_script.py"
    assert example.exists()
    text = example.read_text()
    # Has a top-of-file docstring (template, not executable)
    assert text.lstrip().startswith('"""')
    # Demonstrates the SDK call patterns authors must copy
    assert "pv.step(" in text
    assert "r.headline(" in text


def test_init_returns_created_example_script_true_on_first_init(tmp_path: Path):
    res = scaffold_init(tmp_path)
    assert res.created_example_script is True
    res2 = scaffold_init(tmp_path)
    assert res2.created_example_script is False


def test_init_overwrites_example_script_with_force(tmp_path: Path):
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "example_script.py").write_text("# stale custom content\n")
    res = scaffold_init(tmp_path, force=True)
    assert res.created_example_script is True
    new_content = (plutus / "example_script.py").read_text()
    assert "# stale custom content" not in new_content
    assert "pv.step(" in new_content


def test_example_script_imports_cleanly():
    """The EXAMPLE_SCRIPT template must be syntactically valid Python.

    We compile (not exec) — exec'ing would call `pv.step(...)` and write a
    real results.json at the cwd.
    """
    from plutus_verify.scaffold.templates import EXAMPLE_SCRIPT

    compile(EXAMPLE_SCRIPT, "<example>", "exec")

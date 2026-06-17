"""Tests for the optional `sub_processes` documentation block on the
data_preparation step (v2025). Documentation only — never executed."""
from types import SimpleNamespace

import pytest

from plutus_verify.scaffold.check_report import render_check_report
from plutus_verify.spec.loader import ManifestLoadError, load_manifest_from_yaml_text
from plutus_verify.spec.manifest import (
    DataSourceTiers,
    Env,
    Manifest,
    Repo,
    Step,
    SubProcess,
    SubProcesses,
)


def _manifest(sub_processes_block: str, nine_step: str = "step_2_data_preparation",
              step_id: str = "data_preparation") -> str:
    return f"""\
schema_version: "2.0"
repo: {{name: D, primary_language: python}}
env: {{base: python, python_version: "3.11", requirements_file: r.txt}}
secrets: []
data_sources: {{processed: [], raw: []}}
steps:
  - id: {step_id}
    nine_step: {nine_step}
    required: true
    command: "python prep.py"
{sub_processes_block}
expected: []
nine_step_coverage: {{}}
"""


_BOTH = """\
    sub_processes:
      collection:
        description: "pull ticks from the DB"
        command: "python -m x.collect"
        outputs: ["data/raw/x.parquet"]
      processing:
        description: "resample to 1-minute bars"
"""


def test_both_slots_load():
    m = load_manifest_from_yaml_text(_manifest(_BOTH))
    sp = m.steps[0].sub_processes
    assert isinstance(sp, SubProcesses)
    assert sp.collection.description == "pull ticks from the DB"
    assert sp.collection.command == "python -m x.collect"
    assert sp.collection.outputs == ("data/raw/x.parquet",)
    assert sp.processing.description == "resample to 1-minute bars"
    assert sp.processing.command is None


def test_single_slot_loads_other_is_none():
    block = """\
    sub_processes:
      collection:
        description: "download files from Drive"
"""
    m = load_manifest_from_yaml_text(_manifest(block))
    sp = m.steps[0].sub_processes
    assert sp.collection.description == "download files from Drive"
    assert sp.processing is None


def test_happy_path_no_block_is_none():
    m = load_manifest_from_yaml_text(_manifest(""))
    assert m.steps[0].sub_processes is None


def test_sub_processes_rejected_on_non_data_preparation_step():
    with pytest.raises(ManifestLoadError, match="sub_processes.*only allowed.*data_preparation"):
        load_manifest_from_yaml_text(
            _manifest(_BOTH, nine_step="step_4_in_sample", step_id="in_sample")
        )


def test_slot_without_description_rejected():
    block = """\
    sub_processes:
      collection:
        command: "python -m x.collect"
"""
    with pytest.raises(ManifestLoadError, match="description"):
        load_manifest_from_yaml_text(_manifest(block))


def test_unknown_slot_key_rejected():
    block = """\
    sub_processes:
      gathering:
        description: "nope"
"""
    with pytest.raises(ManifestLoadError, match="schema violation"):
        load_manifest_from_yaml_text(_manifest(block))


def test_unknown_field_within_slot_rejected():
    block = """\
    sub_processes:
      collection:
        description: "ok"
        bogus: "x"
"""
    with pytest.raises(ManifestLoadError, match="schema violation"):
        load_manifest_from_yaml_text(_manifest(block))


def test_check_report_renders_sub_processes_under_step_2():
    step = Step(
        id="data_preparation",
        nine_step="step_2_data_preparation",
        required=True,
        command="python prep.py",
        sub_processes=SubProcesses(
            collection=SubProcess(description="pull ticks from the DB", command="python -m x.collect"),
            processing=SubProcess(description="resample to 1-minute bars"),
        ),
    )
    m = Manifest(
        schema_version="2.0",
        repo=Repo(name="D", primary_language="python"),
        env=Env(base="python", python_version="3.11"),
        secrets=(),
        data_sources=DataSourceTiers(),
        steps=(step,),
        expected=(),
    )
    runtime = SimpleNamespace(
        image="img",
        data_tier_used="raw",
        notes=[],
        step_results={
            "data_preparation": SimpleNamespace(
                exit_code=0, preflight_error=None, skipped_reason=None
            )
        },
        metric_results={},
        artifact_results={},
    )
    out = "\n".join(render_check_report(m, runtime))
    assert "• collection: pull ticks from the DB — python -m x.collect" in out
    assert "• processing: resample to 1-minute bars" in out

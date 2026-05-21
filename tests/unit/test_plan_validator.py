"""Plan validator: second-pass corrections of common Gemma plan defects.

Phase 1 (deterministic): no LLM. Drops bogus stdout metrics on artifact_check
steps; flags `json_file` locate paths that don't exist on disk.

Phase 2 (LLM, optional): an LLM call that returns a structured corrections
JSON. We apply corrections deterministically; we never let the LLM rewrite
the plan freely.
"""
import json
from pathlib import Path

import pytest

from plutus_verify.extract.plan import parse_plan
from plutus_verify.extract.validator import (
    ValidatorError,
    validate_plan,
)
from tests.unit.test_plan_schema import _minimal_valid_plan


def _plan_with_artifact_check_and_stdout_metric():
    p = _minimal_valid_plan()
    # Mark step as artifact_check
    p["steps"][0]["verification_mode"] = "artifact_check"
    # Metric still claims stdout_table — that's the bogus pattern
    p["expected_results"][0]["metrics"] = [
        {
            "name": "should_be_dropped",
            "value": 1.0,
            "locate": {"kind": "stdout_table", "row": "X", "col": 1},
            "tolerance": {"kind": "relative", "value": 0.05},
        },
        {
            "name": "json_file_metric_keep",
            "value": 2.0,
            "locate": {"kind": "json_file", "path": "config/p.json", "jsonpath": "$.x"},
            "tolerance": {"kind": "absolute", "value": 0.01},
        },
    ]
    return p


def test_deterministic_drops_stdout_metric_on_artifact_check_step(tmp_path: Path):
    plan = parse_plan(_plan_with_artifact_check_and_stdout_metric())
    fixed, fixes = validate_plan(plan, readme_text="(unused)", repo_path=tmp_path)
    # The artifact_check step has only 1 metric now (the stdout one was dropped)
    er = next(er for er in fixed.expected_results if er.step_id == plan.steps[0].id)
    names = [m.name for m in er.metrics]
    assert names == ["json_file_metric_keep"]
    # The fix is recorded
    assert any("stdout_table" in f and "artifact_check" in f for f in fixes), fixes


def test_deterministic_flags_missing_json_file_path(tmp_path: Path):
    p = _minimal_valid_plan()
    p["expected_results"][0]["metrics"][0]["locate"] = {
        "kind": "json_file",
        "path": "config/nonexistent.json",
        "jsonpath": "$.x",
    }
    plan = parse_plan(p)
    _, fixes = validate_plan(plan, readme_text="(unused)", repo_path=tmp_path)
    assert any("nonexistent.json" in f for f in fixes)


def test_validator_calls_llm_only_if_client_provided(tmp_path: Path):
    plan = parse_plan(_minimal_valid_plan())
    # No client → no LLM call attempted; returns plan unchanged
    fixed, fixes = validate_plan(plan, readme_text="X", repo_path=tmp_path, llm_client=None)
    assert fixed == plan
    assert fixes == []


def test_validator_applies_llm_renames_and_drops_safely(tmp_path: Path):
    plan = parse_plan(_minimal_valid_plan())

    class _ScriptedLLM:
        def complete_json(self, system, user, *, temperature=0.0, idle_timeout_seconds=None):
            return json.dumps(
                {
                    "rename_row": [
                        {"step_id": plan.steps[0].id, "metric_name": "sharpe_ratio", "new_row": "Sharpe Ratio"}
                    ],
                    "drop_metrics": [],
                    "add_metrics": [],
                    "add_steps": [],
                }
            )

    fixed, fixes = validate_plan(
        plan, readme_text="README", repo_path=tmp_path, llm_client=_ScriptedLLM()
    )
    # The metric's row was renamed
    metrics = next(er for er in fixed.expected_results).metrics
    assert metrics[0].locate.row == "Sharpe Ratio"
    assert any("renamed row" in f.lower() for f in fixes)


def test_validator_tolerates_malformed_llm_output(tmp_path: Path):
    plan = parse_plan(_minimal_valid_plan())

    class _BrokenLLM:
        def complete_json(self, *a, **k):
            return "not json"

    fixed, fixes = validate_plan(
        plan, readme_text="README", repo_path=tmp_path, llm_client=_BrokenLLM()
    )
    # Plan is preserved unchanged when LLM fails
    assert fixed == plan
    # Failure is recorded
    assert any("malformed" in f.lower() or "parse" in f.lower() for f in fixes)


def test_validator_rejects_dangerous_ops(tmp_path: Path):
    """LLM is not allowed to modify command, network, or verification_mode."""
    plan = parse_plan(_minimal_valid_plan())

    class _OverreachLLM:
        def complete_json(self, *a, **k):
            return json.dumps(
                {
                    # An unknown key — should be ignored, not crash
                    "rewrite_command": [{"step_id": plan.steps[0].id, "command": "rm -rf /"}],
                    "rename_row": [],
                    "drop_metrics": [],
                    "add_metrics": [],
                    "add_steps": [],
                }
            )

    fixed, fixes = validate_plan(
        plan, readme_text="README", repo_path=tmp_path, llm_client=_OverreachLLM()
    )
    # Command unchanged
    assert fixed.steps[0].command == plan.steps[0].command

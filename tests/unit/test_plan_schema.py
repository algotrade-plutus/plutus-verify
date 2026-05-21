"""Tests for ExtractedPlan parsing and JSON-schema validation."""
import pytest
from plutus_verify.extract.plan import (
    ExtractedPlan,
    PlanValidationError,
    parse_plan,
)


def _minimal_valid_plan() -> dict:
    return {
        "schema_version": "1.0",
        "repo": {
            "name": "Demo",
            "primary_language": "python",
            "env_setup": {
                "kind": "requirements_txt",
                "path": "requirements.txt",
                "python_version": "3.11",
                "extra_setup_commands": [],
            },
            "secrets_required": [],
        },
        "nine_step_mapping": {
            f"step_{i}_{name}": {"present": True, "section_heading": name, "confidence": 0.9}
            for i, name in enumerate(
                [
                    "hypothesis",
                    "data_collection",
                    "data_processing",
                    "in_sample",
                    "optimization",
                    "out_of_sample",
                    "paper_trading",
                ],
                start=1,
            )
        },
        "steps": [
            {
                "id": "in_sample_backtest",
                "nine_step": "step_4_in_sample",
                "required": True,
                "depends_on": [],
                "command": "python backtesting.py",
                "config_files": [],
                "network": "none",
                "timeout_seconds": 600,
                "produces": ["result/backtest/hpr.svg"],
            }
        ],
        "expected_results": [
            {
                "step_id": "in_sample_backtest",
                "metrics": [
                    {
                        "name": "sharpe_ratio",
                        "value": 0.9516,
                        "locate": {"kind": "stdout_table", "row": "Sharpe Ratio", "col": 1},
                        "tolerance": {"kind": "relative", "value": 0.05},
                    }
                ],
                "charts": [],
            }
        ],
        "extraction_notes": [],
    }


def test_parse_plan_accepts_minimal_valid_plan():
    plan = parse_plan(_minimal_valid_plan())
    assert isinstance(plan, ExtractedPlan)
    assert plan.schema_version == "1.0"
    assert plan.repo.name == "Demo"
    assert len(plan.steps) == 1
    assert plan.steps[0].id == "in_sample_backtest"
    assert plan.expected_results[0].metrics[0].value == 0.9516


def test_parse_plan_rejects_missing_required_field():
    bad = _minimal_valid_plan()
    del bad["repo"]
    with pytest.raises(PlanValidationError):
        parse_plan(bad)


def test_parse_plan_rejects_unknown_nine_step_reference():
    bad = _minimal_valid_plan()
    bad["steps"][0]["nine_step"] = "step_99_made_up"
    with pytest.raises(PlanValidationError):
        parse_plan(bad)


def test_parse_plan_rejects_step_referencing_unknown_dependency():
    bad = _minimal_valid_plan()
    bad["steps"][0]["depends_on"] = ["nonexistent_step"]
    with pytest.raises(PlanValidationError):
        parse_plan(bad)


def test_parse_plan_rejects_expected_results_for_unknown_step():
    bad = _minimal_valid_plan()
    bad["expected_results"][0]["step_id"] = "ghost_step"
    with pytest.raises(PlanValidationError):
        parse_plan(bad)


def test_step_verification_mode_defaults_to_execute():
    plan = parse_plan(_minimal_valid_plan())
    assert plan.steps[0].verification_mode == "execute"


def test_parse_plan_accepts_step_with_artifact_check_mode():
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"][0]["verification_mode"] = "artifact_check"
    plan = parse_plan(plan_dict)
    assert plan.steps[0].verification_mode == "artifact_check"


def test_parse_plan_rejects_unknown_verification_mode():
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"][0]["verification_mode"] = "made_up"
    with pytest.raises(PlanValidationError):
        parse_plan(plan_dict)


def test_parse_plan_accepts_step_with_alternatives_and_no_command():
    plan_dict = _minimal_valid_plan()
    plan_dict["steps"].insert(
        0,
        {
            "id": "data_collection",
            "nine_step": "step_2_data_collection",
            "required": False,
            "alternatives": [
                {
                    "label": "google_drive",
                    "kind": "manual_download",
                    "url": "https://example.com/data",
                    "expected_layout": ["data/is/", "data/os/"],
                },
                {
                    "label": "db_loader",
                    "kind": "command",
                    "command": "python data_loader.py",
                    "needs_secrets": ["DB_NAME"],
                    "network": "bridge",
                    "timeout_seconds": 1800,
                    "produces": ["data/is/", "data/os/"],
                },
            ],
        },
    )
    plan_dict["steps"][1]["depends_on"] = ["data_collection"]
    plan = parse_plan(plan_dict)
    assert plan.steps[0].id == "data_collection"
    assert plan.steps[0].alternatives is not None
    assert plan.steps[0].alternatives[0].label == "google_drive"
    assert plan.steps[0].command is None

"""Tests for the v2 manifest JSON-Schema."""
import pytest
from jsonschema import Draft202012Validator

from plutus_verify.spec.schema import MANIFEST_SCHEMA


def _minimal_valid_dict() -> dict:
    return {
        "schema_version": "2.0",
        "repo": {"name": "Demo", "primary_language": "python"},
        "env": {
            "base": "python",
            "python_version": "3.11",
            "requirements_file": "requirements.txt",
        },
        "secrets": [],
        "data_sources": {"processed": [], "raw": []},
        "steps": [
            {
                "id": "in_sample",
                "nine_step": "step_4_in_sample",
                "required": True,
                "command": "python -m demo.backtest",
                "outputs": ["out/metrics.json"],
            }
        ],
        "expected": [],
        "nine_step_coverage": {},
    }


def test_schema_accepts_minimal():
    Draft202012Validator(MANIFEST_SCHEMA).validate(_minimal_valid_dict())


def test_schema_rejects_wrong_version():
    bad = _minimal_valid_dict()
    bad["schema_version"] = "1.0"
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(bad))
    assert errs, "expected schema_version=1.0 to be rejected"


def test_schema_rejects_unknown_env_base():
    bad = _minimal_valid_dict()
    bad["env"]["base"] = "rust"
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(bad))
    assert errs, "expected schema to reject env.base='rust' (not in enum)"


def test_schema_allows_nine_step_null_on_step():
    d = _minimal_valid_dict()
    d["steps"].append(
        {
            "id": "train_model",
            "nine_step": None,
            "label": "Custom",
            "required": True,
            "command": "python -m demo.train",
            "outputs": ["models/clf.pkl"],
        }
    )
    Draft202012Validator(MANIFEST_SCHEMA).validate(d)


def test_schema_accepts_data_sources_with_satisfies():
    d = _minimal_valid_dict()
    d["data_sources"]["processed"].append(
        {
            "kind": "google_drive",
            "url": "https://drive.google.com/x",
            "expected_layout": ["data/processed/*.parquet"],
            "satisfies": ["data_collection", "data_processing"],
        }
    )
    Draft202012Validator(MANIFEST_SCHEMA).validate(d)


def test_schema_accepts_expected_with_metric_and_reference_output():
    d = _minimal_valid_dict()
    d["expected"].append(
        {
            "step_id": "in_sample",
            "metrics": [
                {
                    "name": "sharpe_ratio",
                    "display_name": "Sharpe Ratio",
                    "value": 0.85,
                    "tolerance": {"kind": "relative", "value": 0.05},
                }
            ],
            "reference_outputs": [
                {
                    "path": "out/equity_curve.png",
                    "compare": "visual_similarity",
                    "threshold": 0.7,
                }
            ],
        }
    )
    Draft202012Validator(MANIFEST_SCHEMA).validate(d)


def test_schema_rejects_locate_property_on_metric():
    d = _minimal_valid_dict()
    d["expected"].append(
        {
            "step_id": "in_sample",
            "metrics": [
                {
                    "name": "sharpe_ratio",
                    "value": 0.85,
                    "tolerance": {"kind": "relative", "value": 0.05},
                    "locate": {"kind": "json_file", "path": "x.json", "jsonpath": "$.s"},
                }
            ],
        }
    )
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(d))
    assert errs, "expected schema to reject `locate` on metric (additionalProperties=False)"


def test_schema_rejects_non_snake_case_metric_name():
    d = _minimal_valid_dict()
    d["expected"].append(
        {
            "step_id": "in_sample",
            "metrics": [
                {
                    "name": "Sharpe Ratio",  # spaces + caps → rejected
                    "value": 0.85,
                    "tolerance": {"kind": "relative", "value": 0.05},
                }
            ],
        }
    )
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(d))
    assert errs, "expected schema to reject non-snake_case metric name"


def test_schema_rejects_unknown_compare_kind():
    d = _minimal_valid_dict()
    d["expected"].append(
        {
            "step_id": "in_sample",
            "metrics": [],
            "reference_outputs": [
                {"path": "out/x.json", "compare": "fuzzy_magic"}
            ],
        }
    )
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(d))
    assert errs, "expected schema to reject compare='fuzzy_magic' (not in enum)"

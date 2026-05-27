"""Tests for the SDK results.json JSON-Schema."""
from __future__ import annotations

import pytest
from jsonschema import ValidationError

from plutus_verify.sdk.schema import (
    ARTIFACT_KINDS,
    NAME_PATTERN,
    RESULTS_SCHEMA,
    UNIT_KINDS,
    validate_results,
)


def _minimal_valid() -> dict:
    return {
        "schema_version": "1.0",
        "step_id": "in_sample_backtest",
        "metrics": [
            {"name": "sharpe_ratio", "value": 0.95, "unit": "ratio"}
        ],
        "artifacts": [],
        "metadata": {},
    }


def _full_valid() -> dict:
    return {
        "schema_version": "1.0",
        "step_id": "in_sample_backtest",
        "metrics": [
            {"name": "sharpe_ratio", "value": 0.9517, "unit": "ratio"},
            {"name": "maximum_drawdown", "value": -0.20, "unit": "ratio"},
            {"name": "trade_count", "value": 42, "unit": "count"},
        ],
        "artifacts": [
            {"name": "equity_curve", "path": "result/backtest/hpr.svg", "kind": "chart"},
            {"name": "raw_returns", "path": "result/backtest/returns.csv", "kind": "csv"},
        ],
        "metadata": {"seed": 2025, "duration_seconds": 12.4, "git_commit": "abc1234"},
    }


def test_constants_match_spec() -> None:
    assert UNIT_KINDS == ("fraction", "ratio", "count", "currency_usd", "seconds")
    assert ARTIFACT_KINDS == ("chart", "csv", "json", "image", "other")
    assert NAME_PATTERN == r"^[a-z][a-z0-9_]*$"


def test_minimal_payload_validates() -> None:
    validate_results(_minimal_valid())


def test_full_payload_validates() -> None:
    validate_results(_full_valid())


def test_missing_schema_version_fails() -> None:
    bad = _minimal_valid()
    del bad["schema_version"]
    with pytest.raises(ValidationError):
        validate_results(bad)


def test_missing_step_id_fails() -> None:
    bad = _minimal_valid()
    del bad["step_id"]
    with pytest.raises(ValidationError):
        validate_results(bad)


def test_percent_unit_rejected() -> None:
    bad = _minimal_valid()
    bad["metrics"][0]["unit"] = "percent"
    with pytest.raises(ValidationError):
        validate_results(bad)


def test_unknown_unit_rejected() -> None:
    bad = _minimal_valid()
    bad["metrics"][0]["unit"] = "bananas"
    with pytest.raises(ValidationError):
        validate_results(bad)


def test_unknown_artifact_kind_rejected() -> None:
    bad = _full_valid()
    bad["artifacts"][0]["kind"] = "pdf"
    with pytest.raises(ValidationError):
        validate_results(bad)


@pytest.mark.parametrize("bad_name", ["SharpeRatio", "sharpe-ratio", "1sharpe", "_sharpe", ""])
def test_non_snake_case_metric_name_rejected(bad_name: str) -> None:
    bad = _minimal_valid()
    bad["metrics"][0]["name"] = bad_name
    with pytest.raises(ValidationError):
        validate_results(bad)


@pytest.mark.parametrize("bad_name", ["EquityCurve", "equity-curve", "9chart"])
def test_non_snake_case_artifact_name_rejected(bad_name: str) -> None:
    bad = _full_valid()
    bad["artifacts"][0]["name"] = bad_name
    with pytest.raises(ValidationError):
        validate_results(bad)


def test_schema_is_draft_2020_12() -> None:
    assert RESULTS_SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_const_version_is_1_0() -> None:
    bad = _minimal_valid()
    bad["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        validate_results(bad)

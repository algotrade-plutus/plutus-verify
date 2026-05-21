"""Tests for the v2 verifier results.json reader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from plutus_verify.spec.runtime.results import (
    Artifact,
    MalformedResultsError,
    Metric,
    MetricNotProducedError,
    MissingResultsError,
    ResultsError,
    ResultsFile,
    load_results,
)


def _write_results(repo: Path, step_id: str, payload: dict) -> Path:
    out_dir = repo / ".plutus" / "run" / step_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "results.json"
    path.write_text(json.dumps(payload))
    return path


def _valid_payload(step_id: str = "in_sample_backtest") -> dict:
    return {
        "schema_version": "1.0",
        "step_id": step_id,
        "metrics": [
            {"name": "sharpe_ratio", "value": 0.9517, "unit": "ratio"},
            {"name": "n_trades", "value": 42, "unit": "count"},
        ],
        "artifacts": [
            {"name": "equity_curve", "path": "result/backtest/hpr.svg", "kind": "chart"},
        ],
        "metadata": {"seed": 2025, "duration_seconds": 12.4, "git_commit": "abc1234"},
    }


def test_happy_path_returns_typed_results_file(tmp_path: Path):
    _write_results(tmp_path, "in_sample_backtest", _valid_payload())

    result = load_results(tmp_path, step_id="in_sample_backtest")

    assert isinstance(result, ResultsFile)
    assert result.schema_version == "1.0"
    assert result.step_id == "in_sample_backtest"
    assert isinstance(result.metrics, tuple)
    assert len(result.metrics) == 2
    assert result.metrics[0] == Metric(name="sharpe_ratio", value=0.9517, unit="ratio")
    assert result.metrics[1] == Metric(name="n_trades", value=42, unit="count")
    assert isinstance(result.artifacts, tuple)
    assert len(result.artifacts) == 1
    assert result.artifacts[0] == Artifact(
        name="equity_curve", path="result/backtest/hpr.svg", kind="chart"
    )
    assert result.metadata == {"seed": 2025, "duration_seconds": 12.4, "git_commit": "abc1234"}


def test_missing_file_raises_missing_results_error(tmp_path: Path):
    with pytest.raises(MissingResultsError) as exc_info:
        load_results(tmp_path, step_id="never_ran")

    msg = str(exc_info.value)
    assert "never_ran" in msg or "results.json" in msg
    expected_path = tmp_path / ".plutus" / "run" / "never_ran" / "results.json"
    assert str(expected_path) in msg
    # Also ensure the umbrella ResultsError matches it.
    assert isinstance(exc_info.value, ResultsError)


def test_invalid_json_raises_malformed_results_error(tmp_path: Path):
    step_id = "broken_step"
    out_dir = tmp_path / ".plutus" / "run" / step_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text("{not json")

    with pytest.raises(MalformedResultsError) as exc_info:
        load_results(tmp_path, step_id=step_id)

    # The underlying JSONDecodeError must be chained.
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
    assert "results.json" in str(exc_info.value)


def test_schema_violation_missing_step_id(tmp_path: Path):
    step_id = "schema_bad"
    out_dir = tmp_path / ".plutus" / "run" / step_id
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = _valid_payload(step_id)
    del payload["step_id"]
    (out_dir / "results.json").write_text(json.dumps(payload))

    with pytest.raises(MalformedResultsError) as exc_info:
        load_results(tmp_path, step_id=step_id)

    # Should chain the underlying jsonschema ValidationError.
    from jsonschema import ValidationError as _ValidationError

    assert isinstance(exc_info.value.__cause__, _ValidationError)
    assert "schema" in str(exc_info.value).lower() or "step_id" in str(exc_info.value)


def test_schema_violation_bad_unit_percent(tmp_path: Path):
    step_id = "bad_unit"
    payload = _valid_payload(step_id)
    payload["metrics"] = [{"name": "sharpe_ratio", "value": 95.0, "unit": "percent"}]
    _write_results(tmp_path, step_id, payload)

    with pytest.raises(MalformedResultsError) as exc_info:
        load_results(tmp_path, step_id=step_id)

    assert isinstance(exc_info.value, ResultsError)


def test_schema_violation_non_snake_case_metric_name(tmp_path: Path):
    step_id = "bad_name"
    payload = _valid_payload(step_id)
    payload["metrics"] = [{"name": "SharpeRatio", "value": 1.0, "unit": "ratio"}]
    _write_results(tmp_path, step_id, payload)

    with pytest.raises(MalformedResultsError):
        load_results(tmp_path, step_id=step_id)


def test_step_id_mismatch_raises_malformed_results_error(tmp_path: Path):
    payload = _valid_payload("foo")
    # Write the file under the directory matching its own step_id...
    _write_results(tmp_path, "foo", payload)
    # ...but ALSO put one at the path we'll request, with the wrong step_id inside.
    out_dir = tmp_path / ".plutus" / "run" / "bar"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(payload))

    with pytest.raises(MalformedResultsError) as exc_info:
        load_results(tmp_path, step_id="bar")

    msg = str(exc_info.value)
    assert "foo" in msg and "bar" in msg


def test_empty_metrics_array_is_valid(tmp_path: Path):
    payload = _valid_payload("empty_metrics")
    payload["metrics"] = []
    _write_results(tmp_path, "empty_metrics", payload)

    result = load_results(tmp_path, step_id="empty_metrics")

    assert result.metrics == ()


def test_optional_artifacts_and_metadata_default(tmp_path: Path):
    # The SDK schema requires both artifacts and metadata to be present, but
    # the reader should tolerate metadata being an empty object and artifacts
    # being an empty list. We also test the "absent" branch by relaxing the
    # written payload — when artifacts/metadata are missing the schema raises,
    # so to exercise the reader's default-fill code path we write a file that
    # the schema accepts (empty containers) and confirm we get () and {}.
    payload = _valid_payload("optionals")
    payload["artifacts"] = []
    payload["metadata"] = {}
    _write_results(tmp_path, "optionals", payload)

    result = load_results(tmp_path, step_id="optionals")

    assert result.artifacts == ()
    assert result.metadata == {}


def test_metric_not_produced_error_is_importable():
    # Task 4 (orchestrator) raises this; load_results does not. Just confirm
    # the symbol exists and is a ResultsError subclass so the orchestrator
    # can re-export / catch uniformly.
    assert issubclass(MetricNotProducedError, ResultsError)


def test_round_trip_via_sdk(tmp_path: Path):
    from plutus_verify.sdk import step

    with step("my_step", repo_path=tmp_path) as r:
        r.headline("sharpe_ratio", 0.95, unit="ratio")

    result = load_results(tmp_path, step_id="my_step")

    assert result.step_id == "my_step"
    assert len(result.metrics) == 1
    assert result.metrics[0].name == "sharpe_ratio"
    assert result.metrics[0].value == 0.95
    assert result.metrics[0].unit == "ratio"

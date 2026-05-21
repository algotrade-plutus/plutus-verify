"""Tests for compare.metrics: locate + tolerance engine."""
import json
from pathlib import Path

import pytest

from plutus_verify.compare.metrics import (
    MetricComparison,
    MetricSources,
    compare_metric,
    within_tolerance,
)
from plutus_verify.extract.plan import ExpectedMetric, Locate, Tolerance


# ---------- tolerance engine ----------


@pytest.mark.parametrize(
    "kind,value,expected,actual,want",
    [
        ("relative", 0.05, 1.0, 1.04, True),
        ("relative", 0.05, 1.0, 1.06, False),
        ("relative", 0.05, -0.2, -0.21, True),    # |Δ|/|expected| = 0.05
        ("absolute", 0.02, -0.20, -0.21, True),
        ("absolute", 0.02, -0.20, -0.23, False),
        ("absolute", 1.0, 17.10, 17.05, True),
        ("absolute", 1.0, 17.10, 18.20, False),
        ("exact", 0.0, 3, 3, True),
        ("exact", 0.0, 3, 4, False),
        ("relative", 0.05, 0.0, 0.0001, False),   # divide-by-zero -> absolute fallback
        ("relative", 0.05, 0.0, 0.0, True),
    ],
)
def test_within_tolerance_matrix(kind, value, expected, actual, want):
    tol = Tolerance(kind=kind, value=value)
    assert within_tolerance(expected, actual, tol) is want


# ---------- stdout_table ----------


def test_compare_metric_locate_stdout_table_pass(tmp_path: Path):
    stdout = (
        "Some preamble\n"
        "| Metric                 | Value                              |\n"
        "|------------------------|------------------------------------|\n"
        "| Sharpe Ratio           | 0.9498                             |\n"
        "| Sortino Ratio          | 1.3501                             |\n"
        "trailing log line\n"
    )
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(kind="stdout_table", row="Sharpe Ratio", col=1),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(expected, MetricSources(stdout=stdout, file_root=tmp_path))
    assert isinstance(result, MetricComparison)
    assert result.pass_ is True
    assert result.actual == pytest.approx(0.9498)
    assert result.unverifiable_reason is None


def test_compare_metric_locate_stdout_table_out_of_tolerance(tmp_path: Path):
    stdout = "| Sharpe Ratio | 2.5 |\n"
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(kind="stdout_table", row="Sharpe Ratio", col=1),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(expected, MetricSources(stdout=stdout, file_root=tmp_path))
    assert result.pass_ is False
    assert result.actual == pytest.approx(2.5)


def test_compare_metric_locate_stdout_table_row_missing(tmp_path: Path):
    stdout = "| Sortino Ratio | 1.0 |\n"
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(kind="stdout_table", row="Sharpe Ratio", col=1),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(expected, MetricSources(stdout=stdout, file_root=tmp_path))
    assert result.pass_ is False
    assert result.unverifiable_reason is not None
    assert "row" in result.unverifiable_reason.lower()


# ---------- json_file ----------


def test_compare_metric_locate_json_file_pass(tmp_path: Path):
    (tmp_path / "parameter").mkdir()
    (tmp_path / "parameter" / "optimized_parameter.json").write_text(
        json.dumps({"step": 3.05})
    )
    expected = ExpectedMetric(
        name="step",
        value=3.1,
        locate=Locate(
            kind="json_file",
            path="parameter/optimized_parameter.json",
            jsonpath="$.step",
        ),
        tolerance=Tolerance(kind="absolute", value=0.5),
    )
    result = compare_metric(expected, MetricSources(stdout="", file_root=tmp_path))
    assert result.pass_ is True
    assert result.actual == pytest.approx(3.05)


def test_compare_metric_locate_json_file_missing_file(tmp_path: Path):
    expected = ExpectedMetric(
        name="step",
        value=3.1,
        locate=Locate(
            kind="json_file",
            path="nope/missing.json",
            jsonpath="$.step",
        ),
        tolerance=Tolerance(kind="absolute", value=0.5),
    )
    result = compare_metric(expected, MetricSources(stdout="", file_root=tmp_path))
    assert result.pass_ is False
    assert result.unverifiable_reason is not None
    assert "missing" in result.unverifiable_reason.lower() or "not found" in result.unverifiable_reason.lower()


def test_compare_metric_locate_json_file_bad_jsonpath(tmp_path: Path):
    (tmp_path / "x.json").write_text(json.dumps({"step": 3.0}))
    expected = ExpectedMetric(
        name="step",
        value=3.1,
        locate=Locate(kind="json_file", path="x.json", jsonpath="$.nonexistent"),
        tolerance=Tolerance(kind="absolute", value=0.5),
    )
    result = compare_metric(expected, MetricSources(stdout="", file_root=tmp_path))
    assert result.pass_ is False
    assert result.unverifiable_reason is not None


# ---------- file_regex ----------


def test_compare_metric_locate_file_regex_pass(tmp_path: Path):
    (tmp_path / "summary.txt").write_text("Final Sharpe: 0.9501 over 252 days")
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(
            kind="file_regex",
            path="summary.txt",
            pattern=r"Final Sharpe:\s+(?P<value>[-+0-9.eE]+)",
        ),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(expected, MetricSources(stdout="", file_root=tmp_path))
    assert result.pass_ is True
    assert result.actual == pytest.approx(0.9501)


def test_compare_metric_uses_llm_fallback_when_locate_fails(tmp_path: Path):
    """When deterministic locate fails AND a match_client is provided, the LLM
    fills in the value, which then goes through the regular tolerance check."""
    from plutus_verify.compare.llm_match import MetricMatchClient, MetricMatchRequest

    class _StubMatch(MetricMatchClient):
        def __init__(self, response):
            self.response = response
            self.called = False

        def match(self, *, metrics, stdout):
            self.called = True
            return self.response

    stdout = "Sharpe ratio: 0.9498\n"  # free text, NOT a markdown table
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(kind="stdout_table", row="Sharpe Ratio", col=1),
        tolerance=Tolerance(kind="relative", value=0.05),
    )

    import json as _json
    match_client = _StubMatch(_json.dumps({"matches": [{"name": "sharpe_ratio", "actual": 0.9498}]}))
    result = compare_metric(
        expected, MetricSources(stdout=stdout, file_root=tmp_path), match_client=match_client
    )
    assert match_client.called is True
    assert result.actual == pytest.approx(0.9498)
    assert result.pass_ is True


def test_compare_metric_does_not_call_llm_when_deterministic_succeeds(tmp_path: Path):
    """LLM is a fallback only — happy path stays deterministic-only."""
    from plutus_verify.compare.llm_match import MetricMatchClient

    class _NeverCall(MetricMatchClient):
        def match(self, *, metrics, stdout):
            raise AssertionError("match should not be called")

    stdout = "| Sharpe Ratio | 0.9498 |\n"
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(kind="stdout_table", row="Sharpe Ratio", col=1),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(
        expected, MetricSources(stdout=stdout, file_root=tmp_path), match_client=_NeverCall()
    )
    assert result.pass_ is True


def test_compare_metric_llm_returns_none_falls_back_to_unverifiable(tmp_path: Path):
    """When deterministic AND LLM both fail to locate, metric is unverifiable."""
    from plutus_verify.compare.llm_match import MetricMatchClient
    import json as _json

    class _Empty(MetricMatchClient):
        def match(self, *, metrics, stdout):
            return _json.dumps({"matches": [{"name": "sharpe_ratio", "actual": None}]})

    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(kind="stdout_table", row="Sharpe Ratio", col=1),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(
        expected, MetricSources(stdout="nothing here", file_root=tmp_path), match_client=_Empty()
    )
    assert result.pass_ is False
    assert result.actual is None
    assert result.unverifiable_reason is not None
    assert "llm" in result.unverifiable_reason.lower()


def test_compare_metric_locate_file_regex_no_match(tmp_path: Path):
    (tmp_path / "summary.txt").write_text("nothing here")
    expected = ExpectedMetric(
        name="sharpe_ratio",
        value=0.9516,
        locate=Locate(
            kind="file_regex",
            path="summary.txt",
            pattern=r"Final Sharpe:\s+(?P<value>[-+0-9.eE]+)",
        ),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    result = compare_metric(expected, MetricSources(stdout="", file_root=tmp_path))
    assert result.pass_ is False
    assert result.unverifiable_reason is not None

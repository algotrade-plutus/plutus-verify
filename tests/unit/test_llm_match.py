"""Tests for LLM-eyeballing metric match (compare.llm_match)."""
import json

import pytest

from plutus_verify.compare.llm_match import (
    MetricMatchClient,
    MetricMatchRequest,
    eyeball_metrics,
)


class _ScriptedMatchClient(MetricMatchClient):
    def __init__(self, response_json: str):
        self.response_json = response_json
        self.calls: list[tuple[list, str]] = []

    def match(self, *, metrics, stdout: str) -> str:
        self.calls.append((list(metrics), stdout))
        return self.response_json


def _req(name: str, value: float) -> MetricMatchRequest:
    return MetricMatchRequest(name=name, expected_approx=value)


def test_eyeball_metrics_extracts_values_from_stdout():
    canned = json.dumps(
        {
            "matches": [
                {"name": "Sharpe Ratio", "actual": 0.9498, "notes": ""},
                {"name": "Sortino Ratio", "actual": 1.3501, "notes": ""},
            ]
        }
    )
    client = _ScriptedMatchClient(canned)
    out = eyeball_metrics(
        metrics=[_req("Sharpe Ratio", 0.9516), _req("Sortino Ratio", 1.349)],
        stdout="some stdout",
        client=client,
    )
    assert out["Sharpe Ratio"] == pytest.approx(0.9498)
    assert out["Sortino Ratio"] == pytest.approx(1.3501)
    assert len(client.calls) == 1


def test_eyeball_metrics_returns_none_for_not_found():
    canned = json.dumps(
        {
            "matches": [
                {"name": "Sharpe Ratio", "actual": None, "notes": "not in stdout"},
            ]
        }
    )
    client = _ScriptedMatchClient(canned)
    out = eyeball_metrics(
        metrics=[_req("Sharpe Ratio", 0.9516)],
        stdout="empty",
        client=client,
    )
    assert out["Sharpe Ratio"] is None


def test_eyeball_metrics_tolerates_markdown_fence_around_json():
    canned = "```json\n" + json.dumps({"matches": [{"name": "x", "actual": 1.0}]}) + "\n```"
    client = _ScriptedMatchClient(canned)
    out = eyeball_metrics(
        metrics=[_req("x", 1.0)],
        stdout="",
        client=client,
    )
    assert out["x"] == pytest.approx(1.0)


def test_eyeball_metrics_returns_empty_on_malformed_json():
    """If LLM returns garbage, fall back to all-None — caller handles as unverifiable."""
    client = _ScriptedMatchClient("not json at all")
    out = eyeball_metrics(
        metrics=[_req("Sharpe Ratio", 0.9516)],
        stdout="...",
        client=client,
    )
    assert out["Sharpe Ratio"] is None


def test_eyeball_metrics_handles_partial_matches():
    """If LLM returns matches for some metrics but not all, others get None."""
    canned = json.dumps(
        {"matches": [{"name": "Sharpe Ratio", "actual": 0.95}]}
    )
    client = _ScriptedMatchClient(canned)
    out = eyeball_metrics(
        metrics=[_req("Sharpe Ratio", 0.95), _req("Sortino Ratio", 1.3)],
        stdout="x",
        client=client,
    )
    assert out["Sharpe Ratio"] == pytest.approx(0.95)
    assert out["Sortino Ratio"] is None

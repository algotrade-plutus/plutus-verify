"""Tests for the top-level ``extract_plan`` orchestrator (Iteration 4).

These cover the wrapper that ties together ``decompose`` and ``stitch``.
Detailed per-call behaviour lives in ``test_extract_decompose.py``; this file
exercises the orchestrator's contract:

  - Returns a validated ExtractedPlan on the happy path
  - Wraps DecomposeError as ExtractError
  - Wraps PlanValidationError (from stitch) as ExtractError
  - Retries on transient network errors (TimeoutError)
"""
from __future__ import annotations

import json

import pytest

from plutus_verify.extract import ExtractError, LLMClient, extract_plan
from plutus_verify.extract.plan import NINE_STEP_KEYS


def _canned_repo() -> str:
    return json.dumps(
        {
            "name": "Demo",
            "primary_language": "python",
            "env_setup": {
                "kind": "requirements_txt",
                "path": "requirements.txt",
                "python_version": "3.11",
            },
            "secrets_required": [],
        }
    )


def _canned_nine_step() -> str:
    return json.dumps(
        {
            k: {
                "present": (k == "step_4_in_sample"),
                "section_heading": "In-sample" if k == "step_4_in_sample" else None,
            }
            for k in NINE_STEP_KEYS
        }
    )


def _canned_steps() -> str:
    return json.dumps(
        [
            {
                "id": "in_sample_backtest",
                "nine_step": "step_4_in_sample",
                "required": True,
                "verification_mode": "execute",
                "command": "python backtesting.py",
                "network": "none",
                "config_files": [],
                "produces": [],
                "alternatives": [],
            }
        ]
    )


def _canned_results() -> str:
    return json.dumps(
        [
            {
                "step_id": "in_sample_backtest",
                "metrics": [
                    {
                        "name": "Sharpe Ratio",
                        "value": 0.9516,
                        "locate": {"kind": "stdout_table", "row": "Sharpe Ratio", "col": 1},
                        "tolerance": {"kind": "relative", "value": 0.05},
                    }
                ],
                "charts": [],
            }
        ]
    )


class _ScriptedClient(LLMClient):
    def __init__(self, completions: list[str]) -> None:
        self._completions = list(completions)
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        self.prompts.append(user)
        if not self._completions:
            raise AssertionError("ran out of canned completions")
        return self._completions.pop(0)


# ---------- Happy path ----------


def test_extract_returns_plan_on_first_try():
    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), _canned_steps(), _canned_results()]
    )
    plan = extract_plan("# any readme", client)
    assert plan.schema_version == "1.0"
    assert plan.repo.name == "Demo"
    assert plan.steps[0].id == "in_sample_backtest"
    assert plan.expected_results[0].metrics[0].value == 0.9516
    # 4 calls, one per element
    assert len(client.prompts) == 4


# ---------- Per-call retry ----------


def test_extract_retries_on_invalid_json_then_succeeds():
    """A bad first response on Call 1 triggers a retry; total 5 calls."""
    client = _ScriptedClient(
        [
            "this is not json",
            _canned_repo(),
            _canned_nine_step(),
            _canned_steps(),
            _canned_results(),
        ]
    )
    plan = extract_plan("# readme", client)
    assert plan.repo.name == "Demo"
    assert len(client.prompts) == 5


# ---------- Hard fail ----------


def test_extract_hard_fails_when_a_call_exhausts_retries():
    """Call 1 fails on both attempt 0 and attempt 1 → ExtractError."""
    client = _ScriptedClient(["nope", "still nope"])
    with pytest.raises(ExtractError) as exc:
        extract_plan("# readme", client, max_retries=1)
    assert "repo" in str(exc.value).lower() or "json" in str(exc.value).lower()


def test_extract_hard_fails_when_stitched_plan_is_invalid():
    """If decompose succeeds but stitched plan violates schema, ExtractError."""
    bad_results = json.dumps(
        [
            {
                "step_id": "completely_nonexistent_step_id",
                "metrics": [],
                "charts": [],
            }
        ]
    )
    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), _canned_steps(), bad_results]
    )
    with pytest.raises(ExtractError) as exc:
        extract_plan("# readme", client)
    assert "schema" in str(exc.value).lower() or "unknown step" in str(exc.value).lower()


# ---------- Code-fence stripping ----------


def test_extract_strips_markdown_code_fence_around_json():
    """LLMs often wrap JSON in ```json ... ``` fences. Tolerate that."""
    fenced = "```json\n" + _canned_repo() + "\n```"
    client = _ScriptedClient(
        [fenced, _canned_nine_step(), _canned_steps(), _canned_results()]
    )
    plan = extract_plan("# readme", client)
    assert plan.schema_version == "1.0"


# ---------- Transient network errors ----------


class _FlakyClient(LLMClient):
    """Raises TimeoutError on the first ``fail_n`` calls; then plays canned responses."""

    def __init__(self, fail_n: int, good_seq: list[str]):
        self._fail_n = fail_n
        self._good = list(good_seq)
        self.attempts = 0

    def complete_json(self, system, user, *, temperature=0.0):
        self.attempts += 1
        if self.attempts <= self._fail_n:
            raise TimeoutError("simulated read timeout")
        if not self._good:
            raise AssertionError("ran out of canned good responses")
        return self._good.pop(0)


def test_extract_retries_on_transient_timeout_then_succeeds():
    """One timeout on Call 1, then all 4 calls succeed → plan returned."""
    client = _FlakyClient(
        fail_n=1,
        good_seq=[_canned_repo(), _canned_nine_step(), _canned_steps(), _canned_results()],
    )
    plan = extract_plan("# readme", client, max_retries=1)
    assert plan.schema_version == "1.0"
    # 1 timeout + 4 successful = 5 attempts
    assert client.attempts == 5

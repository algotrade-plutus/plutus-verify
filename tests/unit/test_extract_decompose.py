"""Tests for the decomposed extraction orchestrator (Iteration 4).

These tests use a scripted LLM client to feed canned responses for each of
the 4 form-filling calls. They exercise:
  - Happy path (all 4 calls succeed)
  - Per-call retry on parse failure
  - Hard-fail when a call exhausts retries
  - Cross-call context plumbing (Call 3 sees Call 2's output, etc.)
  - Code-fence stripping
  - on_attempt callback semantics
"""
from __future__ import annotations

import json

import pytest

from plutus_verify.extract import LLMClient
from plutus_verify.extract.decompose import DecomposeError, decompose
from plutus_verify.extract.plan import NINE_STEP_KEYS


class _ScriptedClient(LLMClient):
    """Returns canned completions in order. Records user prompts for inspection."""

    def __init__(self, completions: list[str]) -> None:
        self._completions = list(completions)
        self.prompts: list[str] = []

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        self.prompts.append(user)
        if not self._completions:
            raise AssertionError("ran out of canned completions")
        return self._completions.pop(0)


# ---------- Canned per-call responses ----------


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


def _canned_nine_step(present: set[str] | None = None) -> str:
    if present is None:
        present = {"step_4_in_sample"}
    return json.dumps(
        {
            k: {
                "present": k in present,
                "section_heading": k.replace("_", " ") if k in present else None,
            }
            for k in NINE_STEP_KEYS
        }
    )


def _canned_steps(ids: list[str] | None = None) -> str:
    if ids is None:
        ids = ["in_sample_backtest"]
    steps = [
        {
            "id": sid,
            "nine_step": "step_4_in_sample",
            "required": True,
            "verification_mode": "execute",
            "command": "python backtesting.py",
            "network": "none",
            "config_files": [],
            "produces": ["result/backtest/hpr.svg"],
            "alternatives": [],
        }
        for sid in ids
    ]
    return json.dumps(steps)


def _canned_results(step_id: str = "in_sample_backtest") -> str:
    return json.dumps(
        [
            {
                "step_id": step_id,
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


# ---------- Happy path ----------


def test_decompose_returns_all_four_elements():
    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), _canned_steps(), _canned_results()]
    )
    elements = decompose("# README", client)
    assert set(elements.keys()) == {"repo", "nine_step", "steps", "results", "additional_steps"}
    assert elements["repo"]["name"] == "Demo"
    assert elements["nine_step"]["step_4_in_sample"]["present"] is True
    assert elements["steps"][0]["id"] == "in_sample_backtest"
    assert elements["results"][0]["metrics"][0]["value"] == 0.9516
    assert elements["additional_steps"] == []  # Call 5 stub
    assert len(client.prompts) == 4


# ---------- Cross-call context ----------


def test_call_3_receives_present_step_keys_from_call_2():
    client = _ScriptedClient(
        [
            _canned_repo(),
            _canned_nine_step(present={"step_2_data_collection", "step_4_in_sample"}),
            _canned_steps(),
            _canned_results(),
        ]
    )
    decompose("# README", client)
    call_3_prompt = client.prompts[2]
    # The JSON-serialised present-steps list appears verbatim in the prompt;
    # the template's prose mentions other step keys, so we check the list specifically.
    present_list_json = '["step_2_data_collection", "step_4_in_sample"]'
    assert present_list_json in call_3_prompt


def test_call_4_receives_step_ids_from_call_3():
    client = _ScriptedClient(
        [
            _canned_repo(),
            _canned_nine_step(),
            _canned_steps(ids=["in_sample_backtest", "out_of_sample_backtest"]),
            _canned_results(),
        ]
    )
    decompose("# README", client)
    call_4_prompt = client.prompts[3]
    assert "in_sample_backtest" in call_4_prompt
    assert "out_of_sample_backtest" in call_4_prompt


# ---------- Code-fence stripping ----------


def test_decompose_strips_markdown_code_fences():
    fenced_repo = "```json\n" + _canned_repo() + "\n```"
    client = _ScriptedClient(
        [fenced_repo, _canned_nine_step(), _canned_steps(), _canned_results()]
    )
    elements = decompose("# README", client)
    assert elements["repo"]["name"] == "Demo"


# ---------- Retry on parse failure ----------


def test_call_retries_once_on_invalid_json_then_succeeds():
    client = _ScriptedClient(
        [
            "not valid json at all",
            _canned_repo(),
            _canned_nine_step(),
            _canned_steps(),
            _canned_results(),
        ]
    )
    elements = decompose("# README", client, per_call_max_retries=1)
    assert elements["repo"]["name"] == "Demo"
    # Retry was for Call 1 → 5 total calls
    assert len(client.prompts) == 5
    # The second prompt (retry) mentions the parser error
    assert "Previous attempt failed" in client.prompts[1]


def test_call_retries_on_schema_failure_then_succeeds():
    """A repo missing 'env_setup' triggers a retry."""
    bad_repo = json.dumps({"name": "X", "primary_language": "python"})  # missing env_setup
    client = _ScriptedClient(
        [bad_repo, _canned_repo(), _canned_nine_step(), _canned_steps(), _canned_results()]
    )
    elements = decompose("# README", client, per_call_max_retries=1)
    assert elements["repo"]["name"] == "Demo"


def test_call_hard_fails_after_retries_exhausted():
    client = _ScriptedClient(["nope", "still nope"])
    with pytest.raises(DecomposeError) as exc:
        decompose("# README", client, per_call_max_retries=1)
    assert "call 'repo'" in str(exc.value)


# ---------- Per-call validation ----------


def test_call_2_rejects_missing_nine_step_keys():
    """Call 2 must emit all 7 nine_step keys."""
    incomplete = json.dumps(
        {"step_1_hypothesis": {"present": True, "section_heading": "H"}}
    )
    client = _ScriptedClient([_canned_repo(), incomplete, incomplete])  # retry also bad
    with pytest.raises(DecomposeError) as exc:
        decompose("# README", client, per_call_max_retries=1)
    assert "nine_step" in str(exc.value)


def test_call_3_rejects_non_array_output():
    """Call 3 must return an array, not an object."""
    not_array = json.dumps({"steps": [{"id": "x"}]})
    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), not_array, not_array]
    )
    with pytest.raises(DecomposeError) as exc:
        decompose("# README", client, per_call_max_retries=1)
    assert "call 'steps'" in str(exc.value)


def test_call_3_normalizes_network_true_to_bridge():
    """LLM slip: 'network': 'true' should be normalised to 'bridge'."""
    slipped = json.dumps(
        [
            {
                "id": "data_collection",
                "nine_step": "step_2_data_collection",
                "required": True,
                "verification_mode": "execute",
                "command": "python loader.py",
                "network": "true",  # ← LLM slip
                "config_files": [],
                "produces": [],
                "alternatives": [],
            }
        ]
    )
    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), slipped, json.dumps([])]
    )
    elements = decompose("# README", client)
    assert elements["steps"][0]["network"] == "bridge"


def test_call_3_normalizes_artifact_only_to_artifact_check():
    """LLM synonym: 'artifact_only' → 'artifact_check'."""
    synonym = json.dumps(
        [
            {
                "id": "optimization",
                "nine_step": "step_5_optimization",
                "required": True,
                "verification_mode": "artifact_only",  # ← synonym
                "command": None,
                "network": "none",
                "config_files": [],
                "produces": ["parameter/x.json"],
                "alternatives": [],
            }
        ]
    )
    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), synonym, json.dumps([])]
    )
    elements = decompose("# README", client)
    assert elements["steps"][0]["verification_mode"] == "artifact_check"


# ---------- on_attempt callback ----------


def test_on_attempt_fires_for_each_call():
    fired: list[tuple[str, bool]] = []

    def cb(label: str, raw: str, err: Exception | None) -> None:
        fired.append((label, err is None))

    client = _ScriptedClient(
        [_canned_repo(), _canned_nine_step(), _canned_steps(), _canned_results()]
    )
    decompose("# README", client, on_attempt=cb)
    assert len(fired) == 4
    labels = [label for label, _ok in fired]
    assert labels == [
        "call_0_repo_attempt_0",
        "call_1_nine_step_attempt_0",
        "call_2_steps_attempt_0",
        "call_3_results_attempt_0",
    ]
    assert all(ok for _label, ok in fired)


def test_on_attempt_fires_for_retries_too():
    fired: list[str] = []

    def cb(label: str, raw: str, err: Exception | None) -> None:
        fired.append(label)

    client = _ScriptedClient(
        [
            "bad",
            _canned_repo(),  # retry of call 0
            _canned_nine_step(),
            _canned_steps(),
            _canned_results(),
        ]
    )
    decompose("# README", client, per_call_max_retries=1, on_attempt=cb)
    assert "call_0_repo_attempt_0" in fired
    assert "call_0_repo_attempt_1" in fired
    assert len(fired) == 5

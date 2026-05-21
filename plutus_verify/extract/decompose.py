"""Decomposed extraction orchestrator (Iteration 4).

Runs the 4 form-filling LLM calls sequentially, each with its own small
template + retry loop, and returns the per-call elements as a dict ready for
:func:`plutus_verify.extract.stitch.stitch`.

The 5th call (extras escape hatch for non-Plutus ML/research steps) is
stubbed: it returns an empty additional_steps list. Add the real call when
we encounter a repo that needs it.

Each call has at most ``per_call_max_retries`` retries. The retry prompt
includes the parser's error message so the model can self-correct.

The ``on_attempt`` callback fires once per LLM call (including retries) with
a short label like ``"call_0_repo_attempt_0"`` and the raw LLM output. The
pipeline uses this to tee each call's response to disk for auditing.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from plutus_verify.extract.client import LLMClient
from plutus_verify.extract.plan import NINE_STEP_KEYS
from plutus_verify.extract.templates import (
    CALL1_REPO_USER,
    CALL2_NINE_STEP_USER,
    CALL3_STEPS_USER,
    CALL4_RESULTS_USER,
    RETRY_SUFFIX,
    SYSTEM_FILL,
)

__all__ = ["DecomposeError", "decompose"]


class DecomposeError(RuntimeError):
    """Per-call retries exhausted; raise to the orchestrator."""


_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL
)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group("body") if m else text.strip()


def _parse_json(raw: str) -> Any:
    body = _strip_fences(raw)
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg} (line {exc.lineno})") from exc


# ---------- Per-call shape parsers ----------


def _parse_call1_repo(raw: str) -> dict[str, Any]:
    data = _parse_json(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object at top level")
    for required in ("name", "primary_language", "env_setup"):
        if required not in data:
            raise ValueError(f"missing required field: {required!r}")
    env = data.get("env_setup")
    if not isinstance(env, dict) or "kind" not in env:
        raise ValueError("env_setup must be an object with a 'kind' field")
    secrets = data.get("secrets_required")
    if secrets is None:
        data["secrets_required"] = []
    elif not isinstance(secrets, list):
        raise ValueError("secrets_required must be an array")
    return data


def _parse_call2_nine_step(raw: str) -> dict[str, Any]:
    data = _parse_json(raw)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object at top level")
    missing = [k for k in NINE_STEP_KEYS if k not in data]
    if missing:
        raise ValueError(f"missing nine_step keys: {missing}")
    for k in NINE_STEP_KEYS:
        entry = data[k]
        if not isinstance(entry, dict) or "present" not in entry:
            raise ValueError(
                f"{k!r} entry must be an object with 'present' (and section_heading)"
            )
    return data


_VALID_NETWORK = {"none", "bridge", "host"}
_VALID_VERIFICATION = {"execute", "artifact_check"}


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    """Per-step normalisation: fix common LLM slips before schema check."""
    out = dict(step)

    # network: tolerate true/"true"/"yes" → "bridge"; false/"false"/"no" → "none"
    net = out.get("network")
    if net in (True, "true", "yes", "True"):
        out["network"] = "bridge"
    elif net in (False, "false", "no", "False"):
        out["network"] = "none"
    elif net is None:
        out["network"] = "none"

    # verification_mode synonyms → canonical
    vm = out.get("verification_mode")
    if vm in ("artifact_only", "evidence", "evidence_only", "check_only", "artifact"):
        out["verification_mode"] = "artifact_check"
    elif vm in ("run", "executed", "execution"):
        out["verification_mode"] = "execute"

    # Strip null values from alternatives entries — the schema requires strings
    # on the optional fields (url, command) and bans null. The LLM correctly
    # emits null for fields that don't apply (e.g., url=null on a "command"
    # alternative, command=null on a "manual_download"); we just drop them.
    alts = out.get("alternatives")
    if isinstance(alts, list):
        cleaned: list[dict[str, Any]] = []
        for alt in alts:
            if isinstance(alt, dict):
                cleaned.append({k: v for k, v in alt.items() if v is not None})
        out["alternatives"] = cleaned

    return out


def _parse_call3_steps(raw: str) -> list[dict[str, Any]]:
    data = _parse_json(raw)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of Step entries at top level")
    out: list[dict[str, Any]] = []
    for i, s in enumerate(data):
        if not isinstance(s, dict):
            raise ValueError(f"steps[{i}] is not an object")
        if not s.get("id") or not s.get("nine_step"):
            raise ValueError(f"steps[{i}] missing required field 'id' or 'nine_step'")
        s = _normalize_step(s)
        net = s.get("network")
        if net not in _VALID_NETWORK:
            raise ValueError(
                f"steps[{i}].network must be one of {sorted(_VALID_NETWORK)}, got {net!r}"
            )
        vm = s.get("verification_mode", "execute")
        if vm not in _VALID_VERIFICATION:
            raise ValueError(
                f"steps[{i}].verification_mode must be one of {sorted(_VALID_VERIFICATION)}, got {vm!r}"
            )
        s["verification_mode"] = vm
        out.append(s)
    return out


_VALID_LOCATE_KIND = {"stdout_table", "json_file", "file_regex"}
_VALID_TOLERANCE_KIND = {"relative", "absolute", "exact"}


def _strip_null_locate_fields(loc: dict[str, Any]) -> dict[str, Any]:
    """Schema rejects null values on row/col/path/etc.; strip them."""
    return {k: v for k, v in loc.items() if v is not None}


def _parse_call4_results(raw: str) -> list[dict[str, Any]]:
    data = _parse_json(raw)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of ExpectedResult entries at top level")
    out: list[dict[str, Any]] = []
    for i, r in enumerate(data):
        if not isinstance(r, dict):
            raise ValueError(f"expected_results[{i}] is not an object")
        if not r.get("step_id"):
            raise ValueError(f"expected_results[{i}] missing 'step_id'")
        r = dict(r)
        # Normalise metrics
        metrics_in = r.get("metrics") or []
        metrics_out: list[dict[str, Any]] = []
        for j, m in enumerate(metrics_in):
            if not isinstance(m, dict):
                raise ValueError(f"results[{i}].metrics[{j}] is not an object")
            loc = m.get("locate")
            tol = m.get("tolerance")
            if not isinstance(loc, dict) or loc.get("kind") not in _VALID_LOCATE_KIND:
                raise ValueError(
                    f"results[{i}].metrics[{j}].locate.kind must be one of {sorted(_VALID_LOCATE_KIND)}"
                )
            if not isinstance(tol, dict) or tol.get("kind") not in _VALID_TOLERANCE_KIND:
                raise ValueError(
                    f"results[{i}].metrics[{j}].tolerance.kind must be one of {sorted(_VALID_TOLERANCE_KIND)}"
                )
            m = dict(m)
            m["locate"] = _strip_null_locate_fields(loc)
            metrics_out.append(m)
        r["metrics"] = metrics_out
        if "charts" not in r or not isinstance(r["charts"], list):
            r["charts"] = []
        out.append(r)
    return out


# ---------- Call dispatcher ----------


_CallParser = Callable[[str], Any]
_AttemptCallback = Callable[[str, str, Optional[Exception]], None]


_NETWORK_ERROR_TYPES: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)
try:  # pragma: no cover - optional dependency at runtime
    import openai as _openai

    _NETWORK_ERROR_TYPES = (
        _openai.APITimeoutError,
        _openai.APIConnectionError,
        _openai.APIError,
        TimeoutError,
        ConnectionError,
    )
except ImportError:
    pass


def _call_complete_json(
    client: LLMClient,
    system: str,
    user: str,
    *,
    temperature: float,
    idle_timeout_seconds: float,
) -> str:
    """Call ``client.complete_json`` with the idle timeout if the client accepts it."""
    try:
        return client.complete_json(
            system, user, temperature=temperature, idle_timeout_seconds=idle_timeout_seconds
        )
    except TypeError:
        return client.complete_json(system, user, temperature=temperature)


def _run_call(
    *,
    call_index: int,
    label: str,
    client: LLMClient,
    user_prompt: str,
    parser: _CallParser,
    temperature: float,
    idle_timeout_seconds: float,
    max_retries: int,
    on_attempt: Optional[_AttemptCallback],
) -> Any:
    """Execute one form-filling call with retry-on-parse-failure.

    Each attempt sends the same user prompt (plus an appended error context
    on retries). The parser raises ``ValueError`` on a structural failure;
    the orchestrator re-prompts up to ``max_retries`` times.
    """
    user = user_prompt
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        raw = ""
        attempt_label = f"call_{call_index}_{label}_attempt_{attempt}"
        try:
            raw = _call_complete_json(
                client,
                SYSTEM_FILL,
                user,
                temperature=temperature,
                idle_timeout_seconds=idle_timeout_seconds,
            )
            parsed = parser(raw)
            if on_attempt:
                on_attempt(attempt_label, raw, None)
            return parsed
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if on_attempt:
                on_attempt(attempt_label, raw, exc)
            if attempt >= max_retries:
                break
            user = user_prompt + RETRY_SUFFIX.format(error=str(exc))
        except _NETWORK_ERROR_TYPES as exc:
            last_error = exc
            if on_attempt:
                on_attempt(attempt_label, raw, exc)
            if attempt >= max_retries:
                break
            # Network errors: same prompt, no need to muddy it with HTTP details.
    raise DecomposeError(
        f"call '{label}' failed after {max_retries + 1} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    )


# ---------- Top-level orchestrator ----------


def decompose(
    readme_text: str,
    client: LLMClient,
    *,
    temperature: float = 0.0,
    idle_timeout_seconds: float = 180.0,
    per_call_max_retries: int = 1,
    on_attempt: Optional[_AttemptCallback] = None,
) -> dict[str, Any]:
    """Run the 4 form-filling calls and return a dict of elements.

    Returned shape::

        {
          "repo":            dict,             # Call 1
          "nine_step":       dict,             # Call 2
          "steps":           list[dict],       # Call 3
          "results":         list[dict],       # Call 4
          "additional_steps": list[dict],      # Call 5 (stub, currently always [])
        }

    Suitable for passing to :func:`plutus_verify.extract.stitch.stitch`.
    """
    repo = _run_call(
        call_index=0,
        label="repo",
        client=client,
        user_prompt=CALL1_REPO_USER.format(readme=readme_text),
        parser=_parse_call1_repo,
        temperature=temperature,
        idle_timeout_seconds=idle_timeout_seconds,
        max_retries=per_call_max_retries,
        on_attempt=on_attempt,
    )

    nine_step = _run_call(
        call_index=1,
        label="nine_step",
        client=client,
        user_prompt=CALL2_NINE_STEP_USER.format(readme=readme_text),
        parser=_parse_call2_nine_step,
        temperature=temperature,
        idle_timeout_seconds=idle_timeout_seconds,
        max_retries=per_call_max_retries,
        on_attempt=on_attempt,
    )

    # Pass Call 2's present-step keys into Call 3 so the LLM knows which to emit.
    present_step_keys = [k for k in NINE_STEP_KEYS if nine_step.get(k, {}).get("present")]
    steps = _run_call(
        call_index=2,
        label="steps",
        client=client,
        user_prompt=CALL3_STEPS_USER.format(
            readme=readme_text,
            present_steps=json.dumps(present_step_keys),
        ),
        parser=_parse_call3_steps,
        temperature=temperature,
        idle_timeout_seconds=idle_timeout_seconds,
        max_retries=per_call_max_retries,
        on_attempt=on_attempt,
    )

    # Pass Call 3's step ids into Call 4.
    step_ids = [s.get("id") for s in steps if s.get("id")]
    results = _run_call(
        call_index=3,
        label="results",
        client=client,
        user_prompt=CALL4_RESULTS_USER.format(
            readme=readme_text,
            step_ids=json.dumps(step_ids),
        ),
        parser=_parse_call4_results,
        temperature=temperature,
        idle_timeout_seconds=idle_timeout_seconds,
        max_retries=per_call_max_retries,
        on_attempt=on_attempt,
    )

    return {
        "repo": repo,
        "nine_step": nine_step,
        "steps": steps,
        "results": results,
        "additional_steps": [],  # Call 5 stub
    }

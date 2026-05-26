"""LLM-eyeballing fallback for metric comparison.

When the deterministic `locate` directive can't extract a value from stdout
(typically because the README claims a markdown-table format but the script
actually emits free text), this module asks the LLM to find each metric in the
captured stdout. The LLM is used as a smart parser, not a judge — the
deterministic tolerance check still runs against the extracted number.

Architecture:
  - ``MetricMatchClient`` protocol: ``match(metrics, stdout) -> raw JSON string``
  - ``OpenAIMetricMatchClient``: production impl, reuses the Ollama plumbing
    from :mod:`plutus_verify.extract.client`.
  - ``eyeball_metrics`` orchestrates: build prompt, call client, parse response,
    return ``{metric_name -> actual | None}``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Protocol

from plutus_verify.util.llm_parsing import strip_markdown_fences


@dataclass(frozen=True)
class MetricMatchRequest:
    name: str
    expected_approx: float


class MetricMatchClient(Protocol):
    """Returns the raw JSON string from the LLM for a single match call."""

    def match(self, *, metrics: list[MetricMatchRequest], stdout: str) -> str: ...


SYSTEM_PROMPT = (
    "You are a value extractor. Given a list of metrics with expected approximate "
    "values, and a script's captured stdout, find each metric's actual value in "
    "the stdout.\n\n"
    "IMPORTANT — match the expected value's UNIT. If expected is a percentage "
    "(e.g., 29.92) and stdout reports the equivalent fraction (e.g., 0.299259), "
    "convert and return 29.9259 — i.e., scale to match the expected scale. "
    "Same in reverse: if expected is 0.05 and stdout has 5%, return 0.05.\n\n"
    "Examples:\n"
    '- expected "0.9516", stdout "Sharpe ratio: 0.9516979860..." -> actual = 0.9516979860 (same unit, no conversion)\n'
    '- expected "29.92" (a percentage), stdout "HPR 0.299259..." (the fraction) -> actual = 29.9259 (multiplied by 100 to match expected unit)\n'
    '- expected "1.81" (a percentage like Monthly return %), stdout "Monthly return 0.01810808..." -> actual = 1.810808\n'
    '- expected "-0.201", stdout "Maximum drawdown: -0.2010986..." -> actual = -0.2010986 (no conversion)\n\n'
    "Use the magnitude of the expected value to infer the intended unit. "
    "If expected is ~2 orders of magnitude bigger than what stdout shows for the same "
    "metric, multiply stdout's value by 100. The goal is to return a number directly "
    "comparable to expected.\n\n"
    "Return JSON ONLY. No prose, no fences. Schema:\n"
    '{"matches": [{"name": "<metric name as given>", "actual": <number>|null, "notes": "<<=20 words>"}]}\n\n'
    "If a metric is genuinely absent from stdout, return actual: null.\n"
    "Always return one entry per requested metric, preserving the names exactly as given."
)


def eyeball_metrics(
    *,
    metrics: list[MetricMatchRequest],
    stdout: str,
    client: MetricMatchClient,
) -> dict[str, Optional[float]]:
    """Ask the LLM to find each metric in stdout. Returns ``{name: actual or None}``.

    On any parsing failure, returns all-None for the requested metrics — the
    caller treats this as ``unverifiable``.
    """
    raw = client.match(metrics=metrics, stdout=stdout)
    body = strip_markdown_fences(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {m.name: None for m in metrics}

    out: dict[str, Optional[float]] = {m.name: None for m in metrics}
    matches = data.get("matches", []) if isinstance(data, dict) else []
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        actual = entry.get("actual")
        if name in out and isinstance(actual, (int, float)):
            out[name] = float(actual)
    return out


# ---------- Production client ----------


def build_user_prompt(metrics: list[MetricMatchRequest], stdout: str) -> str:
    """Render the user message: metric list + stdout block."""
    metric_lines = "\n".join(
        f'- name: "{m.name}", expected approximately: {m.expected_approx}'
        for m in metrics
    )
    # Cap stdout at ~12K chars to avoid blowing context; keep the tail since
    # final metrics are typically printed last.
    MAX = 12000
    if len(stdout) > MAX:
        stdout = stdout[-MAX:]
    return (
        f"Metrics to find:\n{metric_lines}\n\n"
        f"Stdout:\n---\n{stdout}\n---\n\n"
        'Reply JSON only: {"matches": [...]}.'
    )


class OpenAIMetricMatchClient:
    """Production :class:`MetricMatchClient` backed by Ollama /api/chat.

    Constructor mirrors :class:`OpenAICompatClient` so it can share an endpoint
    config. Always uses ``think: false`` for speed (this is mechanical parsing).
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        idle_timeout_seconds: float = 90.0,
        num_ctx: int = 16384,
        echo_stream: bool = False,
    ) -> None:
        # Reuse the production HTTP client — same plumbing, but force think=False.
        from plutus_verify.extract.client import OpenAICompatClient

        self._client = OpenAICompatClient(
            endpoint=endpoint,
            model=model,
            idle_timeout_seconds=idle_timeout_seconds,
            num_ctx=num_ctx,
            echo_stream=echo_stream,
            echo_thinking=False,
            think=False,
        )

    def match(self, *, metrics: list[MetricMatchRequest], stdout: str) -> str:
        user = build_user_prompt(metrics, stdout)
        return self._client.complete_json(
            SYSTEM_PROMPT, user, temperature=0.0
        )

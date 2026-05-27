"""JSON-Schema (Draft 2020-12) for the SDK ``results.json`` file.

Canonical units and artifact kinds are enumerated here so the SDK, the
verifier, and authoring scripts share a single source of truth.

The dimensionless bucket is split on display intent: ``fraction`` for
numbers naturally rendered as a percentage (win rate 0.42, max drawdown
0.15, annual return 0.17), and ``ratio`` for unbounded dimensionless
numbers (Sharpe 1.7, Sortino, profit factor). ``percent`` is rejected so
authors always store a decimal — write 42% as 0.42 with ``unit="fraction"``.
"""
from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

UNIT_KINDS: tuple[str, ...] = ("fraction", "ratio", "count", "currency_usd", "seconds")
ARTIFACT_KINDS: tuple[str, ...] = ("chart", "csv", "json", "image", "other")
NAME_PATTERN: str = r"^[a-z][a-z0-9_]*$"

_METRIC = {
    "type": "object",
    "required": ["name", "value", "unit"],
    "properties": {
        "name": {"type": "string", "pattern": NAME_PATTERN},
        "value": {"type": "number"},
        "unit": {"type": "string", "enum": list(UNIT_KINDS)},
    },
    "additionalProperties": False,
}

_ARTIFACT = {
    "type": "object",
    "required": ["name", "path", "kind"],
    "properties": {
        "name": {"type": "string", "pattern": NAME_PATTERN},
        "path": {"type": "string"},
        "kind": {"type": "string", "enum": list(ARTIFACT_KINDS)},
    },
    "additionalProperties": False,
}

RESULTS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "step_id", "metrics", "artifacts", "metadata"],
    "properties": {
        "schema_version": {"type": "string", "const": "1.0"},
        "step_id": {"type": "string", "pattern": NAME_PATTERN},
        "metrics": {"type": "array", "items": _METRIC},
        "artifacts": {"type": "array", "items": _ARTIFACT},
        "metadata": {"type": "object"},
    },
    "additionalProperties": False,
}


_VALIDATOR = Draft202012Validator(RESULTS_SCHEMA)


def validate_results(payload: dict[str, Any]) -> None:
    """Validate ``payload`` against the results.json schema.

    Raises ``jsonschema.ValidationError`` on the first violation.
    """
    _VALIDATOR.validate(payload)

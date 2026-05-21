"""JSON-Schema (Draft 2020-12) for the v2 Plutus manifest.

Structural-only; cross-field invariants (required commands, satisfies refs)
live in spec/validator.py.
"""
from __future__ import annotations

from typing import Any

from plutus_verify.spec.manifest import NINE_STEP_KEYS

_LOCATE = {
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {"type": "string", "enum": ["stdout_table", "json_file", "file_regex"]},
        "path": {"type": ["string", "null"]},
        "row": {"type": ["string", "null"]},
        "col": {"type": ["integer", "null"]},
        "jsonpath": {"type": ["string", "null"]},
        "pattern": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_TOLERANCE = {
    "type": "object",
    "required": ["kind", "value"],
    "properties": {
        "kind": {"type": "string", "enum": ["relative", "absolute", "exact"]},
        "value": {"type": "number", "minimum": 0},
    },
    "additionalProperties": False,
}

_HEADLINE = {
    "type": "object",
    "required": ["name", "value", "locate", "tolerance"],
    "properties": {
        "name": {"type": "string"},
        "value": {"type": ["number", "string"]},
        "locate": _LOCATE,
        "tolerance": _TOLERANCE,
    },
    "additionalProperties": False,
}

_REFERENCE_OUTPUT = {
    "type": "object",
    "required": ["path", "compare"],
    "properties": {
        "path": {"type": "string"},
        "compare": {
            "type": "string",
            "enum": ["json_numeric_tolerance", "visual_similarity", "byte_exact"],
        },
        "threshold": {"type": ["number", "null"]},
    },
    "additionalProperties": False,
}

_DATA_SOURCE = {
    "type": "object",
    "required": ["kind", "url", "expected_layout", "satisfies"],
    "properties": {
        "kind": {"type": "string"},
        "url": {"type": "string"},
        "expected_layout": {"type": "array", "items": {"type": "string"}},
        "satisfies": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "secrets_required": {"type": "array", "items": {"type": "string"}},
        "label": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

_STEP = {
    "type": "object",
    "required": ["id", "nine_step", "required"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "nine_step": {
            "anyOf": [
                {"type": "string", "enum": list(NINE_STEP_KEYS)},
                {"type": "null"},
            ]
        },
        "required": {"type": "boolean"},
        "command": {"type": ["string", "null"]},
        "label": {"type": ["string", "null"]},
        "network": {"type": "string", "enum": ["none", "bridge", "host"]},
        "timeout_seconds": {"type": "integer", "minimum": 1},
        "inputs": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "array", "items": {"type": "string"}},
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "verification_mode": {
            "type": "string",
            "enum": ["execute", "artifact_check"],
        },
    },
    "additionalProperties": False,
}

_NINE_STEP_COVERAGE_ENTRY = {
    "type": "object",
    "required": ["present"],
    "properties": {
        "present": {"type": "boolean"},
        "section": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

MANIFEST_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "repo",
        "env",
        "secrets",
        "data_sources",
        "steps",
        "expected",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "2.0"},
        "repo": {
            "type": "object",
            "required": ["name", "primary_language"],
            "properties": {
                "name": {"type": "string"},
                "primary_language": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "env": {
            "type": "object",
            "required": ["base", "python_version"],
            "properties": {
                "base": {"type": "string", "enum": ["python", "python-cuda", "none"]},
                "python_version": {"type": "string"},
                "requirements_file": {"type": ["string", "null"]},
                "os_packages": {"type": "array", "items": {"type": "string"}},
                "gpu_required": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "secrets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key"],
                "properties": {
                    "key": {"type": "string"},
                    "purpose": {"type": "string"},
                    "used_by": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
        "data_sources": {
            "type": "object",
            "required": ["processed", "raw"],
            "properties": {
                "processed": {"type": "array", "items": _DATA_SOURCE},
                "raw": {"type": "array", "items": _DATA_SOURCE},
            },
            "additionalProperties": False,
        },
        "steps": {"type": "array", "items": _STEP, "minItems": 1},
        "expected": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step_id"],
                "properties": {
                    "step_id": {"type": "string"},
                    "headlines": {"type": "array", "items": _HEADLINE},
                    "reference_outputs": {
                        "type": "array",
                        "items": _REFERENCE_OUTPUT,
                    },
                },
                "additionalProperties": False,
            },
        },
        "nine_step_coverage": {
            "type": "object",
            "properties": {
                k: _NINE_STEP_COVERAGE_ENTRY for k in NINE_STEP_KEYS
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

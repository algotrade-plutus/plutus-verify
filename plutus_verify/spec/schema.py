"""JSON-Schema (Draft 2020-12) for the v2 Plutus manifest.

Structural-only; cross-field invariants (required commands, satisfies refs)
live in spec/validator.py.
"""
from __future__ import annotations

from typing import Any

from plutus_verify.spec.manifest import NINE_STEP_KEYS

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
    "required": ["name", "value", "tolerance"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "display_name": {"type": "string"},
        "value": {"type": "number"},
        "tolerance": _TOLERANCE,
    },
}

_ARTIFACT = {
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

_SUB_PROCESS = {
    "type": "object",
    "required": ["description"],
    "properties": {
        "description": {"type": "string", "minLength": 1},
        "command": {"type": ["string", "null"]},
        "inputs": {"type": "array", "items": {"type": "string"}},
        "outputs": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

# Optional, documentation-only breakdown of the data_preparation step into its two
# v2025 sub-processes. Never executed by the verifier. A validator invariant
# restricts this block to the step whose nine_step is step_2_data_preparation.
_SUB_PROCESSES = {
    "type": "object",
    "properties": {
        "collection": _SUB_PROCESS,
        "processing": _SUB_PROCESS,
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
        "sub_processes": _SUB_PROCESSES,
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
                "manager": {"type": "string", "enum": ["uv", "pip"]},
                "lockfile": {"type": ["string", "null"]},
                "requirements_file": {"type": ["string", "null"]},
                "os_packages": {"type": "array", "items": {"type": "string"}},
                "gpu_required": {"type": "boolean"},
                "install_project": {"type": "boolean"},
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
                    "metrics": {"type": "array", "items": _HEADLINE},
                    "artifacts": {
                        "type": "array",
                        "items": _ARTIFACT,
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

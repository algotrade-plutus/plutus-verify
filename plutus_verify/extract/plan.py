"""ExtractedPlan dataclasses + JSON-schema validation.

The plan is the contract between the LLM extractor and the deterministic
pipeline. Stable, versioned schema. See docs/plan/ for the design rationale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from plutus_verify.constants import NINE_STEP_KEYS


class PlanValidationError(ValueError):
    """Raised when a plan dict does not match the schema or internal invariants."""


# JSON Schema (Draft 2020-12) for ExtractedPlan v1.0
PLAN_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "repo",
        "nine_step_mapping",
        "steps",
        "expected_results",
        "extraction_notes",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "1.0"},
        "repo": {
            "type": "object",
            "required": ["name", "primary_language", "env_setup", "secrets_required"],
            "properties": {
                "name": {"type": "string"},
                "primary_language": {"type": "string"},
                "env_setup": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "requirements_txt",
                                "environment_yml",
                                "pipfile",
                                "dockerfile",
                                "none",
                            ],
                        },
                        "path": {"type": ["string", "null"]},
                        "python_version": {"type": ["string", "null"]},
                        "extra_setup_commands": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "secrets_required": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["key"],
                        "properties": {
                            "key": {"type": "string"},
                            "purpose": {"type": "string"},
                            "step_ids": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
        "nine_step_mapping": {
            "type": "object",
            "required": list(NINE_STEP_KEYS),
            "properties": {
                k: {
                    "type": "object",
                    "required": ["present", "confidence"],
                    "properties": {
                        "present": {"type": "boolean"},
                        "section_heading": {"type": ["string", "null"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                }
                for k in NINE_STEP_KEYS
            },
            "additionalProperties": False,
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "nine_step", "required"],
                "properties": {
                    "id": {"type": "string"},
                    "nine_step": {"type": "string", "enum": list(NINE_STEP_KEYS)},
                    "required": {"type": "boolean"},
                    "verification_mode": {
                        "type": "string",
                        "enum": ["execute", "artifact_check"],
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "command": {"type": ["string", "null"]},
                    "config_files": {"type": "array", "items": {"type": "string"}},
                    "network": {"type": "string", "enum": ["none", "bridge", "host"]},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "produces": {"type": "array", "items": {"type": "string"}},
                    "alternatives": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["label", "kind"],
                            "properties": {
                                "label": {"type": "string"},
                                "kind": {
                                    "type": "string",
                                    "enum": ["manual_download", "command"],
                                },
                                "url": {"type": ["string", "null"]},
                                "command": {"type": ["string", "null"]},
                                "expected_layout": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "needs_secrets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "network": {"type": "string"},
                                "timeout_seconds": {"type": "integer"},
                                "produces": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "expected_results": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step_id", "metrics", "charts"],
                "properties": {
                    "step_id": {"type": "string"},
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "value", "locate", "tolerance"],
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": ["number", "integer", "string"]},
                                "locate": {
                                    "type": "object",
                                    "required": ["kind"],
                                    "properties": {
                                        "kind": {
                                            "type": "string",
                                            "enum": [
                                                "stdout_table",
                                                "json_file",
                                                "file_regex",
                                            ],
                                        },
                                        "row": {"type": "string"},
                                        "col": {"type": "integer"},
                                        "path": {"type": "string"},
                                        "jsonpath": {"type": "string"},
                                        "pattern": {"type": "string"},
                                    },
                                },
                                "tolerance": {
                                    "type": "object",
                                    "required": ["kind", "value"],
                                    "properties": {
                                        "kind": {
                                            "type": "string",
                                            "enum": ["relative", "absolute", "exact"],
                                        },
                                        "value": {"type": "number", "minimum": 0},
                                    },
                                },
                            },
                        },
                    },
                    "charts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "produced_path"],
                            "properties": {
                                "name": {"type": "string"},
                                "reference_image": {"type": ["string", "null"]},
                                "produced_path": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "extraction_notes": {"type": "array", "items": {"type": "string"}},
    },
}

_VALIDATOR = Draft202012Validator(PLAN_SCHEMA)


# ---------- Dataclasses (light, frozen, json-mirroring) ----------


@dataclass(frozen=True)
class EnvSetup:
    kind: str
    path: Optional[str] = None
    python_version: Optional[str] = None
    extra_setup_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecretRequirement:
    key: str
    purpose: str = ""
    step_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Repo:
    name: str
    primary_language: str
    env_setup: EnvSetup
    secrets_required: tuple[SecretRequirement, ...]


@dataclass(frozen=True)
class NineStepEntry:
    present: bool
    section_heading: Optional[str]
    confidence: float


@dataclass(frozen=True)
class StepAlternative:
    label: str
    kind: Literal["manual_download", "command"]
    url: Optional[str] = None
    command: Optional[str] = None
    expected_layout: tuple[str, ...] = ()
    needs_secrets: tuple[str, ...] = ()
    network: str = "none"
    timeout_seconds: int = 1800
    produces: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    id: str
    nine_step: str
    required: bool
    depends_on: tuple[str, ...] = ()
    command: Optional[str] = None
    config_files: tuple[str, ...] = ()
    network: str = "none"
    timeout_seconds: int = 1800
    produces: tuple[str, ...] = ()
    alternatives: Optional[tuple[StepAlternative, ...]] = None
    verification_mode: Literal["execute", "artifact_check"] = "execute"


@dataclass(frozen=True)
class Locate:
    kind: Literal["stdout_table", "json_file", "file_regex"]
    row: Optional[str] = None
    col: Optional[int] = None
    path: Optional[str] = None
    jsonpath: Optional[str] = None
    pattern: Optional[str] = None


@dataclass(frozen=True)
class Tolerance:
    kind: Literal["relative", "absolute", "exact"]
    value: float


@dataclass(frozen=True)
class ExpectedMetric:
    name: str
    value: "float | str"
    """Expected value. Usually numeric, but Plutus repos sometimes report
    categorical optimization params (e.g., ``stock_weight_option = "equal"``)."""
    locate: Locate
    tolerance: Tolerance


@dataclass(frozen=True)
class ExpectedChart:
    name: str
    produced_path: str
    reference_image: Optional[str] = None


@dataclass(frozen=True)
class ExpectedResult:
    step_id: str
    metrics: tuple[ExpectedMetric, ...]
    charts: tuple[ExpectedChart, ...]


@dataclass(frozen=True)
class ExtractedPlan:
    schema_version: str
    repo: Repo
    nine_step_mapping: dict[str, NineStepEntry]
    steps: tuple[Step, ...]
    expected_results: tuple[ExpectedResult, ...]
    extraction_notes: tuple[str, ...] = ()


# ---------- Parser ----------


def parse_plan(data: dict[str, Any]) -> ExtractedPlan:
    """Validate ``data`` against the JSON schema and structural invariants, then
    return an :class:`ExtractedPlan`.

    Invariants enforced beyond JSON Schema:
      - Every ``step.depends_on`` id refers to another step in the plan.
      - Every ``expected_results[*].step_id`` refers to a step in the plan.
    """
    try:
        _VALIDATOR.validate(data)
    except ValidationError as exc:
        raise PlanValidationError(f"schema violation: {exc.message}") from exc

    step_ids = {s["id"] for s in data["steps"]}
    for step in data["steps"]:
        for dep in step.get("depends_on", []):
            if dep not in step_ids:
                raise PlanValidationError(
                    f"step '{step['id']}' depends_on unknown step '{dep}'"
                )
    for er in data["expected_results"]:
        if er["step_id"] not in step_ids:
            raise PlanValidationError(
                f"expected_results refers to unknown step '{er['step_id']}'"
            )

    return _build_plan(data)


def _build_plan(d: dict[str, Any]) -> ExtractedPlan:
    repo = Repo(
        name=d["repo"]["name"],
        primary_language=d["repo"]["primary_language"],
        env_setup=EnvSetup(
            kind=d["repo"]["env_setup"]["kind"],
            path=d["repo"]["env_setup"].get("path"),
            python_version=d["repo"]["env_setup"].get("python_version"),
            extra_setup_commands=tuple(
                d["repo"]["env_setup"].get("extra_setup_commands", [])
            ),
        ),
        secrets_required=tuple(
            SecretRequirement(
                key=s["key"],
                purpose=s.get("purpose", ""),
                step_ids=tuple(s.get("step_ids", [])),
            )
            for s in d["repo"]["secrets_required"]
        ),
    )

    mapping = {
        k: NineStepEntry(
            present=v["present"],
            section_heading=v.get("section_heading"),
            confidence=v["confidence"],
        )
        for k, v in d["nine_step_mapping"].items()
    }

    steps = tuple(_build_step(s) for s in d["steps"])
    results = tuple(_build_expected_result(r) for r in d["expected_results"])

    return ExtractedPlan(
        schema_version=d["schema_version"],
        repo=repo,
        nine_step_mapping=mapping,
        steps=steps,
        expected_results=results,
        extraction_notes=tuple(d["extraction_notes"]),
    )


def _build_step(s: dict[str, Any]) -> Step:
    alts = s.get("alternatives")
    return Step(
        id=s["id"],
        nine_step=s["nine_step"],
        required=s["required"],
        depends_on=tuple(s.get("depends_on", [])),
        command=s.get("command"),
        config_files=tuple(s.get("config_files", [])),
        network=s.get("network", "none"),
        timeout_seconds=s.get("timeout_seconds", 1800),
        produces=tuple(s.get("produces", [])),
        verification_mode=s.get("verification_mode", "execute"),
        alternatives=(
            tuple(
                StepAlternative(
                    label=a["label"],
                    kind=a["kind"],
                    url=a.get("url"),
                    command=a.get("command"),
                    expected_layout=tuple(a.get("expected_layout", [])),
                    needs_secrets=tuple(a.get("needs_secrets", [])),
                    network=a.get("network", "none"),
                    timeout_seconds=a.get("timeout_seconds", 1800),
                    produces=tuple(a.get("produces", [])),
                )
                for a in alts
            )
            if alts is not None
            else None
        ),
    )


def _build_expected_result(r: dict[str, Any]) -> ExpectedResult:
    metrics = tuple(
        ExpectedMetric(
            name=m["name"],
            value=float(m["value"]) if isinstance(m["value"], (int, float)) else m["value"],
            locate=Locate(
                kind=m["locate"]["kind"],
                row=m["locate"].get("row"),
                col=m["locate"].get("col"),
                path=m["locate"].get("path"),
                jsonpath=m["locate"].get("jsonpath"),
                pattern=m["locate"].get("pattern"),
            ),
            tolerance=Tolerance(kind=m["tolerance"]["kind"], value=m["tolerance"]["value"]),
        )
        for m in r["metrics"]
    )
    charts = tuple(
        ExpectedChart(
            name=c["name"],
            produced_path=c["produced_path"],
            reference_image=c.get("reference_image"),
        )
        for c in r["charts"]
    )
    return ExpectedResult(step_id=r["step_id"], metrics=metrics, charts=charts)

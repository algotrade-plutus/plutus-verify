"""Reader for the SDK-produced ``.plutus/run/<step_id>/results.json`` file.

Counterpart to ``plutus_verify.sdk.run``: the SDK writes the canonical
``results.json`` from inside an author's script, and this module loads it
back into a typed dataclass for the v2 verifier's compare phase.

Validation is delegated to ``plutus_verify.sdk.schema.validate_results`` so
the SDK and the verifier share a single source of truth for the schema.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from plutus_verify.sdk.schema import validate_results


class ResultsError(Exception):
    """Base for results.json loading errors."""


class MissingResultsError(ResultsError):
    """The expected .plutus/run/<step_id>/results.json file does not exist."""


class MalformedResultsError(ResultsError):
    """The results.json file exists but is invalid.

    Raised for bad JSON, schema violations, or a step_id mismatch between
    the file's declared step_id and the caller's request.
    """


class MetricNotProducedError(ResultsError):
    """An expected metric was not present in results.json.

    Not raised by ``load_results``; the orchestrator raises this in Task 4
    when an expected metric name has no matching metric in the loaded
    ``ResultsFile``.
    """


@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    unit: str


@dataclass(frozen=True)
class Artifact:
    name: str
    path: str
    kind: str


@dataclass(frozen=True)
class ResultsFile:
    schema_version: str
    step_id: str
    metrics: tuple[Metric, ...]
    artifacts: tuple[Artifact, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def load_results(repo_path: Path, *, step_id: str) -> ResultsFile:
    """Read ``<repo_path>/.plutus/run/<step_id>/results.json``.

    Raises:
        MissingResultsError: the file does not exist.
        MalformedResultsError: invalid JSON, schema violation, or the file's
            declared ``step_id`` does not match the caller's request.
    """
    path = Path(repo_path) / ".plutus" / "run" / step_id / "results.json"

    if not path.exists():
        raise MissingResultsError(
            f"expected {path} for step_id={step_id!r} but it does not exist"
        )

    try:
        raw = path.read_text()
    except OSError as exc:
        raise MalformedResultsError(f"failed to read {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MalformedResultsError(f"failed to parse {path}: {exc}") from exc

    try:
        validate_results(payload)
    except ValidationError as exc:
        raise MalformedResultsError(
            f"{path} violates results schema: {exc.message}"
        ) from exc

    declared = payload["step_id"]
    if declared != step_id:
        raise MalformedResultsError(
            f"{path} declares step_id={declared!r} but caller expected {step_id!r}"
        )

    metrics = tuple(
        Metric(name=m["name"], value=m["value"], unit=m["unit"])
        for m in payload["metrics"]
    )
    artifacts = tuple(
        Artifact(name=a["name"], path=a["path"], kind=a["kind"])
        for a in payload.get("artifacts", [])
    )
    metadata: dict[str, Any] = dict(payload.get("metadata", {}))

    return ResultsFile(
        schema_version=payload["schema_version"],
        step_id=declared,
        metrics=metrics,
        artifacts=artifacts,
        metadata=metadata,
    )

"""Frozen dataclasses mirroring the v2 manifest YAML structure.

Keep these as light as possible — no methods, no defaults that hide errors.
Validation lives in spec/schema.py and spec/validator.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from plutus_verify.constants import NINE_STEP_KEYS

__all__ = ["NINE_STEP_KEYS"]


@dataclass(frozen=True)
class Repo:
    name: str
    primary_language: str


@dataclass(frozen=True)
class Env:
    base: Literal["python", "python-cuda", "none"]
    python_version: str
    # `uv` (locked, reproducible) is the recommended manager; `pip` (re-resolved
    # at build time) is the deprecated default kept for back-compat. With `uv`,
    # `lockfile` must point at the committed lockfile the verifier restores.
    manager: Literal["uv", "pip"] = "pip"
    lockfile: Optional[str] = None
    requirements_file: Optional[str] = None
    os_packages: tuple[str, ...] = ()
    gpu_required: bool = False


@dataclass(frozen=True)
class Secret:
    key: str
    purpose: str = ""
    used_by: tuple[str, ...] = ()


# Env vars that govern the container's runtime and must never be set from a
# declared secret: injecting e.g. `-e PATH=<host>` overrides the image's
# `ENV PATH=/opt/venv/bin:$PATH` and hides the uv venv (the same failure mode as
# the 0.4.1/0.4.2 bugs). The validator rejects a secret with one of these keys;
# the orchestrator's resolver also drops them defensively.
RESERVED_SECRET_KEYS = frozenset(
    {"PATH", "HOME", "LD_LIBRARY_PATH", "PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
)


@dataclass(frozen=True)
class DataSource:
    kind: str
    url: str
    expected_layout: tuple[str, ...]
    satisfies: tuple[str, ...]
    secrets_required: tuple[str, ...] = ()
    label: Optional[str] = None


@dataclass(frozen=True)
class DataSourceTiers:
    processed: tuple[DataSource, ...] = ()
    raw: tuple[DataSource, ...] = ()


@dataclass(frozen=True)
class SubProcess:
    """One documented sub-activity of the data_preparation step. Documentation
    only — never executed by the verifier."""
    description: str
    command: Optional[str] = None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubProcesses:
    """The v2025 data_preparation step's two sub-processes. Optional; each slot is
    individually optional. Restricted to the data_preparation step by the validator."""
    collection: Optional[SubProcess] = None
    processing: Optional[SubProcess] = None


@dataclass(frozen=True)
class Step:
    id: str
    nine_step: Optional[str]
    required: bool
    command: Optional[str] = None
    label: Optional[str] = None
    network: Literal["none", "bridge", "host"] = "none"
    timeout_seconds: int = 1800
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    verification_mode: Literal["execute", "artifact_check"] = "execute"
    sub_processes: Optional[SubProcesses] = None


@dataclass(frozen=True)
class Tolerance:
    kind: Literal["relative", "absolute", "exact"]
    value: float


@dataclass(frozen=True)
class ExpectedMetric:
    name: str
    value: float
    tolerance: Tolerance
    display_name: Optional[str] = None


@dataclass(frozen=True)
class Artifact:
    path: str
    compare: Literal["json_numeric_tolerance", "visual_similarity", "byte_exact"]
    threshold: Optional[float] = None


@dataclass(frozen=True)
class ExpectedBlock:
    step_id: str
    metrics: tuple[ExpectedMetric, ...] = ()
    artifacts: tuple[Artifact, ...] = ()


@dataclass(frozen=True)
class NineStepCoverage:
    present: bool
    section: Optional[str] = None


@dataclass(frozen=True)
class Manifest:
    schema_version: str
    repo: Repo
    env: Env
    secrets: tuple[Secret, ...]
    data_sources: DataSourceTiers
    steps: tuple[Step, ...]
    expected: tuple[ExpectedBlock, ...]
    nine_step_coverage: dict[str, NineStepCoverage] = field(default_factory=dict)



"""Frozen dataclasses mirroring the v2 manifest YAML structure.

Keep these as light as possible — no methods, no defaults that hide errors.
Validation lives in spec/schema.py and spec/validator.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass(frozen=True)
class Repo:
    name: str
    primary_language: str


@dataclass(frozen=True)
class Env:
    base: Literal["python", "python-cuda", "none"]
    python_version: str
    requirements_file: Optional[str] = None
    os_packages: tuple[str, ...] = ()
    gpu_required: bool = False


@dataclass(frozen=True)
class Secret:
    key: str
    purpose: str = ""
    used_by: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class Locate:
    kind: Literal["stdout_table", "stdout_regex", "json_file", "file_regex"]
    path: Optional[str] = None
    row: Optional[str] = None
    col: Optional[int] = None
    jsonpath: Optional[str] = None
    pattern: Optional[str] = None


@dataclass(frozen=True)
class Tolerance:
    kind: Literal["relative", "absolute", "exact"]
    value: float


@dataclass(frozen=True)
class Headline:
    name: str
    value: "float | str"
    locate: Locate
    tolerance: Tolerance


@dataclass(frozen=True)
class ReferenceOutput:
    path: str
    compare: Literal["json_numeric_tolerance", "visual_similarity", "byte_exact"]
    threshold: Optional[float] = None


@dataclass(frozen=True)
class ExpectedBlock:
    step_id: str
    headlines: tuple[Headline, ...] = ()
    reference_outputs: tuple[ReferenceOutput, ...] = ()


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


# v2 manifest copy of the 9-step keys; mirrors plutus_verify.extract.plan.NINE_STEP_KEYS.
# Plan 4 is done; extract/plan.py was deliberately kept because `plutus transfer`
# still depends on it. Deduplication is a future cleanup.
NINE_STEP_KEYS: tuple[str, ...] = (
    "step_1_hypothesis",
    "step_2_data_collection",
    "step_3_data_processing",
    "step_4_in_sample",
    "step_5_optimization",
    "step_6_out_of_sample",
    "step_7_paper_trading",
)

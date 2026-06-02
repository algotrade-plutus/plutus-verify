# Plutus v2 Spec — Foundation (Plan 1 of 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `plutus_verify.spec` package that defines, loads, validates, and adapts the v2 manifest. Wire `pipeline.py` to use `.plutus/manifest.yaml` when present, falling back to the existing LLM `extract/` path otherwise. End state: the verifier can run end-to-end on a repo that ships a `.plutus/` directory, with no LLM extraction call.

**Architecture:** Bridge approach. The v2 manifest is loaded into a new `spec.Manifest` dataclass, then **adapted to the existing `ExtractedPlan` shape** so the proven build/execute/compare/report code keeps working unchanged. A native v2 executor (input/output pre-flight, data-tier resolver, reference-output comparator) is deliberately deferred to Plan 2. Some v2 fidelity is lost in the adapter (documented per task) — Plan 2 closes those gaps.

**Tech Stack:** Python 3.11+, dataclasses, `pyyaml` (already a dep), `jsonschema` (already a dep). No new dependencies.

**Spec reference:** [/Users/dan/.claude/plans/hmm-okay-i-think-wondrous-sundae.md](/Users/dan/.claude/plans/hmm-okay-i-think-wondrous-sundae.md)

---

## File Structure

**New package** — `plutus_verify/spec/`:
- `__init__.py` — public surface (`Manifest`, `load_manifest`, `to_extracted_plan`)
- `manifest.py` — frozen dataclasses mirroring the YAML structure
- `schema.py` — JSON-Schema (Draft 2020-12) dict for v2
- `loader.py` — YAML → dict → validate → dataclass pipeline
- `validator.py` — invariants beyond JSON Schema (required commands, satisfies refs)
- `adapter.py` — `Manifest` → `ExtractedPlan` conversion for the bridge

**Tests** — `tests/unit/`:
- `test_spec_manifest.py` — dataclass round-trip
- `test_spec_schema.py` — JSON-Schema accept/reject
- `test_spec_loader.py` — YAML loading
- `test_spec_validator.py` — invariant enforcement
- `test_spec_adapter.py` — conversion to `ExtractedPlan`
- `test_pipeline_spec_detection.py` — pipeline branch selection

**Fixtures** — `tests/integration/fixtures/`:
- `spec_v2_minimal/.plutus/manifest.yaml` — minimal valid manifest
- `spec_v2_full/.plutus/manifest.yaml` — exercises every feature

**Integration** — `tests/integration/`:
- `test_spec_e2e.py` — load fixture manifest, adapt, exercise downstream

**Modified files:**
- `plutus_verify/pipeline.py` — branch on `.plutus/manifest.yaml` presence (insert before extract stage)

---

## Task 1: Dataclasses for the v2 manifest

**Files:**
- Create: `plutus_verify/spec/__init__.py`
- Create: `plutus_verify/spec/manifest.py`
- Test: `tests/unit/test_spec_manifest.py`

- [ ] **Step 1: Create empty package marker**

Create `plutus_verify/spec/__init__.py`:

```python
"""Plutus v2 manifest: dataclasses, schema, loader, validator, adapter.

The v2 manifest is the source of truth for repos that ship a .plutus/
directory. Versus the LLM-extracted ExtractedPlan, it is author-authored,
declaratively types the runtime environment, lists step inputs+outputs as a
hard contract, and tiers data acquisition (download > preprocess > run).
"""
from plutus_verify.spec.manifest import (
    DataSource,
    DataSourceTiers,
    Env,
    ExpectedBlock,
    ExpectedMetric,
    Locate,
    Manifest,
    NineStepCoverage,
    ReferenceOutput,
    Repo,
    Secret,
    Step,
    Tolerance,
)
from plutus_verify.spec.loader import ManifestLoadError, load_manifest

__all__ = [
    "DataSource",
    "DataSourceTiers",
    "Env",
    "ExpectedBlock",
    "ExpectedMetric",
    "Locate",
    "Manifest",
    "ManifestLoadError",
    "NineStepCoverage",
    "ReferenceOutput",
    "Repo",
    "Secret",
    "Step",
    "Tolerance",
    "load_manifest",
]
```

- [ ] **Step 2: Write the failing dataclass round-trip test**

Create `tests/unit/test_spec_manifest.py`:

```python
"""Tests for the v2 Manifest dataclasses."""
from plutus_verify.spec.manifest import (
    DataSource,
    DataSourceTiers,
    Env,
    ExpectedBlock,
    ExpectedMetric,
    Locate,
    Manifest,
    NineStepCoverage,
    ReferenceOutput,
    Repo,
    Secret,
    Step,
    Tolerance,
)


def test_manifest_minimal_construction():
    m = Manifest(
        schema_version="2.0",
        repo=Repo(name="Demo", primary_language="python"),
        env=Env(
            base="python",
            python_version="3.11",
            requirements_file="requirements.txt",
        ),
        secrets=(),
        data_sources=DataSourceTiers(),
        steps=(
            Step(
                id="in_sample",
                nine_step="step_4_in_sample",
                required=True,
                command="python -m demo.backtest",
                outputs=("out/metrics.json",),
            ),
        ),
        expected=(),
        nine_step_coverage={},
    )
    assert m.steps[0].id == "in_sample"
    assert m.env.base == "python"
    assert m.data_sources.processed == ()
    assert m.data_sources.raw == ()


def test_step_with_free_form_nine_step():
    s = Step(
        id="train_model",
        nine_step=None,
        label="Custom: train classifier",
        required=True,
        command="python -m demo.ml.train",
        outputs=("models/clf.pkl",),
    )
    assert s.nine_step is None
    assert s.label == "Custom: train classifier"


def test_data_source_satisfies_multiple_steps():
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/*.parquet",),
        satisfies=("data_collection", "data_processing"),
    )
    assert ds.satisfies == ("data_collection", "data_processing")


def test_metric_uses_locate_and_tolerance():
    h = ExpectedMetric(
        name="sharpe_ratio",
        value=0.85,
        locate=Locate(kind="json_file", path="out/m.json", jsonpath="$.sharpe"),
        tolerance=Tolerance(kind="relative", value=0.05),
    )
    assert h.locate.kind == "json_file"
    assert h.tolerance.value == 0.05


def test_reference_output_with_threshold():
    r = ReferenceOutput(
        path="out/equity_curve.png",
        compare="visual_similarity",
        threshold=0.7,
    )
    assert r.compare == "visual_similarity"
    assert r.threshold == 0.7
```

- [ ] **Step 3: Run test, expect ImportError**

Run: `pytest tests/unit/test_spec_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus_verify.spec.manifest'`

- [ ] **Step 4: Implement the dataclasses**

Create `plutus_verify/spec/manifest.py`:

```python
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
    kind: str  # google_drive | s3 | github_release | http | manual
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
    nine_step: Optional[str]  # one of NINE_STEP_KEYS or None for free-form
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
    kind: Literal["stdout_table", "json_file", "file_regex"]
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
class ExpectedMetric:
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
    metrics: tuple[ExpectedMetric, ...] = ()
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


NINE_STEP_KEYS: tuple[str, ...] = (
    "step_1_hypothesis",
    "step_2_data_collection",
    "step_3_data_processing",
    "step_4_in_sample",
    "step_5_optimization",
    "step_6_out_of_sample",
    "step_7_paper_trading",
)
```

Note: this leaves `loader` unimported from `__init__.py` for now — Task 2 adds it. Run the test ignoring that for now:

- [ ] **Step 5: Temporarily relax `__init__.py` until loader exists**

Edit `plutus_verify/spec/__init__.py` — comment out the loader import for this task only:

```python
# from plutus_verify.spec.loader import ManifestLoadError, load_manifest
```

And remove `ManifestLoadError`, `load_manifest` from `__all__`. (They get re-added in Task 2.)

- [ ] **Step 6: Run the test, expect PASS**

Run: `pytest tests/unit/test_spec_manifest.py -v`
Expected: 5 PASSED.

- [ ] **Step 7: Commit**

```bash
git add plutus_verify/spec/__init__.py plutus_verify/spec/manifest.py tests/unit/test_spec_manifest.py
git commit -m "feat(spec): v2 manifest dataclasses"
```

---

## Task 2: JSON-Schema for the v2 manifest

**Files:**
- Create: `plutus_verify/spec/schema.py`
- Test: `tests/unit/test_spec_schema.py`

- [ ] **Step 1: Write the failing schema test**

Create `tests/unit/test_spec_schema.py`:

```python
"""Tests for the v2 manifest JSON-Schema."""
import pytest
from jsonschema import Draft202012Validator

from plutus_verify.spec.schema import MANIFEST_SCHEMA


def _minimal_valid_dict() -> dict:
    return {
        "schema_version": "2.0",
        "repo": {"name": "Demo", "primary_language": "python"},
        "env": {
            "base": "python",
            "python_version": "3.11",
            "requirements_file": "requirements.txt",
        },
        "secrets": [],
        "data_sources": {"processed": [], "raw": []},
        "steps": [
            {
                "id": "in_sample",
                "nine_step": "step_4_in_sample",
                "required": True,
                "command": "python -m demo.backtest",
                "outputs": ["out/metrics.json"],
            }
        ],
        "expected": [],
        "nine_step_coverage": {},
    }


def test_schema_accepts_minimal():
    Draft202012Validator(MANIFEST_SCHEMA).validate(_minimal_valid_dict())


def test_schema_rejects_wrong_version():
    bad = _minimal_valid_dict()
    bad["schema_version"] = "1.0"
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(bad))
    assert errs, "expected schema_version=1.0 to be rejected"


def test_schema_rejects_unknown_env_base():
    bad = _minimal_valid_dict()
    bad["env"]["base"] = "rust"
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(bad))
    assert errs


def test_schema_allows_nine_step_null_on_step():
    d = _minimal_valid_dict()
    d["steps"].append(
        {
            "id": "train_model",
            "nine_step": None,
            "label": "Custom",
            "required": True,
            "command": "python -m demo.train",
            "outputs": ["models/clf.pkl"],
        }
    )
    Draft202012Validator(MANIFEST_SCHEMA).validate(d)


def test_schema_accepts_data_sources_with_satisfies():
    d = _minimal_valid_dict()
    d["data_sources"]["processed"].append(
        {
            "kind": "google_drive",
            "url": "https://drive.google.com/x",
            "expected_layout": ["data/processed/*.parquet"],
            "satisfies": ["data_collection", "data_processing"],
        }
    )
    Draft202012Validator(MANIFEST_SCHEMA).validate(d)


def test_schema_accepts_expected_with_metric_and_reference_output():
    d = _minimal_valid_dict()
    d["expected"].append(
        {
            "step_id": "in_sample",
            "metrics": [
                {
                    "name": "sharpe_ratio",
                    "value": 0.85,
                    "locate": {
                        "kind": "json_file",
                        "path": "out/metrics.json",
                        "jsonpath": "$.sharpe",
                    },
                    "tolerance": {"kind": "relative", "value": 0.05},
                }
            ],
            "reference_outputs": [
                {
                    "path": "out/equity_curve.png",
                    "compare": "visual_similarity",
                    "threshold": 0.7,
                }
            ],
        }
    )
    Draft202012Validator(MANIFEST_SCHEMA).validate(d)


def test_schema_rejects_unknown_compare_kind():
    d = _minimal_valid_dict()
    d["expected"].append(
        {
            "step_id": "in_sample",
            "metrics": [],
            "reference_outputs": [
                {"path": "out/x.json", "compare": "fuzzy_magic"}
            ],
        }
    )
    v = Draft202012Validator(MANIFEST_SCHEMA)
    errs = list(v.iter_errors(d))
    assert errs
```

- [ ] **Step 2: Run test, expect ImportError**

Run: `pytest tests/unit/test_spec_schema.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the JSON-Schema**

Create `plutus_verify/spec/schema.py`:

```python
"""JSON-Schema (Draft 2020-12) for the v2 Plutus manifest.

Structural-only; cross-field invariants (required commands, satisfies refs)
live in spec/validator.py.
"""
from __future__ import annotations

from typing import Any

NINE_STEP_KEYS = (
    "step_1_hypothesis",
    "step_2_data_collection",
    "step_3_data_processing",
    "step_4_in_sample",
    "step_5_optimization",
    "step_6_out_of_sample",
    "step_7_paper_trading",
)

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
                    "metrics": {"type": "array", "items": _HEADLINE},
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
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/unit/test_spec_schema.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/spec/schema.py tests/unit/test_spec_schema.py
git commit -m "feat(spec): v2 manifest JSON-Schema"
```

---

## Task 3: YAML loader (yaml → dict → schema-validate → dataclass)

**Files:**
- Create: `plutus_verify/spec/loader.py`
- Test: `tests/unit/test_spec_loader.py`

- [ ] **Step 1: Write the failing loader test**

Create `tests/unit/test_spec_loader.py`:

```python
"""Tests for spec.loader: YAML/dict → Manifest."""
from pathlib import Path

import pytest

from plutus_verify.spec import Manifest, load_manifest
from plutus_verify.spec.loader import (
    ManifestLoadError,
    load_manifest_from_dict,
    load_manifest_from_yaml_text,
)


_MIN_YAML = """\
schema_version: "2.0"
repo:
  name: Demo
  primary_language: python
env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
secrets: []
data_sources:
  processed: []
  raw: []
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.backtest"
    outputs: ["out/metrics.json"]
expected: []
nine_step_coverage: {}
"""


def test_load_from_yaml_text_returns_manifest():
    m = load_manifest_from_yaml_text(_MIN_YAML)
    assert isinstance(m, Manifest)
    assert m.repo.name == "Demo"
    assert m.steps[0].id == "in_sample"
    assert m.steps[0].outputs == ("out/metrics.json",)


def test_load_from_dict_returns_manifest():
    import yaml

    data = yaml.safe_load(_MIN_YAML)
    m = load_manifest_from_dict(data)
    assert isinstance(m, Manifest)
    assert m.env.python_version == "3.11"


def test_load_from_path(tmp_path: Path):
    plutus_dir = tmp_path / ".plutus"
    plutus_dir.mkdir()
    (plutus_dir / "manifest.yaml").write_text(_MIN_YAML)
    m = load_manifest(tmp_path)
    assert m.repo.name == "Demo"


def test_load_missing_dotplutus_raises(tmp_path: Path):
    with pytest.raises(ManifestLoadError, match="no .plutus/manifest.yaml"):
        load_manifest(tmp_path)


def test_load_schema_violation_wraps_error(tmp_path: Path):
    bad = _MIN_YAML.replace('"2.0"', '"1.0"')
    with pytest.raises(ManifestLoadError, match="schema"):
        load_manifest_from_yaml_text(bad)


def test_load_full_manifest_with_all_features():
    yaml_text = """\
schema_version: "2.0"
repo:
  name: ProtoMM
  primary_language: python
env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
  os_packages: [build-essential]
  gpu_required: false
secrets:
  - key: TIINGO_API_KEY
    purpose: market data
    used_by: [data_collection]
data_sources:
  processed:
    - kind: google_drive
      url: https://drive.google.com/x
      expected_layout: ["data/processed/*.parquet"]
      satisfies: [data_collection, data_processing]
  raw:
    - kind: github_release
      url: https://github.com/x/y/releases/v1/raw.tar.gz
      expected_layout: ["data/raw/*.parquet"]
      satisfies: [data_collection]
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge
    command: "python -m proto_mm.data.collect"
    outputs: ["data/raw/*.parquet"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python -m proto_mm.data.preprocess"
    inputs: [data/raw]
    outputs: ["data/processed/*.parquet"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m proto_mm.backtest"
    inputs: [data/processed]
    outputs: ["out/metrics.json", "out/equity.png"]
  - id: train_model
    nine_step: null
    label: "Custom: train classifier"
    required: true
    command: "python -m proto_mm.ml.train"
    outputs: ["models/clf.pkl"]
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.85
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs:
      - path: "out/metrics.json"
        compare: json_numeric_tolerance
      - path: "out/equity.png"
        compare: visual_similarity
        threshold: 0.7
nine_step_coverage:
  step_1_hypothesis: {present: true, section: "1. Hypothesis"}
  step_2_data_collection: {present: true, section: "2. Data"}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    assert len(m.steps) == 4
    assert m.steps[3].nine_step is None
    assert m.steps[3].label == "Custom: train classifier"
    assert len(m.data_sources.processed) == 1
    assert m.data_sources.processed[0].satisfies == ("data_collection", "data_processing")
    assert m.expected[0].metrics[0].value == 0.85
    assert m.expected[0].reference_outputs[1].threshold == 0.7
    assert m.nine_step_coverage["step_1_hypothesis"].present is True
```

- [ ] **Step 2: Run test, expect ImportError**

Run: `pytest tests/unit/test_spec_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus_verify.spec.loader'`.

- [ ] **Step 3: Implement the loader**

Create `plutus_verify/spec/loader.py`:

```python
"""YAML → dict → schema-validate → Manifest pipeline.

Use :func:`load_manifest(repo_path)` for "is there a .plutus/ directory here?"
flow, or :func:`load_manifest_from_yaml_text` / :func:`load_manifest_from_dict`
when the caller already has the data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from plutus_verify.spec.manifest import (
    DataSource,
    DataSourceTiers,
    Env,
    ExpectedBlock,
    ExpectedMetric,
    Locate,
    Manifest,
    NineStepCoverage,
    ReferenceOutput,
    Repo,
    Secret,
    Step,
    Tolerance,
)
from plutus_verify.spec.schema import MANIFEST_SCHEMA


class ManifestLoadError(ValueError):
    """Raised for any failure to load a v2 manifest (file, YAML, schema)."""


_VALIDATOR = Draft202012Validator(MANIFEST_SCHEMA)


def load_manifest(repo_path: Path) -> Manifest:
    """Load `.plutus/manifest.yaml` from inside `repo_path`."""
    manifest_path = repo_path / ".plutus" / "manifest.yaml"
    if not manifest_path.exists():
        raise ManifestLoadError(f"no .plutus/manifest.yaml in {repo_path}")
    return load_manifest_from_yaml_text(manifest_path.read_text())


def load_manifest_from_yaml_text(text: str) -> Manifest:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestLoadError(f"YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestLoadError("manifest YAML root must be a mapping")
    return load_manifest_from_dict(data)


def load_manifest_from_dict(data: dict[str, Any]) -> Manifest:
    try:
        _VALIDATOR.validate(data)
    except ValidationError as exc:
        raise ManifestLoadError(f"schema violation: {exc.message}") from exc
    return _build(data)


def _build(d: dict[str, Any]) -> Manifest:
    repo = Repo(name=d["repo"]["name"], primary_language=d["repo"]["primary_language"])
    env = Env(
        base=d["env"]["base"],
        python_version=d["env"]["python_version"],
        requirements_file=d["env"].get("requirements_file"),
        os_packages=tuple(d["env"].get("os_packages", ())),
        gpu_required=d["env"].get("gpu_required", False),
    )
    secrets = tuple(
        Secret(
            key=s["key"],
            purpose=s.get("purpose", ""),
            used_by=tuple(s.get("used_by", ())),
        )
        for s in d["secrets"]
    )
    data_sources = DataSourceTiers(
        processed=tuple(_build_data_source(x) for x in d["data_sources"]["processed"]),
        raw=tuple(_build_data_source(x) for x in d["data_sources"]["raw"]),
    )
    steps = tuple(_build_step(x) for x in d["steps"])
    expected = tuple(_build_expected(x) for x in d["expected"])
    coverage = {
        k: NineStepCoverage(present=v["present"], section=v.get("section"))
        for k, v in d.get("nine_step_coverage", {}).items()
    }
    return Manifest(
        schema_version=d["schema_version"],
        repo=repo,
        env=env,
        secrets=secrets,
        data_sources=data_sources,
        steps=steps,
        expected=expected,
        nine_step_coverage=coverage,
    )


def _build_data_source(d: dict[str, Any]) -> DataSource:
    return DataSource(
        kind=d["kind"],
        url=d["url"],
        expected_layout=tuple(d["expected_layout"]),
        satisfies=tuple(d["satisfies"]),
        secrets_required=tuple(d.get("secrets_required", ())),
        label=d.get("label"),
    )


def _build_step(d: dict[str, Any]) -> Step:
    return Step(
        id=d["id"],
        nine_step=d["nine_step"],
        required=d["required"],
        command=d.get("command"),
        label=d.get("label"),
        network=d.get("network", "none"),
        timeout_seconds=d.get("timeout_seconds", 1800),
        inputs=tuple(d.get("inputs", ())),
        outputs=tuple(d.get("outputs", ())),
        depends_on=tuple(d.get("depends_on", ())),
        verification_mode=d.get("verification_mode", "execute"),
    )


def _build_expected(d: dict[str, Any]) -> ExpectedBlock:
    metrics = tuple(
        ExpectedMetric(
            name=h["name"],
            value=h["value"],
            locate=Locate(
                kind=h["locate"]["kind"],
                path=h["locate"].get("path"),
                row=h["locate"].get("row"),
                col=h["locate"].get("col"),
                jsonpath=h["locate"].get("jsonpath"),
                pattern=h["locate"].get("pattern"),
            ),
            tolerance=Tolerance(
                kind=h["tolerance"]["kind"], value=h["tolerance"]["value"]
            ),
        )
        for h in d.get("metrics", [])
    )
    refs = tuple(
        ReferenceOutput(
            path=r["path"],
            compare=r["compare"],
            threshold=r.get("threshold"),
        )
        for r in d.get("reference_outputs", [])
    )
    return ExpectedBlock(step_id=d["step_id"], metrics=metrics, reference_outputs=refs)
```

- [ ] **Step 4: Re-enable loader exports in `spec/__init__.py`**

Edit `plutus_verify/spec/__init__.py` and uncomment the loader import line, restore `ManifestLoadError`, `load_manifest` to `__all__`.

- [ ] **Step 5: Run tests, expect PASS**

Run: `pytest tests/unit/test_spec_loader.py tests/unit/test_spec_manifest.py -v`
Expected: 11 PASSED.

- [ ] **Step 6: Commit**

```bash
git add plutus_verify/spec/__init__.py plutus_verify/spec/loader.py tests/unit/test_spec_loader.py
git commit -m "feat(spec): YAML loader for v2 manifest"
```

---

## Task 4: Cross-field invariants validator

**Files:**
- Create: `plutus_verify/spec/validator.py`
- Modify: `plutus_verify/spec/loader.py` (call validator after schema check)
- Test: `tests/unit/test_spec_validator.py`

- [ ] **Step 1: Write the failing validator tests**

Create `tests/unit/test_spec_validator.py`:

```python
"""Tests for the v2 manifest invariants that JSON-Schema can't express."""
import pytest

from plutus_verify.spec.loader import ManifestLoadError, load_manifest_from_yaml_text


_BASE = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps: %s
expected: []
nine_step_coverage: {}
"""


def _yaml(steps: str) -> str:
    return _BASE % steps


def test_data_collection_without_command_rejected():
    steps = """
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    outputs: ["data/raw/x.parquet"]
"""
    with pytest.raises(ManifestLoadError, match="data_collection.*command"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_data_processing_without_command_rejected():
    steps = """
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    outputs: ["data/processed/x.parquet"]
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "python collect.py"
    outputs: ["data/raw/x.parquet"]
"""
    with pytest.raises(ManifestLoadError, match="data_processing.*command"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_duplicate_step_ids_rejected():
    steps = """
  - id: same
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
  - id: same
    nine_step: step_6_out_of_sample
    required: true
    command: "echo b"
"""
    with pytest.raises(ManifestLoadError, match="duplicate step id"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_depends_on_unknown_step_rejected():
    steps = """
  - id: a
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
    depends_on: ["ghost"]
"""
    with pytest.raises(ManifestLoadError, match="depends_on.*ghost"):
        load_manifest_from_yaml_text(_yaml(steps))


def test_expected_refers_to_unknown_step_rejected():
    yaml_text = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: a
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
expected:
  - step_id: ghost
    metrics: []
    reference_outputs: []
nine_step_coverage: {}
"""
    with pytest.raises(ManifestLoadError, match="expected.*ghost"):
        load_manifest_from_yaml_text(yaml_text)


def test_data_source_satisfies_unknown_step_rejected():
    yaml_text = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources:
  processed:
    - kind: s3
      url: s3://x
      expected_layout: ["data/processed/*.parquet"]
      satisfies: ["data_collection", "ghost"]
  raw: []
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "echo a"
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "echo b"
expected: []
nine_step_coverage: {}
"""
    with pytest.raises(ManifestLoadError, match="satisfies.*ghost"):
        load_manifest_from_yaml_text(yaml_text)


def test_secret_used_by_unknown_step_rejected():
    yaml_text = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets:
  - key: K
    used_by: [ghost]
data_sources: {processed: [], raw: []}
steps:
  - id: a
    nine_step: step_4_in_sample
    required: true
    command: "echo a"
expected: []
nine_step_coverage: {}
"""
    with pytest.raises(ManifestLoadError, match="secret K.*used_by.*ghost"):
        load_manifest_from_yaml_text(yaml_text)
```

- [ ] **Step 2: Run tests, expect ImportError or AttributeError**

Run: `pytest tests/unit/test_spec_validator.py -v`
Expected: all FAIL with `ManifestLoadError` not raised (since validator doesn't exist yet, the load succeeds).

- [ ] **Step 3: Implement the validator**

Create `plutus_verify/spec/validator.py`:

```python
"""Cross-field invariants for the v2 manifest.

JSON-Schema validates structure; this module enforces relationships:
  - data_collection / data_processing steps must declare a command
  - step ids unique
  - every depends_on references an existing step
  - every expected.step_id references an existing step
  - every data_source.satisfies references an existing step
  - every secret.used_by references an existing step
"""
from __future__ import annotations

from plutus_verify.spec.manifest import Manifest


class ManifestInvariantError(ValueError):
    """Raised when a structurally-valid manifest violates a cross-field rule."""


_DATA_STEP_IDS = ("data_collection", "data_processing")


def check_invariants(m: Manifest) -> None:
    step_ids = [s.id for s in m.steps]
    if len(set(step_ids)) != len(step_ids):
        dupes = sorted({sid for sid in step_ids if step_ids.count(sid) > 1})
        raise ManifestInvariantError(f"duplicate step id(s): {dupes}")

    step_id_set = set(step_ids)

    for s in m.steps:
        if s.id in _DATA_STEP_IDS and not s.command:
            raise ManifestInvariantError(
                f"step '{s.id}' requires a non-empty command (data steps must "
                "have runnable code even when data_sources provides downloads)"
            )
        for dep in s.depends_on:
            if dep not in step_id_set:
                raise ManifestInvariantError(
                    f"step '{s.id}' depends_on unknown step '{dep}'"
                )

    for er in m.expected:
        if er.step_id not in step_id_set:
            raise ManifestInvariantError(
                f"expected refers to unknown step_id '{er.step_id}'"
            )

    for tier_name, sources in (("processed", m.data_sources.processed), ("raw", m.data_sources.raw)):
        for ds in sources:
            for step_id in ds.satisfies:
                if step_id not in step_id_set:
                    raise ManifestInvariantError(
                        f"data_sources.{tier_name} entry (url={ds.url}) "
                        f"satisfies unknown step '{step_id}'"
                    )

    for sec in m.secrets:
        for step_id in sec.used_by:
            # Allow data-source qualifiers like "data_sources.processed.s3"
            if step_id.startswith("data_sources."):
                continue
            if step_id not in step_id_set:
                raise ManifestInvariantError(
                    f"secret {sec.key} used_by unknown step '{step_id}'"
                )
```

- [ ] **Step 4: Wire validator into the loader**

Edit `plutus_verify/spec/loader.py`. Find:

```python
def load_manifest_from_dict(data: dict[str, Any]) -> Manifest:
    try:
        _VALIDATOR.validate(data)
    except ValidationError as exc:
        raise ManifestLoadError(f"schema violation: {exc.message}") from exc
    return _build(data)
```

Replace with:

```python
def load_manifest_from_dict(data: dict[str, Any]) -> Manifest:
    try:
        _VALIDATOR.validate(data)
    except ValidationError as exc:
        raise ManifestLoadError(f"schema violation: {exc.message}") from exc
    m = _build(data)
    from plutus_verify.spec.validator import ManifestInvariantError, check_invariants

    try:
        check_invariants(m)
    except ManifestInvariantError as exc:
        raise ManifestLoadError(str(exc)) from exc
    return m
```

- [ ] **Step 5: Run tests, expect PASS**

Run: `pytest tests/unit/test_spec_validator.py tests/unit/test_spec_loader.py -v`
Expected: 13 PASSED (7 new + 6 existing).

- [ ] **Step 6: Commit**

```bash
git add plutus_verify/spec/validator.py plutus_verify/spec/loader.py tests/unit/test_spec_validator.py
git commit -m "feat(spec): cross-field invariants validator"
```

---

## Task 5: Adapter to existing `ExtractedPlan` (bridge to legacy pipeline)

**Files:**
- Create: `plutus_verify/spec/adapter.py`
- Test: `tests/unit/test_spec_adapter.py`

**Adapter mapping (note documented losses):**

| v2 Manifest                              | v1 `ExtractedPlan`                                |
|------------------------------------------|---------------------------------------------------|
| `repo.name`, `repo.primary_language`     | `Repo.name`, `Repo.primary_language`              |
| `env.requirements_file`                  | `Repo.env_setup.path` (kind=`requirements_txt`)   |
| `env.python_version`                     | `Repo.env_setup.python_version`                   |
| `env.os_packages`, `env.gpu_required`    | LOST in adapter (Plan 2 native build)             |
| `secrets[*]`                             | `Repo.secrets_required[*]`                        |
| `data_sources.raw[*]` (satisfies=[X])    | One `Step(X).alternatives[*]` of kind=manual_download |
| `data_sources.processed[*]` (multi-sat)  | LOST (logged warning); Plan 2 handles natively    |
| `steps[*].command/network/timeout`       | `Step.command/network/timeout_seconds`            |
| `steps[*].outputs`                       | `Step.produces`                                   |
| `steps[*].inputs`                        | LOST in adapter (Plan 2 native pre-flight)        |
| `steps[*].depends_on/verification_mode`  | `Step.depends_on/verification_mode`               |
| `steps[*].nine_step` (str)               | `Step.nine_step`                                  |
| `steps[*].nine_step` (None — free-form)  | Mapped to `step_4_in_sample` placeholder + extraction_notes entry |
| `expected[*].metrics[*]`               | `ExpectedResult.metrics[*]`                       |
| `expected[*].reference_outputs[*]`       | `ExpectedResult.charts[*]` (only `visual_similarity`); other kinds LOST until Plan 2 |
| `nine_step_coverage`                     | `nine_step_mapping` (confidence forced to 1.0)    |

- [ ] **Step 1: Write the failing adapter tests**

Create `tests/unit/test_spec_adapter.py`:

```python
"""Tests for spec.adapter: Manifest → ExtractedPlan bridge."""
from plutus_verify.extract.plan import ExtractedPlan
from plutus_verify.spec.adapter import to_extracted_plan
from plutus_verify.spec.loader import load_manifest_from_yaml_text


_MIN = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets:
  - key: API
    purpose: testing
    used_by: [in_sample]
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.backtest"
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.85
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []
nine_step_coverage:
  step_4_in_sample: {present: true, section: "Backtest"}
"""


def test_adapter_returns_extracted_plan():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert isinstance(p, ExtractedPlan)
    assert p.schema_version == "1.0"
    assert p.repo.name == "Demo"


def test_adapter_maps_env_to_requirements_txt():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert p.repo.env_setup.kind == "requirements_txt"
    assert p.repo.env_setup.path == "requirements.txt"
    assert p.repo.env_setup.python_version == "3.11"


def test_adapter_maps_secrets():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert len(p.repo.secrets_required) == 1
    assert p.repo.secrets_required[0].key == "API"
    assert p.repo.secrets_required[0].step_ids == ("in_sample",)


def test_adapter_maps_step_and_outputs_to_produces():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert len(p.steps) == 1
    s = p.steps[0]
    assert s.id == "in_sample"
    assert s.command == "python -m demo.backtest"
    assert s.produces == ("out/metrics.json",)


def test_adapter_maps_metrics_to_expected_metrics():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    assert len(p.expected_results) == 1
    er = p.expected_results[0]
    assert er.step_id == "in_sample"
    assert len(er.metrics) == 1
    assert er.metrics[0].name == "sharpe_ratio"
    assert er.metrics[0].value == 0.85
    assert er.metrics[0].locate.kind == "json_file"


def test_adapter_maps_nine_step_coverage_to_mapping():
    m = load_manifest_from_yaml_text(_MIN)
    p = to_extracted_plan(m)
    entry = p.nine_step_mapping["step_4_in_sample"]
    assert entry.present is True
    assert entry.section_heading == "Backtest"
    assert entry.confidence == 1.0


def test_adapter_translates_raw_data_source_to_alternative():
    yaml_text = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources:
  processed: []
  raw:
    - kind: github_release
      url: https://github.com/x/y/raw.tar.gz
      expected_layout: ["data/raw/*.parquet"]
      satisfies: [data_collection]
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge
    command: "python collect.py"
    outputs: ["data/raw/x.parquet"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python preprocess.py"
    outputs: ["data/processed/x.parquet"]
expected: []
nine_step_coverage: {}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    p = to_extracted_plan(m)
    dc = next(s for s in p.steps if s.id == "data_collection")
    assert dc.alternatives is not None
    assert len(dc.alternatives) == 1
    alt = dc.alternatives[0]
    assert alt.kind == "manual_download"
    assert alt.url == "https://github.com/x/y/raw.tar.gz"
    assert alt.expected_layout == ("data/raw/*.parquet",)


def test_adapter_free_form_step_gets_placeholder_nine_step():
    yaml_text = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: train
    nine_step: null
    label: ML train
    required: true
    command: "python train.py"
    outputs: ["models/clf.pkl"]
expected: []
nine_step_coverage: {}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    p = to_extracted_plan(m)
    s = p.steps[0]
    assert s.nine_step == "step_4_in_sample"  # placeholder
    assert any("free-form step 'train'" in note for note in p.extraction_notes)


def test_adapter_processed_data_source_logs_warning_in_notes():
    yaml_text = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: r.txt}
secrets: []
data_sources:
  processed:
    - kind: s3
      url: s3://x
      expected_layout: ["data/processed/*.parquet"]
      satisfies: [data_collection, data_processing]
  raw: []
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "python a.py"
    outputs: ["data/raw/x"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python b.py"
    outputs: ["data/processed/x"]
expected: []
nine_step_coverage: {}
"""
    m = load_manifest_from_yaml_text(yaml_text)
    p = to_extracted_plan(m)
    notes_blob = " ".join(p.extraction_notes)
    assert "data_sources.processed" in notes_blob
    assert "Plan 2" in notes_blob
```

- [ ] **Step 2: Run tests, expect ImportError**

Run: `pytest tests/unit/test_spec_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus_verify.spec.adapter'`.

- [ ] **Step 3: Implement the adapter**

Create `plutus_verify/spec/adapter.py`:

```python
"""Bridge: v2 Manifest → v1 ExtractedPlan.

This adapter is intentionally lossy: it lets the existing build/execute/compare
code run against v2-authored repos with no changes. Plan 2 will introduce a
native v2 executor and retire the adapter.

Documented losses (each emits an extraction_notes entry on the returned plan):
  - env.os_packages, env.gpu_required (Plan 2 generates the Dockerfile natively)
  - steps[*].inputs (Plan 2 adds input pre-flight)
  - reference_outputs of compare != visual_similarity (Plan 2 adds full comparator)
  - data_sources.processed entries that span multiple steps (Plan 2 has tier resolver)
  - steps[*].nine_step == None becomes step_4_in_sample placeholder
"""
from __future__ import annotations

from plutus_verify.extract.plan import (
    EnvSetup,
    ExpectedChart,
    ExpectedMetric,
    ExpectedResult,
    ExtractedPlan,
    Locate as PlanLocate,
    NineStepEntry,
    Repo as PlanRepo,
    SecretRequirement,
    Step as PlanStep,
    StepAlternative,
    Tolerance as PlanTolerance,
)
from plutus_verify.spec.manifest import (
    DataSource,
    Manifest,
    NINE_STEP_KEYS,
    Step,
)


_FREE_FORM_PLACEHOLDER = "step_4_in_sample"


def to_extracted_plan(m: Manifest) -> ExtractedPlan:
    notes: list[str] = []

    repo = PlanRepo(
        name=m.repo.name,
        primary_language=m.repo.primary_language,
        env_setup=_env_setup(m, notes),
        secrets_required=_secrets(m),
    )

    raw_by_step = _raw_data_sources_indexed_by_step(m)
    for ds in m.data_sources.processed:
        if len(ds.satisfies) > 1:
            notes.append(
                f"v2 data_sources.processed entry (kind={ds.kind}, url={ds.url}) "
                f"satisfies multiple steps {list(ds.satisfies)}; not natively "
                "honored by the legacy pipeline. Plan 2 implements the tier resolver."
            )

    steps = tuple(_step(s, raw_by_step.get(s.id, ()), notes) for s in m.steps)
    expected = tuple(_expected(er, notes) for er in m.expected)

    mapping = {k: NineStepEntry(present=False, section_heading=None, confidence=1.0) for k in NINE_STEP_KEYS}
    for k, v in m.nine_step_coverage.items():
        mapping[k] = NineStepEntry(present=v.present, section_heading=v.section, confidence=1.0)

    return ExtractedPlan(
        schema_version="1.0",
        repo=repo,
        nine_step_mapping=mapping,
        steps=steps,
        expected_results=expected,
        extraction_notes=tuple(notes),
    )


def _env_setup(m: Manifest, notes: list[str]) -> EnvSetup:
    if m.env.os_packages:
        notes.append(
            f"v2 env.os_packages {list(m.env.os_packages)} ignored by the legacy "
            "pipeline; Plan 2 generates the Dockerfile natively."
        )
    if m.env.gpu_required:
        notes.append("v2 env.gpu_required=true ignored by the legacy pipeline.")
    return EnvSetup(
        kind="requirements_txt",
        path=m.env.requirements_file,
        python_version=m.env.python_version,
        extra_setup_commands=(),
    )


def _secrets(m: Manifest) -> tuple[SecretRequirement, ...]:
    return tuple(
        SecretRequirement(
            key=s.key,
            purpose=s.purpose,
            step_ids=tuple(u for u in s.used_by if not u.startswith("data_sources.")),
        )
        for s in m.secrets
    )


def _raw_data_sources_indexed_by_step(m: Manifest) -> dict[str, tuple[DataSource, ...]]:
    out: dict[str, list[DataSource]] = {}
    for ds in m.data_sources.raw:
        for step_id in ds.satisfies:
            out.setdefault(step_id, []).append(ds)
    return {k: tuple(v) for k, v in out.items()}


def _step(s: Step, raw_sources: tuple[DataSource, ...], notes: list[str]) -> PlanStep:
    if s.nine_step is None:
        notes.append(
            f"v2 free-form step '{s.id}' (label={s.label!r}) mapped to "
            f"placeholder nine_step={_FREE_FORM_PLACEHOLDER}."
        )
        nine_step = _FREE_FORM_PLACEHOLDER
    else:
        nine_step = s.nine_step
    if s.inputs:
        notes.append(
            f"v2 step '{s.id}' inputs {list(s.inputs)} not enforced in adapter; "
            "Plan 2 adds input pre-flight."
        )
    alternatives = (
        tuple(
            StepAlternative(
                label=ds.label or f"{ds.kind} download",
                kind="manual_download",
                url=ds.url,
                expected_layout=ds.expected_layout,
                needs_secrets=ds.secrets_required,
                network="bridge",
                timeout_seconds=1800,
                produces=ds.expected_layout,
            )
            for ds in raw_sources
        )
        if raw_sources
        else None
    )
    return PlanStep(
        id=s.id,
        nine_step=nine_step,
        required=s.required,
        depends_on=s.depends_on,
        command=s.command,
        config_files=(),
        network=s.network,
        timeout_seconds=s.timeout_seconds,
        produces=s.outputs,
        alternatives=alternatives,
        verification_mode=s.verification_mode,
    )


def _expected(er, notes: list[str]) -> ExpectedResult:
    metrics = tuple(
        ExpectedMetric(
            name=h.name,
            value=h.value,
            locate=PlanLocate(
                kind=h.locate.kind,
                row=h.locate.row,
                col=h.locate.col,
                path=h.locate.path,
                jsonpath=h.locate.jsonpath,
                pattern=h.locate.pattern,
            ),
            tolerance=PlanTolerance(kind=h.tolerance.kind, value=h.tolerance.value),
        )
        for h in er.metrics
    )
    chart_refs = []
    for r in er.reference_outputs:
        if r.compare == "visual_similarity":
            chart_refs.append(
                ExpectedChart(
                    name=r.path,
                    produced_path=r.path,
                    reference_image=None,
                )
            )
        else:
            notes.append(
                f"v2 reference_outputs path={r.path} compare={r.compare} "
                "not supported by legacy pipeline; Plan 2 adds the full comparator."
            )
    return ExpectedResult(step_id=er.step_id, metrics=tuple(metrics), charts=tuple(chart_refs))
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/unit/test_spec_adapter.py -v`
Expected: 9 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/spec/adapter.py tests/unit/test_spec_adapter.py
git commit -m "feat(spec): adapter from v2 Manifest to v1 ExtractedPlan"
```

---

## Task 6: Wire pipeline.py to branch on `.plutus/manifest.yaml`

**Files:**
- Modify: `plutus_verify/pipeline.py` (extract stage)
- Test: `tests/unit/test_pipeline_spec_detection.py`

- [ ] **Step 1: Write the failing pipeline-branch test**

Create `tests/unit/test_pipeline_spec_detection.py`:

```python
"""Tests that pipeline.py uses the v2 spec when .plutus/manifest.yaml exists,
falling back to the LLM extractor otherwise.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.config import Config
from plutus_verify.extract.plan import ExtractedPlan
from plutus_verify.ingest import IngestResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline


_MIN_MANIFEST = """\
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo hi"
    outputs: ["out/metrics.json"]
expected: []
nine_step_coverage: {}
"""


def _make_ingest_result(repo_path: Path, *, with_manifest: bool) -> IngestResult:
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "README.md").write_text("# Demo\nSee .plutus/.")
    if with_manifest:
        plutus = repo_path / ".plutus"
        plutus.mkdir()
        (plutus / "manifest.yaml").write_text(_MIN_MANIFEST)
    meta_path = repo_path.parent / "meta.json"
    meta_path.write_text("{}")
    return IngestResult(
        git_url=str(repo_path),
        repo_path=repo_path,
        readme_path=repo_path / "README.md",
        commit_sha="0" * 40,
        branch="main",
        meta_path=meta_path,
    )


def test_pipeline_uses_spec_when_dotplutus_present(tmp_path: Path, monkeypatch):
    """When .plutus/manifest.yaml exists, the LLM extractor must NOT be called."""
    repo_path = tmp_path / "repo"
    ingest_result = _make_ingest_result(repo_path, with_manifest=True)

    # Patch ingest() so we don't actually clone
    from plutus_verify import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest", lambda *a, **kw: ingest_result)

    llm_client = MagicMock()
    llm_client.complete.side_effect = AssertionError("LLM must not be called when spec exists")

    # Stop pipeline after extract stage
    inputs = PipelineInputs(
        source=str(repo_path),
        out_dir=tmp_path / "out",
        config=Config(),
        skip_clone=True,
        extract_only=True,
    )
    result = run_pipeline(
        inputs,
        llm_client=llm_client,
        builder=MagicMock(),
        runner=MagicMock(),
        vision=MagicMock(),
    )
    assert isinstance(result.plan, ExtractedPlan)
    assert result.plan.repo.name == "Demo"
    llm_client.complete.assert_not_called()


def test_pipeline_falls_back_to_extract_when_no_dotplutus(tmp_path: Path, monkeypatch):
    """When .plutus/ is absent, the legacy extract path is used (verified by
    confirming the pre_loaded_plan branch was honored — that branch only runs
    when the spec branch does NOT short-circuit)."""
    from plutus_verify.extract.plan import EnvSetup, Repo as PlanRepo

    repo_path = tmp_path / "repo"
    ingest_result = _make_ingest_result(repo_path, with_manifest=False)

    from plutus_verify import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest", lambda *a, **kw: ingest_result)

    sentinel_plan = ExtractedPlan(
        schema_version="1.0",
        repo=PlanRepo(
            name="SentinelRepo",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={},
        steps=(),
        expected_results=(),
        extraction_notes=("from-sentinel",),
    )
    inputs = PipelineInputs(
        source=str(repo_path),
        out_dir=tmp_path / "out",
        config=Config(),
        skip_clone=True,
        extract_only=True,
        pre_loaded_plan=sentinel_plan,
    )
    result = run_pipeline(
        inputs,
        llm_client=MagicMock(),
        builder=MagicMock(),
        runner=MagicMock(),
        vision=MagicMock(),
    )
    # The spec branch would have ignored pre_loaded_plan and built a plan from
    # the manifest. Since the sentinel plan came through, we know the spec
    # branch did NOT fire.
    assert "from-sentinel" in result.plan.extraction_notes
    assert result.plan.repo.name == "SentinelRepo"
```

- [ ] **Step 2: Run tests, expect FAIL**

Run: `pytest tests/unit/test_pipeline_spec_detection.py -v`
Expected: FAIL — pipeline doesn't yet branch on `.plutus/`; it always calls `extract_plan`.

- [ ] **Step 3: Modify pipeline.py to add the spec branch**

Open `plutus_verify/pipeline.py`. Find the extract stage (starts at the comment `# ---------- extract ----------`, currently around line 198). Locate this block:

```python
    if inputs.pre_loaded_plan is not None:
```

**Replace the whole if/elif/elif/else extract chain** (from `if inputs.pre_loaded_plan is not None:` down to and including `extract_artifacts = ["plan.json", "extract_call_*.txt"]`) with the version below. The only change is adding a new branch FIRST that detects `.plutus/manifest.yaml`:

```python
    spec_path = ing.repo_path / ".plutus" / "manifest.yaml"
    if spec_path.exists():
        from plutus_verify.spec.adapter import to_extracted_plan
        from plutus_verify.spec.loader import load_manifest

        try:
            manifest = load_manifest(ing.repo_path)
        except Exception as exc:
            progress.error("extract", f"v2 spec load failed: {exc}")
            raise
        plan = to_extracted_plan(manifest)
        plan = _apply_artifact_only_override(plan, inputs.config.overrides.artifact_only_steps)
        plan_path.write_text(json.dumps(_plan_to_dict(plan), indent=2))
        n_steps = len(plan.steps)
        n_metrics = sum(len(er.metrics) for er in plan.expected_results)
        n_charts = sum(len(er.charts) for er in plan.expected_results)
        extract_outcome = "ok"
        extract_summary = (
            f"v2 spec — {n_steps} steps, {n_metrics} metrics, {n_charts} charts"
        )
        progress.stage(
            "extract",
            f"loaded .plutus/manifest.yaml — {extract_summary}  "
            f"({time.monotonic() - stage_start:.1f}s)",
        )
        extract_artifacts = ["plan.json", "manifest.yaml"]
    elif inputs.pre_loaded_plan is not None:
        plan = inputs.pre_loaded_plan
        # Persist so the re-run is auditable
        if not plan_path.exists():
            plan_path.write_text(json.dumps(_plan_to_dict(plan), indent=2))
        progress.stage("extract", "skipped (pre-loaded plan provided)")
        extract_outcome = "skipped"
        extract_summary = "used pre-loaded plan.json"
        extract_artifacts = ["plan.json"]
    elif inputs.resume_existing and plan_path.exists():
        plan = parse_plan(json.loads(plan_path.read_text()))
        progress.stage("extract", "skipped (using existing plan.json from out_dir)")
        extract_outcome = "skipped"
        extract_summary = "reused existing plan.json"
        extract_artifacts = ["plan.json"]
    elif _should_skip(inputs.resume_from, "extract") and plan_path.exists():
        plan = parse_plan(json.loads(plan_path.read_text()))
        progress.stage("extract", "skipped (resume-from past extract)")
        extract_outcome = "skipped"
        extract_summary = "reused existing plan.json"
        extract_artifacts = ["plan.json"]
    else:
        readme_text = ing.readme_path.read_text()
        progress.stage("extract", "generating plan via 4 LLM calls")

        retry_counts: dict[str, int] = {}

        def _save_attempt(label: str, raw: str, err: Exception | None) -> None:
            tag = "ok" if err is None else type(err).__name__
            (inputs.out_dir / f"extract_{label}_{tag}.txt").write_text(raw)
            if err is not None:
                (inputs.out_dir / f"extract_{label}_{tag}.err").write_text(str(err))
            try:
                call_num = label.split("_")[1]
                element = label.split("_")[2]
            except IndexError:
                call_num, element = "?", label
            if err is None:
                progress.substep(
                    "extract", f"call {int(call_num) + 1}/4 {element}: ok"
                )
            else:
                retry_counts[element] = retry_counts.get(element, 0) + 1
                msg = str(err).splitlines()[0] if str(err) else type(err).__name__
                if len(msg) > 120:
                    msg = msg[:117] + "..."
                progress.substep(
                    "extract",
                    f"call {int(call_num) + 1}/4 {element}: retry "
                    f"{retry_counts[element]} — {type(err).__name__}: {msg}",
                )

        try:
            plan = extract_plan(
                readme_text,
                llm_client,
                temperature=inputs.config.llm.temperature,
                max_retries=inputs.config.llm.max_retries,
                first_attempt_idle_seconds=float(
                    getattr(inputs.config.llm, "first_attempt_timeout_seconds", 180)
                ),
                retry_idle_seconds=float(inputs.config.llm.timeout_seconds),
                on_attempt=_save_attempt,
            )
        except Exception as exc:
            progress.error("extract", f"{type(exc).__name__}: {exc}")
            raise
        plan = _apply_artifact_only_override(plan, inputs.config.overrides.artifact_only_steps)
        plan, validator_fixes = validate_plan(
            plan,
            readme_text=readme_text,
            repo_path=ing.repo_path,
            llm_client=None,
        )
        if validator_fixes:
            (inputs.out_dir / "validator_fixes.json").write_text(
                json.dumps(validator_fixes, indent=2)
            )
            progress.substep(
                "extract",
                f"validator applied {len(validator_fixes)} fix(es) to plan",
            )
        plan_path.write_text(json.dumps(_plan_to_dict(plan), indent=2))
        n_steps = len(plan.steps)
        n_metrics = sum(len(er.metrics) for er in plan.expected_results)
        n_charts = sum(len(er.charts) for er in plan.expected_results)
        n_retries = sum(retry_counts.values())
        extract_outcome = "ok"
        extract_summary = (
            f"{n_steps} steps, {n_metrics} metrics, {n_charts} charts"
            + (f" ({n_retries} retry)" if n_retries else "")
        )
        progress.stage(
            "extract",
            f"plan.json written — {extract_summary}  "
            f"({time.monotonic() - stage_start:.1f}s)",
        )
        extract_artifacts = ["plan.json", "extract_call_*.txt"]
```

(Only the first `if` branch is new. The rest is the existing code unchanged — included so a worker reading this task in isolation has the complete block.)

- [ ] **Step 4: Run the new tests, expect PASS**

Run: `pytest tests/unit/test_pipeline_spec_detection.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Run the full unit suite to confirm nothing else broke**

Run: `pytest tests/unit -v`
Expected: all PASSED (existing tests + new ones).

- [ ] **Step 6: Commit**

```bash
git add plutus_verify/pipeline.py tests/unit/test_pipeline_spec_detection.py
git commit -m "feat(pipeline): branch to v2 spec when .plutus/manifest.yaml is present"
```

---

## Task 7: Integration fixture + end-to-end test (extract → adapt only)

**Files:**
- Create: `tests/integration/fixtures/spec_v2_minimal/.plutus/manifest.yaml`
- Create: `tests/integration/fixtures/spec_v2_minimal/README.md`
- Create: `tests/integration/fixtures/spec_v2_minimal/requirements.txt`
- Create: `tests/integration/test_spec_e2e.py`

- [ ] **Step 1: Create the fixture repo**

Create `tests/integration/fixtures/spec_v2_minimal/README.md`:

```markdown
# spec_v2_minimal fixture

A minimal repo that ships a `.plutus/manifest.yaml`. Used by the v2 spec
pipeline integration test.
```

Create `tests/integration/fixtures/spec_v2_minimal/requirements.txt`:

```
# empty by design — fixture is for spec-pipeline tests, not real execution
```

Create `tests/integration/fixtures/spec_v2_minimal/.plutus/manifest.yaml`:

```yaml
schema_version: "2.0"
repo:
  name: SpecV2Minimal
  primary_language: python
env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
secrets: []
data_sources:
  processed: []
  raw:
    - kind: github_release
      url: https://example.com/raw.tar.gz
      expected_layout: ["data/raw/*.parquet"]
      satisfies: [data_collection]
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge
    command: "python -c 'print(\"collect\")'"
    outputs: ["data/raw/x.parquet"]
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "python -c 'print(\"preprocess\")'"
    inputs: [data/raw]
    outputs: ["data/processed/x.parquet"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -c 'print(\"backtest\")'"
    inputs: [data/processed]
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.85
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []
nine_step_coverage:
  step_2_data_collection: {present: true, section: "Data"}
  step_3_data_processing: {present: true, section: "Preprocess"}
  step_4_in_sample: {present: true, section: "In-sample"}
```

- [ ] **Step 2: Write the integration test**

Create `tests/integration/test_spec_e2e.py`:

```python
"""End-to-end test: pipeline ingests a fixture repo with .plutus/, runs through
the extract stage (loads + adapts the v2 manifest), and emits a plan.json
identical-in-shape to what the LLM extractor would have produced.

Does NOT exercise build/execute/compare — those need Docker. This test verifies
the spec→adapter→pipeline integration.
"""
from pathlib import Path
from unittest.mock import MagicMock

from plutus_verify.config import Config
from plutus_verify.ingest import IngestResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline


_FIXTURE = Path(__file__).parent / "fixtures" / "spec_v2_minimal"


def test_spec_e2e_extract_only(tmp_path: Path, monkeypatch):
    # Stub ingest to return the fixture repo unmodified
    from plutus_verify import pipeline as pipeline_mod

    fake_meta = tmp_path / "meta.json"
    fake_meta.write_text("{}")
    monkeypatch.setattr(
        pipeline_mod,
        "ingest",
        lambda *a, **kw: IngestResult(
            git_url=str(_FIXTURE),
            repo_path=_FIXTURE,
            readme_path=_FIXTURE / "README.md",
            commit_sha="0" * 40,
            branch="main",
            meta_path=fake_meta,
        ),
    )

    out = tmp_path / "out"
    inputs = PipelineInputs(
        source=str(_FIXTURE),
        out_dir=out,
        config=Config(),
        skip_clone=True,
        extract_only=True,
    )
    llm_client = MagicMock()
    llm_client.complete.side_effect = AssertionError("LLM must not be called")

    result = run_pipeline(
        inputs,
        llm_client=llm_client,
        builder=MagicMock(),
        runner=MagicMock(),
        vision=MagicMock(),
    )

    plan = result.plan
    assert plan.repo.name == "SpecV2Minimal"
    assert len(plan.steps) == 3
    step_ids = [s.id for s in plan.steps]
    assert step_ids == ["data_collection", "data_processing", "in_sample"]

    dc = plan.steps[0]
    assert dc.alternatives is not None and len(dc.alternatives) == 1
    assert dc.alternatives[0].kind == "manual_download"
    assert dc.alternatives[0].url == "https://example.com/raw.tar.gz"

    er = plan.expected_results[0]
    assert er.metrics[0].name == "sharpe_ratio"

    # plan.json was persisted
    assert (out / "plan.json").exists()
    llm_client.complete.assert_not_called()
```

- [ ] **Step 3: Run the integration test, expect PASS**

Run: `pytest tests/integration/test_spec_e2e.py -v`
Expected: 1 PASSED.

- [ ] **Step 4: Run the FULL suite to confirm no regressions**

Run: `pytest -v`
Expected: all PASSED. If any pre-existing test fails, investigate before committing — do NOT mark this task complete.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/fixtures/spec_v2_minimal tests/integration/test_spec_e2e.py
git commit -m "test(spec): integration test for v2 manifest → pipeline extract stage"
```

---

## Task 8: README addendum + v2 manifest example

**Files:**
- Modify: `README.md` (append a "v2 manifest preview" section)
- Create: `docs/plan/2026-05-20-plutus-spec-v2-foundation.md` already done — link from README

- [ ] **Step 1: Append a section to README.md**

Open the existing `README.md`. Use the Edit tool to append (after the existing `## Status` table — the file ends with the M5 row):

Find: `| M5 — Batch mode + CI polish | ◐ partial | \`--batch\` works; GitHub Action wrapper TBD |`

Append after that line (with a blank line separator) the following text — note that the YAML block uses real triple backticks (three backtick characters), not escaped ones:

```
## v2 manifest (preview)

Repos that ship a `.plutus/manifest.yaml` skip LLM extraction entirely — the
manifest IS the plan. See
[`docs/plan/2026-05-20-plutus-spec-v2-foundation.md`](docs/plan/2026-05-20-plutus-spec-v2-foundation.md)
for the foundation work.

A minimal manifest looks like:

[OPEN-FENCE]yaml
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.backtest"
    outputs: ["out/metrics.json"]
expected: []
nine_step_coverage: {}
[CLOSE-FENCE]

Authoring tools (`plutus init`, `plutus check`, `plutus snapshot`) land in Plan 3.
Native v2 execution (input/output pre-flight, data-tier resolver, full
reference-output comparator) lands in Plan 2.
```

When inserting into README.md, replace `[OPEN-FENCE]` and `[CLOSE-FENCE]` with literal triple backticks. The bracket placeholders only exist to escape the nested code block in this plan document.

- [ ] **Step 2: Verify README renders correctly**

Run: `head -200 README.md | tail -40`
Expected: the new section appears after `## Status`; the YAML block is enclosed by literal triple backticks (no brackets, no backslashes).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: preview the v2 manifest in README"
```

---

## Final verification

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: all tests pass (existing + new).

- [ ] **Step 2: Confirm new module structure**

Run: `ls plutus_verify/spec/`
Expected: `__init__.py adapter.py loader.py manifest.py schema.py validator.py`

- [ ] **Step 3: Confirm new tests exist**

Run: `ls tests/unit/test_spec_*.py tests/unit/test_pipeline_spec_detection.py tests/integration/test_spec_e2e.py`
Expected: all 6 files listed.

- [ ] **Step 4: Smoke-check the pipeline branch with a quick scripted check**

Run from the project root:

```bash
python - <<'PY'
from pathlib import Path
from plutus_verify.spec import load_manifest
from plutus_verify.spec.adapter import to_extracted_plan

m = load_manifest(Path("tests/integration/fixtures/spec_v2_minimal"))
p = to_extracted_plan(m)
print(f"OK: {p.repo.name} — {len(p.steps)} steps, {len(p.extraction_notes)} adapter notes")
for n in p.extraction_notes:
    print(f"  note: {n}")
PY
```

Expected: prints `OK: SpecV2Minimal — 3 steps, …` and one or more adapter notes about inputs being dropped.

---

## Out of scope for this plan (deferred)

- **`plutus init` / `plutus check` / `plutus snapshot` scaffold commands** → Plan 3
- **Generated `.github/workflows/plutus.yml`** → Plan 3
- **Env-to-Dockerfile generator** (replaces `repo2docker` call in `build/`) → Plan 2
- **Native input/output pre-flight in `execute.py`** → Plan 2
- **Data-tier resolver in execute** (today: only raw → alternatives mapping) → Plan 2
- **`reference_outputs` comparator for `json_numeric_tolerance` and `byte_exact`** → Plan 2
- **`plutus transfer` for legacy repos** → Plan 4
- **Deletion of `extract/plan.py` and the legacy `ExtractedPlan` dataclasses** → Plan 4

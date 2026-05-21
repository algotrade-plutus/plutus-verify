# Plutus v2 Spec — Native Execution (Plan 2 of 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement native v2 execution: a parallel pipeline path that consumes a v2 `Manifest` directly through build/execute/compare — no adapter, no v1 plumbing. The existing v1 path stays in place; Plan 4 will retire it.

**Architecture:** New `plutus_verify/spec/runtime/` subpackage holds the native v2 modules (dockerfile generator, data-tier resolver, I/O preflight, reference-output comparators, orchestrator). The pipeline detects `.plutus/manifest.yaml` and routes the build/execute/compare stages to the new code. Existing v1 modules are untouched.

**Tech Stack:** Python 3.11+, existing deps (`pyyaml`, `jsonschema`, `gdown`, `docker`, `pillow`). No new deps for v1 of the data-tier resolver — Google Drive support reuses `fetch.py`; S3/github_release use stdlib `urllib` for tarball downloads. Plan 3's CLI will add `boto3` if needed.

**Spec reference:** [/Users/dan/.claude/plans/hmm-okay-i-think-wondrous-sundae.md](/Users/dan/.claude/plans/hmm-okay-i-think-wondrous-sundae.md), Plan 1 finished at [docs/plan/2026-05-20-plutus-spec-v2-foundation.md](2026-05-20-plutus-spec-v2-foundation.md)

---

## Architectural decisions (recorded)

1. **Native path, not adapter upgrade.** Plan 2 builds a separate `spec/runtime/` package; the v1 build/execute/compare are untouched. Pipeline routes by manifest presence. Trade-off: a few hundred lines of duplication for clear separation while v1 still exists.
2. **Dockerfile template, not a Dockerfile per repo.** The generator emits a deterministic Dockerfile from `env: {base, python_version, os_packages, requirements_file, gpu_required}`. No author-supplied Dockerfile permitted.
3. **Data-tier resolver is in-process, not a CLI.** Tries `data_sources.processed` entries first (which can satisfy multiple steps), then `raw`. Falls through to running the step command if nothing succeeds. Reuses `fetch.py`'s Google Drive downloader for `kind: google_drive`; uses `urllib` for `github_release` and direct-`http`; S3 is unsupported in Plan 2 (emits a warning and falls through).
4. **Reference output comparators:** three rules in this plan — `json_numeric_tolerance`, `byte_exact`, `visual_similarity` (delegates to existing `compare/charts.py`).
5. **Preflight asserts existence**, not contents. Inputs must exist before run; declared outputs must exist after. Output-shape validation (e.g., minimum file size, JSON schema) is out of scope for Plan 2.
6. **No GPU support in v1 of Dockerfile generator.** `gpu_required: true` triggers a `NotImplementedError` with a clear "deferred to Plan 2.5" message. Authors with GPU pipelines fall back to the legacy `extract/` path until then.

---

## File Structure

**New package** — `plutus_verify/spec/runtime/`:
- `__init__.py` — public surface (`run_v2_pipeline`, `V2RuntimeResult`)
- `dockerfile_gen.py` — `generate_dockerfile(env: Env, secrets: tuple[Secret, ...]) -> str`
- `data_resolver.py` — tier resolution + downloads; emits per-step `DataTierResult`
- `preflight.py` — `assert_inputs_present(step, repo_path)`, `assert_outputs_present(step, repo_path)`
- `refcompare.py` — `compare_reference_output(ref: ReferenceOutput, expected_path, produced_path, vision_client)`
- `orchestrator.py` — `run_v2_pipeline(manifest, repo_path, runner, vision, …) -> V2RuntimeResult`

**Tests** — `tests/unit/`:
- `test_runtime_dockerfile_gen.py`
- `test_runtime_data_resolver.py`
- `test_runtime_preflight.py`
- `test_runtime_refcompare.py`
- `test_runtime_orchestrator.py`
- `test_pipeline_routes_v2_runtime.py`

**Integration** — `tests/integration/`:
- `test_v2_runtime_e2e.py` — exercises orchestrator with fakes for runner+vision

**Modified files:**
- `plutus_verify/pipeline.py` — route to `run_v2_pipeline` when `inputs.spec_manifest is not None`

---

## Task 1: Dockerfile generator

**Files:**
- Create: `plutus_verify/spec/runtime/__init__.py` (initially just package marker)
- Create: `plutus_verify/spec/runtime/dockerfile_gen.py`
- Test: `tests/unit/test_runtime_dockerfile_gen.py`

- [ ] **Step 1: Create package marker**

Create `plutus_verify/spec/runtime/__init__.py` with one-line docstring:

```python
"""Native v2 execution: build, run, compare directly from Manifest (no adapter)."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_runtime_dockerfile_gen.py`:

```python
"""Tests for the v2 Dockerfile generator."""
import pytest

from plutus_verify.spec.manifest import Env, Secret
from plutus_verify.spec.runtime.dockerfile_gen import (
    UnsupportedEnvError,
    generate_dockerfile,
)


def _minimal_env() -> Env:
    return Env(base="python", python_version="3.11", requirements_file="requirements.txt")


def test_generates_minimal_dockerfile():
    df = generate_dockerfile(_minimal_env(), secrets=())
    assert "FROM python:3.11-slim" in df
    assert "WORKDIR /srv/repo" in df
    assert "COPY requirements.txt ." in df
    assert "pip install --no-cache-dir -r requirements.txt" in df
    assert "COPY . ." in df


def test_includes_os_packages_layer():
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        os_packages=("build-essential", "libpq-dev"),
    )
    df = generate_dockerfile(env, secrets=())
    assert "apt-get update" in df
    assert "build-essential libpq-dev" in df


def test_omits_apt_layer_when_no_os_packages():
    df = generate_dockerfile(_minimal_env(), secrets=())
    assert "apt-get" not in df


def test_omits_requirements_layer_when_unset():
    env = Env(base="python", python_version="3.11", requirements_file=None)
    df = generate_dockerfile(env, secrets=())
    assert "requirements.txt" not in df
    assert "pip install" not in df


def test_gpu_required_raises_unsupported():
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        gpu_required=True,
    )
    with pytest.raises(UnsupportedEnvError, match="GPU.*Plan 2.5"):
        generate_dockerfile(env, secrets=())


def test_base_python_cuda_raises_unsupported():
    env = Env(base="python-cuda", python_version="3.11", requirements_file="requirements.txt")
    with pytest.raises(UnsupportedEnvError, match="python-cuda"):
        generate_dockerfile(env, secrets=())


def test_deterministic_output():
    """Same input → byte-identical Dockerfile, so image hash is stable."""
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        os_packages=("libpq-dev", "build-essential"),
    )
    df1 = generate_dockerfile(env, secrets=())
    df2 = generate_dockerfile(env, secrets=())
    assert df1 == df2
    # os_packages sorted to keep determinism even if input order varies
    env_reordered = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        os_packages=("build-essential", "libpq-dev"),
    )
    df3 = generate_dockerfile(env_reordered, secrets=())
    assert df1 == df3
```

- [ ] **Step 3: Run test, expect ImportError**

Run: `source .venv/bin/activate && pytest tests/unit/test_runtime_dockerfile_gen.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Implement the generator**

Create `plutus_verify/spec/runtime/dockerfile_gen.py`:

```python
"""Generate a deterministic Dockerfile from a v2 manifest's Env block.

The Dockerfile shape is fixed by the standard. Authors do not write Dockerfiles
in the v2 world; they declare env and we emit the build. This module mirrors
``plutus_verify.build.dockerfile`` but consumes the v2 ``Env`` directly.
"""
from __future__ import annotations

from plutus_verify.spec.manifest import Env, Secret


class UnsupportedEnvError(NotImplementedError):
    """Raised when an Env asks for capability not yet implemented."""


def generate_dockerfile(env: Env, *, secrets: tuple[Secret, ...] = ()) -> str:
    if env.gpu_required:
        raise UnsupportedEnvError(
            "env.gpu_required=true is not supported in Plan 2 — deferred to Plan 2.5"
        )
    if env.base == "python-cuda":
        raise UnsupportedEnvError(
            "env.base=python-cuda not supported in Plan 2 — deferred to Plan 2.5"
        )
    if env.base == "none":
        raise UnsupportedEnvError("env.base=none not supported (no base image)")

    _ = secrets  # reserved for future use (e.g., build-time env)

    lines: list[str] = [
        f"FROM python:{env.python_version}-slim",
        "WORKDIR /srv/repo",
    ]
    if env.os_packages:
        joined = " ".join(sorted(set(env.os_packages)))
        lines.extend(
            [
                "RUN apt-get update \\",
                f"    && apt-get install -y --no-install-recommends {joined} \\",
                "    && rm -rf /var/lib/apt/lists/*",
            ]
        )
    if env.requirements_file:
        lines.extend(
            [
                f"COPY {env.requirements_file} .",
                f"RUN pip install --no-cache-dir -r {env.requirements_file}",
            ]
        )
    lines.extend(
        [
            "COPY . .",
            'CMD ["python", "--version"]',
        ]
    )
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Run tests, expect PASS**

Run: `source .venv/bin/activate && pytest tests/unit/test_runtime_dockerfile_gen.py -v`
Expected: 7 PASSED.

- [ ] **Step 6: Commit**

```bash
git add plutus_verify/spec/runtime/__init__.py plutus_verify/spec/runtime/dockerfile_gen.py tests/unit/test_runtime_dockerfile_gen.py
git commit -m "feat(spec/runtime): native Dockerfile generator from v2 Env"
```

---

## Task 2: Data-tier resolver

**Files:**
- Create: `plutus_verify/spec/runtime/data_resolver.py`
- Test: `tests/unit/test_runtime_data_resolver.py`

Resolver behavior:
- Walks `manifest.data_sources.processed` first; if a source succeeds (all `expected_layout` files appear), marks every step in `satisfies` as `satisfied_by_download`.
- Then walks `manifest.data_sources.raw` for any step not yet satisfied.
- Anything not satisfied falls through — caller runs the step command.
- Downloader dispatch by `kind`: `google_drive` reuses `fetch.py`; `github_release` and `http` use `urllib` + tarball/zip extraction; `s3` and unknown kinds → log a warning and skip the source.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_runtime_data_resolver.py`:

```python
"""Tests for the v2 data-tier resolver."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.manifest import DataSource, DataSourceTiers, Manifest
from plutus_verify.spec.runtime.data_resolver import (
    DataTierResolution,
    DataTierResult,
    resolve_data_tiers,
)


def _manifest_with_sources(processed=(), raw=()) -> Manifest:
    from plutus_verify.spec.manifest import Env, Repo, Step
    return Manifest(
        schema_version="2.0",
        repo=Repo(name="T", primary_language="python"),
        env=Env(base="python", python_version="3.11", requirements_file="r.txt"),
        secrets=(),
        data_sources=DataSourceTiers(processed=tuple(processed), raw=tuple(raw)),
        steps=(
            Step(id="data_collection", nine_step="step_2_data_collection", required=True, command="echo c"),
            Step(id="data_processing", nine_step="step_3_data_processing", required=True, command="echo p"),
            Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="echo b"),
        ),
        expected=(),
    )


def test_no_data_sources_marks_nothing_satisfied(tmp_path):
    m = _manifest_with_sources()
    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=lambda *a, **kw: False)
    assert res.satisfied == frozenset()
    assert res.tier_used == "code"


def test_processed_satisfies_multiple_steps(tmp_path):
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    m = _manifest_with_sources(processed=(ds,))

    def fake_dl(source, target_dir):
        (target_dir / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (target_dir / "data" / "processed" / "x").write_text("ok")
        return True

    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=fake_dl)
    assert res.satisfied == frozenset({"data_collection", "data_processing"})
    assert res.tier_used == "processed"


def test_raw_satisfies_one_step_when_processed_unavailable(tmp_path):
    raw_ds = DataSource(
        kind="github_release",
        url="https://github.com/x/y/raw.tar.gz",
        expected_layout=("data/raw/x",),
        satisfies=("data_collection",),
    )
    m = _manifest_with_sources(raw=(raw_ds,))

    def fake_dl(source, target_dir):
        (target_dir / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (target_dir / "data" / "raw" / "x").write_text("ok")
        return True

    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=fake_dl)
    assert res.satisfied == frozenset({"data_collection"})
    assert res.tier_used == "raw"


def test_processed_falls_through_to_raw_on_failure(tmp_path):
    proc = DataSource(
        kind="s3",  # unsupported
        url="s3://x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    raw = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/raw/x",),
        satisfies=("data_collection",),
    )
    m = _manifest_with_sources(processed=(proc,), raw=(raw,))

    def fake_dl(source, target_dir):
        if source.kind == "s3":
            return False
        (target_dir / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (target_dir / "data" / "raw" / "x").write_text("ok")
        return True

    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=fake_dl)
    assert res.satisfied == frozenset({"data_collection"})
    assert res.tier_used == "raw"


def test_layout_already_present_counts_as_satisfied(tmp_path):
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "processed" / "x").write_text("ok")
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    m = _manifest_with_sources(processed=(ds,))

    downloader = MagicMock(return_value=False)
    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=downloader)
    assert res.satisfied == frozenset({"data_collection", "data_processing"})
    downloader.assert_not_called()


def test_force_tier_code_skips_all_downloads(tmp_path):
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    m = _manifest_with_sources(processed=(ds,))
    downloader = MagicMock(return_value=True)
    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=downloader, force_tier="code")
    assert res.satisfied == frozenset()
    assert res.tier_used == "code"
    downloader.assert_not_called()
```

- [ ] **Step 2: Run, expect ImportError**

Run: `source .venv/bin/activate && pytest tests/unit/test_runtime_data_resolver.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `plutus_verify/spec/runtime/data_resolver.py`:

```python
"""Tiered data acquisition: processed > raw > run the code.

Resolver is downloader-agnostic — the caller injects a downloader callable
that returns True/False per attempted source. The default downloader (built
below) reuses fetch.py for Google Drive and urllib for plain HTTP / github
release tarballs. S3 is not implemented in Plan 2.
"""
from __future__ import annotations

import logging
import shutil
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from plutus_verify.spec.manifest import DataSource, Manifest

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataTierResult:
    satisfied: frozenset[str]
    tier_used: Literal["processed", "raw", "code"]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataTierResolution:  # placeholder alias retained for forward-compat
    pass


Downloader = Callable[[DataSource, Path], bool]


def resolve_data_tiers(
    manifest: Manifest,
    *,
    repo_path: Path,
    downloader: Downloader,
    force_tier: Optional[Literal["processed", "raw", "code"]] = None,
) -> DataTierResult:
    notes: list[str] = []
    if force_tier == "code":
        return DataTierResult(
            satisfied=frozenset(), tier_used="code", notes=("forced --data-tier=code",)
        )

    satisfied: set[str] = set()
    tier_used: Literal["processed", "raw", "code"] = "code"

    if force_tier in (None, "processed"):
        for ds in manifest.data_sources.processed:
            if _layout_present(repo_path, ds.expected_layout):
                notes.append(f"processed/{ds.kind}: layout already present")
                satisfied.update(ds.satisfies)
                tier_used = "processed"
                continue
            try:
                ok = downloader(ds, repo_path)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"processed/{ds.kind} failed: {exc}")
                continue
            if ok and _layout_present(repo_path, ds.expected_layout):
                notes.append(f"processed/{ds.kind}: downloaded")
                satisfied.update(ds.satisfies)
                tier_used = "processed"

    if force_tier in (None, "raw"):
        for ds in manifest.data_sources.raw:
            if set(ds.satisfies).issubset(satisfied):
                continue
            if _layout_present(repo_path, ds.expected_layout):
                notes.append(f"raw/{ds.kind}: layout already present")
                satisfied.update(ds.satisfies)
                if tier_used == "code":
                    tier_used = "raw"
                continue
            try:
                ok = downloader(ds, repo_path)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"raw/{ds.kind} failed: {exc}")
                continue
            if ok and _layout_present(repo_path, ds.expected_layout):
                notes.append(f"raw/{ds.kind}: downloaded")
                satisfied.update(ds.satisfies)
                if tier_used == "code":
                    tier_used = "raw"

    return DataTierResult(satisfied=frozenset(satisfied), tier_used=tier_used, notes=tuple(notes))


def _layout_present(repo_path: Path, expected_layout: tuple[str, ...]) -> bool:
    if not expected_layout:
        return False
    for entry in expected_layout:
        if any(ch in entry for ch in "*?["):
            if not any(True for _ in repo_path.glob(entry.rstrip("/"))):
                return False
        else:
            if not (repo_path / entry).exists():
                return False
    return True


def default_downloader(source: DataSource, target_dir: Path) -> bool:
    """Built-in downloader. Dispatches by ``source.kind``."""
    kind = source.kind
    if kind == "google_drive":
        return _download_google_drive(source.url, target_dir)
    if kind in ("github_release", "http"):
        return _download_url_archive(source.url, target_dir)
    if kind == "s3":
        _log.warning("s3 downloader is not implemented in Plan 2; skipping %s", source.url)
        return False
    _log.warning("unknown data-source kind %r; skipping %s", kind, source.url)
    return False


def _download_google_drive(url: str, target_dir: Path) -> bool:
    try:
        from plutus_verify.fetch import _default_gdown_file, _default_gdown_folder
    except ImportError:
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        if "/folders/" in url:
            _default_gdown_folder(url, output=str(target_dir))
        else:
            _default_gdown_file(url, output=str(target_dir))
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("gdown failed for %s: %s", url, exc)
        return False


def _download_url_archive(url: str, target_dir: Path) -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / Path(url).name
    try:
        with urllib.request.urlopen(url) as resp, archive_path.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as exc:  # noqa: BLE001
        _log.warning("download failed for %s: %s", url, exc)
        return False
    suffix = "".join(archive_path.suffixes).lower()
    try:
        if suffix.endswith(".tar.gz") or suffix.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(target_dir)
        elif suffix.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(target_dir)
        else:
            return True  # raw file download — no extraction
    except Exception as exc:  # noqa: BLE001
        _log.warning("archive extraction failed for %s: %s", archive_path, exc)
        return False
    return True
```

- [ ] **Step 4: Run, expect PASS**

Run: `source .venv/bin/activate && pytest tests/unit/test_runtime_data_resolver.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/spec/runtime/data_resolver.py tests/unit/test_runtime_data_resolver.py
git commit -m "feat(spec/runtime): tiered data-source resolver"
```

---

## Task 3: Input/output preflight

**Files:**
- Create: `plutus_verify/spec/runtime/preflight.py`
- Test: `tests/unit/test_runtime_preflight.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_runtime_preflight.py`:

```python
"""Tests for v2 input/output preflight."""
from pathlib import Path

import pytest

from plutus_verify.spec.manifest import Step
from plutus_verify.spec.runtime.preflight import (
    PreflightError,
    assert_inputs_present,
    assert_outputs_present,
)


def _step(inputs=(), outputs=()) -> Step:
    return Step(
        id="s1",
        nine_step="step_4_in_sample",
        required=True,
        command="echo x",
        inputs=inputs,
        outputs=outputs,
    )


def test_inputs_present_passes_when_all_exist(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.parquet").write_text("ok")
    s = _step(inputs=("data",))
    assert_inputs_present(s, tmp_path)  # no raise


def test_inputs_glob_passes_when_at_least_one_match(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.parquet").write_text("ok")
    s = _step(inputs=("data/*.parquet",))
    assert_inputs_present(s, tmp_path)


def test_inputs_raises_when_missing(tmp_path):
    s = _step(inputs=("data/x.parquet",))
    with pytest.raises(PreflightError, match="missing input"):
        assert_inputs_present(s, tmp_path)


def test_outputs_present_passes_when_all_exist(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "m.json").write_text("{}")
    s = _step(outputs=("out/m.json",))
    assert_outputs_present(s, tmp_path)


def test_outputs_glob_passes_when_at_least_one_match(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.png").write_text("x")
    (tmp_path / "out" / "b.png").write_text("y")
    s = _step(outputs=("out/*.png",))
    assert_outputs_present(s, tmp_path)


def test_outputs_raises_when_missing_after_run(tmp_path):
    s = _step(outputs=("out/m.json",))
    with pytest.raises(PreflightError, match="missing output"):
        assert_outputs_present(s, tmp_path)


def test_empty_inputs_and_outputs_pass(tmp_path):
    s = _step()
    assert_inputs_present(s, tmp_path)
    assert_outputs_present(s, tmp_path)
```

- [ ] **Step 2: Run, expect ImportError**

Run: `source .venv/bin/activate && pytest tests/unit/test_runtime_preflight.py -v`

- [ ] **Step 3: Implement**

Create `plutus_verify/spec/runtime/preflight.py`:

```python
"""Pre- and post-execution existence checks for declared inputs/outputs."""
from __future__ import annotations

from pathlib import Path

from plutus_verify.spec.manifest import Step


class PreflightError(RuntimeError):
    """A declared input was missing before a step, or an output after."""


def assert_inputs_present(step: Step, repo_path: Path) -> None:
    missing = [p for p in step.inputs if not _path_matches(repo_path, p)]
    if missing:
        raise PreflightError(
            f"step '{step.id}' missing input(s) before run: {missing}"
        )


def assert_outputs_present(step: Step, repo_path: Path) -> None:
    missing = [p for p in step.outputs if not _path_matches(repo_path, p)]
    if missing:
        raise PreflightError(
            f"step '{step.id}' missing output(s) after run: {missing}"
        )


def _path_matches(repo_path: Path, entry: str) -> bool:
    if any(ch in entry for ch in "*?["):
        return any(True for _ in repo_path.glob(entry.rstrip("/")))
    return (repo_path / entry).exists()
```

- [ ] **Step 4: Run, expect PASS**

Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/spec/runtime/preflight.py tests/unit/test_runtime_preflight.py
git commit -m "feat(spec/runtime): input/output preflight checks"
```

---

## Task 4: Reference-output comparator

**Files:**
- Create: `plutus_verify/spec/runtime/refcompare.py`
- Test: `tests/unit/test_runtime_refcompare.py`

Three comparators in this plan:
- `json_numeric_tolerance` — JSON dicts, deep-walk, numeric values within relative tolerance (default 0.05); non-numeric values byte-equal.
- `byte_exact` — file bytes identical.
- `visual_similarity` — delegates to existing `compare/charts.py` LLM judge.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_runtime_refcompare.py`:

```python
"""Tests for v2 reference-output comparators."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.manifest import ReferenceOutput
from plutus_verify.spec.runtime.refcompare import (
    CompareResult,
    compare_reference_output,
)


def test_byte_exact_pass(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("hello")
    ref = ReferenceOutput(path="a", compare="byte_exact")
    r = compare_reference_output(ref, expected_path=a, produced_path=b, vision_client=None)
    assert r.ok and r.kind == "byte_exact"


def test_byte_exact_fail(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("world")
    ref = ReferenceOutput(path="a", compare="byte_exact")
    r = compare_reference_output(ref, expected_path=a, produced_path=b, vision_client=None)
    assert not r.ok
    assert "bytes differ" in r.detail


def test_json_numeric_tolerance_pass_within_tolerance(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"sharpe": 0.85, "n_trades": 100}))
    prod.write_text(json.dumps({"sharpe": 0.86, "n_trades": 100}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok


def test_json_numeric_tolerance_fail_outside_tolerance(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"sharpe": 0.85}))
    prod.write_text(json.dumps({"sharpe": 1.20}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert not r.ok
    assert "sharpe" in r.detail


def test_json_numeric_tolerance_handles_nested(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"outer": {"inner": 1.0}}))
    prod.write_text(json.dumps({"outer": {"inner": 1.04}}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok


def test_json_numeric_tolerance_byte_equal_strings(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"name": "foo"}))
    prod.write_text(json.dumps({"name": "bar"}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert not r.ok
    assert "name" in r.detail


def test_visual_similarity_calls_vision_client(tmp_path: Path):
    exp = tmp_path / "e.png"
    prod = tmp_path / "p.png"
    exp.write_bytes(b"\x89PNG\r\n\x1a\n")
    prod.write_bytes(b"\x89PNG\r\n\x1a\n")
    vc = MagicMock()
    vc.match.return_value = MagicMock(score=0.85, match=True, reason="similar")
    ref = ReferenceOutput(path="p.png", compare="visual_similarity", threshold=0.7)
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=vc)
    assert r.ok
    vc.match.assert_called_once()


def test_missing_files_fail_gracefully(tmp_path: Path):
    ref = ReferenceOutput(path="ghost.json", compare="byte_exact")
    r = compare_reference_output(
        ref, expected_path=tmp_path / "ghost.json", produced_path=tmp_path / "ghost.json", vision_client=None
    )
    assert not r.ok
    assert "not found" in r.detail
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

Create `plutus_verify/spec/runtime/refcompare.py`:

```python
"""Comparators for v2 reference outputs.

Three kinds, each dispatched on ``ReferenceOutput.compare``:
  - json_numeric_tolerance: deep-walk JSON; numeric values within relative
    tolerance (default 5%); non-numeric must be byte-equal.
  - byte_exact: file bytes identical.
  - visual_similarity: delegates to existing chart-similarity vision client.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from plutus_verify.spec.manifest import ReferenceOutput

DEFAULT_RELATIVE_TOLERANCE = 0.05


@dataclass(frozen=True)
class CompareResult:
    ok: bool
    kind: str
    detail: str = ""


def compare_reference_output(
    ref: ReferenceOutput,
    *,
    expected_path: Path,
    produced_path: Path,
    vision_client: Optional[Any],
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> CompareResult:
    if not expected_path.exists():
        return CompareResult(ok=False, kind=ref.compare, detail=f"expected file not found: {expected_path}")
    if not produced_path.exists():
        return CompareResult(ok=False, kind=ref.compare, detail=f"produced file not found: {produced_path}")

    if ref.compare == "byte_exact":
        return _byte_exact(expected_path, produced_path)
    if ref.compare == "json_numeric_tolerance":
        return _json_numeric(expected_path, produced_path, relative_tolerance)
    if ref.compare == "visual_similarity":
        return _visual_similarity(ref, expected_path, produced_path, vision_client)
    return CompareResult(ok=False, kind=ref.compare, detail=f"unknown compare kind: {ref.compare}")


def _byte_exact(expected: Path, produced: Path) -> CompareResult:
    if expected.read_bytes() == produced.read_bytes():
        return CompareResult(ok=True, kind="byte_exact")
    return CompareResult(ok=False, kind="byte_exact", detail=f"bytes differ ({expected.name} vs {produced.name})")


def _json_numeric(expected: Path, produced: Path, tol: float) -> CompareResult:
    try:
        exp = json.loads(expected.read_text())
        prod = json.loads(produced.read_text())
    except json.JSONDecodeError as e:
        return CompareResult(ok=False, kind="json_numeric_tolerance", detail=f"invalid JSON: {e}")
    diffs: list[str] = []
    _walk(exp, prod, "", tol, diffs)
    if diffs:
        return CompareResult(
            ok=False, kind="json_numeric_tolerance", detail="; ".join(diffs[:5])
        )
    return CompareResult(ok=True, kind="json_numeric_tolerance")


def _walk(exp: Any, prod: Any, path: str, tol: float, diffs: list[str]) -> None:
    if isinstance(exp, dict) and isinstance(prod, dict):
        for k in exp:
            sub = f"{path}.{k}" if path else k
            if k not in prod:
                diffs.append(f"missing key {sub}")
                continue
            _walk(exp[k], prod[k], sub, tol, diffs)
        return
    if isinstance(exp, list) and isinstance(prod, list):
        if len(exp) != len(prod):
            diffs.append(f"{path} length {len(prod)} != expected {len(exp)}")
            return
        for i, (e, p) in enumerate(zip(exp, prod)):
            _walk(e, p, f"{path}[{i}]", tol, diffs)
        return
    if isinstance(exp, bool) or isinstance(prod, bool):
        if exp != prod:
            diffs.append(f"{path}: {prod!r} != {exp!r}")
        return
    if isinstance(exp, (int, float)) and isinstance(prod, (int, float)):
        if exp == 0:
            if abs(prod) > tol:
                diffs.append(f"{path}: {prod} not within ±{tol} of 0")
            return
        if abs(prod - exp) / abs(exp) > tol:
            diffs.append(f"{path}: {prod} not within ±{tol * 100:.0f}% of {exp}")
        return
    if exp != prod:
        diffs.append(f"{path}: {prod!r} != {exp!r}")


def _visual_similarity(
    ref: ReferenceOutput,
    expected: Path,
    produced: Path,
    vision_client: Optional[Any],
) -> CompareResult:
    if vision_client is None:
        return CompareResult(ok=False, kind="visual_similarity", detail="vision_client required")
    threshold = ref.threshold or 0.7
    try:
        match = vision_client.match(
            reference_image_path=expected,
            produced_image_path=produced,
            threshold=threshold,
        )
    except Exception as exc:  # noqa: BLE001
        return CompareResult(ok=False, kind="visual_similarity", detail=str(exc))
    if getattr(match, "match", False):
        return CompareResult(ok=True, kind="visual_similarity", detail=getattr(match, "reason", ""))
    return CompareResult(
        ok=False,
        kind="visual_similarity",
        detail=f"score={getattr(match, 'score', 'n/a')}: {getattr(match, 'reason', '')}",
    )
```

- [ ] **Step 4: Run, expect PASS**

Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/spec/runtime/refcompare.py tests/unit/test_runtime_refcompare.py
git commit -m "feat(spec/runtime): reference-output comparators (json/byte/visual)"
```

---

## Task 5: Native v2 orchestrator

**Files:**
- Create: `plutus_verify/spec/runtime/orchestrator.py`
- Test: `tests/unit/test_runtime_orchestrator.py`

The orchestrator chains: build (gen Dockerfile, build image) → for each step (preflight inputs, skip if `satisfied_by_download`, run via `Runner`, preflight outputs) → for each `expected` block (compare headlines + reference_outputs) → emit a `V2RuntimeResult`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_runtime_orchestrator.py`:

```python
"""Tests for the native v2 orchestrator."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.loader import load_manifest_from_yaml_text
from plutus_verify.spec.runtime.orchestrator import V2RuntimeResult, run_v2_pipeline


_YAML = """\
schema_version: "2.0"
repo: {name: T, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    command: "echo data"
    outputs: ["data/raw/x"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo backtest"
    inputs: [data/raw]
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    headlines:
      - name: sharpe
        value: 0.85
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []
nine_step_coverage: {}
"""


def _stage_repo(tmp_path: Path):
    """Pre-create files the steps' inputs/outputs check expects."""
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "x").write_text("ok")
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.86}')


def test_runtime_runs_all_steps_and_compares_headlines(tmp_path):
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)
    image_builder = MagicMock(return_value="built-image-tag")
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1,
    )

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert isinstance(result, V2RuntimeResult)
    assert result.image == "built-image-tag"
    image_builder.assert_called_once()
    assert runner.run.call_count == 2  # data_collection + in_sample
    assert result.headline_results["in_sample"]["sharpe"].ok


def test_runtime_skips_steps_satisfied_by_data_source(tmp_path):
    _stage_repo(tmp_path)
    yaml = _YAML.replace(
        "data_sources: {processed: [], raw: []}",
        """data_sources:
  processed: []
  raw:
    - kind: github_release
      url: https://example.com/raw.tar.gz
      expected_layout: ["data/raw/x"]
      satisfies: [data_collection]""",
    )
    manifest = load_manifest_from_yaml_text(yaml)
    image_builder = MagicMock(return_value="img")
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
        downloader=lambda *a, **kw: True,  # pretend download succeeds
    )

    # data_collection skipped → only in_sample ran
    assert runner.run.call_count == 1
    assert result.data_tier_used == "raw"


def test_runtime_propagates_step_failure(tmp_path):
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)
    runner = MagicMock()
    # data_collection fails — in_sample should still be attempted? Per design,
    # downstream steps that declare it as depends_on skip. With no depends_on,
    # in_sample runs anyway. The orchestrator records the failure but does not
    # raise — it surfaces in `result.step_results`.
    runner.run.side_effect = [
        MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1),
        MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1),
    ]

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert result.step_results["data_collection"].exit_code == 1
    assert result.step_results["in_sample"].exit_code == 0


def test_runtime_preflight_failure_marks_step_skipped(tmp_path):
    """If input is missing AND not satisfied by a data source, step should
    surface a clear preflight error in step_results."""
    # in_sample needs data/raw but we don't pre-stage it
    manifest = load_manifest_from_yaml_text(_YAML)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    # data_collection has no inputs, runs OK; outputs missing → preflight failure post-run
    dc = result.step_results["data_collection"]
    assert dc.preflight_error is not None
    assert "missing output" in dc.preflight_error
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

Create `plutus_verify/spec/runtime/orchestrator.py`:

```python
"""Native v2 pipeline: build → execute → compare, consuming a Manifest directly.

No adapter to v1 plumbing. Mirrors the v1 pipeline shape but consumes
``plutus_verify.spec.manifest.Manifest`` end-to-end. Designed to be called from
``run_pipeline`` when ``.plutus/manifest.yaml`` is present.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.spec.manifest import Manifest, Step
from plutus_verify.spec.runtime.data_resolver import (
    DataSource,
    DataTierResult,
    default_downloader,
    resolve_data_tiers,
)
from plutus_verify.spec.runtime.dockerfile_gen import generate_dockerfile
from plutus_verify.spec.runtime.preflight import (
    PreflightError,
    assert_inputs_present,
    assert_outputs_present,
)
from plutus_verify.spec.runtime.refcompare import (
    CompareResult,
    compare_reference_output,
)


@dataclass
class StepRuntimeResult:
    step_id: str
    exit_code: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    skipped_reason: Optional[str] = None
    preflight_error: Optional[str] = None


@dataclass
class HeadlineResult:
    name: str
    ok: bool
    actual: Any
    expected: Any
    detail: str = ""


@dataclass
class V2RuntimeResult:
    image: str
    data_tier_used: str
    step_results: dict[str, StepRuntimeResult] = field(default_factory=dict)
    headline_results: dict[str, dict[str, HeadlineResult]] = field(default_factory=dict)
    reference_results: dict[str, list[CompareResult]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


ImageBuilder = Callable[[str, Path], str]  # (dockerfile_text, repo_path) -> image_tag
Runner = Any  # duck-typed: .run(image=, command=, cwd=, network=, timeout_seconds=, env=)


def run_v2_pipeline(
    manifest: Manifest,
    *,
    repo_path: Path,
    image_builder: ImageBuilder,
    runner: Runner,
    vision_client: Optional[Any],
    secrets: dict[str, str],
    downloader: Optional[Callable[[DataSource, Path], bool]] = None,
    force_data_tier: Optional[str] = None,
    expected_dir: Optional[Path] = None,
) -> V2RuntimeResult:
    dockerfile = generate_dockerfile(manifest.env, secrets=manifest.secrets)
    image = image_builder(dockerfile, repo_path)

    tier = resolve_data_tiers(
        manifest,
        repo_path=repo_path,
        downloader=downloader or default_downloader,
        force_tier=force_data_tier,
    )

    result = V2RuntimeResult(image=image, data_tier_used=tier.tier_used)
    result.notes.extend(tier.notes)

    expected_root = expected_dir or (repo_path / ".plutus" / "expected")

    for step in _topo_sort(manifest.steps):
        sr = _run_step(
            step,
            image=image,
            repo_path=repo_path,
            runner=runner,
            secrets=secrets,
            satisfied=tier.satisfied,
        )
        result.step_results[step.id] = sr

    for er in manifest.expected:
        result.headline_results[er.step_id] = _compare_headlines(er, repo_path)
        result.reference_results[er.step_id] = _compare_refs(
            er, repo_path, expected_root, vision_client
        )

    return result


def _topo_sort(steps: tuple[Step, ...]) -> list[Step]:
    by_id = {s.id: s for s in steps}
    out: list[Step] = []
    seen: set[str] = set()

    def visit(sid: str) -> None:
        if sid in seen:
            return
        for dep in by_id[sid].depends_on:
            if dep in by_id:
                visit(dep)
        seen.add(sid)
        out.append(by_id[sid])

    for s in steps:
        visit(s.id)
    return out


def _run_step(
    step: Step,
    *,
    image: str,
    repo_path: Path,
    runner: Runner,
    secrets: dict[str, str],
    satisfied: frozenset[str],
) -> StepRuntimeResult:
    if step.id in satisfied:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=0,
            duration_seconds=0.0,
            skipped_reason="satisfied_by_data_source",
        )
    try:
        assert_inputs_present(step, repo_path)
    except PreflightError as exc:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=-1,
            duration_seconds=0.0,
            preflight_error=str(exc),
        )
    if not step.command:
        return StepRuntimeResult(
            step_id=step.id,
            exit_code=-1,
            duration_seconds=0.0,
            preflight_error=f"step '{step.id}' has no command and is not satisfied by a data source",
        )

    exec_result = runner.run(
        image=image,
        command=step.command,
        cwd=repo_path,
        network=step.network,
        timeout_seconds=step.timeout_seconds,
        env=secrets,
    )
    sr = StepRuntimeResult(
        step_id=step.id,
        exit_code=getattr(exec_result, "exit_code", -1),
        duration_seconds=getattr(exec_result, "duration_seconds", 0.0),
        stdout=getattr(exec_result, "stdout", ""),
        stderr=getattr(exec_result, "stderr", ""),
    )
    if sr.exit_code == 0:
        try:
            assert_outputs_present(step, repo_path)
        except PreflightError as exc:
            sr.preflight_error = str(exc)
    return sr


def _compare_headlines(er, repo_path: Path) -> dict[str, "HeadlineResult"]:
    out: dict[str, HeadlineResult] = {}
    for h in er.headlines:
        try:
            actual = _locate_value(h.locate, repo_path)
            ok, detail = _within_tolerance(actual, h.value, h.tolerance)
            out[h.name] = HeadlineResult(name=h.name, ok=ok, actual=actual, expected=h.value, detail=detail)
        except Exception as exc:  # noqa: BLE001
            out[h.name] = HeadlineResult(
                name=h.name, ok=False, actual=None, expected=h.value, detail=str(exc)
            )
    return out


def _locate_value(locate, repo_path: Path) -> Any:
    if locate.kind == "json_file" and locate.path and locate.jsonpath:
        from jsonpath_ng import parse as _parse_jsonpath

        data = json.loads((repo_path / locate.path).read_text())
        expr = _parse_jsonpath(locate.jsonpath)
        matches = [m.value for m in expr.find(data)]
        if not matches:
            raise KeyError(f"no match for jsonpath {locate.jsonpath} in {locate.path}")
        return matches[0]
    raise NotImplementedError(f"locate kind {locate.kind} not supported in Plan 2")


def _within_tolerance(actual: Any, expected: Any, tol) -> tuple[bool, str]:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if tol.kind == "exact":
            return actual == expected, "" if actual == expected else f"{actual} != {expected}"
        if tol.kind == "absolute":
            ok = abs(actual - expected) <= tol.value
            return ok, "" if ok else f"|{actual} - {expected}| > {tol.value}"
        # relative
        if expected == 0:
            ok = abs(actual) <= tol.value
        else:
            ok = abs(actual - expected) / abs(expected) <= tol.value
        return ok, "" if ok else f"{actual} not within ±{tol.value * 100:.0f}% of {expected}"
    return actual == expected, "" if actual == expected else f"{actual!r} != {expected!r}"


def _compare_refs(er, repo_path: Path, expected_root: Path, vision_client) -> list[CompareResult]:
    out: list[CompareResult] = []
    for r in er.reference_outputs:
        expected_path = expected_root / er.step_id / r.path
        produced_path = repo_path / r.path
        out.append(
            compare_reference_output(
                r,
                expected_path=expected_path,
                produced_path=produced_path,
                vision_client=vision_client,
            )
        )
    return out
```

- [ ] **Step 4: Run, expect PASS**

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/spec/runtime/orchestrator.py tests/unit/test_runtime_orchestrator.py
git commit -m "feat(spec/runtime): native v2 orchestrator"
```

---

## Task 6: Wire pipeline to route v2 manifests through the native runtime

**Files:**
- Modify: `plutus_verify/pipeline.py` — replace the adapter-based v2 path with native runtime for build/execute/compare stages
- Modify: `plutus_verify/spec/runtime/__init__.py` — export public surface
- Test: `tests/unit/test_pipeline_routes_v2_runtime.py`

Current state (Plan 1): pipeline detects `.plutus/manifest.yaml`, loads via spec, **adapts to ExtractedPlan**, then runs through the existing build/execute/compare/report stages. Plan 2 keeps the same routing decision but, when a manifest is present, **uses `run_v2_pipeline`** to do build/execute/compare and synthesizes a final report identical in shape to the v1 one.

- [ ] **Step 1: Update `plutus_verify/spec/runtime/__init__.py`**

```python
"""Native v2 execution: build, run, compare directly from Manifest (no adapter)."""
from plutus_verify.spec.runtime.orchestrator import (
    HeadlineResult,
    StepRuntimeResult,
    V2RuntimeResult,
    run_v2_pipeline,
)

__all__ = [
    "HeadlineResult",
    "StepRuntimeResult",
    "V2RuntimeResult",
    "run_v2_pipeline",
]
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_pipeline_routes_v2_runtime.py`:

```python
"""When .plutus/manifest.yaml is present, the pipeline must use the native v2
runtime (no adapter, no LLM extract). Plan 2 routing test."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.config import Config
from plutus_verify.ingest import IngestResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline


_MIN = """\
schema_version: "2.0"
repo: {name: D, primary_language: python}
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


def test_pipeline_uses_native_v2_runtime_when_manifest_present(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# D")
    (repo / "out").mkdir()
    (repo / "out" / "metrics.json").write_text("{}")
    plutus = repo / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text(_MIN)

    from plutus_verify import pipeline as pmod

    monkeypatch.setattr(
        pmod, "ingest",
        lambda *a, **kw: IngestResult(
            git_url=str(repo), repo_path=repo, readme_path=repo / "README.md",
            commit_sha="0" * 40, branch="main", meta_path=tmp_path / "meta.json",
        ),
    )

    # Patch run_v2_pipeline to confirm it's called and to short-circuit
    sentinel = MagicMock()
    sentinel.image = "built-img"
    sentinel.data_tier_used = "code"
    sentinel.step_results = {}
    sentinel.headline_results = {}
    sentinel.reference_results = {}
    sentinel.notes = []
    fake_run_v2 = MagicMock(return_value=sentinel)
    monkeypatch.setattr(pmod, "run_v2_pipeline", fake_run_v2)

    llm = MagicMock()
    llm.complete.side_effect = AssertionError("LLM must not be called")

    inputs = PipelineInputs(
        source=str(repo), out_dir=tmp_path / "out", config=Config(),
        skip_clone=True,
    )
    result = run_pipeline(inputs, llm_client=llm, builder=MagicMock(), runner=MagicMock(), vision=MagicMock())

    fake_run_v2.assert_called_once()
    # Some sort of report should still be assembled — but the test only
    # checks routing here; the actual report-shape assertion is in the
    # integration test (Task 7).
```

- [ ] **Step 3: Run, expect FAIL** (pipeline doesn't yet have a `run_v2_pipeline` symbol to patch)

Run: `source .venv/bin/activate && pytest tests/unit/test_pipeline_routes_v2_runtime.py -v`

- [ ] **Step 4: Modify `pipeline.py`**

Find the v2 spec branch added in Plan 1 (look for `if spec_path.exists():` inside the extract stage). Replace its body to do this instead:
1. Load manifest (same as before)
2. **Skip adapter** — keep the manifest and stop the extract stage there (write a minimal `plan.json` placeholder for audit but do not produce an `ExtractedPlan`)
3. Set a new pipeline-state field `spec_manifest` for downstream stages to consume

Then, when reaching the build/execute/compare/report stages: if `spec_manifest` is set, call `run_v2_pipeline(...)` for build+execute+compare combined, then synthesize a `report.md`/`report.json` from `V2RuntimeResult`. Skip the legacy v1 build/execute/compare entirely.

The exact insertion points are:
- The extract stage (Plan 1's branch) — change behavior
- The build stage — add `if inputs._spec_manifest:` short-circuit that calls `run_v2_pipeline` and synthesizes downstream state
- The report stage — add a v2 result formatter (use the same `report.md` writer signature as v1 with a translation from `V2RuntimeResult`)

**Note to implementer:** this is the most invasive task in the plan. If the existing pipeline's structure makes this awkward (e.g., the build/execute/compare/report stages have intertwined state), **report DONE_WITH_CONCERNS or BLOCKED** rather than forcing it. The acceptable scope of this task: get the test in Step 2 passing without breaking any existing test. If full report synthesis is too hard, leave a `TODO(plan2-task6-report-synthesis)` comment in the new branch and have it produce a minimal `report.json` with the v2 result fields.

Add at the top of `pipeline.py`:
```python
from plutus_verify.spec.runtime import run_v2_pipeline, V2RuntimeResult
```

- [ ] **Step 5: Run new test, expect PASS**

Run: `source .venv/bin/activate && pytest tests/unit/test_pipeline_routes_v2_runtime.py -v`

- [ ] **Step 6: Run full suite — confirm no regressions**

Run: `source .venv/bin/activate && pytest -v 2>&1 | tail -5`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add plutus_verify/pipeline.py plutus_verify/spec/runtime/__init__.py tests/unit/test_pipeline_routes_v2_runtime.py
git commit -m "feat(pipeline): route v2 manifests to native runtime instead of adapter"
```

---

## Task 7: Integration test — full v2 path with stubbed runner

**Files:**
- Create: `tests/integration/test_v2_runtime_e2e.py`

This test exercises `run_v2_pipeline` end-to-end with a real fixture manifest and stubbed runner+vision. It complements Task 6's unit-level routing test.

- [ ] **Step 1: Write the test**

Create `tests/integration/test_v2_runtime_e2e.py`:

```python
"""End-to-end test of the native v2 runtime against the spec_v2_minimal fixture."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime import V2RuntimeResult, run_v2_pipeline


_FIXTURE = Path(__file__).parent / "fixtures" / "spec_v2_minimal"


def test_v2_runtime_end_to_end(tmp_path):
    manifest = load_manifest(_FIXTURE)

    # Copy fixture repo to tmp_path so the test can mutate output dirs
    import shutil
    work = tmp_path / "repo"
    shutil.copytree(_FIXTURE, work)

    # Pre-stage all outputs declared by steps (since we stub the runner)
    (work / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (work / "data" / "raw" / "x.parquet").write_text("ok")
    (work / "data" / "processed").mkdir(parents=True, exist_ok=True)
    (work / "data" / "processed" / "x.parquet").write_text("ok")
    (work / "out").mkdir(parents=True, exist_ok=True)
    (work / "out" / "metrics.json").write_text('{"sharpe": 0.86}')

    image_builder = MagicMock(return_value="fixture-image")
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=work,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
        downloader=lambda *a, **kw: False,  # no downloads — force code path
    )

    assert isinstance(result, V2RuntimeResult)
    assert result.image == "fixture-image"
    assert result.data_tier_used == "code"
    # 3 steps in fixture, all should have an entry in step_results
    assert set(result.step_results.keys()) == {"data_collection", "data_processing", "in_sample"}
    # headline should pass (0.86 is within ±5% of 0.85)
    assert result.headline_results["in_sample"]["sharpe_ratio"].ok
```

- [ ] **Step 2: Run, expect PASS**

Run: `source .venv/bin/activate && pytest tests/integration/test_v2_runtime_e2e.py -v`
Expected: 1 PASSED.

- [ ] **Step 3: Full suite check**

Run: `source .venv/bin/activate && pytest -v 2>&1 | tail -5`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_v2_runtime_e2e.py
git commit -m "test(spec/runtime): integration test for native v2 pipeline"
```

---

## Final verification

- [ ] **Run full suite:** `source .venv/bin/activate && pytest -v 2>&1 | tail -10`
- [ ] **Confirm structure:** `ls plutus_verify/spec/runtime/` — expect 6 files (`__init__.py`, `dockerfile_gen.py`, `data_resolver.py`, `preflight.py`, `refcompare.py`, `orchestrator.py`)
- [ ] **Smoke-check the orchestrator with the fixture:**

```bash
source .venv/bin/activate && python - <<'PY'
from pathlib import Path
from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime import run_v2_pipeline
from unittest.mock import MagicMock

m = load_manifest(Path("tests/integration/fixtures/spec_v2_minimal"))
runner = MagicMock()
runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
result = run_v2_pipeline(
    m, repo_path=Path("tests/integration/fixtures/spec_v2_minimal"),
    image_builder=MagicMock(return_value="x"), runner=runner,
    vision_client=None, secrets={}, downloader=lambda *a, **kw: False,
)
print(f"OK: tier={result.data_tier_used}, steps={list(result.step_results)}")
PY
```

## Out of scope (deferred)

- GPU support (`env.gpu_required`, `env.base=python-cuda`) → Plan 2.5
- S3 downloader → Plan 2.5
- Real Docker build invocation (image_builder is callable-injected; the actual `docker build` wiring happens in Plan 3 when `plutus check` ships)
- `plutus check` / `plutus init` / `plutus snapshot` CLI → Plan 3
- Deleting the v2→v1 adapter and v1 ExtractedPlan path → Plan 4
- Synthesizing a full v1-compatible `report.md` from `V2RuntimeResult` — Task 6 leaves a minimal version with a TODO if needed; full parity comes when the legacy path is retired in Plan 4

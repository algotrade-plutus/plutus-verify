# Plutus v2 Spec — Scaffold CLI (Plan 3 of 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship the author-facing tooling: `plutus init` (scaffold `.plutus/manifest.yaml` + GitHub Actions workflow), `plutus check` (run the native v2 pipeline locally against a working copy), `plutus snapshot` (capture run outputs into `.plutus/expected/`).

**Architecture:** New `plutus_verify/scaffold/` subpackage holds the three commands' logic. The CLI in `plutus_verify/__main__.py` is refactored into a Click group, with the existing single-command behavior preserved as `plutus-verify verify <git_url>` (and the bare form for backward compatibility). New subcommands: `init`, `check`, `snapshot`.

**Tech Stack:** Click (already a dep). No new deps.

---

## Architectural decisions (recorded)

1. **CLI structure:** Click group with subcommands. The existing single-command behavior of `plutus-verify <git_url>` is preserved via Click's invoke-without-subcommand pattern (bare form falls through to `verify`).
2. **`plutus init` is non-interactive:** emits a TODO-marked template. Users open `.plutus/manifest.yaml` in their editor and fill it in. Interactive scaffolding is out of scope.
3. **`plutus check` uses the native v2 path:** calls `run_v2_pipeline` from Plan 2 with real `DockerRunner` and a real image builder. Same engine as the cloud verifier.
4. **`plutus snapshot` is opt-in copy-from-out:** runs `plutus check` first, then copies each step's declared `outputs:` into `.plutus/expected/<step_id>/`. No automatic capture of un-declared files.
5. **CI workflow:** `init` drops a `.github/workflows/plutus.yml` only when one doesn't already exist. Never overwrites.
6. **No README generation in Plan 3.** `plutus render-readme` is mentioned in the design spec but deferred.

---

## File Structure

**New package** — `plutus_verify/scaffold/`:
- `__init__.py` — exports `scaffold_init`, `scaffold_check`, `scaffold_snapshot`
- `init.py` — `scaffold_init(repo_path: Path, *, force: bool = False) -> InitResult`
- `check.py` — `scaffold_check(repo_path: Path, *, secrets, force_data_tier, ...) -> CheckResult`
- `snapshot.py` — `scaffold_snapshot(repo_path: Path, *, run_check_first: bool = True) -> SnapshotResult`
- `templates.py` — string constants for the manifest skeleton + workflow YAML

**Modified:**
- `plutus_verify/__main__.py` — refactor to Click group with `init`, `check`, `snapshot`, `verify` subcommands
- `pyproject.toml` — add `plutus = "plutus_verify.__main__:cli"` script alias

**Tests** — `tests/unit/`:
- `test_scaffold_init.py`
- `test_scaffold_check.py`
- `test_scaffold_snapshot.py`
- `test_cli_group.py`

---

## Task 1: Scaffold templates module

**Files:**
- Create: `plutus_verify/scaffold/__init__.py`
- Create: `plutus_verify/scaffold/templates.py`
- Test: `tests/unit/test_scaffold_templates.py`

- [ ] **Step 1: Create package marker**

`plutus_verify/scaffold/__init__.py`:
```python
"""Author-facing tooling: `plutus init` / `check` / `snapshot`."""
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_scaffold_templates.py`:

```python
"""Templates emitted by `plutus init`."""
import yaml

from plutus_verify.scaffold.templates import MANIFEST_SKELETON, WORKFLOW_YAML


def test_manifest_skeleton_is_valid_yaml():
    data = yaml.safe_load(MANIFEST_SKELETON)
    assert isinstance(data, dict)
    assert data["schema_version"] == "2.0"
    assert "repo" in data
    assert "env" in data
    assert "steps" in data
    assert "expected" in data


def test_manifest_skeleton_has_todo_markers():
    # Skeleton must guide authors with TODO markers, not leave silent empty fields
    assert "TODO" in MANIFEST_SKELETON


def test_manifest_skeleton_loads_via_load_manifest_from_yaml_text():
    """The skeleton must pass schema validation as-is, so authors can run
    `plutus check` and get a useful error pointing at their TODOs (not a
    schema-violation cliff)."""
    from plutus_verify.spec.loader import load_manifest_from_yaml_text

    m = load_manifest_from_yaml_text(MANIFEST_SKELETON)
    assert m.schema_version == "2.0"


def test_workflow_yaml_is_valid_github_actions():
    data = yaml.safe_load(WORKFLOW_YAML)
    assert data["name"] == "plutus reproducibility"
    assert "on" in data or True in data  # PyYAML maps "on:" to True sometimes; just check structure
    assert "jobs" in data
    assert "check" in data["jobs"]
```

- [ ] **Step 3: Run, expect FAIL**

`source .venv/bin/activate && pytest tests/unit/test_scaffold_templates.py -v`

- [ ] **Step 4: Implement templates**

Create `plutus_verify/scaffold/templates.py`:

```python
"""Static template strings emitted by `plutus init`."""
from __future__ import annotations

MANIFEST_SKELETON = """\
# Plutus v2 manifest. Fill in TODO markers, then `plutus check` locally.
schema_version: "2.0"

repo:
  name: TODO_repo_name
  primary_language: python

env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
  # os_packages: [build-essential]
  # gpu_required: false

secrets:
  # - key: TIINGO_API_KEY
  #   purpose: market data download
  #   used_by: [data_collection]

data_sources:
  processed: []
  raw: []
  # processed:
  #   - kind: google_drive
  #     url: https://drive.google.com/...
  #     expected_layout: ["data/processed/*.parquet"]
  #     satisfies: [data_collection, data_processing]

steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge          # TODO: 'none' if no network is needed
    timeout_seconds: 1800
    command: "TODO_python_module_to_collect_data"
    outputs: ["data/raw/"]   # TODO: list the exact file paths/globs
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "TODO_python_module_to_preprocess"
    inputs: [data/raw]
    outputs: ["data/processed/"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "TODO_python_module_to_backtest"
    inputs: [data/processed]
    outputs: ["out/metrics.json"]

expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.0           # TODO: replace with the value you got
        locate: {kind: json_file, path: "out/metrics.json", jsonpath: "$.sharpe"}
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []

nine_step_coverage:
  step_1_hypothesis: {present: true, section: "TODO"}
  step_2_data_collection: {present: true, section: "TODO"}
  step_3_data_processing: {present: true, section: "TODO"}
  step_4_in_sample: {present: true, section: "TODO"}
  step_5_optimization: {present: false, section: null}
  step_6_out_of_sample: {present: false, section: null}
  step_7_paper_trading: {present: false, section: null}
"""


WORKFLOW_YAML = """\
name: plutus reproducibility
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install plutus-verify
        run: pip install plutus-verify
      - name: Run reproducibility check
        run: plutus check --secrets-from-env
        env:
          # Add per-secret entries here; mirror your manifest's `secrets:` block.
          # TIINGO_API_KEY: ${{ secrets.TIINGO_API_KEY }}
          PLUTUS_PLACEHOLDER: ""
"""
```

- [ ] **Step 5: Run, expect PASS**

Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add plutus_verify/scaffold/__init__.py plutus_verify/scaffold/templates.py tests/unit/test_scaffold_templates.py
git commit -m "feat(scaffold): manifest skeleton + CI workflow templates"
```

---

## Task 2: `plutus init` implementation

**Files:**
- Create: `plutus_verify/scaffold/init.py`
- Test: `tests/unit/test_scaffold_init.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scaffold_init.py`:

```python
"""Tests for `plutus init`."""
from pathlib import Path

import pytest

from plutus_verify.scaffold.init import InitResult, scaffold_init


def test_init_creates_manifest_and_workflow(tmp_path: Path):
    res = scaffold_init(tmp_path)
    assert isinstance(res, InitResult)
    assert (tmp_path / ".plutus" / "manifest.yaml").exists()
    assert (tmp_path / ".github" / "workflows" / "plutus.yml").exists()
    assert (tmp_path / ".plutus" / "expected").is_dir()
    assert res.created_manifest is True
    assert res.created_workflow is True


def test_init_does_not_overwrite_existing_manifest(tmp_path: Path):
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text("# my custom manifest\n")
    res = scaffold_init(tmp_path)
    assert res.created_manifest is False
    assert (plutus / "manifest.yaml").read_text() == "# my custom manifest\n"


def test_init_does_not_overwrite_existing_workflow(tmp_path: Path):
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "plutus.yml").write_text("# custom workflow\n")
    res = scaffold_init(tmp_path)
    assert res.created_workflow is False


def test_init_force_overwrites(tmp_path: Path):
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text("# old\n")
    res = scaffold_init(tmp_path, force=True)
    assert res.created_manifest is True
    assert "schema_version" in (plutus / "manifest.yaml").read_text()


def test_init_skeleton_is_loadable(tmp_path: Path):
    """After init, the manifest must pass schema validation so `plutus check`
    has a sensible starting state."""
    scaffold_init(tmp_path)
    from plutus_verify.spec.loader import load_manifest

    m = load_manifest(tmp_path)
    assert m.schema_version == "2.0"
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

Create `plutus_verify/scaffold/init.py`:

```python
"""`plutus init`: scaffold `.plutus/manifest.yaml` + `.github/workflows/plutus.yml`.

Non-interactive. Idempotent unless `force=True`. Never destroys existing files
without explicit consent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from plutus_verify.scaffold.templates import MANIFEST_SKELETON, WORKFLOW_YAML


@dataclass(frozen=True)
class InitResult:
    repo_path: Path
    created_manifest: bool
    created_workflow: bool
    created_expected_dir: bool


def scaffold_init(repo_path: Path, *, force: bool = False) -> InitResult:
    plutus_dir = repo_path / ".plutus"
    plutus_dir.mkdir(exist_ok=True)
    expected_dir = plutus_dir / "expected"
    created_expected = not expected_dir.exists()
    expected_dir.mkdir(exist_ok=True)

    manifest_path = plutus_dir / "manifest.yaml"
    created_manifest = False
    if force or not manifest_path.exists():
        manifest_path.write_text(MANIFEST_SKELETON)
        created_manifest = True

    workflow_dir = repo_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "plutus.yml"
    created_workflow = False
    if force or not workflow_path.exists():
        workflow_path.write_text(WORKFLOW_YAML)
        created_workflow = True

    return InitResult(
        repo_path=repo_path,
        created_manifest=created_manifest,
        created_workflow=created_workflow,
        created_expected_dir=created_expected,
    )
```

- [ ] **Step 4: Run, expect PASS**

5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/scaffold/init.py tests/unit/test_scaffold_init.py
git commit -m "feat(scaffold): plutus init"
```

---

## Task 3: `plutus check` implementation

**Files:**
- Create: `plutus_verify/scaffold/check.py`
- Test: `tests/unit/test_scaffold_check.py`

`scaffold_check(repo_path, ...)` loads the manifest, builds a Docker image via the existing builder, runs the native v2 pipeline, returns a `CheckResult` carrying the same `V2RuntimeResult` plus a render-ready summary.

The function takes injectable adapters (image_builder, runner, vision_client) for testability — production CLI wires real ones in Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scaffold_check.py`:

```python
"""Tests for `plutus check` (programmatic API)."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.check import CheckResult, scaffold_check
from plutus_verify.scaffold.init import scaffold_init


def test_check_returns_result_when_manifest_valid(tmp_path: Path):
    scaffold_init(tmp_path)
    # Pre-stage so the dummy run doesn't fail preflight
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="dummy-image"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert isinstance(res, CheckResult)
    assert res.runtime_result.image == "dummy-image"
    assert res.exit_code in (0, 1, 2)


def test_check_missing_manifest_raises(tmp_path: Path):
    from plutus_verify.spec.loader import ManifestLoadError

    with pytest.raises(ManifestLoadError):
        scaffold_check(
            tmp_path,
            image_builder=MagicMock(),
            runner=MagicMock(),
            vision_client=None,
            secrets={},
        )


def test_check_exit_code_zero_when_all_pass(tmp_path: Path):
    """All steps exit 0, metrics pass → exit 0."""
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert res.exit_code == 0


def test_check_exit_code_two_when_required_step_fails(tmp_path: Path):
    """A required step exits non-zero → exit 2."""
    scaffold_init(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)

    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1)
    res = scaffold_check(
        tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    assert res.exit_code == 2
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

Create `plutus_verify/scaffold/check.py`:

```python
"""`plutus check`: run the native v2 pipeline locally against a working copy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime import V2RuntimeResult, run_v2_pipeline


@dataclass(frozen=True)
class CheckResult:
    runtime_result: V2RuntimeResult
    exit_code: int


def scaffold_check(
    repo_path: Path,
    *,
    image_builder: Callable[[str, Path], str],
    runner: Any,
    vision_client: Optional[Any],
    secrets: dict[str, str],
    force_data_tier: Optional[str] = None,
) -> CheckResult:
    manifest = load_manifest(repo_path)
    runtime = run_v2_pipeline(
        manifest,
        repo_path=repo_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=vision_client,
        secrets=secrets,
        force_data_tier=force_data_tier,
    )
    return CheckResult(runtime_result=runtime, exit_code=_exit_code(manifest, runtime))


def _exit_code(manifest, runtime: V2RuntimeResult) -> int:
    """0 = all required steps + metrics pass; 1 = soft fail; 2 = required hard fail."""
    required_ids = {s.id for s in manifest.steps if s.required}

    for sid, sr in runtime.step_results.items():
        if sid in required_ids and sr.exit_code != 0 and sr.skipped_reason is None:
            return 2
        if sid in required_ids and sr.preflight_error is not None:
            return 2

    for step_id, hrs in runtime.metric_results.items():
        for name, hr in hrs.items():
            if not hr.ok:
                return 1
    for step_id, refs in runtime.reference_results.items():
        for r in refs:
            if not r.ok:
                return 1
    return 0
```

- [ ] **Step 4: Run, expect PASS**

4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/scaffold/check.py tests/unit/test_scaffold_check.py
git commit -m "feat(scaffold): plutus check programmatic API"
```

---

## Task 4: `plutus snapshot` implementation

**Files:**
- Create: `plutus_verify/scaffold/snapshot.py`
- Test: `tests/unit/test_scaffold_snapshot.py`

Snapshot copies each step's declared `outputs:` from the repo working copy into `.plutus/expected/<step_id>/`. By default runs `plutus check` first to make sure the outputs are fresh; `run_check_first=False` lets the author capture an existing successful run without re-running.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scaffold_snapshot.py`:

```python
"""Tests for `plutus snapshot`."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.init import scaffold_init
from plutus_verify.scaffold.snapshot import SnapshotResult, scaffold_snapshot


def _stage_repo(tmp_path: Path, with_outputs: bool = True):
    scaffold_init(tmp_path)
    if with_outputs:
        (tmp_path / "out").mkdir(exist_ok=True)
        (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.0}')
        (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "raw" / "x.parquet").write_text("ok")
        (tmp_path / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "processed" / "x.parquet").write_text("ok")


def test_snapshot_without_run_copies_existing_outputs(tmp_path: Path):
    _stage_repo(tmp_path)
    res = scaffold_snapshot(tmp_path, run_check_first=False)
    assert isinstance(res, SnapshotResult)
    expected_root = tmp_path / ".plutus" / "expected"
    assert (expected_root / "in_sample" / "out" / "metrics.json").exists()
    # The skeleton's data_* steps declare outputs ending in / (directory globs);
    # snapshot should copy whatever's there.
    assert res.files_copied >= 1


def test_snapshot_skips_missing_outputs_with_warning(tmp_path: Path):
    _stage_repo(tmp_path, with_outputs=False)
    res = scaffold_snapshot(tmp_path, run_check_first=False)
    # Nothing to copy → still returns, just files_copied=0 and notes mentions skipped
    assert res.files_copied == 0
    assert any("missing" in n.lower() for n in res.notes)


def test_snapshot_with_run_runs_check_first(tmp_path: Path):
    _stage_repo(tmp_path)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
    res = scaffold_snapshot(
        tmp_path,
        run_check_first=True,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )
    # check ran (image_builder called); snapshot copied
    assert res.check_result is not None
    assert res.files_copied >= 1


def test_snapshot_with_run_aborts_on_check_failure(tmp_path: Path):
    """If `plutus check` fails (required step non-zero), snapshot should not
    overwrite reference outputs from a failing run."""
    _stage_repo(tmp_path)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1)

    with pytest.raises(RuntimeError, match="check failed"):
        scaffold_snapshot(
            tmp_path,
            run_check_first=True,
            image_builder=MagicMock(return_value="img"),
            runner=runner,
            vision_client=None,
            secrets={},
        )
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

Create `plutus_verify/scaffold/snapshot.py`:

```python
"""`plutus snapshot`: capture step outputs into `.plutus/expected/`."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.scaffold.check import CheckResult, scaffold_check
from plutus_verify.spec.loader import load_manifest


@dataclass
class SnapshotResult:
    files_copied: int
    check_result: Optional[CheckResult]
    notes: list[str] = field(default_factory=list)


def scaffold_snapshot(
    repo_path: Path,
    *,
    run_check_first: bool = True,
    image_builder: Optional[Callable[[str, Path], str]] = None,
    runner: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    secrets: Optional[dict[str, str]] = None,
) -> SnapshotResult:
    manifest = load_manifest(repo_path)

    check_result: Optional[CheckResult] = None
    if run_check_first:
        if image_builder is None or runner is None:
            raise ValueError("run_check_first=True requires image_builder and runner")
        check_result = scaffold_check(
            repo_path,
            image_builder=image_builder,
            runner=runner,
            vision_client=vision_client,
            secrets=secrets or {},
        )
        if check_result.exit_code == 2:
            raise RuntimeError(
                "plutus check failed (exit 2 — required step failed); "
                "refusing to snapshot outputs from a failing run"
            )

    expected_root = repo_path / ".plutus" / "expected"
    expected_root.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []
    files_copied = 0
    for step in manifest.steps:
        step_dir = expected_root / step.id
        step_dir.mkdir(parents=True, exist_ok=True)
        for output in step.outputs:
            src = repo_path / output.rstrip("/")
            if not src.exists() and any(ch in output for ch in "*?["):
                matches = list(repo_path.glob(output.rstrip("/")))
                if not matches:
                    notes.append(f"step '{step.id}': output '{output}' missing — skipped")
                    continue
                for m in matches:
                    rel = m.relative_to(repo_path)
                    dest = step_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if m.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(m, dest)
                    else:
                        shutil.copy2(m, dest)
                    files_copied += 1
                continue
            if not src.exists():
                notes.append(f"step '{step.id}': output '{output}' missing — skipped")
                continue
            rel = Path(output.rstrip("/"))
            dest = step_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                files_copied += sum(1 for _ in dest.rglob("*") if _.is_file())
            else:
                shutil.copy2(src, dest)
                files_copied += 1

    return SnapshotResult(files_copied=files_copied, check_result=check_result, notes=notes)
```

- [ ] **Step 4: Run, expect PASS**

4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/scaffold/snapshot.py tests/unit/test_scaffold_snapshot.py
git commit -m "feat(scaffold): plutus snapshot"
```

---

## Task 5: Refactor CLI into a Click group

**Files:**
- Modify: `plutus_verify/__main__.py` — wrap existing command in a Click group with subcommands `init`, `check`, `snapshot`, `verify`
- Modify: `pyproject.toml` — add `plutus = "plutus_verify.__main__:cli"` script alias
- Test: `tests/unit/test_cli_group.py`

Strategy:
- Rename current `@click.command` function `main` → keep as `verify` subcommand
- Add new top-level `@click.group(invoke_without_command=True)` named `cli`
- The group's callback, when invoked without a subcommand and with positional args, forwards to `verify` for backward compat
- Add `init`, `check`, `snapshot` subcommands that delegate to `plutus_verify.scaffold.*`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli_group.py`:

```python
"""Tests for the refactored CLI group."""
from pathlib import Path

from click.testing import CliRunner

from plutus_verify.__main__ import cli


def test_cli_has_init_subcommand():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "check" in result.output
    assert "snapshot" in result.output


def test_init_subcommand_creates_files(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".plutus" / "manifest.yaml").exists()
    assert (tmp_path / ".github" / "workflows" / "plutus.yml").exists()


def test_check_subcommand_loads_manifest(tmp_path: Path, monkeypatch):
    """`plutus check` should load and validate the manifest, error if absent."""
    runner = CliRunner()
    result = runner.invoke(cli, ["check", str(tmp_path)])
    assert result.exit_code != 0
    assert "no .plutus/manifest.yaml" in result.output or "manifest" in result.output.lower()
```

- [ ] **Step 2: Run, expect FAIL** (no `cli` symbol or it's the old single command)

- [ ] **Step 3: Refactor `__main__.py`**

Open `plutus_verify/__main__.py`. The current single command is decorated with `@click.command`. Convert as follows:

1. Rename the current `main` function (the verify behavior) to `verify_cmd` and keep all its `@click.option` decorators
2. Add a new top-level group:

```python
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """plutus: reproducibility tooling."""
    if ctx.invoked_subcommand is None:
        click.echo(cli.get_help(ctx))


@cli.command("verify")
# ... existing @click.option decorators ...
def verify_cmd(...):
    # existing body
```

3. Add three new commands:

```python
@cli.command("init")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option("--force", is_flag=True, help="overwrite existing manifest/workflow")
def init_cmd(repo_path: Path, force: bool) -> None:
    from plutus_verify.scaffold.init import scaffold_init
    res = scaffold_init(Path(repo_path), force=force)
    click.echo(f"created manifest: {res.created_manifest}")
    click.echo(f"created workflow: {res.created_workflow}")


@cli.command("check")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option("--secrets-from-env", is_flag=True, help="use environment variables as secrets")
@click.option("--data-tier", type=click.Choice(["processed", "raw", "code", "auto"]), default="auto")
def check_cmd(repo_path: Path, secrets_from_env: bool, data_tier: str) -> None:
    import os
    from plutus_verify.scaffold.check import scaffold_check
    from plutus_verify.spec.loader import ManifestLoadError

    try:
        from plutus_verify.runner_docker import DockerRunner

        def real_image_builder(dockerfile_text: str, rp: Path) -> str:
            # TODO(plan3-task5-real-builder): wire to docker build via stdin.
            # For now this is a placeholder so plutus check can be invoked
            # against a fixture in CI without real docker.
            raise NotImplementedError(
                "real image_builder requires Docker; use programmatic API for tests"
            )

        secrets = dict(os.environ) if secrets_from_env else {}
        res = scaffold_check(
            Path(repo_path),
            image_builder=real_image_builder,
            runner=DockerRunner(),
            vision_client=None,
            secrets=secrets,
            force_data_tier=None if data_tier == "auto" else data_tier,
        )
    except ManifestLoadError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(2)
        return
    except NotImplementedError as exc:
        click.echo(f"not yet wired: {exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(3)
        return

    click.echo(f"image: {res.runtime_result.image}")
    click.echo(f"data tier: {res.runtime_result.data_tier_used}")
    for sid, sr in res.runtime_result.step_results.items():
        click.echo(f"  step {sid}: exit={sr.exit_code} skipped={sr.skipped_reason}")
    ctx = click.get_current_context()
    ctx.exit(res.exit_code)


@cli.command("snapshot")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option("--no-run", is_flag=True, help="don't run check first; snapshot existing outputs")
def snapshot_cmd(repo_path: Path, no_run: bool) -> None:
    from plutus_verify.scaffold.snapshot import scaffold_snapshot

    if not no_run:
        click.echo("error: running check before snapshot requires --no-run for now (real builder not wired)", err=True)
        ctx = click.get_current_context()
        ctx.exit(3)
        return
    res = scaffold_snapshot(Path(repo_path), run_check_first=False)
    click.echo(f"copied {res.files_copied} file(s) to .plutus/expected/")
    for n in res.notes:
        click.echo(f"  {n}")
```

4. The existing entrypoint `main` (referenced in `pyproject.toml` as `plutus-verify = "plutus_verify.__main__:main"`) keeps working — define it as:

```python
def main():
    """Backward-compatible bare entrypoint: same as `plutus verify ...`."""
    cli(args=sys.argv[1:], prog_name="plutus-verify", standalone_mode=True)
```

Wait — that calls cli but the existing CLI took positional `source` as the first arg. So `plutus-verify <git_url>` would now fail because `cli` is a group expecting a subcommand. To preserve backward compat:

```python
def main():
    """Backward-compatible: `plutus-verify <git_url>` → `plutus verify <git_url>`."""
    args = sys.argv[1:]
    # If first arg looks like a known subcommand, pass through; else inject 'verify'
    known = {"init", "check", "snapshot", "verify", "--help", "-h", "--version"}
    if args and args[0] not in known and not args[0].startswith("-"):
        args = ["verify"] + args
    cli(args=args, prog_name="plutus-verify", standalone_mode=True)
```

- [ ] **Step 4: Update pyproject.toml**

Add to `[project.scripts]`:
```toml
plutus = "plutus_verify.__main__:cli"
plutus-verify = "plutus_verify.__main__:main"
```

(Keep the existing `plutus-verify` line — just add the `plutus` one. The package needs reinstall: `pip install -e .` to pick up the new entrypoint, but tests use `click.testing.CliRunner` directly so this is only needed for shell usage.)

- [ ] **Step 5: Run new tests, expect PASS**

3 PASSED.

- [ ] **Step 6: Run full suite — no regressions**

Run: `source .venv/bin/activate && pytest -v 2>&1 | tail -5`
All pass.

- [ ] **Step 7: Commit**

```bash
git add plutus_verify/__main__.py pyproject.toml tests/unit/test_cli_group.py
git commit -m "feat(cli): plutus group with init/check/snapshot/verify subcommands"
```

---

## Final verification

- [ ] `source .venv/bin/activate && pytest -v 2>&1 | tail -5` — all green
- [ ] `ls plutus_verify/scaffold/` — 4 files (`__init__.py`, `init.py`, `check.py`, `snapshot.py`, `templates.py`)
- [ ] CLI help shows the new subcommands:
```bash
source .venv/bin/activate && python -m plutus_verify --help
```
- [ ] Init smoke test:
```bash
source .venv/bin/activate && python - <<'PY'
from pathlib import Path
import tempfile
from plutus_verify.scaffold.init import scaffold_init
with tempfile.TemporaryDirectory() as d:
    res = scaffold_init(Path(d))
    print(f"manifest={res.created_manifest} workflow={res.created_workflow}")
    print((Path(d) / ".plutus" / "manifest.yaml").read_text()[:200])
PY
```

## Out of scope (deferred)

- Real Docker image builder wired to `plutus check` (today raises `NotImplementedError(3)`). Wiring it requires the auto-fixing slim-Python build flow from `plutus_verify/build/runner.py` to accept a raw Dockerfile string. → Plan 4 or a follow-up.
- `plutus render-readme` → not in this plan; deferred per design spec.
- `plutus transfer` (legacy migrator) → Plan 4.
- Auto-detect manifest from cwd if no path given → trivial polish; not in this plan.

# Plutus v2 Spec — Legacy Transfer (Plan 4 of 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship `plutus transfer` — a low-friction migration tool that takes a legacy Plutus repo (README-based, no `.plutus/`) and emits a *draft* `.plutus/manifest.yaml.draft` for the author to hand-clean. Repurposes the existing LLM extractor (decompose + stitch) and converts its `ExtractedPlan` output to a v2 `Manifest` shape via a reverse adapter.

**Architecture:** New module `plutus_verify/scaffold/transfer.py` calls the existing LLM decompose + stitch pipeline (`plutus_verify.extract`) → gets an `ExtractedPlan` → converts to a draft v2 `Manifest` via a new `extract_to_v2.py` reverse adapter → writes `.plutus/manifest.yaml.draft` with `# TODO(plutus-transfer):` markers wherever the LLM was uncertain. The author edits the draft, renames it to `manifest.yaml`, then runs `plutus check`.

**Tech Stack:** Existing deps. No new ones.

**Why "draft":** The user's explicit framing of legacy transfer: "this can be later and can involve human so it's not urgent and the complexity for automating the whole process can be not very high." We don't promise lossless conversion — we promise a good starting point + clear TODOs.

---

## Architectural decisions (recorded)

1. **Reverse adapter is best-effort and TODO-marker-heavy.** Fields the LLM can fill confidently (commands, secrets, outputs, headline metrics) get copied directly. Fields the LLM can't infer (data sources, env os_packages, reference output files) get `null`/`[]` + TODO comments in the emitted YAML.
2. **Output goes to `.plutus/manifest.yaml.draft`, not `manifest.yaml`.** The `.draft` extension forces the author to consciously rename it, which is the explicit "I've reviewed this" gate. `plutus check` ignores `.draft` files.
3. **No new schema fields.** The v2 manifest format is locked. The transfer tool produces whatever can be produced; rest gets TODO.
4. **Doesn't delete `extract/plan.py` or related modules.** The transfer tool depends on them. Full v1-schema deletion is deferred to a future cleanup plan.
5. **Doesn't touch the existing pipeline's legacy branch.** Repos without `.plutus/` still run through the v1 LLM path as before. The transfer tool is the migration on-ramp, not a forced replacement.

---

## File Structure

**New module** — `plutus_verify/scaffold/`:
- `transfer.py` — `scaffold_transfer(repo_path, llm_client) -> TransferResult`
- `extract_to_v2.py` — `to_v2_manifest_yaml(plan: ExtractedPlan) -> str` (reverse adapter; emits YAML text with TODO markers)

**Modified:**
- `plutus_verify/__main__.py` — add `transfer` subcommand to the Click group
- `pyproject.toml` — no changes needed (existing `plutus` entry covers it)

**Tests** — `tests/unit/`:
- `test_extract_to_v2.py` — reverse adapter unit tests
- `test_scaffold_transfer.py` — programmatic API
- `test_cli_transfer.py` — CLI command

---

## Task 1: Reverse adapter (ExtractedPlan → draft YAML)

**Files:**
- Create: `plutus_verify/scaffold/extract_to_v2.py`
- Test: `tests/unit/test_extract_to_v2.py`

The reverse adapter emits YAML text directly (not a `Manifest` object) — that way TODO comments survive into the file the author edits. YAML is built as a string, not via `yaml.dump`, so we control comment placement.

Reverse-adapter mapping (each v1 field → v2 location, with TODO if uncertain):

| v1 `ExtractedPlan`                     | v2 `Manifest` YAML emitted                                          |
|----------------------------------------|---------------------------------------------------------------------|
| `repo.name`, `repo.primary_language`   | direct                                                              |
| `repo.env_setup.python_version`        | `env.python_version` (default `"3.11"` if missing)                  |
| `repo.env_setup.path`                  | `env.requirements_file`                                             |
| `repo.env_setup.kind == "dockerfile"`  | `env.base: TODO_python_version` + `# TODO: Dockerfile path was X`   |
| `repo.secrets_required[*]`             | `secrets[*]` (key/purpose/used_by)                                  |
| `steps[*]` with `alternatives` of `manual_download` | `data_sources.raw[*]` with `satisfies: [step.id]`      |
| `steps[*]` (everything else)           | `steps[*]` (id, nine_step, required, command, network, outputs from `produces`) |
| `steps[*]` (no `inputs` in v1)         | empty `inputs: []` + `# TODO: declare inputs`                      |
| `expected_results[*].metrics[*]`       | `expected[*].headlines[*]` (name, value, locate, tolerance)         |
| `expected_results[*].charts[*]`        | `expected[*].reference_outputs[*]` with `compare: visual_similarity` |
| `nine_step_mapping`                    | `nine_step_coverage` (drop confidence)                              |
| Anywhere LLM uncertain (low confidence on nine_step entries) | preserve as TODO comment           |

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_extract_to_v2.py`:

```python
"""Tests for the v1 → v2 reverse adapter (used by `plutus transfer`)."""
import yaml

from plutus_verify.extract.plan import (
    EnvSetup,
    ExpectedChart,
    ExpectedMetric,
    ExpectedResult,
    ExtractedPlan,
    Locate,
    NineStepEntry,
    Repo,
    SecretRequirement,
    Step,
    StepAlternative,
    Tolerance,
)
from plutus_verify.scaffold.extract_to_v2 import to_v2_manifest_yaml


def _minimal_plan() -> ExtractedPlan:
    return ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="Demo",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(SecretRequirement(key="API", purpose="data", step_ids=("data_collection",)),),
        ),
        nine_step_mapping={
            "step_1_hypothesis": NineStepEntry(present=True, section_heading="Hypothesis", confidence=0.9),
            "step_2_data_collection": NineStepEntry(present=True, section_heading="Data", confidence=0.95),
            "step_3_data_processing": NineStepEntry(present=False, section_heading=None, confidence=0.4),
            "step_4_in_sample": NineStepEntry(present=True, section_heading="Backtest", confidence=0.95),
            "step_5_optimization": NineStepEntry(present=False, section_heading=None, confidence=0.3),
            "step_6_out_of_sample": NineStepEntry(present=False, section_heading=None, confidence=0.2),
            "step_7_paper_trading": NineStepEntry(present=False, section_heading=None, confidence=0.1),
        },
        steps=(
            Step(
                id="data_collection",
                nine_step="step_2_data_collection",
                required=True,
                command="python -m demo.collect",
                produces=("data/raw/x.parquet",),
                network="bridge",
            ),
            Step(
                id="in_sample",
                nine_step="step_4_in_sample",
                required=True,
                command="python -m demo.backtest",
                produces=("out/metrics.json",),
            ),
        ),
        expected_results=(
            ExpectedResult(
                step_id="in_sample",
                metrics=(
                    ExpectedMetric(
                        name="sharpe_ratio",
                        value=0.85,
                        locate=Locate(kind="json_file", path="out/metrics.json", jsonpath="$.sharpe"),
                        tolerance=Tolerance(kind="relative", value=0.05),
                    ),
                ),
                charts=(),
            ),
        ),
    )


def test_emitted_yaml_is_parseable():
    """The draft must be valid YAML (TODO comments are allowed; YAML treats them as comments)."""
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    assert data["schema_version"] == "2.0"


def test_emitted_yaml_passes_v2_schema_validation():
    """A perfectly-extracted plan should yield a manifest that already validates,
    so authors can run `plutus check` against the draft (after renaming)."""
    from plutus_verify.spec.loader import load_manifest_from_yaml_text

    text = to_v2_manifest_yaml(_minimal_plan())
    m = load_manifest_from_yaml_text(text)
    assert m.repo.name == "Demo"
    assert len(m.steps) == 2
    assert m.steps[1].outputs == ("out/metrics.json",)


def test_emitted_yaml_has_todo_markers_for_inputs():
    """v1 has no `inputs:` field. The reverse adapter must emit `inputs: []`
    with a TODO comment per step prompting the author to declare them."""
    text = to_v2_manifest_yaml(_minimal_plan())
    assert "# TODO(plutus-transfer): declare inputs" in text


def test_emitted_yaml_translates_secrets():
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    assert any(s["key"] == "API" for s in data["secrets"])


def test_emitted_yaml_translates_metrics_to_headlines():
    text = to_v2_manifest_yaml(_minimal_plan())
    data = yaml.safe_load(text)
    er = data["expected"][0]
    assert er["step_id"] == "in_sample"
    assert er["headlines"][0]["name"] == "sharpe_ratio"
    assert er["headlines"][0]["value"] == 0.85


def test_emitted_yaml_translates_charts_to_visual_similarity():
    plan = _minimal_plan()
    # Add a chart
    plan = ExtractedPlan(
        schema_version=plan.schema_version,
        repo=plan.repo,
        nine_step_mapping=plan.nine_step_mapping,
        steps=plan.steps,
        expected_results=(
            ExpectedResult(
                step_id="in_sample",
                metrics=plan.expected_results[0].metrics,
                charts=(ExpectedChart(name="eq", produced_path="out/eq.png", reference_image=None),),
            ),
        ),
    )
    text = to_v2_manifest_yaml(plan)
    data = yaml.safe_load(text)
    er = data["expected"][0]
    assert er["reference_outputs"][0]["compare"] == "visual_similarity"
    assert er["reference_outputs"][0]["path"] == "out/eq.png"


def test_emitted_yaml_translates_manual_download_to_data_source():
    plan = _minimal_plan()
    # Add a manual_download alternative to data_collection
    new_steps = list(plan.steps)
    dc = new_steps[0]
    new_steps[0] = Step(
        id=dc.id,
        nine_step=dc.nine_step,
        required=dc.required,
        command=dc.command,
        network=dc.network,
        produces=dc.produces,
        alternatives=(
            StepAlternative(
                label="Google Drive",
                kind="manual_download",
                url="https://drive.google.com/x",
                expected_layout=("data/raw/x.parquet",),
            ),
        ),
    )
    plan = ExtractedPlan(
        schema_version=plan.schema_version,
        repo=plan.repo,
        nine_step_mapping=plan.nine_step_mapping,
        steps=tuple(new_steps),
        expected_results=plan.expected_results,
    )
    text = to_v2_manifest_yaml(plan)
    data = yaml.safe_load(text)
    assert len(data["data_sources"]["raw"]) == 1
    raw = data["data_sources"]["raw"][0]
    assert raw["url"] == "https://drive.google.com/x"
    assert raw["satisfies"] == ["data_collection"]


def test_emitted_yaml_marks_low_confidence_nine_steps():
    text = to_v2_manifest_yaml(_minimal_plan())
    # nine_step_3_data_processing was present=False; confidence 0.4 (low) → expect a TODO
    assert "TODO(plutus-transfer)" in text
```

- [ ] **Step 2: Run, expect FAIL**

`source .venv/bin/activate && pytest tests/unit/test_extract_to_v2.py -v`

- [ ] **Step 3: Implement the reverse adapter**

Create `plutus_verify/scaffold/extract_to_v2.py`:

```python
"""Reverse adapter: v1 ExtractedPlan → draft v2 manifest YAML text.

Used by `plutus transfer`. Best-effort; emits TODO markers wherever the v1
shape can't fully describe what v2 needs.
"""
from __future__ import annotations

from io import StringIO
from typing import TextIO

from plutus_verify.extract.plan import ExtractedPlan, Step, StepAlternative


_TODO_TAG = "# TODO(plutus-transfer):"


def to_v2_manifest_yaml(plan: ExtractedPlan) -> str:
    buf = StringIO()
    buf.write("# Draft v2 manifest produced by `plutus transfer`. Review TODOs,\n")
    buf.write("# rename to `manifest.yaml`, then run `plutus check`.\n")
    buf.write('schema_version: "2.0"\n\n')

    buf.write("repo:\n")
    buf.write(f"  name: {plan.repo.name}\n")
    buf.write(f"  primary_language: {plan.repo.primary_language}\n\n")

    _write_env(buf, plan)
    _write_secrets(buf, plan)
    _write_data_sources(buf, plan)
    _write_steps(buf, plan)
    _write_expected(buf, plan)
    _write_nine_step_coverage(buf, plan)

    return buf.getvalue()


def _write_env(buf: TextIO, plan: ExtractedPlan) -> None:
    env = plan.repo.env_setup
    buf.write("env:\n")
    if env.kind == "requirements_txt":
        buf.write("  base: python\n")
        buf.write(f"  python_version: \"{env.python_version or '3.11'}\"\n")
        if env.path:
            buf.write(f"  requirements_file: {env.path}\n")
    elif env.kind == "dockerfile":
        buf.write(f"  base: python  {_TODO_TAG} legacy used Dockerfile at {env.path}; reconstruct python_version and os_packages here\n")
        buf.write(f"  python_version: \"{env.python_version or '3.11'}\"\n")
        if env.path:
            buf.write(f"  requirements_file: requirements.txt  {_TODO_TAG} verify\n")
    else:
        buf.write(f"  base: python  {_TODO_TAG} v1 env kind was {env.kind!r}; choose v2 base\n")
        buf.write(f"  python_version: \"{env.python_version or '3.11'}\"\n")
    buf.write(f"  {_TODO_TAG} declare os_packages if your build needs apt-installed libs\n")
    buf.write("\n")


def _write_secrets(buf: TextIO, plan: ExtractedPlan) -> None:
    if not plan.repo.secrets_required:
        buf.write("secrets: []\n\n")
        return
    buf.write("secrets:\n")
    for s in plan.repo.secrets_required:
        buf.write(f"  - key: {s.key}\n")
        if s.purpose:
            buf.write(f"    purpose: {_yaml_str(s.purpose)}\n")
        if s.step_ids:
            buf.write(f"    used_by: [{', '.join(s.step_ids)}]\n")
    buf.write("\n")


def _write_data_sources(buf: TextIO, plan: ExtractedPlan) -> None:
    raw_entries: list[tuple[Step, StepAlternative]] = []
    for s in plan.steps:
        for alt in s.alternatives or ():
            if alt.kind == "manual_download" and alt.url:
                raw_entries.append((s, alt))

    buf.write("data_sources:\n")
    buf.write(f"  processed: []  {_TODO_TAG} list pre-processed download(s) (Tier 1) here if available\n")
    if not raw_entries:
        buf.write("  raw: []\n\n")
        return
    buf.write("  raw:\n")
    for s, alt in raw_entries:
        kind = "google_drive" if "drive.google.com" in alt.url else "http"
        buf.write(f"    - kind: {kind}\n")
        buf.write(f"      url: {alt.url}\n")
        if alt.expected_layout:
            buf.write(f"      expected_layout: [{', '.join(_yaml_str(p) for p in alt.expected_layout)}]\n")
        else:
            buf.write(f"      expected_layout: []  {_TODO_TAG} list expected files\n")
        buf.write(f"      satisfies: [{s.id}]\n")
    buf.write("\n")


def _write_steps(buf: TextIO, plan: ExtractedPlan) -> None:
    buf.write("steps:\n")
    for s in plan.steps:
        buf.write(f"  - id: {s.id}\n")
        buf.write(f"    nine_step: {s.nine_step}\n")
        buf.write(f"    required: {str(s.required).lower()}\n")
        if s.network != "none":
            buf.write(f"    network: {s.network}\n")
        if s.timeout_seconds and s.timeout_seconds != 1800:
            buf.write(f"    timeout_seconds: {s.timeout_seconds}\n")
        if s.command:
            buf.write(f"    command: {_yaml_str(s.command)}\n")
        buf.write(f"    inputs: []  {_TODO_TAG} declare inputs (files/dirs the step needs before run)\n")
        if s.produces:
            buf.write(f"    outputs: [{', '.join(_yaml_str(p) for p in s.produces)}]\n")
        else:
            buf.write(f"    outputs: []  {_TODO_TAG} declare outputs (files/dirs the step produces)\n")
        if s.depends_on:
            buf.write(f"    depends_on: [{', '.join(s.depends_on)}]\n")
    buf.write("\n")


def _write_expected(buf: TextIO, plan: ExtractedPlan) -> None:
    if not plan.expected_results:
        buf.write("expected: []\n\n")
        return
    buf.write("expected:\n")
    for er in plan.expected_results:
        buf.write(f"  - step_id: {er.step_id}\n")
        if er.metrics:
            buf.write("    headlines:\n")
            for m in er.metrics:
                buf.write(f"      - name: {m.name}\n")
                buf.write(f"        value: {m.value!r}\n")
                buf.write("        locate:\n")
                buf.write(f"          kind: {m.locate.kind}\n")
                if m.locate.path:
                    buf.write(f"          path: {_yaml_str(m.locate.path)}\n")
                if m.locate.jsonpath:
                    buf.write(f"          jsonpath: {_yaml_str(m.locate.jsonpath)}\n")
                if m.locate.row:
                    buf.write(f"          row: {_yaml_str(m.locate.row)}\n")
                if m.locate.col is not None:
                    buf.write(f"          col: {m.locate.col}\n")
                if m.locate.pattern:
                    buf.write(f"          pattern: {_yaml_str(m.locate.pattern)}\n")
                buf.write(f"        tolerance: {{kind: {m.tolerance.kind}, value: {m.tolerance.value}}}\n")
        else:
            buf.write("    headlines: []\n")
        if er.charts:
            buf.write("    reference_outputs:\n")
            for c in er.charts:
                buf.write(f"      - path: {_yaml_str(c.produced_path)}\n")
                buf.write("        compare: visual_similarity\n")
                buf.write(f"        threshold: 0.7  {_TODO_TAG} tune threshold\n")
        else:
            buf.write("    reference_outputs: []\n")
    buf.write("\n")


def _write_nine_step_coverage(buf: TextIO, plan: ExtractedPlan) -> None:
    buf.write("nine_step_coverage:\n")
    for k, entry in plan.nine_step_mapping.items():
        section = f'"{entry.section_heading}"' if entry.section_heading else "null"
        line = f"  {k}: {{present: {str(entry.present).lower()}, section: {section}}}"
        if entry.confidence < 0.6:
            line += f"  {_TODO_TAG} LLM uncertain (confidence={entry.confidence:.2f}); review"
        buf.write(line + "\n")


def _yaml_str(s: str) -> str:
    # Always double-quote so embedded special chars survive
    return '"' + s.replace('"', '\\"') + '"'
```

- [ ] **Step 4: Run, expect PASS**

7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/scaffold/extract_to_v2.py tests/unit/test_extract_to_v2.py
git commit -m "feat(scaffold): reverse adapter (v1 ExtractedPlan -> draft v2 YAML)"
```

---

## Task 2: `scaffold_transfer` programmatic API

**Files:**
- Create: `plutus_verify/scaffold/transfer.py`
- Test: `tests/unit/test_scaffold_transfer.py`

`scaffold_transfer(repo_path, llm_client)` runs the existing decompose+stitch pipeline against the repo's README, then calls the reverse adapter, and writes `.plutus/manifest.yaml.draft`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scaffold_transfer.py`:

```python
"""Tests for `plutus transfer` programmatic API."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.scaffold.transfer import (
    TransferError,
    TransferResult,
    scaffold_transfer,
)


def _write_readme(tmp_path: Path, content: str = "# Demo repo") -> None:
    (tmp_path / "README.md").write_text(content)


def test_transfer_writes_draft_manifest(tmp_path, monkeypatch):
    _write_readme(tmp_path)

    # Stub the extractor — return a minimal ExtractedPlan
    from plutus_verify.extract.plan import (
        EnvSetup,
        ExtractedPlan,
        NineStepEntry,
        Repo,
        Step,
    )

    plan = ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="Demo",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={
            f"step_{i}_{n}": NineStepEntry(present=True, section_heading=n, confidence=0.95)
            for i, n in enumerate(
                ["hypothesis", "data_collection", "data_processing", "in_sample", "optimization", "out_of_sample", "paper_trading"],
                start=1,
            )
        },
        steps=(
            Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="python a.py", produces=("out/m.json",)),
        ),
        expected_results=(),
    )

    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )

    res = scaffold_transfer(tmp_path, llm_client=MagicMock())

    draft_path = tmp_path / ".plutus" / "manifest.yaml.draft"
    assert draft_path.exists()
    assert "schema_version" in draft_path.read_text()
    assert isinstance(res, TransferResult)
    assert res.draft_path == draft_path


def test_transfer_does_not_overwrite_existing_manifest(tmp_path, monkeypatch):
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml").write_text("# already there\n")

    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: MagicMock(),
    )

    with pytest.raises(TransferError, match="manifest.yaml already exists"):
        scaffold_transfer(tmp_path, llm_client=MagicMock())


def test_transfer_missing_readme_raises(tmp_path):
    with pytest.raises(TransferError, match="README.md"):
        scaffold_transfer(tmp_path, llm_client=MagicMock())


def test_transfer_overwrites_existing_draft(tmp_path, monkeypatch):
    """A previous draft is replaced — that's the whole point of re-running transfer."""
    _write_readme(tmp_path)
    plutus = tmp_path / ".plutus"
    plutus.mkdir()
    (plutus / "manifest.yaml.draft").write_text("# stale draft\n")

    from plutus_verify.extract.plan import EnvSetup, ExtractedPlan, NineStepEntry, Repo

    plan = ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="Fresh",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={
            f"step_{i}_{n}": NineStepEntry(present=False, section_heading=None, confidence=0.5)
            for i, n in enumerate(
                ["hypothesis", "data_collection", "data_processing", "in_sample", "optimization", "out_of_sample", "paper_trading"],
                start=1,
            )
        },
        steps=(),
        expected_results=(),
    )
    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )

    scaffold_transfer(tmp_path, llm_client=MagicMock())
    content = (plutus / "manifest.yaml.draft").read_text()
    assert "Fresh" in content
    assert "stale draft" not in content
```

- [ ] **Step 2: Run, expect FAIL**

- [ ] **Step 3: Implement**

Create `plutus_verify/scaffold/transfer.py`:

```python
"""`plutus transfer`: convert a legacy README-based repo into a v2 draft manifest."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plutus_verify.extract import extract_plan
from plutus_verify.scaffold.extract_to_v2 import to_v2_manifest_yaml


class TransferError(RuntimeError):
    """Transfer cannot proceed (missing README, existing manifest, etc.)."""


@dataclass(frozen=True)
class TransferResult:
    draft_path: Path
    plan_summary: str


def scaffold_transfer(repo_path: Path, *, llm_client: Any) -> TransferResult:
    readme = repo_path / "README.md"
    if not readme.exists():
        raise TransferError(f"no README.md in {repo_path}")
    plutus_dir = repo_path / ".plutus"
    if (plutus_dir / "manifest.yaml").exists():
        raise TransferError(
            f"{plutus_dir / 'manifest.yaml'} already exists — refusing to overwrite. "
            "Delete it first if you want to re-transfer."
        )

    plan = extract_plan(readme.read_text(), llm_client)
    draft_yaml = to_v2_manifest_yaml(plan)

    plutus_dir.mkdir(exist_ok=True)
    draft_path = plutus_dir / "manifest.yaml.draft"
    draft_path.write_text(draft_yaml)

    summary = (
        f"transferred {plan.repo.name}: {len(plan.steps)} steps, "
        f"{sum(len(er.metrics) for er in plan.expected_results)} metrics"
    )
    return TransferResult(draft_path=draft_path, plan_summary=summary)
```

- [ ] **Step 4: Run, expect PASS**

4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add plutus_verify/scaffold/transfer.py tests/unit/test_scaffold_transfer.py
git commit -m "feat(scaffold): plutus transfer programmatic API"
```

---

## Task 3: `plutus transfer` CLI subcommand

**Files:**
- Modify: `plutus_verify/__main__.py` — add `transfer` subcommand to the Click group
- Test: `tests/unit/test_cli_transfer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli_transfer.py`:

```python
"""Tests for `plutus transfer` CLI subcommand."""
from pathlib import Path
from unittest.mock import MagicMock

from click.testing import CliRunner

from plutus_verify.__main__ import cli


def test_transfer_subcommand_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "transfer" in result.output


def test_transfer_missing_readme_errors(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["transfer", str(tmp_path)])
    assert result.exit_code != 0
    assert "README" in result.output


def test_transfer_writes_draft(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("# Demo")

    from plutus_verify.extract.plan import EnvSetup, ExtractedPlan, NineStepEntry, Repo

    plan = ExtractedPlan(
        schema_version="1.0",
        repo=Repo(
            name="DemoCLI",
            primary_language="python",
            env_setup=EnvSetup(kind="requirements_txt", path="requirements.txt", python_version="3.11"),
            secrets_required=(),
        ),
        nine_step_mapping={
            f"step_{i}_{n}": NineStepEntry(present=False, section_heading=None, confidence=0.5)
            for i, n in enumerate(
                ["hypothesis", "data_collection", "data_processing", "in_sample", "optimization", "out_of_sample", "paper_trading"],
                start=1,
            )
        },
        steps=(),
        expected_results=(),
    )
    monkeypatch.setattr(
        "plutus_verify.scaffold.transfer.extract_plan",
        lambda *a, **kw: plan,
    )
    # The CLI builds its own llm_client; we patch the constructor to a no-op
    monkeypatch.setattr(
        "plutus_verify.__main__.OpenAICompatClient",
        lambda *a, **kw: MagicMock(),
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["transfer", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".plutus" / "manifest.yaml.draft").exists()
```

- [ ] **Step 2: Run, expect FAIL** (no `transfer` subcommand yet)

- [ ] **Step 3: Add the subcommand to `plutus_verify/__main__.py`**

Add after the existing `snapshot_cmd`:

```python
@cli.command("transfer")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option(
    "--llm-endpoint",
    default="http://localhost:11434/v1",
    help="OpenAI-compatible endpoint for the LLM extractor",
    show_default=True,
)
@click.option("--llm-model", default="gemma4:26b", show_default=True)
def transfer_cmd(repo_path: Path, llm_endpoint: str, llm_model: str) -> None:
    """Convert a legacy README-based repo into a v2 draft manifest."""
    from plutus_verify.scaffold.transfer import TransferError, scaffold_transfer

    llm = OpenAICompatClient(endpoint=llm_endpoint, model=llm_model)
    try:
        res = scaffold_transfer(Path(repo_path), llm_client=llm)
    except TransferError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(2)
        return
    click.echo(f"wrote draft: {res.draft_path}")
    click.echo(res.plan_summary)
    click.echo("Next: review the TODO markers, then `mv .plutus/manifest.yaml.draft .plutus/manifest.yaml`")
```

If `OpenAICompatClient` isn't already imported at top of `__main__.py`, add the import (it should already be — used by the existing `verify` command).

- [ ] **Step 4: Run, expect PASS**

3 PASSED.

- [ ] **Step 5: Full suite — no regressions**

`source .venv/bin/activate && pytest -v 2>&1 | tail -5`

- [ ] **Step 6: Commit**

```bash
git add plutus_verify/__main__.py tests/unit/test_cli_transfer.py
git commit -m "feat(cli): plutus transfer subcommand"
```

---

## Task 4: Documentation — update README + final design note

**Files:**
- Modify: `README.md` — add a "Migrating a legacy repo" section
- Create: `docs/plan/2026-05-21-plutus-spec-v2-DONE.md` — short summary of the post-Plan-4 state + what's still deferred

- [ ] **Step 1: Append to README.md**

After the existing "v2 manifest (preview)" section, append:

```
## Migrating a legacy repo

For repos that already exist as v1 (README + LLM extraction), run:

[OPEN-FENCE]bash
plutus transfer /path/to/repo --llm-endpoint http://localhost:11434/v1
[CLOSE-FENCE]

This writes `.plutus/manifest.yaml.draft`. Open it, address every
`# TODO(plutus-transfer):` marker, rename to `manifest.yaml`, and run
`plutus check` to verify the migration.
```

Replace `[OPEN-FENCE]` / `[CLOSE-FENCE]` with actual triple backticks when inserting.

- [ ] **Step 2: Create the final design note**

Create `docs/plan/2026-05-21-plutus-spec-v2-DONE.md`:

```markdown
# Plutus v2 spec — Plans 1-4 complete

Four plans landed the v2 manifest format:

- **Plan 1** — foundation: `plutus_verify/spec/` (dataclasses, schema, loader,
  validator, adapter), pipeline branch on `.plutus/manifest.yaml`.
- **Plan 2** — native execution: `plutus_verify/spec/runtime/` (Dockerfile
  generator, data-tier resolver, I/O preflight, reference-output comparators,
  orchestrator). Pipeline routes v2 manifests to the native runtime.
- **Plan 3** — author CLI: `plutus_verify/scaffold/` (init/check/snapshot
  templates + commands), Click group restructure of `__main__.py`.
- **Plan 4** — legacy transfer: `plutus transfer` repurposes the LLM extractor
  to emit a draft v2 manifest for hand-cleaning.

## End-state architecture

```
plutus-verify <git_url>          # legacy LLM path (still works)
plutus init <repo_path>          # scaffold .plutus/manifest.yaml + CI workflow
plutus check <repo_path>         # native v2 verification (Plan 2 runtime)
plutus snapshot <repo_path>      # capture run outputs into .plutus/expected/
plutus transfer <repo_path>      # legacy README → draft v2 manifest
plutus verify <git_url>          # explicit equivalent of bare `plutus-verify <git_url>`
```

## Still deferred (not in any of these 4 plans)

- Real Docker `image_builder` wired to `plutus check` (today raises
  `NotImplementedError`; you must call `scaffold_check` programmatically with a
  custom builder for CI runs).
- Deletion of v1 `extract/plan.py` — the transfer tool depends on it; full
  schema retirement is a follow-up cleanup.
- The legacy "no manifest" pipeline branch in `pipeline.py` — still routes
  through LLM extract + v1 build/execute/compare for repos without `.plutus/`.
- GPU support (`env.gpu_required`, `env.base=python-cuda`).
- S3 downloader in the data-tier resolver.
- `plutus render-readme` (generate README from manifest).
- `plutus_verify` SDK for in-code instrumentation (`pv.headline(...)`,
  `pv.export_manifest()`).
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/plan/2026-05-21-plutus-spec-v2-DONE.md
git commit -m "docs: migration guide for legacy repos + Plans 1-4 wrap-up"
```

---

## Final verification

- [ ] `source .venv/bin/activate && pytest -v 2>&1 | tail -5` — all green
- [ ] `ls plutus_verify/scaffold/` — 7 files (`__init__.py`, `init.py`, `check.py`, `snapshot.py`, `templates.py`, `transfer.py`, `extract_to_v2.py`)
- [ ] CLI help shows `transfer`:
```bash
source .venv/bin/activate && python -m plutus_verify --help | grep transfer
```
- [ ] All branches surveyed: `git log --oneline main..HEAD | wc -l` — ~30 commits across 4 plans

## Out of scope (explicitly deferred to future work)

See `docs/plan/2026-05-21-plutus-spec-v2-DONE.md` "Still deferred" section.

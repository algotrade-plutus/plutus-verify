# Plutus v2 Spec — `plutus bootstrap` (Plan 9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** A new `plutus bootstrap` command that runs **after** the author has instrumented their scripts with `pv.step(...)` and produced `.plutus/run/<step_id>/results.json` files. It generates a partially-filled `manifest.yaml.draft` (≈70% complete from defaults + results.json) plus a companion `manifest_TODO.md` guidance document explaining the ~8 fields that require domain knowledge.

**Architecture:** Conservative — results.json + filesystem detection only. No LLM, no script grep, no README parsing. Reuses Plan 8's ruamel.yaml editor settings for diff-friendly emission.

**Tech Stack:** No new deps. Uses existing `plutus_verify.spec.runtime.results.load_results`, `plutus_verify.scaffold.manifest_edit` (for ruamel.yaml settings), and Click for the CLI.

---

## Why this plan exists

After Plans 1–8, the author flow for a brand-new Plutus repo is:

1. Write code + `pv.step(...)` instrumentation
2. `plutus init` → empty manifest skeleton with all TODOs
3. **Hand-fill ~30 fields in `.plutus/manifest.yaml`** — env, secrets, data, steps, metrics names + tolerances + placeholder values
4. `plutus check` → fails (placeholder values don't match real run)
5. `plutus snapshot --no-run` → fills value slots
6. Review diff, commit

Step 3 is the friction point. The author types ~30 fields by hand, and many of them — schema version, metrics names, step IDs, etc. — are derivable from artifacts the SDK already wrote. `plutus bootstrap` collapses step 3 from "type 30 fields" to "fill 8 TODO blocks." The author still needs to make 8 conscious choices (secrets, data sources, step commands, dependencies, 9-step mapping) — but those are the choices that genuinely require domain knowledge; everything else has a defensible default.

---

## Architectural decisions (recorded)

User-approved in plan-mode dialogue (2026-05-22):

1. **Conservative scope.** results.json + filesystem only. No LLM, no script grep, no README parsing. Deterministic and fast.
2. **Command name `plutus bootstrap`.** Distinct verb. `init` = empty skeleton, `bootstrap` = create-from-run-artifacts, `snapshot` = fill values in existing manifest.
3. **Defaults everywhere, TODO only on the truly unknowable.** Tolerance defaults to relative 5%, network to none, timeout to 1800 — without TODO markers. Only 8 fields get TODOs.
4. **Two output files.** `.plutus/manifest.yaml.draft` (the deliverable) + `.plutus/manifest_TODO.md` (companion guidance). Same pattern as `plutus transfer` from Plan 6.
5. **Refuse to overwrite without `--force`.** Bootstrap refuses if `manifest.yaml.draft` OR `manifest_TODO.md` exists. Never touches `manifest.yaml` (no `.draft` extension) — if the author has already renamed, bootstrap errors out (they're past this stage).
6. **`ruamel.yaml` for emission.** Reuse the round-trip-preserving editor's settings from Plan 8 — `mapping=2, sequence=4, offset=2`, `width=4096` — so the emitted YAML matches the existing manifest convention.

---

## Field-by-field automation

### 🟢 Fully derived (no TODO)
- `schema_version` — `"2.0"`
- `expected[].step_id` — directory name under `.plutus/run/`
- `expected[].metrics[].name|value|unit` — from each results.json
- `expected[].metrics[].display_name` — derived from `name` (`sharpe_ratio` → `"Sharpe Ratio"`)
- `expected[].reference_outputs[]` — from results.json `artifacts[]`:
  - `kind: chart|image` → `compare: visual_similarity`
  - `kind: json` → `compare: json_numeric_tolerance`
  - `kind: csv|other` → `compare: byte_exact`

### 🟡 Defaulted (no TODO unless author overrides)
- `repo.name` — `Path.cwd().name`
- `repo.primary_language` — `"python"` (detect via `.py` files)
- `env.base` — `"python"`
- `env.python_version` — read `.python-version`, else `pyproject.toml` `requires-python` major.minor, else `"3.11"`
- `env.requirements_file` — `"requirements.txt"` if present, else `null`
- `steps[].network` — `"none"`
- `steps[].timeout_seconds` — `1800`
- `steps[].verification_mode` — `"execute"`
- `expected[].metrics[].tolerance` — `{kind: relative, value: 0.05}`

### 🔴 TODO markers (manual)
- `env.os_packages`
- `secrets[]`
- `data_sources[]`
- `steps[].id` (for steps that DON'T run `pv.step` — e.g., `data_collection`, `optimization`)
- `steps[].command`
- `steps[].nine_step`
- `steps[].inputs`
- `steps[].depends_on`
- `nine_step_coverage`

---

## File structure

**New:**
- `plutus_verify/scaffold/bootstrap.py` — `scaffold_bootstrap()` + filesystem detection helpers + YAML emission
- `plutus_verify/scaffold/manifest_template_todo.py` — `MANIFEST_TODO_MD` template string

**Modified:**
- `plutus_verify/scaffold/__init__.py` — re-export `scaffold_bootstrap`, `BootstrapResult`, `BootstrapError`
- `plutus_verify/__main__.py` — `bootstrap` subcommand

**Tests:**
- `tests/unit/test_scaffold_bootstrap.py` — ~12 tests
- `tests/unit/test_cli_bootstrap.py` — 4 tests

---

## Task 1: Filesystem detection helpers

**Files:**
- Create: `plutus_verify/scaffold/bootstrap.py` (skeleton + helpers)
- Test: `tests/unit/test_scaffold_bootstrap.py` (helper tests only)

Public-but-private helpers (underscore-prefixed):

```python
def _detect_python_version(repo_path: Path) -> str:
    """Return major.minor like '3.11'.
    
    Order: .python-version file → pyproject.toml [project] requires-python →
    fallback '3.11'. For requires-python, extract first major.minor pattern
    (e.g., '>=3.11' → '3.11', '>=3.11,<3.13' → '3.11').
    """

def _detect_requirements_file(repo_path: Path) -> Optional[str]:
    """Return 'requirements.txt' if it exists, else None.
    
    Pyproject-only repos are valid (env.requirements_file is optional in v2).
    """

def _detect_repo_name(repo_path: Path) -> str:
    """Return repo_path.resolve().name. Handles trailing slash, '.' input."""

def _to_display_name(snake_case: str) -> str:
    """Title-case a snake_case identifier.
    
    'sharpe_ratio'        → 'Sharpe Ratio'
    'maximum_drawdown'    → 'Maximum Drawdown'
    'hpr'                 → 'Hpr'      (single short word; author can override)
    'annual_return_pct'   → 'Annual Return Pct'
    """

def _artifact_compare_kind(artifact_kind: str) -> str:
    """Map results.json artifact 'kind' to manifest reference_outputs 'compare'.
    
    chart, image           → 'visual_similarity'
    json                   → 'json_numeric_tolerance'
    csv, other, unknown    → 'byte_exact'
    """
```

TDD steps:
- [ ] Write tests in `test_scaffold_bootstrap.py` covering each helper:
  - `_detect_python_version`: `.python-version` present, `pyproject.toml` only, neither, multiple constraints (`>=3.11,<3.13`)
  - `_detect_requirements_file`: present, absent
  - `_detect_repo_name`: simple, with trailing slash, with `.` input → resolves to actual dir
  - `_to_display_name`: snake_case, single word, multiple underscores
  - `_artifact_compare_kind`: each of the 5 kinds + an unknown kind
- [ ] Run-fail, implement, run-pass
- [ ] Commit:
  ```
  feat(scaffold): bootstrap detection helpers (Plan 9 Task 1)
  
  Filesystem helpers for `plutus bootstrap`: detect python_version
  (.python-version > pyproject.toml requires-python > '3.11'),
  requirements file, repo name, plus display-name derivation and
  artifact-kind → compare-strategy mapping.
  ```

---

## Task 2: Bootstrap core

**Files:**
- Modify: `plutus_verify/scaffold/bootstrap.py` (add core function + dataclasses)
- Test: `tests/unit/test_scaffold_bootstrap.py` (add core tests)

Public API:

```python
class BootstrapError(RuntimeError):
    """Failed to bootstrap a manifest draft."""


@dataclass(frozen=True)
class BootstrapResult:
    draft_path: Path             # absolute path to manifest.yaml.draft
    todo_path: Path              # absolute path to manifest_TODO.md
    steps_with_metrics: int      # number of expected[] blocks created
    metrics_total: int           # sum of metrics across all blocks
    notes: list[str]


def scaffold_bootstrap(
    repo_path: Path,
    *,
    force: bool = False,
) -> BootstrapResult:
    """Generate .plutus/manifest.yaml.draft + manifest_TODO.md from results.json.
    
    Preconditions:
      - .plutus/run/<step_id>/results.json exists for at least one step
        (i.e., author has instrumented + run scripts)
      - .plutus/manifest.yaml does NOT exist (author past this stage)
      - .plutus/manifest.yaml.draft does not exist OR force=True
      - .plutus/manifest_TODO.md does not exist OR force=True
    
    Strategy:
      1. Glob .plutus/run/<step_id>/results.json files
      2. load_results() each via plutus_verify.spec.runtime.results
      3. Build a Python dict matching v2 manifest schema with:
         - 🟢 fields fully filled from results.json + helpers
         - 🟡 fields filled with defaults
         - 🔴 fields = TODO sentinel values (empty lists, "TODO_..." strings)
           plus ruamel.yaml comments
      4. Emit YAML via ruamel.yaml (indent 2/4/2, width 4096) — matches
         the manifest_edit.py editor's settings exactly
      5. Write manifest_TODO.md via Task 3's template
      6. Return BootstrapResult
    
    Raises:
        BootstrapError: per the preconditions above. Each failure mode has
            a distinct, debugging-grade message.
    """
```

Sentinel-value strategy for TODO fields:

| Field | YAML emission |
|---|---|
| `env.os_packages` | `os_packages: []  # TODO_os_packages: list apt packages your deps need (e.g., libpq-dev for psycopg2)` |
| `secrets` | `secrets: []  # TODO_secrets: list env vars + purpose + used_by (see manifest_TODO.md)` |
| `data_sources.processed` / `raw` | empty lists with TODO comments |
| `steps[].id` (free-form) | none auto-emitted; comment in steps section: `# TODO_steps: add data_collection/optimization/etc. steps that don't run pv.step` |
| `steps[].command` (for the auto-derived steps) | `command: TODO_command_for_<step_id>` |
| `steps[].nine_step` | `nine_step: TODO_nine_step` |
| `steps[].inputs` | `inputs: []  # TODO_inputs` |
| `steps[].depends_on` | `depends_on: []  # TODO_depends_on` |
| `nine_step_coverage` | all entries `{present: false, section: null}` + top comment `# TODO_nine_step_coverage` |

The string sentinels `TODO_*` make it trivially greppable: an author can run `grep TODO_ .plutus/manifest.yaml.draft` to find every spot they still need to fill.

The schema-level validation will fail on these (e.g., `command: TODO_command_for_in_sample_backtest` isn't a valid Python invocation), which is exactly what we want — `plutus check` against an unfilled draft must fail loudly.

TDD steps:
- [ ] Test: happy path — single results.json → draft with one expected block, all metrics auto-filled, TODOs on env.os_packages, secrets, etc.
- [ ] Test: multiple results.json → multiple expected blocks
- [ ] Test: refuses on existing manifest.yaml → `BootstrapError`, message mentions "already past bootstrap stage"
- [ ] Test: refuses on existing draft without force
- [ ] Test: refuses on existing TODO without force
- [ ] Test: force=True overwrites both
- [ ] Test: no results.json → `BootstrapError`, message tells author what to do
- [ ] Test: emitted YAML loads cleanly via `load_manifest_from_yaml_text` (will fail validation due to TODO sentinels — that's expected; just check YAML parses)
- [ ] Test: `_to_display_name` is applied to every metric name in the output
- [ ] Test: artifact kind → compare mapping is applied for `reference_outputs[]`
- [ ] Implement
- [ ] Run-pass
- [ ] Commit:
  ```
  feat(scaffold): scaffold_bootstrap generates draft from results.json (Plan 9 Task 2)
  
  Reads .plutus/run/<step_id>/results.json files, emits a manifest.yaml.draft
  that is ~70% complete (schema_version, env detection, expected.metrics +
  reference_outputs all auto-filled) with grep-able TODO_* sentinels on the
  fields that require domain knowledge. Refuses to overwrite without --force.
  ```

---

## Task 3: `MANIFEST_TODO_MD` guidance template

**Files:**
- Create: `plutus_verify/scaffold/manifest_template_todo.py`
- Test: `tests/unit/test_scaffold_bootstrap.py` (add a few tests verifying the file is emitted with expected sections)

Module:

```python
"""Static template for .plutus/manifest_TODO.md, written by `plutus bootstrap`.

Each section explains one TODO field in the generated draft. Authors read
the markdown alongside the .draft YAML, fill in the TODOs, rename .draft
to .yaml, run plutus check, commit.
"""
from __future__ import annotations


MANIFEST_TODO_MD = """\
# Plutus manifest TODO checklist

`plutus bootstrap` produced `.plutus/manifest.yaml.draft` with ~70% of the
manifest auto-filled from your scripts' results.json files and the filesystem.
The remaining ~30% requires domain knowledge that the verifier can't infer.

This document walks through each TODO in the draft. When all TODOs are
resolved, rename `manifest.yaml.draft` → `manifest.yaml` and run
`plutus check` to verify.

For a complete worked example, see
`out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` in the
plutus-verify repo.

---

## 1. `env.os_packages` — apt packages your deps need

**What it is:** Linux packages (apt) that must be installed in the Docker
image before `pip install -r requirements.txt`. Required for any Python
dep that has a native build step (psycopg2 needs libpq-dev, cffi needs
libffi-dev, etc.).

**Why the verifier needs it:** Otherwise `pip install` fails inside the
generated Docker image.

**Example:**

```yaml
env:
  os_packages: [build-essential, libpq-dev]
```

**Common pitfall:** Listing packages that don't exist in Debian Slim (the
base image). When in doubt, test in `python:3.11-slim` interactively.

---

## 2. `secrets[]` — required environment variables

**What it is:** Per-key declaration: which env var the step's script reads,
why, and which steps use it.

**Why the verifier needs it:** `plutus check` reads the host env (or a
.env file via `--secrets-from-env`) and propagates only the declared keys
into the container. Undeclared keys are NOT propagated — protects against
accidentally leaking unrelated host secrets.

**Example:**

```yaml
secrets:
  - key: DB_NAME
    purpose: Algotrade database name
    used_by: [data_collection]
  - key: DB_PASSWORD
    purpose: Algotrade database password
    used_by: [data_collection]
```

**Common pitfall:** Forgetting `used_by`. A secret with no `used_by` is
declared-but-unused; the schema validator emits a warning. Always list
the step IDs that actually need the secret.

---

## 3. `data_sources[]` — pre-built data downloads (optional)

**What it is:** Tiered data-source declaration. If declared, the verifier
will download data instead of re-running your `data_collection` script.

**Why the verifier needs it:** Re-running data collection from primary
sources (e.g., the database) is slow and often requires credentials. A
declared `data_source` lets the verifier skip data_collection entirely
if the download succeeds.

**Tiered model:**
- `processed:` — fully-processed data; skip both `data_collection` AND
  `data_processing` (if present)
- `raw:` — raw data; skip `data_collection` only

**Example:**

```yaml
data_sources:
  processed: []
  raw:
    - kind: google_drive
      url: https://drive.google.com/drive/folders/<folder-id>
      expected_layout:
        - data/is/VN30F1M_data.csv
        - data/is/VN30F2M_data.csv
        - data/os/VN30F1M_data.csv
        - data/os/VN30F2M_data.csv
      satisfies: [data_collection]
```

**Supported `kind` values:** `google_drive`, `github_release`, `http`.
(S3 is on the roadmap but not yet wired.)

**Common pitfall:** `expected_layout` paths are RELATIVE to repo root.
The verifier checks these files exist after download; if the layout
doesn't match, it falls through to running the step's command.

You can also leave `data_sources` empty (both lists `[]`) — the verifier
will simply run each step's command (Tier 3 fallback).

---

## 4. `steps[].id` — free-form steps not covered by `pv.step`

**What it is:** Some steps don't emit metrics — `data_collection`,
`data_processing`, `optimization` (when shipped as a pre-computed
artifact), etc. These don't call `pv.step(...)` and therefore have no
results.json file. Bootstrap can't auto-detect them. You must add them
to `steps[]` by hand.

**Why the verifier needs it:** Without these declarations, the verifier
doesn't know how to download data or run setup steps; backtests fail
because their input files are missing.

**Example (adding `data_collection` and `optimization` to a freshly-
bootstrapped manifest that only auto-detected the two backtest steps):**

```yaml
steps:
  # auto-detected (already in the draft):
  - id: in_sample_backtest
    command: TODO_command_for_in_sample_backtest
    ...
  
  # add by hand:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge          # data_collection talks to DB/internet
    command: "python data_loader.py"
    inputs: []
    outputs:
      - data/is/VN30F1M_data.csv
      - data/is/VN30F2M_data.csv
  
  - id: optimization
    nine_step: step_5_optimization
    required: true
    network: none
    verification_mode: artifact_check  # ship the optimized params, skip optuna
    inputs:
      - parameter/optimization_parameter.json
    outputs:
      - parameter/optimized_parameter.json
    depends_on: [data_collection]
```

---

## 5. `steps[].command` — which script runs this step

**What it is:** The shell command the verifier invokes inside the
container. Bootstrap emits `command: TODO_command_for_<step_id>` for
each auto-detected step — replace each.

**Example:**

```yaml
- id: in_sample_backtest
  command: "python backtesting.py"
```

**Common pitfall:** The command runs from `/srv/repo` (the container's
WORKDIR, which mirrors your repo root). Use relative paths.

---

## 6. `steps[].nine_step` — Plutus 9-step mapping

**What it is:** Which of the standard Plutus framework steps this is. One of:
`step_1_hypothesis`, `step_2_data_collection`, `step_3_data_processing`,
`step_4_in_sample`, `step_5_optimization`, `step_6_out_of_sample`,
`step_7_paper_trading`. Use `null` for steps that don't fit the framework.

**Why the verifier needs it:** Cross-checks against `nine_step_coverage`
and surfaces in the report so reviewers can see which framework
phases the repo exercises.

**Example:**

```yaml
- id: in_sample_backtest
  nine_step: step_4_in_sample
- id: train_classifier
  nine_step: null            # free-form ML step; not in the framework
  label: "Custom: train classifier"
```

---

## 7. `steps[].inputs` — files this step reads

**What it is:** Repo-relative paths the step's command reads at runtime.
Preflighted before each step — if any are missing, the step is reported
as failed without running.

**Example:**

```yaml
- id: in_sample_backtest
  inputs:
    - data/is/VN30F1M_data.csv
    - data/is/VN30F2M_data.csv
    - parameter/backtesting_parameter.json
```

**Common pitfall:** Globs are allowed (`data/is/*.csv`) but only match
against existing files at preflight time. Don't list outputs (files
the step *writes*) as inputs.

---

## 8. `steps[].depends_on` — dependency graph

**What it is:** Step IDs that must complete before this one. The
orchestrator topo-sorts steps and runs them in dependency order.

**Example:**

```yaml
- id: out_of_sample_backtest
  depends_on: [optimization]
```

**Common pitfall:** A step that depends on a download-only step (no
command) still needs the dependency declared; the verifier uses it to
order data acquisition before backtesting.

---

## 9. `nine_step_coverage` — README section mapping (optional)

**What it is:** For each Plutus framework step, whether your README has
a section covering it, and the section heading. Surfaces in the
verification report.

**Example:**

```yaml
nine_step_coverage:
  step_1_hypothesis: {present: true, section: "Hypothesis"}
  step_2_data_collection: {present: true, section: "Data Collection"}
  step_3_data_processing: {present: false, section: null}
  step_4_in_sample: {present: true, section: "In-sample Backtesting"}
  step_5_optimization: {present: true, section: "Optimization"}
  step_6_out_of_sample: {present: true, section: "Out-of-sample Backtesting"}
  step_7_paper_trading: {present: false, section: null}
```

You can leave everything `present: false` if you haven't written that
section yet. The verifier won't fail on missing sections.

---

## After filling everything in

```bash
mv .plutus/manifest.yaml.draft .plutus/manifest.yaml
plutus check .
```

If `plutus check` reports failures, the most common causes are:
- A `TODO_command_for_<step>` left unreplaced
- `data_sources.expected_layout` paths that don't match what the
  download actually produces
- A metric in the manifest that the script doesn't emit (rename or
  remove the manifest entry — or add the corresponding `r.metric(...)`
  call to the script)
- Tolerance too tight for genuine reproducibility (relax `tolerance.value`
  if the verifier reports a small numerical drift)

For a full reference, see the worked manifest at
`out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` in the
plutus-verify repo.
"""
```

TDD:
- [ ] Test that `MANIFEST_TODO_MD` contains each of the 9 section headers
- [ ] Test that bootstrap writes the file when called
- [ ] Implement (just paste the template)
- [ ] Commit:
  ```
  feat(scaffold): MANIFEST_TODO_MD guidance template (Plan 9 Task 3)
  
  ~250-line markdown walkthrough of each TODO field that bootstrap leaves
  in manifest.yaml.draft. Sections cover env.os_packages, secrets,
  data_sources, free-form steps, command, nine_step, inputs, depends_on,
  nine_step_coverage, plus a closing "after filling in" troubleshooting
  block.
  ```

---

## Task 4: CLI subcommand

**Files:**
- Modify: `plutus_verify/__main__.py`
- Test: `tests/unit/test_cli_bootstrap.py`

```python
@cli.command("bootstrap")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing manifest.yaml.draft and manifest_TODO.md.",
)
def bootstrap_cmd(repo_path: Path, force: bool) -> None:
    """Generate manifest.yaml.draft + manifest_TODO.md from .plutus/run/."""
    from plutus_verify.scaffold.bootstrap import (
        BootstrapError,
        scaffold_bootstrap,
    )
    try:
        result = scaffold_bootstrap(Path(repo_path), force=force)
    except BootstrapError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(3)
        return
    click.echo(
        f"draft:    {result.draft_path.relative_to(Path(repo_path).resolve())}  "
        f"({result.steps_with_metrics} steps, {result.metrics_total} metrics)"
    )
    click.echo(
        f"guidance: {result.todo_path.relative_to(Path(repo_path).resolve())}"
    )
    if result.notes:
        click.echo("notes:")
        for note in result.notes:
            click.echo(f"  - {note}")
    click.echo("")
    click.echo(
        "Next: fill in the TODO markers in the draft (see manifest_TODO.md),"
    )
    click.echo(
        "      rename .draft → .yaml, then run `plutus check`."
    )
```

TDD:
- [ ] Test: `plutus bootstrap --help` mentions `--force`
- [ ] Test: success path prints both file paths and the "Next:" hint
- [ ] Test: `BootstrapError` → exit 3 + error to stderr
- [ ] Test: `--force` passes through to `scaffold_bootstrap(force=True)`
- [ ] Implement
- [ ] Commit:
  ```
  feat(cli): plutus bootstrap subcommand (Plan 9 Task 4)
  
  CLI surface for scaffold_bootstrap. Default repo_path = '.'.
  --force overwrites the draft and TODO doc. Output mirrors plutus init's
  style: paths printed, plus a "Next:" hint pointing at manifest_TODO.md.
  ```

---

## Task 5: Integration verification

**Files:** none committed (out/ is gitignored)

Steps:
1. Move `out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` aside to `manifest.yaml.bak`.
2. Confirm `.plutus/run/<step_id>/results.json` files are still present from Plan 7 Task 4.
3. Run:
   ```bash
   cd /Users/dan/algotrade-research/plutus-automation-scoring
   source .venv/bin/activate
   python -m plutus_verify bootstrap out/transfer-test/ProtoMarketMaker
   ```
4. Inspect outputs:
   - `out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml.draft` — should contain both `in_sample_backtest` and `out_of_sample_backtest` expected blocks with 6 metrics each, all auto-filled; `env.python_version: "3.11"`; `env.requirements_file: requirements.txt`; TODO markers on the 8 unknowable fields
   - `out/transfer-test/ProtoMarketMaker/.plutus/manifest_TODO.md` — ~250 lines of guidance
5. Visual diff (cosmetic): compare `manifest.yaml.draft` against `manifest.yaml.bak`. The auto-filled portions (schema_version, env, expected.metrics, expected.reference_outputs) should be structurally equivalent. Differences are expected in the 8 TODO regions.
6. Restore the manifest:
   ```bash
   mv out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml.bak \
      out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml
   ```
7. Update `docs/plan/2026-05-21-plutus-spec-v2-DONE.md` to mark Plan 9 complete.

Commit (just the DONE.md update):
```
docs: Plan 9 complete — plutus bootstrap generates manifest drafts

bootstrap reads .plutus/run/<step_id>/results.json + filesystem and
produces a 70%-filled manifest.yaml.draft plus a companion
manifest_TODO.md walking the author through the 8 fields that require
domain knowledge. Closes the friction gap in the new-repo author flow:
write code → instrument → run → bootstrap → fill 8 TODOs → check → commit.

Verified against ProtoMarketMaker: draft regenerated from the sandbox's
results.json files contains both expected blocks with all 12 metrics
auto-filled and snake_case → display_name conversions applied.
```

---

## Verification

**Unit:** ~12 new tests in `test_scaffold_bootstrap.py` + 4 in `test_cli_bootstrap.py`. Full suite stays green (429 → ~445).

**Integration:** ProtoMarketMaker sandbox bootstrap roundtrip.

**Regression:** none. Bootstrap is additive; no existing modules change behavior.

---

## Out of scope

- Auto-creating `secrets[]` candidates by grepping for `os.environ.get`
- Parsing README for `nine_step_coverage` heuristics
- LLM-assisted draft generation (would reintroduce the v1 dependency we shed in Plan 6)
- Inferring `steps[].command` from script entry points (would require AST parsing or running a probe)
- Iterative refinement (`plutus bootstrap --refine` that updates an existing draft)

---

## Critical files referenced

- `plutus_verify/spec/runtime/results.py:78` — `load_results()`
- `plutus_verify/scaffold/manifest_edit.py:44-50` — ruamel.yaml indent/width settings
- `plutus_verify/scaffold/snapshot.py` — refuse-without-force pattern
- `plutus_verify/scaffold/extract_to_v2.py:208+` — pattern for emitting YAML + TODO companion
- `out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` — worked example lifted into Task 3 template

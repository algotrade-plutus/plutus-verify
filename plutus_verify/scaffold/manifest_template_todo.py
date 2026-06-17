"""Static template for ``.plutus/manifest_TODO.md``, written by ``plutus bootstrap``.

Each section explains one TODO field in the generated draft. Authors read this
alongside the draft YAML, fill in the TODO_* markers, rename ``manifest.yaml.draft``
to ``manifest.yaml``, run ``plutus check``, and commit.
"""
from __future__ import annotations


MANIFEST_TODO_MD = """\
# Plutus manifest TODO checklist

`plutus bootstrap` produced `.plutus/manifest.yaml.draft` with ~70% of the
manifest auto-filled from your scripts' `results.json` files and the
filesystem. The remaining ~30% requires domain knowledge that the verifier
can't infer.

This document walks through each TODO in the draft. When all TODOs are
resolved, rename `manifest.yaml.draft` → `manifest.yaml` and run
`plutus check` to verify.

To find every spot still needing input:

```bash
grep TODO_ .plutus/manifest.yaml.draft
```

For a complete worked example, see
`out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` in the
plutus-verify repo.

---

## 1. `env.os_packages` — apt packages your deps need

**What it is:** Linux packages (apt) installed in the Docker image before
`pip install -r requirements.txt`. Required for any Python dep that has a
native build step (psycopg2 → libpq-dev, cffi → libffi-dev, etc.).

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
why, and which steps need it.

**Why the verifier needs it:** `plutus check` reads the host env (or a
.env file via `--secrets-from-env`) and propagates only the declared keys
into the container. Undeclared keys are NOT propagated — this protects
against accidentally leaking unrelated host secrets.

**Example:**

```yaml
secrets:
  - key: DB_NAME
    purpose: Algotrade database name
    used_by: [data_preparation]
  - key: DB_PASSWORD
    purpose: Algotrade database password
    used_by: [data_preparation]
```

**Common pitfall:** Forgetting `used_by`. A secret with no `used_by` is
declared-but-unused; the schema validator emits a warning. Always list
the step IDs that actually need the secret.

---

## 3. `data_sources[]` — pre-built data downloads (optional)

**What it is:** Tiered data-source declaration. If declared, the verifier
downloads pre-built data instead of re-running your `data_preparation`
script.

**Why the verifier needs it:** Re-running data preparation from primary
sources (e.g., the database) is slow and often requires credentials. A
declared `data_source` lets the verifier skip data_preparation entirely
if the download succeeds.

**Tiered model:**

- `processed:` — fully-processed data; skip the `data_preparation` step
- `raw:` — raw data still needing processing inside `data_preparation`

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
      satisfies: [data_preparation]
```

**Supported `kind` values:** `google_drive`, `github_release`, `http`.
S3 is on the roadmap.

**Common pitfall:** `expected_layout` paths are RELATIVE to repo root.
The verifier checks these exist after download; if they don't match,
it falls through to running the step's command.

Leaving `data_sources` empty (both lists `[]`) is fine — the verifier
will just run each step's command (Tier 3 fallback).

---

## 4. `steps[]` free-form additions — steps not covered by `pv.step`

**What it is:** Some steps don't emit metrics — `data_preparation`,
`optimization` (when shipped as a pre-computed artifact), etc. These
don't call `pv.step(...)` and therefore leave no results.json. Bootstrap
can't auto-detect them. You must add them to `steps[]` by hand.

**Why the verifier needs it:** Without these declarations, the verifier
doesn't know how to download data or run setup steps; backtests fail
because their input files are missing.

The bootstrap draft includes a `TODO_steps` comment marker in the
`steps:` block where you should add these entries.

**Example (adding `data_preparation` and `optimization` to a freshly-
bootstrapped manifest that only auto-detected the two backtest steps):**

```yaml
steps:
  # auto-detected (already in the draft):
  - id: in_sample_backtest
    command: TODO_command_for_in_sample_backtest
    ...

  # add by hand:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    network: bridge          # data_preparation talks to DB/internet
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
    depends_on: [data_preparation]
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

- `step_1_hypothesis`
- `step_2_data_preparation`
- `step_3_forming_set_of_rules`
- `step_4_in_sample`
- `step_5_optimization`
- `step_6_out_of_sample`
- `step_7_paper_trading`

Or `null` for steps that don't fit the framework (e.g., a custom ML
training step).

**Why the verifier needs it:** Cross-checks against `nine_step_coverage`
and surfaces in the report so reviewers can see which framework phases
the repo exercises.

**Example:**

```yaml
- id: in_sample_backtest
  nine_step: step_4_in_sample
- id: train_classifier
  nine_step: null            # free-form ML step; not in the framework
  label: "Custom: train classifier"
```

---

## 6b. `steps[].sub_processes` — document data preparation (optional)

**What it is:** An optional, documentation-only breakdown of the
`data_preparation` step into its two v2025 sub-processes, `collection` and
`processing`. Only valid on the data_preparation step.

**Why:** When a repo actually collects and/or processes data, this records
**what** each sub-activity is and **how** it's performed. The verifier never
runs these — the step's own `command` (or a satisfying `data_source`) is what
executes. Omit the block entirely on the happy path where you just download
ready-to-use files.

**Example:**

```yaml
- id: data_preparation
  nine_step: step_2_data_preparation
  required: true
  command: "python data_loader.py"
  sub_processes:                 # optional; both slots individually optional
    collection:
      description: "query the DB for raw VN30F ticks"   # required if slot present
      command: "python data_loader.py --collect"        # optional
      outputs: [data/raw/x.csv]                          # optional
    processing:
      description: "clean + resample raw ticks to backtest inputs"
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
a section covering it, plus the section heading. Surfaces in the
verification report.

**Example:**

```yaml
nine_step_coverage:
  step_1_hypothesis: {present: true, section: "Hypothesis"}
  step_2_data_preparation: {present: true, section: "Data Preparation"}
  step_3_forming_set_of_rules: {present: false, section: null}
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

- A `TODO_command_for_<step>` left unreplaced (the schema validator
  will reject the literal string `TODO_command_for_...`)
- `data_sources.expected_layout` paths that don't match what the
  download actually produces
- A metric in the manifest that the script doesn't emit (either rename
  / remove the manifest entry, or add the corresponding `r.metric(...)`
  call to the script)
- Tolerance too tight for genuine reproducibility (relax `tolerance.value`
  if the verifier reports a small numerical drift)

For a full reference, see the worked manifest at
`out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` in the
plutus-verify repo.
"""

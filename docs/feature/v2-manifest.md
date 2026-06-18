---
feature: v2-manifest
date: 2026-06-01
version: 1.0
status: current
---

# v2 Manifest & Results Contract

## What It Does

A v2 manifest (`.plutus/manifest.yaml`) lets a repo **declare its verification
plan explicitly** instead of having a local LLM guess it from the README. When a
repo ships a manifest, `plutus-verify` skips LLM extraction entirely — the
manifest *is* the plan — and runs a deterministic native pipeline.

The manifest is one half of a contract. The other half is the **results
contract**: each metric-emitting script writes a strict
`.plutus/run/<step_id>/results.json` (most easily via the bundled Python SDK),
and the verifier compares the manifest's declared `expected` values against
exactly that file. No stdout scraping, no markdown-table parsing, no guessing
where a number lives.

## How It Works

1. You author `.plutus/manifest.yaml` (by hand, via [`plutus init`](authoring-tools.md),
   or via [`plutus transfer`](legacy-migration.md) / [`plutus bootstrap`](authoring-tools.md)).
2. Each step's script emits its metrics through the SDK:
   `with pv.step("in_sample") as r: r.metric("sharpe_ratio", float(s), unit="ratio")`.
   That writes `.plutus/run/in_sample/results.json`.
3. `plutus check` (local) or `plutus-verify` (remote) builds the env from
   `env`, resolves data per `data_sources`, runs each step, reads back the
   `results.json` files, and compares them to the manifest's `expected` metrics
   and `artifacts`.

The verifier reads each metric by **name** from `results.json` — there are no
locators in v2. Units are canonical decimals; `percent` is deliberately rejected
so the "29.92% vs 0.2992" ambiguity that plagued v1 cannot happen.

## Configuration — the manifest

### Top-level keys

| Key | Required | Notes |
|-----|----------|-------|
| `schema_version` | yes | must be exactly `"2.0"` |
| `repo` | yes | `{name, primary_language}` |
| `env` | yes | runtime declaration |
| `secrets` | yes | may be empty `[]` |
| `data_sources` | yes | `{processed: [...], raw: [...]}` (both arrays required) |
| `steps` | yes | at least one step |
| `expected` | yes | per-step metrics/artifacts; may be empty |
| `nine_step_coverage` | no | map keyed by the nine-step keys |

Unknown keys are rejected at every level (`additionalProperties: false`).

### Annotated example

```yaml
schema_version: "2.0"                  # const — exactly "2.0"
repo:
  name: ProtoMM
  primary_language: python
env:
  base: python                         # python | python-cuda | none
  python_version: "3.11"
  manager: uv                          # uv (locked, recommended) | pip (deprecated)
  lockfile: uv.lock                    # required when manager: uv
  # requirements_file: requirements.txt  # pip path only; or pyproject.toml; null if none
  os_packages: [build-essential]       # optional apt packages
  gpu_required: false
secrets:
  - key: TIINGO_API_KEY
    purpose: market data
    used_by: [data_preparation]         # step ids, or "data_sources.*" qualifiers
data_sources:
  processed:                           # ready-to-run preprocessed data
    - kind: google_drive
      url: https://drive.google.com/...
      expected_layout: ["data/processed/*.parquet"]
      satisfies: [data_preparation]
  raw:                                 # raw inputs that still need processing
    - kind: github_release
      url: https://github.com/x/y/releases/v1/raw.tar.gz
      expected_layout: ["data/raw/*.parquet"]
      satisfies: [data_preparation]
steps:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    network: bridge                    # outbound network for the download
    command: "python -m proto_mm.data.collect"   # data_* steps MUST have a command
    outputs: ["data/raw/*.parquet"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m proto_mm.backtest"
    inputs: [data/processed]           # see "inputs allowlist" caveat
    outputs: ["out/metrics.json", "out/equity.png"]
    depends_on: [data_preparation]
  - id: train_model
    nine_step: null                    # free-form / custom (e.g. ML) step
    label: "Custom: train classifier"
    required: true
    command: "python -m proto_mm.ml.train"
    outputs: ["models/clf.pkl"]
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio             # snake_case ^[a-z][a-z0-9_]*$
        display_name: "Sharpe Ratio"   # optional, report-only
        value: 0.85
        tolerance: {kind: relative, value: 0.05}
    artifacts:
      - path: "out/equity.png"
        compare: visual_similarity     # json_numeric_tolerance | visual_similarity | byte_exact
        threshold: 0.7
nine_step_coverage:
  step_1_hypothesis: {present: true, section: "1. Hypothesis"}
```

### The nine-step taxonomy

A step's `nine_step` is one of seven keys (or `null` for a free-form step).
Despite the name, the canonical set has **7** entries:

`step_1_hypothesis`, `step_2_data_preparation`, `step_3_forming_set_of_rules`,
`step_4_in_sample`, `step_5_optimization`, `step_6_out_of_sample`,
`step_7_paper_trading`.

### Step options

| Field | Default | Notes |
|-------|---------|-------|
| `id` | — | unique, non-empty |
| `nine_step` | — | one of the 7 keys, or `null` (free-form) |
| `required` | — | only required steps gate the exit code |
| `command` | `null` | the shell command; required for the `data_preparation` step |
| `network` | `none` | `none` / `bridge` / `host` |
| `timeout_seconds` | `1800` | per-step timeout |
| `inputs` | `[]` | positive allowlist of paths staged into the container (see caveat) |
| `outputs` | `[]` | declared output paths copied back out of the container |
| `depends_on` | `[]` | step ids; topo-sort edges |
| `verification_mode` | `execute` | `execute` runs the step; `artifact_check` only checks output files exist |
| `sub_processes` | — | optional doc-only breakdown of `data_preparation` (see below) |

### Documenting data preparation (`sub_processes`)

The `data_preparation` step (step 2) covers two sub-activities — *data collection*
and *data processing*. An optional `sub_processes` block documents them for
completeness. It is **documentation only**: the verifier never runs it (the step's
own `command` or a satisfying `data_source` is what executes), and it is **only
valid on the data_preparation step**. Omit it entirely on the happy path where a
repo just downloads ready-to-use files.

```yaml
- id: data_preparation
  nine_step: step_2_data_preparation
  required: true
  command: "python data_loader.py"
  sub_processes:                 # optional; both slots individually optional
    collection:
      description: "query the DB for raw VN30F ticks"   # required when the slot is present
      command: "python data_loader.py --collect"        # optional
      outputs: ["data/raw/*.parquet"]                    # optional (also: inputs)
    processing:
      description: "clean + resample raw ticks to the backtest inputs"
```

When present, the collection/processing descriptions are surfaced under the
**Step 2: Data Preparation** section of `plutus check` output.

### Reproducible environments (uv)

`env.manager` selects how the verifier materializes the environment:

- **`uv`** (recommended) — the verifier restores the committed lockfile exactly
  with `uv sync --frozen`, so the env matches what the author had. Requires
  `env.lockfile` (e.g. `uv.lock`). `--frozen` fails the build if the lock and
  `pyproject.toml` disagree — that failure is the integrity signal.
- **`pip`** (default, deprecated) — dependencies are re-resolved at build time
  from `requirements_file`, so the restored env may drift from the author's.

A non-`uv` (or lockfile-less) env is **not reproducibly locked**: `plutus check`
reports `env: NOT reproducible` and emits a deprecation note. This is a notice
today; it will become a soft fail (exit 1) in a future release. Pin with uv + a
committed lockfile to clear it.

### Data tiers

`data_sources` has two required arrays — `processed` (preprocessed,
ready-to-run) and `raw` (still needs the processing step). Each source's `kind`
captures the backing store (`google_drive`, `github_release`, `http`, `s3`,
`manual`). The native runtime resolves them in order: try `processed`, fall
through to `raw`, then fall through to running the step's command — which is why
data steps must always carry a runnable `command`. Committed-CSV repos simply
omit the source and read the file directly. (Informally: Tier 1 = committed
CSVs, Tier 2 = Drive/release-backed, Tier 3 = DB-backed via `bridge` + secrets.)

## The results contract

Every metric-emitting step writes `.plutus/run/<step_id>/results.json`:

```json
{
  "schema_version": "1.0",
  "step_id": "in_sample",
  "metrics":  [{"name": "sharpe_ratio", "value": 0.85, "unit": "ratio"}],
  "artifacts":[{"name": "equity_curve", "path": "out/equity.png", "kind": "chart"}],
  "metadata": {"duration_seconds": 12.3, "git_commit": "abc1234"}
}
```

The Python SDK is the easiest producer:

```python
import plutus_verify as pv

with pv.step("in_sample") as r:
    r.metric("sharpe_ratio", float(sharpe), unit="ratio")
    r.metric("win_rate",     float(win),    unit="fraction")
    r.artifact("equity_curve", "out/equity.png", kind="chart")
    r.metadata(seed=42)
```

- The write is **atomic** (`results.json.tmp` → `os.replace`) and happens **only
  on clean exit** of the `with` block — a raised exception writes nothing.
- `duration_seconds` and `git_commit` are auto-injected unless you set them.
- Valid units: `fraction`, `ratio`, `count`, `currency_usd`, `seconds`.
  **`percent` is rejected** — store `0.42`, not `42`.
- Metric/artifact names must be snake_case and unique within a step.

Non-Python authors can hand-write the JSON to the same schema.

## Limitations & Caveats

- **`inputs` is a complete-coverage allowlist, not "data inputs."** When
  `step.inputs` is non-empty, only matching paths are staged into the container —
  including the script's own source files. A narrow `inputs: [data/processed]`
  that omits the source dir makes `python -m ...` fail with exit 2. Recommended
  default for new manifests is `inputs: []` (the whole repo, minus
  `.dockerignore` exclusions, is staged), tightening step-by-step afterward.
  See [secret-and-leak-hardening](../design/secret-and-leak-hardening.md).
- **Undeclared outputs are dropped.** Files a script writes that aren't matched
  by `step.outputs` (and aren't under `.plutus/run/<step_id>/`) are discarded
  when the per-step staging dir is cleaned up.
- **No locators.** Manifests written for an earlier preview (with `locate:`
  blocks) fail schema validation; metrics are matched by name against
  `results.json`. Migrating means instrumenting scripts with the SDK.
- **GPU and S3 are unsupported.** `env.base: python-cuda` / `gpu_required: true`
  raise an error; `data_sources` backends are Drive / GitHub release / http
  (no S3 yet).
- **The manifest version stays `2.0`** even across breaking schema changes,
  because v2 has not been released externally.

## Related Features

- [authoring-tools](authoring-tools.md) — scaffold and verify a manifest.
- [legacy-migration](legacy-migration.md) — generate a draft manifest from a README.
- [repo-verification](repo-verification.md) — the shared CLI + exit-code contract.

## Source Materials

- Plans: `docs/plan/2026-05-20-plutus-spec-v2-foundation.md`,
  `docs/plan/2026-05-21-plutus-spec-v2-results-contract.md`
- Report: `docs/completion-report/2026-05-25-phase-a-v2-manifest-format.md`
- Code: `plutus_verify/spec/{manifest,schema,loader,validator,adapter}.py`,
  `plutus_verify/sdk/{run,schema}.py`, `plutus_verify/constants.py`
</content>

# plutus-verify

Automated reproducibility verifier for PLUTUS-standard algorithmic-trading
research repos. Given a repo's git URL, the tool:

1. **Ingests** the repo (`git clone --depth=1`).
2. **Extracts** a structured `ExtractedPlan` from `README.md` with a locally-hosted
   LLM (Gemma 4 26B A4B by default; any OpenAI-compatible endpoint works).
3. **Builds** a Docker image with `repo2docker` (auto-detects
   `requirements.txt`/`environment.yml`/`Dockerfile`/…) and overlays your
   secrets file.
4. **Executes** each step of the plan in the container, capturing stdout,
   stderr, exit code, and artifacts.
5. **Compares** every reported metric to the actual output (with configurable
   tolerance per metric) and judges chart similarity using the LLM's vision
   capability.
6. **Reports** a verdict — `reproduced` / `partial` / `failed` — with a
   per-9-step coverage table, exit code, `report.md`, and machine-readable
   `report.json`.

See [`docs/plan/2026-05-15-plutus-verify-design.md`](docs/plan/2026-05-15-plutus-verify-design.md) for the full design.

## Install

Requires Python ≥ 3.11. From the project root:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm,runner,charts]"
```

External tools you'll need at runtime:
- `git` (for ingest)
- `docker` (for the build + execute stages)
- `jupyter-repo2docker` (installed via `[runner]`)
- A locally-running Gemma endpoint exposing the OpenAI chat-completions API
  (vLLM, TGI, sglang, llama.cpp server). Defaults to `http://localhost:8000/v1`.

## CLI

```bash
plutus-verify <git_url>
              [--ref <branch|sha>]
              [--secrets path/to/.env]
              [--config path/to/plutus-verify.yaml]
              [--out ./out]
              [--resume-from extract|build|execute|compare|report]
              [--prefer-data-path google_drive|db_loader|auto]
              [--llm-endpoint http://localhost:8000/v1]
              [--no-charts]                  # bypass vision when Gemma vision is down
              [--dry-run]                    # ingest + extract + build only
              [--extract-only]               # ingest + extract; stop after plan.json

plutus-verify ./local/path --skip-clone
plutus-verify --batch repos.txt --out ./out
```

Exit codes:
- `0` — every required step reproduced
- `1` — required steps ran cleanly but ≥1 metric/chart was partial
- `2` — a required step failed, or the pipeline couldn't start

## Quick example

```bash
plutus-verify https://github.com/algotrade-plutus/ProtoMarketMaker \
              --secrets ./secrets/proto-mm.env \
              --llm-endpoint http://localhost:8000/v1
```

Outputs land under `./out/<run_id>/`:
- `plan.json` — what Gemma extracted (hand-edit + `--resume-from execute` to override)
- `meta.json` — repo url/sha/branch
- `report.json` — machine-readable result
- `report.md` — reviewer-friendly summary
- `step_<n>.log` — captured stdout/stderr per executed step

## Configuration

`plutus-verify.yaml` overrides the defaults (see
[`docs/plan/2026-05-15-plutus-verify-design.md`](docs/plan/2026-05-15-plutus-verify-design.md#plutus-verifyyaml-sample) for the full surface):

```yaml
llm:
  endpoint: http://localhost:8000/v1
  model: gemma-4-26b-a4b
  vision_model: gemma-4-26b-a4b

tolerances:
  ratio_relative: 0.05
  percentage_absolute: 1.0
  overrides:
    sharpe_ratio: {kind: relative, value: 0.05}
    max_drawdown: {kind: absolute, value: 0.02}

charts:
  match_threshold: 0.7

execute:
  default_network: none
  data_step_network: bridge
```

## Architecture

```
ingest  →  extract  →  build  →  execute  →  compare  →  report
  git       Gemma     repo2docker  Docker      numeric +    JSON +
  clone     -> JSON    build       step runs   Gemma chart  Markdown
                                               judging      + exit code
```

Every stage's outputs live on disk under `./out/<run_id>/`, so a single stage
can be re-run with `--resume-from <stage>` (after, e.g., hand-editing
`plan.json` when the extractor was wrong).

## Testing

```bash
pytest tests/unit          # fast, no Docker, no LLM endpoint required
pytest tests/integration   # uses real subprocess, still no Docker/LLM
```

The end-to-end test against a real Gemma + a real Plutus repo is the
verifier's "E2E" tier — run it nightly, not as a regression gate.

## Status

| Milestone | Status | Notes |
|----------:|:------:|-------|
| M1 — Plan extraction | ✅ done | extractor + retry, plan schema validated |
| M2 — Build + execute | ✅ scaffolded | Docker + repo2docker wrappers; live runs need Docker installed |
| M3 — Numeric comparison + report | ✅ done | all three locate kinds + tolerance + exit codes |
| M4 — Chart visual judgment | ✅ scaffolded | OpenAI-compat vision client wired in |
| M5 — Batch mode + CI polish | ◐ partial | `--batch` works; GitHub Action wrapper TBD |

## v2 manifest (preview)

Repos that ship a `.plutus/manifest.yaml` skip LLM extraction entirely — the
manifest IS the plan. See
[`docs/plan/2026-05-20-plutus-spec-v2-foundation.md`](docs/plan/2026-05-20-plutus-spec-v2-foundation.md)
for the foundation work.

A minimal manifest looks like:

```yaml
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
```

Authoring tools (`plutus init`, `plutus check`, `plutus snapshot`) land in Plan 3.
Native v2 execution (input/output pre-flight, data-tier resolver, full
reference-output comparator) lands in Plan 2.

## Migrating a legacy repo

For repos that already exist as v1 (README + LLM extraction), run:

```bash
plutus transfer /path/to/repo --llm-endpoint http://localhost:11434/v1
```

This writes `.plutus/manifest.yaml.draft`. Open it, address every
`# TODO(plutus-transfer):` marker, rename to `manifest.yaml`, and run
`plutus check` to verify the migration.

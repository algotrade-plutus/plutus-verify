# plutus-verify

Reproducibility verifier and tooling for **PLUTUS-standard** algorithmic-trading
research repos.

A compliant repo declares a `.plutus/manifest.yaml` and emits a strict per-step
results contract. `plutus check` then builds an isolated container, runs each
step, compares the produced metrics and artifacts against the values the manifest
declares, and exits with a verdict — `0` reproduced, `1` partial, `2` failed.

The manifest **is** the plan: the verifier runs deterministically with no LLM in
the loop.

## The two contracts

1. **The manifest** — `.plutus/manifest.yaml`, committed to the repo, declares the
   runtime env, data sources, steps, and the `expected` metrics/artifacts.
   Validated against a JSON Schema plus cross-field invariants.
2. **The results contract** — each step writes `.plutus/run/<step_id>/results.json`
   with `metrics` (snake_case names, canonical decimal units — `percent` is
   rejected), `artifacts`, and `metadata`. The verifier reads each metric **by
   name**; no stdout scraping, no markdown-table parsing.

See [`docs/design/v2-spec-and-execution.md`](docs/design/v2-spec-and-execution.md)
for the design and [`docs/feature/v2-manifest.md`](docs/feature/v2-manifest.md)
for the full manifest/results reference.

## Install

Requires Python ≥ 3.11. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,runner]"     # runner = Docker support, needed for `check`
```

Optional extras:
- `runner` — `docker` + `repo2docker` + `build` (required for `check`)
- `llm` — `openai` client (for `transfer` and remote `verify`)
- `charts` — `cairosvg` + `pillow` (rasterizing artifacts for visual comparison)

Runtime tools: `git` and `docker` must be on `PATH`.

## Quick start

```bash
plutus init .                      # scaffold .plutus/manifest.yaml + CI workflow + example script
# 1. instrument each step's script (see .plutus/example_script.py):
#      import plutus_verify as pv
#      with pv.step("in_sample") as r:
#          r.metric("sharpe_ratio", float(sharpe), unit="ratio")
#          r.artifact("equity_curve", "out/equity.png", kind="chart")
# 2. fill in .plutus/manifest.yaml (env, data_sources, steps, expected)
plutus check . --secrets-from-env  # build, run, compare → exit 0 / 1 / 2
```

Exit codes:
- `0` — every required step ran cleanly **and** all metric/artifact comparisons passed
- `1` — required steps ran, but ≥1 comparison was partial (soft fail)
- `2` — a required step failed, or the pipeline couldn't start (bad manifest, build error)

`plutus check` builds an image from `.plutus/Dockerfile.generated` (derived from
the manifest's `env`), then runs each step in an isolated staging copy of the
repo filtered by `.dockerignore` (and `step.inputs`, if declared) — the host
`.env` and stale caches cannot leak into the container at runtime. Outputs land
in `.plutus/run/<step_id>/`.

## CLI

All subcommands are under the `plutus` entrypoint (`plutus -h` for help):

| Command | What it does |
|---|---|
| `plutus init [path]` | Scaffold `.plutus/manifest.yaml`, `.github/workflows/plutus.yml`, and an example instrumented script. |
| `plutus check [path]` | Build → run each step → compare against `expected`. The reproducibility gate. |
| `plutus snapshot [path]` | Capture step outputs into `.plutus/expected/` and fill `expected.metrics[].value` in the manifest. |
| `plutus bootstrap [path]` | Auto-fill a draft manifest from existing `.plutus/run/` results (run after instrumenting + a local run). |
| `plutus transfer [path]` | Draft a manifest for a README-only repo by extracting its plan with an LLM (+ `instrument_TODO.md`). |
| `plutus verify <git_url>` | Verify a remote repo: clone a git URL, extract its plan from the README via an LLM, build, run, and compare. |

Useful `check` flags: `--secrets-from-env` (inject env vars as secrets),
`--data-tier processed|raw|code|auto`, `--visual-check` (enable
`visual_similarity` comparisons; needs `PLUTUS_VISION_ENDPOINT` +
`PLUTUS_VISION_MODEL`).

## The manifest

A minimal valid manifest (all required top-level keys present):

```yaml
schema_version: "2.0"
repo: {name: Demo, primary_language: python}
env:
  base: python                         # python | python-cuda | none
  python_version: "3.11"
  requirements_file: requirements.txt  # null if none
  gpu_required: false
secrets: []                            # required, may be empty
data_sources: {processed: [], raw: []} # both arrays required
steps:
  - id: in_sample
    nine_step: step_4_in_sample        # one of the 7 nine-step keys, or null
    required: true                     # gates the exit code
    command: "python -m demo.backtest"
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 1.42
        tolerance: {kind: relative, value: 0.05}
```

The nine-step taxonomy keys are `step_1_hypothesis`, `step_2_data_collection`,
`step_3_data_processing`, `step_4_in_sample`, `step_5_optimization`,
`step_6_out_of_sample`, `step_7_paper_trading`. Repo-specific steps that don't
fit a key use `nine_step: null` + a `label`.

## Scoring & skills

Two Claude Code skills (under [`skills/`](skills/)) wrap the workflow:

- **`plutus-transform`** — turns a research repo into a verifiable one via a
  four-phase workflow (Survey → Decide → Instrument → Verify), anchored on
  `plutus check` exiting 0, then auto-chains into scoring.
  ([`docs/feature/plutus-transform-skill.md`](docs/feature/plutus-transform-skill.md))
- **`plutus-scoring`** — scores a compliant repo against the compliance rubric and
  emits per-bucket scores, ranked improvement paths, and a re-run command.
  ([`docs/feature/plutus-scoring-skill.md`](docs/feature/plutus-scoring-skill.md))

The rubric has four weighted buckets summing to 100%: **Reproducible (50)** —
`plutus check` exit 0 within tolerance · **Tidy / well-documented (25)** ·
**Standardized / template (10)** · **Innovative (15)**. See
[`skills/plutus-scoring/references/compliance-rubric.md`](skills/plutus-scoring/references/compliance-rubric.md).

## Architecture

```
manifest ─→ build ──────→ run steps ─────→ compare ────→ report
.plutus/   Dockerfile     isolated         results.json   exit
manifest   .generated     staging copies   vs expected    0 / 1 / 2
```

Design docs live under [`docs/design/`](docs/design/); user-facing feature docs
under [`docs/feature/`](docs/feature/).

## Testing

```bash
pytest tests/unit          # fast, no Docker, no LLM endpoint required
pytest tests/integration   # real subprocess, still no Docker/LLM
```

The end-to-end tier (real Docker + a real Plutus repo) is run on demand, not as a
regression gate.

## Changelog

- **v2 (0.2.x, current):** repos declare a `.plutus/manifest.yaml` and emit a results contract; verification is deterministic with no LLM in the hot path.
- **v1 (earlier):** plans were extracted from the README by an LLM — still available via `plutus verify <git_url>` for un-instrumented remote repos.

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

## Snapshot & check: bless vs verify

`plutus` separates *blessing* a baseline from *verifying* against it. Both run the
**identical pipeline inside the container** — they differ only in the final move.

- **`plutus snapshot` = bless.** Builds the image, runs every step in the
  container, harvests each step's produced outputs, then **writes the
  groundtruth**: metric numbers → `manifest.yaml` (`expected.metrics[].value`),
  artifact files → `.plutus/expected/<step>/`, plus a human-facing copy to your
  declared output paths (`result/…`). This is the *only* way to bless a baseline.
- **`plutus check` = verify.** Runs the same pipeline, then **compares** the
  freshly produced outputs against the frozen groundtruth. It is **read-only** —
  it never writes `.plutus/expected/` or your committed working-tree files.

Three stores, by role:

| Store | Role | Written by | Commit it? |
|---|---|---|---|
| `.plutus/expected/<step>/…` + `manifest.yaml` numbers | frozen groundtruth (the database) | `snapshot` only | **yes** |
| `result/…` (your declared output paths) | human-facing view for the README | `snapshot` only | **yes** |
| `.plutus/results/<step>/…` | per-run scratch buffer + inter-step data bus | `snapshot` **and** `check` | **no — gitignore it** |

Because produced bytes land in the gitignored `.plutus/results/`, running `check`
leaves your working tree clean — safe in CI, pre-commit, or while editing. A
forgotten `snapshot` is caught (missing groundtruth → fail), and drift from a code
change you never re-blessed fails on purpose. The same in-container run produces
both baselines, so `byte_exact` works for build-sensitive artifacts (charts,
`*.parquet`, `model.pkl`) that a laptop baseline could never match.

> **Add `.plutus/results/` to your repo's `.gitignore`** (next to `.plutus/run/`).
> New to the workflow? See [GUIDELINE.md](GUIDELINE.md) for a step-by-step migration.

## Install

Requires Python ≥ 3.11. To **use** the tool, install it with the `runner` extra
(Docker support, needed for `check`):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[runner]"
```

Consumer-facing extras:
- `runner` — `docker` + `repo2docker` + `build` (required for `check`/`snapshot`)
- `llm` — `openai` client (for `transfer` and remote `verify`)
- `charts` — `cairosvg` + `pillow` (rasterizing artifacts for visual comparison)

To **develop** plutus-verify, use uv — the dev/test toolchain lives in a PEP 735
dependency group that `uv sync` installs automatically:

```bash
uv sync          # creates .venv with everything needed to run the full suite
uv run pytest    # 0 flags needed
```

Runtime tools: `git` and `docker` must be on `PATH`.

### Installing into a strategy repo (no PyPI needed)

A strategy repo's step scripts `import plutus_verify`, but the SDK is **never** a
project dependency — `plutus check` stages a wheel into the Docker image at build
time. To run those scripts (or `check`/`snapshot`) locally, install plutus-verify
one of two ways — **PyPI is not required**:

- **Release wheel (recommended):** `uv pip install <release-wheel>` /
  `uv tool install <release-wheel>`. The wheel from `scripts/release-build.sh`
  **self-bundles** a copy of itself at `plutus_verify/_bundled/`, so the install
  method (wheel / `uv tool` / editable) doesn't matter — only that `_bundled/`
  contains the `.whl`.
- **Editable checkout:** `pip install -e .` (as above).

A **plain** `uv build` / `python -m build` wheel is **not** self-bundling (its
`_bundled/` holds only `__init__.py`), but `check` still stages the SDK from it by
re-packing the installed files — so a plain wheel works too. The **release** wheel
is preferred (self-bundling, no re-pack step). `check` only errors — with an
actionable `SdkBundleError` — if the install has no usable files at all (e.g. no
`RECORD` manifest).

## Quick start

```bash
plutus init .                      # scaffold .plutus/manifest.yaml + CI workflow + example script
echo ".plutus/results/" >> .gitignore   # per-run scratch buffer — never committed
# 1. instrument each step's script (see .plutus/example_script.py):
#      import plutus_verify as pv
#      with pv.step("in_sample") as r:
#          r.metric("sharpe_ratio", float(sharpe), unit="ratio")
#          r.artifact("equity_curve", "out/equity.png", kind="chart")
# 2. fill in .plutus/manifest.yaml (env, data_sources, steps, expected)
plutus snapshot .                  # bless: build, run in-container, write groundtruth + result/
git add .plutus/expected manifest.yaml result && git commit -m "bless baseline"
plutus check .                     # verify: rebuild, rerun, compare → exit 0 / 1 / 2 (read-only)
```

Exit codes:
- `0` — every required step ran cleanly **and** all metric/artifact comparisons passed
- `1` — required steps ran, but ≥1 comparison was partial (soft fail)
- `2` — a required step failed, or the pipeline couldn't start (bad manifest, build error)

`plutus check` builds an image from `.plutus/Dockerfile.generated` (derived from
the manifest's `env`), then runs each step in an isolated staging copy of the
repo filtered by `.dockerignore` (and `step.inputs`, if declared) — the host
`.env` and stale caches cannot leak into the container at runtime. Bookkeeping
lands in `.plutus/run/<step_id>/`; produced artifacts are harvested to the
gitignored `.plutus/results/<step_id>/` and compared there, so `check` never
touches your committed files. Earlier steps' outputs flow to later steps through
that same buffer (the inter-step data bus), so multi-step pipelines reproduce
end-to-end without writing the working tree.

## CLI

All subcommands are under the `plutus` entrypoint (`plutus -h` for help):

| Command | What it does |
|---|---|
| `plutus init [path]` | Scaffold `.plutus/manifest.yaml`, `.github/workflows/plutus.yml`, and an example instrumented script. |
| `plutus check [path]` | **Verify** (read-only): build → run each step in-container → compare produced output (in `.plutus/results/`) against the groundtruth. The reproducibility gate. |
| `plutus snapshot [path]` | **Bless**: build → run each step in-container → write the groundtruth (`.plutus/expected/` + `manifest.yaml` values) and a human-facing `result/` copy. `--no-run` blesses pre-existing local outputs instead. |
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

The nine-step taxonomy keys are `step_1_hypothesis`, `step_2_data_preparation`,
`step_3_forming_set_of_rules`, `step_4_in_sample`, `step_5_optimization`,
`step_6_out_of_sample`, `step_7_paper_trading`. Repo-specific steps that don't
fit a key use `nine_step: null` + a `label`.

The `data_preparation` step takes an optional, documentation-only `sub_processes`
block (`collection` + `processing`) to record what/how data is prepared when a repo
does more than download ready-to-use files. It is never executed and is only valid
on that step — see [docs/feature/v2-manifest.md](docs/feature/v2-manifest.md).

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
                                                  ┌─ snapshot → bless:  write .plutus/expected/ + manifest values + result/
manifest ─→ build ──→ run steps ──→ harvest ──────┤
.plutus/   Docker     isolated      .plutus/       └─ check → verify: compare vs groundtruth → exit 0 / 1 / 2 (read-only)
manifest   .generated staging       results/<step>
```

`snapshot` and `check` share every stage up to `harvest`; only the final verb
differs (write groundtruth vs. compare against it).

Design docs live under [`docs/design/`](docs/design/); user-facing feature docs
under [`docs/feature/`](docs/feature/).

## Testing

```bash
uv sync                        # one-time: install the full dev/test toolchain
uv run pytest                  # whole suite, no flags
uv run pytest tests/unit       # fast, no Docker, no LLM endpoint required
uv run pytest tests/integration  # real subprocess, still no Docker/LLM
```

The end-to-end tier (real Docker + a real Plutus repo) is run on demand, not as a
regression gate.

## Changelog

- **0.4.4:** `check` is now **read-only** — produced artifacts are harvested to the
  gitignored `.plutus/results/` and compared there, never overwriting committed
  files; earlier steps reach later ones through that buffer. `snapshot` now runs
  **in-container** by default (same environment `check` reproduces) and writes both
  the groundtruth and a human-facing `result/` copy. Dev workflow moved to uv
  (`uv sync` + `uv run pytest`). See [GUIDELINE.md](GUIDELINE.md).
- **v2 (0.2.x–0.4.x):** repos declare a `.plutus/manifest.yaml` and emit a results contract; verification is deterministic with no LLM in the hot path.
- **v1 (earlier):** plans were extracted from the README by an LLM — still available via `plutus verify <git_url>` for un-instrumented remote repos.

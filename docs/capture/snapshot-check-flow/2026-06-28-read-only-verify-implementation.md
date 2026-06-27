---
feature: snapshot-check-flow
type: implementation
date: 2026-06-28
time: 00:41
source-skill: superpowers:test-driven-development
tags: [snapshot, check, read-only, results-buffer, inter-step-bus, uv, "L1", "L2"]
---

# Implementation — read-only `check` + in-container `snapshot` (L1 + L2), and uv adoption

> Implements [docs/plan/snapshot-check-flow-redesign.md](../../plan/snapshot-check-flow-redesign.md)
> (design status now `implemented`; see its §12 for the terse as-built list). The plan started as
> a 9-step dogfood brief (2 limitations + 1 design question) and was deliberated into a two-verb
> model. This session reconciled the doc, then landed the code in two increments via TDD, then
> migrated the project's dev workflow to uv.

## What was wrong (the two limitations)

- **L1 — `snapshot` blessed from the laptop, not the container.** The CLI hard-blocked the
  in-container path (`--no-run` forced, `exit 3`), so baselines were captured from host-disk
  outputs while `check` byte-compares in the container. `scaffold_snapshot(run_check_first=True)`
  already worked; the CLI just never wired the builder/runner.
- **L2 — `check` overwrote the working tree.** `extract_outputs` copied every `step.outputs`
  match from staging back over the author's `result/…` files, so a *verification* mutated tracked
  files (README charts churned on every run) and `check` was not read-only. The writeback was also
  secretly the **inter-step data bus** (step N's output reached step N+1 via cwd), so it couldn't
  just be deleted.

## The model (unchanged from the plan, now built)

Two verbs over three stores:

| Store | Role | Written by | Committed |
|---|---|---|---|
| `.plutus/expected/<step>/…` + `manifest.yaml` numbers | groundtruth / database | **`snapshot` only** | yes |
| `.plutus/results/<step>/…` | per-run harvest buffer + inter-step bus | `snapshot` **and** `check` | no — gitignored |
| `result/…` | human-facing view (README) | `snapshot` only | yes |

`snapshot` = bless (run in container → harvest to `.plutus/results/` → write `.plutus/expected/`
+ `result/`); `check` = verify (same harvest → diff against groundtruth, read-only).

## Changes

**L1 (CLI wiring).**
- [`__main__.py` `snapshot_cmd`](../../../plutus_verify/__main__.py#L481): dropped the `--no-run`
  hard block; without the flag it builds `make_image_builder()` + `DockerRunner()` and calls
  `scaffold_snapshot(run_check_first=True)`. `--no-run` stays as the local-bytes opt-out.
- [`real_image_builder.py`](../../../plutus_verify/spec/runtime/real_image_builder.py#L58):
  `.plutus/results/` added to the `.dockerignore` baseline so the buffer never leaks into the image.

**L2 (read-only verify + harvest).**
- [`staging.py`](../../../plutus_verify/spec/runtime/staging.py): `extract_outputs` harvests
  declared outputs to `.plutus/results/<step>/` (was: working-tree root); `.plutus/run/<step>/`
  bookkeeping still returns to cwd. New `stage_prior_results(repo, staging, step)` is the inter-step
  bus — it remaps `.plutus/results/<step>/<path>` → `staging/<path>` and respects `step.inputs`
  (so an unrelated earlier output can't leak into a step that didn't declare it). New
  `harvest_committed_outputs` mirrors `artifact_check` (shipped) outputs into the buffer for a
  uniform compare.
- [`orchestrator.py` `_run_step`](../../../plutus_verify/spec/runtime/orchestrator.py): clears the
  per-step buffer; injects the bus after `populate_staging`; runs the **input** preflight against
  the staging sandbox (committed inputs + injected intermediates) and the **output** preflight
  against `.plutus/results/<step>/`. `_compare_artifacts` reads `produced_path` from
  `.plutus/results/<step>/<path>`. `_compare_metrics` unchanged.
- [`check.py`](../../../plutus_verify/scaffold/check.py#L37): wipes `.plutus/results/` at run start
  (alongside `.plutus/run/`).
- [`snapshot.py`](../../../plutus_verify/scaffold/snapshot.py): with `run_check_first=True`, blesses
  artifacts from `.plutus/results/` into both `.plutus/expected/<step>/` and `result/`; with
  `--no-run`, blesses from the author's local outputs as before. Metric-bless unchanged.
- [`preflight.py`](../../../plutus_verify/spec/runtime/preflight.py) and
  [`artifact_compare.py`](../../../plutus_verify/spec/runtime/artifact_compare.py): **unchanged** —
  the call sites just pass a different base path. (A nice outcome: the read-only refactor needed
  zero changes to the comparison and existence-check primitives.)

## Decisions resolved during the session

- **Metrics channel stays in `.plutus/run/`** (the plan briefly implied moving `results.json` to
  `.plutus/results/`). It already works and is orthogonal to L1/L2 — only artifact *files* moved.
  Avoided gratuitous churn across `load_results` / `_compare_metrics` / the metric-bless.
- **`.plutus/results/` must be wiped per run** (per-step clear in `_run_step` + whole-tree wipe in
  `check.py`), symmetric to the `.plutus/run/` wipe, so a stale prior-run artifact can never be
  compared or blessed.
- **Decision 1 = inter-step bus via `.plutus/results/`** (thread harvested outputs forward — the
  only option that survives a first snapshot). **Decision 2 = yes, write `result/`.**
- **gitignore is the strategy author's job**, not the framework's — the framework manages
  `.dockerignore` and never writes a user `.gitignore`.

## Tests (TDD, RED→GREEN throughout)

- New: `extract_outputs` → results buffer; `stage_prior_results` (bus + `step.inputs` filter);
  results-buffer wipe; CLI in-container snapshot + `--no-run` opt-out; dockerignore baseline entry;
  run-first snapshot blesses from buffer **and** writes `result/`.
- **Migrated ~13 tests** whose mock runners produced nothing and leaned on pre-staged `repo_path`
  files — once outputs must be *harvested from the run*, each mock now writes its declared outputs
  into the staging cwd (as a real container does). The 3-step `spec_v2_minimal` e2e fixture now
  genuinely exercises the inter-step bus end-to-end.
- Suite: **554 passed, 0 failed** via `uv run pytest`.

## uv migration (same session)

The project now uses uv as its dev/workflow tool (build backend left as setuptools):
- [`pyproject.toml`](../../../pyproject.toml): feature extras (`llm`, `runner`, `charts`) stay as
  consumer-facing `[project.optional-dependencies]`; dev/test toolchain moved to a PEP 735
  `[dependency-groups].dev` (a superset incl. `build`, `docker`, `jupyter-repo2docker`, `cairosvg`,
  `pillow`, `openai`); `[tool.uv].default-groups = ["dev"]`.
- `uv.lock` generated and **tracked** (now that uv is the dev workflow, the lock gives reproducible
  dev/CI; consumers are unaffected — they resolve published version ranges).
- Dev flow is now flag-free: `uv sync && uv run pytest`.

## Watch-for

- **`stage_prior_results` injects ALL prior steps' buffers, filtered only by `step.inputs`.** If a
  step declares *no* inputs, every earlier produced file is injected (consistent with
  `populate_staging`'s "empty inputs ⇒ dockerignore governs"). Two steps producing the same declared
  path → later step wins (sorted by step id; not topological). Fine today; revisit if a real pipeline
  has colliding output paths.
- **Output existence is now checked in `.plutus/results/<step>/`, not `repo_path`.** A step that
  exits 0 but writes nothing now surfaces a `missing output(s)` preflight error (previously a stale
  committed file at `repo_path` could mask it). This is stricter — intended — but it is why the mock
  runners had to start producing outputs.
- **`artifact_check` steps** are mirrored into the buffer via `harvest_committed_outputs` (full
  `repo_path.rglob`, skipping `.plutus/`). Cheap for normal repos; could be slow on a huge working
  tree. Only matters if an `artifact_check` step declares `expected.artifacts`.
- **First snapshot prints FAIL lines** for missing references (the embedded `check` returns exit 1),
  but `scaffold_snapshot` only aborts on exit 2 (a required *step* crash), so the bless proceeds.
  Cosmetic only.
- **Pre-existing `test_compare_charts` failure was an env gap, not a bug** — it scored `partial`
  without `cairosvg`/`pillow`. The uv dev group installs them, so it now passes; don't be surprised
  it was red before the migration.
- **Strategy-repo follow-up (not framework-enforced):** authors should add `.plutus/results/` to
  their repo's `.gitignore` (same as `.plutus/run/`).
- **`snapshot` CLI has no `--secrets-from-env` / `--visual-check` yet** — it runs with `secrets={}`
  and `vision_client=None`. Steps needing secrets to produce baselines aren't covered by the
  in-container snapshot path; add the flags (mirroring `check_cmd`) when that need arises.

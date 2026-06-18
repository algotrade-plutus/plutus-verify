---
feature: plutus-transform-skill
date: 2026-06-01
version: 1.0
status: current
---

# `plutus-transform` Skill

## What It Does

`plutus-transform` is a Claude Code skill that drives the **end-to-end
transformation** of a v1-ish Plutus trading-research repo into a v2-verifiable
repo. Where the `plutus` CLI gives you the individual tools (`init`, `transfer`,
`bootstrap`, `check`), this skill orchestrates them into a guided workflow that
ends with one concrete, checkable outcome: **`plutus check .` exits 0** with
every README-claimed metric matching script output within declared tolerance.

It recognizes prompts like "make this repo plutus-compliant", "transform this
into plutus v2", "integrate plutus-verify", "set up plutus check", and "add
reproducibility verification". When it finishes a clean transform, it
auto-chains into [`plutus-scoring`](plutus-scoring-skill.md) to produce the
compliance score.

## How It Works

A **pre-flight** confirms the repo path, that `plutus_verify` is importable,
probes the installed version (loading the matching `references/v<minor>.md`
delta notes), and warns about uncommitted changes. Then four sequential phases:

### Phase 1 — Survey

Dispatches parallel read-only `Explore` agents to map five things: the pipeline
shape (top-level scripts, `__main__` blocks), README claims (verbatim metric
tables, chart references, IS/OOS date ranges, risk-free-rate assumptions),
dependencies (`pyproject.toml` + `uv.lock` as the reproducible source; a `requirements.txt` or pin-less `pyproject.toml` is a deprecated fallback to be ported to uv; pin conflicts surface explicitly at `uv lock` time),
secrets & env (`os.environ`/`os.getenv` greps cross-referenced with
`.env.example`), and architectural smells (module-level DB connections, broken
data paths, `.env` placeholders). Produces a Survey Report.

### Phase 2 — Decide

The *only* interactive phase. A single `AskUserQuestion` poses five decisions:

- **D1** — data sourcing tier (DB-backed / Drive / processed CSVs / layered).
- **D2** — optimization verification mode (`artifact_check` default / `execute`).
- **D3** — paper-trading inclusion (skip default / `artifact_check`).
- **D4** — source of truth: README claims (default) vs script output.
- **D5** — env reproducibility (port to uv default / loosen + re-lock / keep) —
  always asked, because a non-uv / lockfile-less env is now reported as not
  reproducible (a deprecation, becoming a soft-fail). Port to uv = declare deps
  in `pyproject.toml`, run `uv lock`, commit `uv.lock`, set `env.manager: uv` +
  `env.lockfile: uv.lock`.

### Phase 3 — Instrument & manifest

Non-interactive except for boundary asks. Creates an isolation branch first
(`git checkout -b plutus-verify-v2`), builds the env via `uv sync --frozen`
against the committed `uv.lock` (installing the SDK with `uv pip install`),
probes the schema at runtime (never hardcodes `UNIT_KINDS`/`ARTIFACT_KINDS`), **additively**
instruments metric-emitting scripts (`import plutus_verify as pv`; append
`with pv.step(...)` at the end of `__main__`; wrap every metric in `float(...)`),
authors `.plutus/manifest.yaml` from a tier template, captures chart baselines
*before any execution*, and validates with `load_manifest`. Boundary asks
(require confirmation): porting deps to uv (editing `pyproject.toml`, running
`uv lock`, committing `uv.lock`, setting `env.manager` / `env.lockfile`), quoting
`.env.example` placeholders, deleting module-level connections (always deferred
to the maintainer).

### Phase 4 — Verify

Smoke-runs each instrumented step on the host, runs
`plutus check . --secrets-from-env`, and confirms exit 0. On failure it matches
the symptom against `references/known-gotchas.md`. The rule is strict:
**fix manifest-side only** — never silently widen a tolerance, flip the
source-of-truth decision, or refactor the target.

### After verification

- **Phase 4.5 — Transform summary** quotes back the five decisions, lists
  architectural smells worked around but not fixed, and records manifest
  workarounds. This feeds the scoring hand-off.
- **Phase 6 — Consolidate knowledge** is silent unless the session diverged
  substantially from the documented workflow (a failure not matching a known
  gotcha, a decision outside D1–D5, a template reshape, or 3+ manifest revisions
  before green). On divergence it writes `.plutus/skill-feedback.md`; it never
  auto-promotes a gotcha — the user decides.
- **Final step** hands off to `plutus-scoring` via the `Skill` tool. The skill
  is "not done" until the score is emitted.

## The gotcha catalogue

Phase 4 troubleshooting is anchored on a numbered catalogue of known failure
modes — **G1–G7, plus G11 and G12** (there is no G8/G9/G10):

| # | Failure mode | Manifest-side fix |
|---|--------------|-------------------|
| **G1** | A transitively-imported module opens a DB connection at *import* time, so even CSV-only steps need the DB. | Set the step `network: bridge` and extend the DB secrets' `used_by`. |
| **G2** | Dependency file has internally-conflicting pins (e.g. `numpy==2.4` vs a `numba` needing `numpy<2.3`). | `uv lock` surfaces the conflict explicitly and names the offending constraint; loosen that ONE constraint in `pyproject.toml` and re-run `uv lock` (no silent strip-all). The re-locked `uv.lock` is a reviewable commit. |
| **G3** | `.env` placeholders like `HOST=<redis_host>` crash `source .env` (angle brackets are shell metacharacters). | Don't source — `eval "$(grep -E '^(K1|K2)=' .env | sed 's/^/export /')"` then `--secrets-from-env`. |
| **G4** | `visual_similarity` artifacts silently failed pre-0.2.6 when no baseline existed. | Populate `.plutus/expected/` baseline in Phase 3 before execution; 0.2.6+ makes a missing snapshot a non-blocking SKIP. |
| **G5** | Container stdout/stderr swallowed pre-0.2.6 (FAIL with no diagnostic). | Manual `docker run` repro; 0.2.6 added per-step artifact rendering. |
| **G6** | The SDK rejects `Decimal` metric values. | Cast every metric with `float(...)`. |
| **G7** | A chart baseline captured *after* the smoke-run is tautological (script compared to itself). | Capture the baseline from v1-committed bytes *before* any execution. |
| **G11** | On v0.2.9 only, the runtime volume mount bypasses `.dockerignore`, so host `.env`/`data/cache/*.parquet` leak in and a bridge step can short-circuit. | Closed on 0.2.10 by per-step staging; on 0.2.9, `rm -rf data/cache/` and wire `--secrets-from-env`. |
| **G12** | On v0.2.10+, declaring a non-empty `step.inputs` that omits the script binary makes every execution step FAIL exit 2 — `inputs` is a complete-coverage allowlist. | Use `inputs: []` (falls back to `.dockerignore`-only filtering) or expand inputs to cover everything the script reads. |

## Configuration

Install once (creates a symlink, so in-repo edits propagate immediately):

```bash
bash skills/plutus-transform/install.sh
bash skills/plutus-scoring/install.sh    # the companion it chains into
```

Then invoke with `/plutus-transform` or any trigger phrase, pointing at the repo.

## Limitations & Caveats

- **Targets `plutus-verify` 0.2.7+**; version-specific deltas live in
  `references/v<minor>.md` and are loaded at pre-flight. The uv-locked env path
  (D5 = port to uv, `env.manager: uv`) requires **0.4.0+**.
- **Manifest-side fixes only** — the skill deliberately refuses to "fix" a repo
  by loosening tolerances or refactoring source; real source fixes are deferred
  to the maintainer and recorded as smells.
- **One interactive phase** — Phase 2 is the only place it asks; the rest runs
  to completion unless a boundary ask is triggered.

## Related Features

- [plutus-scoring-skill](plutus-scoring-skill.md) — the rubric scorer it chains into.
- [authoring-tools](authoring-tools.md) — the underlying `init`/`check`/`snapshot` commands.
- [legacy-migration](legacy-migration.md) — the `plutus transfer` step it can use.

## Source Materials

- Code: `skills/plutus-transform/SKILL.md`, `skills/plutus-transform/references/`
- Report: `docs/completion-report/2026-05-27-plutus-transform-skill.md`,
  `docs/completion-report/2026-06-01-v0.2.x-leak-closure-arc-pause.md`
</content>

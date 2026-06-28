---
title: plutus-document skill + rename plutus-transform → plutus-standardize
date: 2026-06-28
status: approved (design); implementation pending
---

# plutus-document skill + `plutus-transform` → `plutus-standardize`

## Problem

The `plutus-transform` skill makes a research repo verifiable (instrument code,
author `.plutus/manifest.yaml`, get `plutus check` to exit 0) and chains into
`plutus-scoring`. It **reads** the repo's README (extracting metric tables and
chart references as truth) but never **produces or standardizes** a README. The
Plutus Reproducibility Standard requires a specific README structure (see the
reference repo `ProtoMarketMaker/README.md`) where every reported number is
reproducible by `plutus check`. Today an author must hand-write that README and
keep it consistent with the manifest by hand.

## Goal

1. A new **`plutus-document`** skill that renders/refreshes the repo's `README.md`
   to the Plutus Reproducibility Standard, with all verified facts sourced from the
   blessed groundtruth (consistent with `plutus check`/`snapshot` by construction)
   and narrative preserved / drafted / co-authored.
2. Rename **`plutus-transform` → `plutus-standardize`** to reflect "bring a repo to
   the Plutus Reproducibility Standard."
3. Chain: `plutus-standardize` → `plutus-scoring` → `plutus-document`. The new skill
   is also runnable standalone.

Non-goals (v1): a README `--check`/lint mode for CI drift detection (future);
non-README docs; auto-commit/publish (the skill writes the file; the author reviews
and commits, consistent with the standardize branch model).

## Decisions (from brainstorming)

- **D-A — README facts: render from groundtruth.** Metric tables from
  `expected.metrics[].value`, chart embeds from declared artifact paths, repro block
  from `env` + the pinned plutus-verify wheel. Consistent by construction.
- **D-B — Narrative: adaptive.** Preserve & restructure existing prose, draft gaps
  from code (marked for review), and drop into interactive co-authoring when a
  section has no recoverable source (render from scratch with the author).
- **D-C — Architecture: separate skill, chained last** (`standardize → scoring →
  document`); also standalone.
- **D-D — Names:** `plutus-standardize` (renamed) and `plutus-document` (new).

## The standard, encoded (section map)

A README template mirrors the reference repo. Each section is **G** (groundtruth-
rendered, deterministic) or **N** (narrative):

| Section | Kind | Source |
|---|---|---|
| Badges (score, type) | G | score ← `plutus-scoring`; type (`Sample`/`PROTO`) ← decision/config |
| Title + tagline | N | existing title + one-liner |
| Abstract | G+N | prose + headline IS/OOS metrics + reproducibility claim |
| Introduction | N | existing / docstrings / co-author |
| 1. Forming Algorithm Hypothesis | N | existing / code / co-author (formulas) |
| 2. Data Preparation | G | `data_sources` → source/period/fees + "Obtaining the data" (Drive tree + DB console cmd) |
| 3. Forming Set of Rules + Evaluation Metrics | G+N | rules prose; metric list ← `expected.metrics` |
| Implementation & Reproducibility | G | console scripts ← `steps[].command`; uv env setup; `.env` ← `secrets`; `plutus check` block + pinned wheel URL |
| 4. In-sample Backtesting | G | step command + metric table + chart embeds |
| 5. Optimization | G | command + optimized params (param file) + seed |
| 6. Out-of-sample Backtesting | G | command + metric table + chart embeds |
| Reference | N | existing citations |

**Bridge:** `nine_step` → README heading (`step_2_data_preparation`→§2,
`step_4_in_sample`→§4, `step_5_optimization`→§5, `step_6_out_of_sample`→§6).

**Micro-decisions:**
- Metric tables render from `expected.metrics` (value + `display_name`) so each table
  equals exactly what `plutus check` verifies. Extra display-only metrics (e.g.
  "Monthly return") are opt-in narrative, not auto-pulled from the ephemeral
  `results.json`.
- Charts embedded from their `result/…` working-tree paths (what the README links),
  matching the reference and the 0.5.0 `snapshot`-writes-`result/` behavior.
- Non-score badges (`Sample`, `PROTO`) come from a small decision/config, not
  groundtruth.

## Inputs consumed by `plutus-document`

`.plutus/manifest.yaml` (steps: id/nine_step/command/outputs; data_sources; env:
uv/lockfile/install_project; secrets; expected.metrics: name/display_name/value;
expected.artifacts: path) · chart files at `result/…` (and `.plutus/expected/…`) ·
plutus-verify version + release-wheel URL · compliance score (from scoring) ·
existing README + code docstrings · the 5 Decisions from `plutus-standardize`
Phase 2 (when chained).

## Workflow (phases — mirroring `plutus-standardize`'s style)

1. **Gather groundtruth** — load + validate manifest; collect metrics/artifacts/
   data/env/secrets/steps; resolve plutus-verify version + wheel URL; read score
   (chained) or ask/accept (standalone).
2. **Gather narrative material** — read existing README + docstrings; classify each
   N-section: *has-source* / *draft-from-code* / *needs-user*.
3. **Render G-sections** — deterministic: tables, chart embeds, data section,
   env/repro block, badges.
4. **Produce N-sections** — preserve & restructure existing prose; draft gaps
   (marked `⚠ review`); interactive co-author when a section has no recoverable
   source (hypothesis / rules / abstract).
5. **Assemble & write `README.md`** — standard order; prior README preserved by git
   (branch model). Emit a review checklist: which sections were drafted/co-authored
   and what to verify.
6. **Consolidate knowledge** — silent unless the run diverged from the documented
   shape (same Phase-6 pattern as `plutus-standardize`).

## Consistency guarantee

Because the G-sections render from committed groundtruth (manifest + declared
artifacts + pinned wheel), the README is consistent with `plutus check` by
construction. The N-sections are author intent, not verified facts.

## Rename scope (`plutus-transform` → `plutus-standardize`)

- `skills/plutus-transform/` → `skills/plutus-standardize/`; update `SKILL.md`
  frontmatter `name` + `description` (keep recognizing old phrasings like "transform
  this", "make plutus-compliant"), body references, `install.sh`, and the skill's
  `README.md`.
- Update cross-references in **live** docs/skills only (leave `docs/archive/**`
  untouched — historical record): `skills/plutus-scoring/**`, project `README.md`
  ("Scoring & skills"), `docs/feature/plutus-transform-skill.md` (rename file +
  content), `docs/feature/{plutus-scoring-skill,authoring-tools,legacy-migration,
  reproducible-env}.md`, `docs/design/{skill-layer,secret-and-leak-hardening}.md`.
- **Chain wiring:** `plutus-standardize`'s final hand-off invokes `plutus-scoring`
  (as today, renamed). `plutus-scoring`'s hand-off invokes `plutus-document` (new),
  passing the score. `plutus-document` reads the score for the badge.

## New skill layout (`skills/plutus-document/`)

- `SKILL.md` — the six-phase workflow above, with a name/description that triggers on
  "write the plutus README", "generate the standard readme", "document this repo for
  plutus", etc.
- `references/readme-template.md` — the standard README skeleton (the section map
  rendered as a template with G/N markers and placeholders), derived from the
  reference repo.
- `references/section-map.md` — the G/N table + `nine_step`→heading bridge + the
  micro-decisions, as the authoritative mapping the skill follows.
- `install.sh` — mirror the existing skills' installer.
- `README.md` — short human-facing overview.

## Testing / acceptance

The artifacts are skill (prompt) markdown, not runnable code, so acceptance is by
inspection against the reference repo:

- Rename: `grep -r plutus-transform` finds no live references (archive excluded); the
  renamed skill loads and its description still triggers on the old phrasings.
- `plutus-document` template, when mentally applied to `ProtoMarketMaker`'s manifest +
  groundtruth, reproduces that repo's README structure (sections, metric tables from
  `expected.metrics`, chart embeds at `result/…`, the `plutus check` repro block with
  the pinned wheel).
- Chain references resolve end-to-end: `standardize` → `scoring` → `document`.

---
subject: skill-layer
date: 2026-06-01
version: 1.0
status: current
---

# Skill Layer — Architecture & Design

## Overview

The skill layer is the agent-facing front-end to `plutus-verify`. The CLI
provides primitives (`init`, `transfer`, `bootstrap`, `check`, `snapshot`); the
two Claude Code skills — **`plutus-transform`** and **`plutus-scoring`** —
orchestrate those primitives into guided, end-to-end workflows that a human (or
Claude) can invoke conversationally and that converge on concrete, checkable
outcomes.

The two skills form a pipeline of their own: `plutus-transform` makes a repo
v2-verifiable and ends with `plutus check .` exiting 0, then **auto-chains** into
`plutus-scoring`, which applies the 50/25/10/15 compliance rubric and emits a
score + improvement paths + a re-run command. They were deliberately split (in
0.2.7) so that scoring can also run standalone on any already-compliant repo.

This layer also doubles as the framework's **test harness**: running the skills
against real downstream repos is how upstream defects were surfaced across the
v0.2.5→0.2.10 arc (see [secret-and-leak-hardening](secret-and-leak-hardening.md)).

## Architecture

```
trigger phrase / slash command
        │
        ▼
plutus-transform  ── Pre-flight ── Survey ── Decide ── Instrument ── Verify
   (skills/plutus-transform/SKILL.md)   │       (D1-D5)   (pv.step,    (plutus check
        │                          parallel Explore        manifest)    exit 0)
        │                          + AskUserQuestion            │
        │                                                  Phase 4.5 summary
        │                                                       │
        └──────────── Skill tool hand-off ─────────────────────►│
                                                                ▼
                                       plutus-scoring ── Score ── Improvement paths ── Re-run cmd
                                       (skills/plutus-scoring/SKILL.md)   (50/25/10/15 rubric)

both: ~/.claude/skills/<skill> ── symlink ──► repo skills/<skill>/   (edits propagate live)
```

### Components

#### `plutus-transform` — `skills/plutus-transform/`
- **Purpose:** transform a v1-ish repo into a v2-verifiable repo.
- **Structure:** Pre-flight + four sequential phases (Survey → Decide →
  Instrument → Verify) + Phase 4.5 (transform summary) + Phase 6 (knowledge
  consolidation) + a mandatory hand-off to `plutus-scoring`.
- **References:** `decision-tree.md` (the five Phase-2 decisions),
  `known-gotchas.md` (the G1–G7 / G11 / G12 catalogue), `v<minor>.md`
  (version-specific deltas loaded at pre-flight).

#### `plutus-scoring` — `skills/plutus-scoring/`
- **Purpose:** apply the compliance rubric to a v2 repo.
- **Structure:** Pre-flight + three phases (Score → Improvement paths → Re-run
  command). Read-only; does not modify the repo or run `plutus check` itself.
- **References:** `compliance-rubric.md` (the four weighted buckets).

#### Installation
Both install via `bash skills/<skill>/install.sh`, which creates a **symlink**
`~/.claude/skills/<skill>` → the repo path (not a copy). Idempotent. Because it's
a symlink, in-repo edits propagate immediately on the next session — no re-install.

## Design Principles

- **Converge on a checkable outcome.** Transform isn't "done" until
  `plutus check` exits 0 and the score is emitted.
- **One interactive phase.** `plutus-transform` asks all its questions in a
  single Phase-2 `AskUserQuestion`; everything else runs to completion modulo
  boundary asks.
- **Manifest-side fixes only.** The skill never "fixes" a repo by loosening
  tolerances, flipping the source-of-truth decision, or refactoring source. Real
  source fixes are deferred to the maintainer and recorded as smells.
- **Probe, don't hardcode.** Schema enums (`UNIT_KINDS`, `ARTIFACT_KINDS`,
  `MANIFEST_SCHEMA`) are read at runtime; version deltas come from `v<minor>.md`.
- **The skill is a feedback channel.** Phase 6 writes `.plutus/skill-feedback.md`
  when a session diverges from the documented workflow.

## Design Decisions

### Split into two skills (0.2.7)
- **Context:** transformation and scoring are distinct concerns with different
  invocation patterns — you transform once, but you might score repeatedly or
  score a repo someone else made v2-compliant.
- **Decision:** two skills; `plutus-transform` auto-chains into `plutus-scoring`
  via the `Skill` tool at the end, passing context through the Phase 4.5 summary
  (worked-around smells become scoring improvement-path item 4).
- **Rationale:** scoring is independently useful and read-only; transformation is
  a guided, mutating workflow.
- **Trade-offs:** the two must agree on the hand-off contract (the Phase 4.5
  summary shape).

### A numbered, promotable gotcha catalogue
- **Context:** the same failure modes recurred across downstream repos.
- **Decision:** encode them as numbered gotchas (G1–G7, then G11, G12 — there is
  no G8/G9/G10) with a manifest-side fix each, and a Phase-6 path that drafts
  promotion candidates without auto-promoting.
- **Rationale:** turns repeated debugging into a lookup; the human decides what
  graduates into the catalogue.

### Symlink install
- **Decision:** install via symlink, not copy.
- **Rationale:** the skills live in the framework repo and evolve with it; a
  symlink means a framework edit is live in the next Claude session with no
  re-install step.

## Data Model

- **Decision Block** (Phase 2): the five recorded answers D1–D5 (data tier,
  optimization mode, paper-trading inclusion, source-of-truth, pin fix-up).
- **Transform summary** (Phase 4.5): decisions quote-back + smells + manifest
  workarounds — the hand-off payload to scoring.
- **`.plutus/skill-feedback.md`** (Phase 6): structured what-happened /
  what-the-Skill-said / draft-promotion sections.
- **The rubric** (scoring): four buckets — Reproducible 50, Tidy 25,
  Standardized 10, Innovative 15 — total rounded to the nearest 5%.

## Error Handling & Edge Cases

- **Pre-flight gates.** `plutus-transform` warns on uncommitted changes and
  probes that `plutus_verify` is importable. `plutus-scoring` fails fast toward
  `plutus-transform`/`plutus init` if the repo isn't v2-compliant.
- **Auto-chain failure.** If `plutus-scoring` can't be invoked (e.g. not
  installed), `plutus-transform` surfaces `bash skills/plutus-scoring/install.sh`
  and stops.
- **Boundary asks.** Mutating actions outside the manifest (rewriting dependency
  files, quoting `.env` placeholders, deleting module-level connections) require
  explicit confirmation; deleting connections is always deferred.

## Performance Considerations

- Phase 1 (Survey) fans out parallel read-only `Explore` agents in a single
  message to map the repo quickly.

## The downstream feedback loop

The skills' most important architectural role is as a closed feedback loop with
real downstream repos. The arc that hardened the framework
(see [secret-and-leak-hardening](secret-and-leak-hardening.md)) was driven by
running `plutus-transform` against `cs408-2026/Group09-BuyHighSellLow` once per
release and capturing `.plutus/skill-feedback.md`. Each iteration's feedback was
the test-bench output that drove the next release. The
[skill feedback test-bench](../../memory) is the standing channel for this:
treat each issue as either an upstream fix or a documented known-limitation.

## Future Considerations

- **Other downstream tiers.** Tier 3 (DB-backed) has been the lens for the whole
  arc; running the skill against Tier 1 (committed CSVs) or Tier 2 (Drive-backed)
  repos is the recommended way to surface the next class of gaps.
- **Gotcha promotion.** G8–G10 are unallocated slots; the Phase-6 mechanism
  exists to fill them as new recurring failures graduate.
- **Version drift.** The skill targets 0.2.7+; new framework releases need a
  `references/v<minor>.md` delta entry.

## Features Covered

- [plutus-transform-skill](../feature/plutus-transform-skill.md) — the transform workflow + gotcha catalogue.
- [plutus-scoring-skill](../feature/plutus-scoring-skill.md) — the rubric scorer.
- [authoring-tools](../feature/authoring-tools.md) — the CLI primitives the skills orchestrate.

## Source Materials

- Code: `skills/plutus-transform/`, `skills/plutus-scoring/` (SKILL.md + references)
- Reports: `docs/completion-report/2026-05-27-plutus-transform-skill.md`,
  `docs/completion-report/2026-05-27-v0.2.7-byte-fallback-and-skill-split.md`,
  `docs/completion-report/2026-06-01-v0.2.x-leak-closure-arc-pause.md`
</content>

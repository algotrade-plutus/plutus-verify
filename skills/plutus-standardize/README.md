# plutus-standardize (Claude Skill)

A Claude Code Skill that brings a v1-ish Plutus trading-research repo up to the
**Plutus Reproducibility Standard**: it instruments the code, authors
`.plutus/manifest.yaml`, and runs a four-phase workflow (Survey → Decide →
Instrument → Verify) anchored on `plutus check` exiting 0, then auto-chains into
[`plutus-scoring`](../plutus-scoring/) for the rubric score, which in turn chains
into [`plutus-document`](../plutus-document/) to render the standard README.

The skill is named for its outcome (bring the repo *to the standard*) rather than a
spec-version qualifier, so it can evolve to handle future Plutus spec versions
without rename. The current frontmatter `description` carries the v1→v2 specifics
and still recognizes the older "transform" phrasings.

## Companion skills

| Skill | Intent |
|---|---|
| **plutus-standardize** (this) | Make a v1-ish repo Plutus-Reproducible (instrument + manifest + verify). Runs once per repo. |
| [**plutus-scoring**](../plutus-scoring/) | Score a compliant repo against the rubric. Standalone-invokable, or auto-chained from this skill. |
| [**plutus-document**](../plutus-document/) | Render the standard Plutus-Reproducible README from the verified groundtruth + narrative. Chained after scoring, or standalone. |

The split is by intent: standardize is a one-time setup; scoring is a recurring
read-only check; document renders the standard README and can re-run after a
re-snapshot. Chain order: **standardize → scoring → document**.

## Source data

- Case study: [../../docs/others/zbounce-v1-to-v2-upgrade.md](../../docs/others/zbounce-v1-to-v2-upgrade.md) — the Z-Bounce transformation that informed every decision in the workflow
- Design: [../../docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md](../../docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md) — phase shapes, interaction model, version-tolerance story

## Install

```bash
bash install.sh
bash ../plutus-scoring/install.sh    # also install the companions
bash ../plutus-document/install.sh
```

Each creates a symlink at `~/.claude/skills/<name>` pointing at its directory.
Idempotent — re-running prints a "symlink already exists" note. Edits in-repo are
picked up on the next Claude Code session because the install is a symlink, not a
copy.

Invoke as `/plutus-standardize` in any Claude Code session, or rely on
description-based autoload from trigger phrases like "make this repo
plutus-compliant", "transform this into plutus v2", or "integrate plutus-verify".

## Status

Content-complete. SKILL.md has all four phase bodies, the Phase 4.5 summary, Phase 6
consolidation, and the final hand-off step that invokes `plutus-scoring` (which
chains to `plutus-document`). `references/` has the gotcha catalogue (G1–G7),
decision tree, per-version notes, and three manifest templates (Tier 1/2/3). The
compliance rubric lives in `../plutus-scoring/references/`.

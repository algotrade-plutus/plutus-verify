# plutus-transform (Claude Skill)

A Claude Code Skill that standardizes the transformation of v1-ish Plutus trading-research repos into v2-verifiable repos. Runs a four-phase workflow (Survey → Decide → Instrument → Verify) anchored on `plutus check` exiting 0, then auto-chains into the [`plutus-scoring`](../plutus-scoring/) skill for the rubric score and re-run command.

The skill is named generically (no `v1-to-v2` qualifier) so the same skill can evolve to handle future Plutus spec versions without rename. The current frontmatter `description` carries the v1→v2 specifics.

## Companion skills

| Skill | Intent |
|---|---|
| **plutus-transform** (this) | Make a v1-ish repo v2-compliant. Runs once per repo. |
| [**plutus-scoring**](../plutus-scoring/) | Score a v2-compliant repo against the rubric. Standalone-invokable, or auto-chained from this skill. |

The split is by intent: transform is a one-time setup; scoring is a recurring read-only check.

## Source data

- Case study: [../../docs/others/zbounce-v1-to-v2-upgrade.md](../../docs/others/zbounce-v1-to-v2-upgrade.md) — the Z-Bounce transformation that informed every decision in the workflow
- Design: [../../docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md](../../docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md) — phase shapes, interaction model, version-tolerance story
- Split rationale: [../../docs/completion-report/2026-05-27-v0.2.7-byte-fallback-and-skill-split.md](../../docs/completion-report/2026-05-27-v0.2.7-byte-fallback-and-skill-split.md)

## Install

```bash
bash install.sh
bash ../plutus-scoring/install.sh   # also install the companion
```

Each creates a symlink at `~/.claude/skills/<name>` pointing at its directory. Idempotent — re-running prints a "symlink already exists" note. Edits in-repo are picked up on the next Claude Code session because the install is a symlink, not a copy.

Invoke as `/plutus-transform` in any Claude Code session, or rely on description-based autoload from trigger phrases like "make this repo plutus-compliant" or "integrate plutus-verify".

## Status

Content-complete. SKILL.md has all four phase bodies, the Phase 4.5 summary, Phase 6 consolidation, and the final hand-off step that invokes `plutus-scoring`. `references/` has the gotcha catalogue (G1–G7), decision tree, per-version notes (v0.2.5/v0.2.6/v0.2.7), and three manifest templates (Tier 1/2/3). The compliance rubric moved to `../plutus-scoring/references/` with the skill split.

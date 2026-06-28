# plutus-scoring (Claude Skill)

A Claude Code Skill that scores a Plutus v2-compliant repo against the compliance rubric (50/25/10/15: Reproducible, Tidy, Standardized, Innovative), emits ranked improvement paths, and produces a copy-pasteable re-run command for the maintainer.

Invokable standalone on any v2-compliant repo, or chained automatically from [`plutus-standardize`](../plutus-standardize/) as its final hand-off step.

## When to use

- "score this repo's plutus compliance"
- "what's our plutus score"
- "rate this repo for plutus-verify"
- "how plutus-compliant is this"

If the target repo isn't v2-compliant yet (no `.plutus/manifest.yaml`), the Skill fails fast and points the operator at `plutus-standardize` or `plutus init`.

## Source data

- Rubric: [references/compliance-rubric.md](references/compliance-rubric.md) — the 50/25/10/15 model, originally derived from the Z-Bounce case study.
- Version notes: [references/v0.2.7.md](references/v0.2.7.md) (and later versions as they ship) — scoring nuances per `plutus-verify` release.

## Install

```bash
bash install.sh
```

Creates a symlink at `~/.claude/skills/plutus-scoring` pointing at this directory. Idempotent — re-running prints a "symlink already exists" note.

Invoke as `/plutus-scoring` in any Claude Code session, or rely on description-based autoload from the trigger phrases above.

## Relationship to plutus-standardize

| | plutus-standardize | plutus-scoring |
|---|---|---|
| **Intent** | "Make this v1-ish repo v2-compliant" | "Score this v2 repo against the rubric" |
| **Phases** | Survey → Decide → Instrument → Verify → Summary → Hand-off | Score → Improvement paths → Re-run command |
| **Invocation** | Manual (user-triggered) | Standalone OR auto-chained from plutus-standardize |
| **Modifies the repo** | Yes (instruments scripts, authors manifest, etc.) | No (read-only) |

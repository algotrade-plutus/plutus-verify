# plutus-document (Claude Skill)

A Claude Code Skill that renders/refreshes a repo's `README.md` to the **Plutus
Reproducibility Standard**. Every verified fact — metric tables, chart embeds, the
data section, the environment + `plutus check` reproduction block, and the score
badge — is rendered from the blessed groundtruth (the `.plutus/manifest.yaml`,
declared artifact paths, and pinned `plutus-verify` wheel), so the README is
consistent with `plutus check` / `plutus snapshot` **by construction**. The strategy
narrative (Abstract, Introduction, Hypothesis, Rules, Reference) is preserved from
existing material, drafted from code, or co-authored.

The skill writes only `README.md`; the author reviews and commits it.

## Companion skills

| Skill | Intent |
|---|---|
| [**plutus-standardize**](../plutus-standardize/) | Make a v1-ish repo Plutus-Reproducible (instrument + manifest + verify). |
| [**plutus-scoring**](../plutus-scoring/) | Score a compliant repo against the rubric; hands off to this skill with the score. |
| **plutus-document** (this) | Render the standard README from the verified groundtruth + narrative. |

Chain order: **`plutus-standardize` → `plutus-scoring` → `plutus-document`**. This
skill is also runnable standalone to refresh the README after a re-snapshot.

## References

- [`references/section-map.md`](references/section-map.md) — the authoritative
  groundtruth → README section mapping (which sections are rendered vs narrative).
- [`references/readme-template.md`](references/readme-template.md) — the standard
  README skeleton the skill fills.
- Exemplar of the target structure: a compliant repo's `README.md` (e.g.
  `ProtoMarketMaker`).

## Install

```bash
bash install.sh
```

Creates a symlink at `~/.claude/skills/plutus-document` pointing at this directory.
Idempotent — re-running prints a "symlink already exists" note. Edits in-repo are
picked up on the next Claude Code session (symlink, not a copy).

Invoke as `/plutus-document` in any Claude Code session, or rely on
description-based autoload from phrases like "write the plutus README" or "generate
the standard readme".

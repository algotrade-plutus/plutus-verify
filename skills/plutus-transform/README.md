# plutus-transform (Claude Skill)

A Claude Code Skill that restructures a flat / script-based trading-research repo into the
**canonical installable Python project** — a `src/<pkg>/` package with console-script
entry points, a uv-locked environment, package-qualified imports, and a minimal test
suite. The canonical shape it targets is defined in
[references/canonical-layout.md](references/canonical-layout.md).

It runs six phases (Pre-flight → Survey → Decide → Restructure → Re-wire manifest →
Verify) plus a silent knowledge-consolidation phase, all on an isolated
`plutus-transform` branch.

## Optional and orthogonal

`plutus-transform` is **not** part of the standard reproducibility chain. The standard
chain makes a repo *verifiable*; this skill makes the *code* canonical.

| Skill | Intent |
|---|---|
| [**plutus-standardize**](../plutus-standardize/) | Make a repo Plutus-Reproducible (instrument + manifest + verify). |
| [**plutus-scoring**](../plutus-scoring/) | Score a compliant repo against the rubric. |
| [**plutus-document**](../plutus-document/) | Render the standard Plutus-Reproducible README. |
| **plutus-transform** (this) | Reshape code into the canonical installable package. **Optional.** |

**Detect & adapt** — the skill keys off `.plutus/manifest.yaml`:
- **manifest present** → after the restructure it re-wires the manifest's `env` + step
  commands to the new console scripts, re-greens `plutus check`, and re-snapshots the
  baselines.
- **no manifest** → it leaves canonical code and *offers* `plutus-standardize` next
  (which sets `env.install_project: true` cleanly against the new package layout).

The hand-off is always an **offer**, never an auto-chain.

## Install

```bash
bash install.sh
```

Creates a symlink at `~/.claude/skills/plutus-transform` pointing at this directory.
Idempotent — re-running prints a "symlink already exists" note. In-repo edits are picked
up on the next Claude Code session (symlink, not copy).

Invoke as `/plutus-transform` in any Claude Code session, or rely on description-based
autoload from trigger phrases like "transform this into the canonical project",
"restructure into a src/ layout", or "make this an installable package".

## Status

Draft — content-complete, **untested**. Per `superpowers:writing-skills`, a workflow skill
is validated by running it against a live candidate repo. `references/` has the
canonical-layout reference, the Phase-2 decision tree (T1–T5), the `pyproject.toml`
template, and the gotcha catalogue (GT1–GT10).

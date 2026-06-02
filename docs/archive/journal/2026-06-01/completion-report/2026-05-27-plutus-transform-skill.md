# `plutus-transform` Claude Skill — initial ship

A Claude Code Skill that standardizes the v1-ish → v2 transformation workflow for Plutus trading-research repos, anchored on `plutus check` exiting 0. Shipped as a self-contained subdirectory of this repo (`skills/plutus-transform/`) plus an idempotent symlink installer into `~/.claude/skills/`.

Source data: [`docs/others/zbounce-v1-to-v2-upgrade.md`](../others/zbounce-v1-to-v2-upgrade.md) (case study from the Z-Bounce integration). Design draft: [`docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md`](../plan/2026-05-27-skill-design-v1-to-v2-transformer.md). Execution plan: [`~/.claude/plans/i-make-a-docs-others-zbounce-v1-to-v2-up-ticklish-conway.md`](file:///Users/dan/.claude/plans/i-make-a-docs-others-zbounce-v1-to-v2-up-ticklish-conway.md).

## TL;DR

One session, three passes (scaffold → content fill → rename). Final shape: **11 files, 883 lines** under `skills/plutus-transform/`. Invocable as `/plutus-transform` or via description-based autoload from phrases like "make this repo plutus-compliant" or "integrate plutus-verify".

| Pass | What landed |
|---|---|
| **A** — Scaffold | Directory layout, frontmatter, install.sh, stub references — see "Scaffold" below |
| **B** — Content fill | Phase prompts in SKILL.md, full content in every `references/*.md`, three full manifest templates |
| **C** — Rename | `plutus-transformer` → `plutus-transform` (verb form, consistent with skill naming convention) |
| **D** — Branch isolation | Phase 3 step 1: `git init` if needed, then `git checkout -b plutus-verify-v2` before any disk writes — keeps the maintainer's `main` clean and the transformation reviewable as a single branch diff |

**No code in the verifier package itself changed.** This is purely additive tooling. `pytest` posture unchanged.

## Files (11)

```
skills/plutus-transform/
├── SKILL.md                                    138 lines
├── README.md                                    25 lines
├── install.sh                                   15 lines
└── references/
    ├── known-gotchas.md                        132 lines
    ├── compliance-rubric.md                     49 lines
    ├── decision-tree.md                         93 lines
    ├── v0.2.5.md                                39 lines
    ├── v0.2.6.md                                33 lines
    └── manifest-templates/
        ├── db-backed-loader.yaml               149 lines  (Tier 3)
        ├── drive-backed.yaml                   134 lines  (Tier 2)
        └── processed-csv-shipped.yaml          116 lines  (Tier 1)
```

## Pass A — Scaffold

Goal: prove the layout, install path, and that `~/.claude/skills/` picks up the skill, before anyone has to read or judge phase prompts.

| Item | What landed |
|---|---|
| **Directory tree** | `skills/plutus-transform/` with `references/` and `references/manifest-templates/` subdirs. Mirrors design doc §6 verbatim. |
| **SKILL.md frontmatter** | `name`, `description` (414 chars, weaves the trigger phrases from design doc §2). YAML parses cleanly. |
| **install.sh** | Idempotent symlink installer: creates `~/.claude/skills/plutus-transform` → repo dir. Re-running prints "symlink already exists" and exits 0. Refuses to overwrite a non-symlink target. |
| **README.md** | In-repo orientation: source-data pointers, install instructions, status. |
| **References stubs** | 5 `.md` stubs + 3 `.yaml` template stubs, each pointing at its source-data section in the case study. |

Verification: layout matches plan (4 dirs + 10 files initially, later 11 after status update), install symlinks cleanly with idempotent re-run, frontmatter parses, only `skills/` is new in `git status`.

## Pass B — Content fill

Goal: turn the stubs into operational reference content the Skill body can dispatch against. Source-data faithful (no embellishment beyond the case study), structured for the phase that consumes it.

| File | Consumed by | What's in it |
|---|---|---|
| [`known-gotchas.md`](../../skills/plutus-transform/references/known-gotchas.md) | Phase 4 | 6 gotchas (**G1**–**G6**) in Symptom → Diagnosis → Fix format. G1 = module-level DB connection forces network/secret routing; G2 = conflicting requirements.txt pins; G3 = `.env` placeholder parse errors; G4 = pre-0.2.6 silent `visual_similarity` failure; G5 = swallowed container stderr; G6 = SDK rejects `Decimal` metric values. |
| [`compliance-rubric.md`](../../skills/plutus-transform/references/compliance-rubric.md) | Phase 5 | The 50/25/10/15 model (Reproducible / Tidy / Standardized / Innovative) with bucket-by-bucket scoring guides and output-format spec. |
| [`decision-tree.md`](../../skills/plutus-transform/references/decision-tree.md) | Phase 2 | 5 mutually-exclusive choices (**D1**–**D5**) with options, recommended defaults, rationale. D5 is conditional on Phase 1 detecting a pin conflict (G2). |
| [`v0.2.5.md`](../../skills/plutus-transform/references/v0.2.5.md) | Phases 3-4 | Deltas from 0.2.0: `reference_outputs` → `artifacts` rename, `unit="fraction"` introduction, `--visual-check` opt-in, snapshot-required-if-artifacts gotcha. |
| [`v0.2.6.md`](../../skills/plutus-transform/references/v0.2.6.md) | Phases 3-4 | Deltas from 0.2.5: `refcompare` → `artifact_compare` rename, non-blocking SKIP for missing snapshots, per-step artifact rendering. |
| `manifest-templates/db-backed-loader.yaml` | Phase 3 (D1=DB) | Tier 3 template with `<PLACEHOLDER>` markers. Z-Bounce-style. 4 steps. |
| `manifest-templates/drive-backed.yaml` | Phase 3 (D1=Drive) | Tier 2 template. ProtoMarketMaker-style `data_sources.raw[]` with `kind: google_drive`. 4 steps. |
| `manifest-templates/processed-csv-shipped.yaml` | Phase 3 (D1=CSV) | Tier 1 template. `data_sources.processed[]` with `kind: local`; `data_collection` step omitted entirely. 3 steps. |
| [`SKILL.md`](../../skills/plutus-transform/SKILL.md) | All phases | Pre-flight + 5 phase bodies + verification-before-completion + interaction model. 145 lines (well under the 200-line budget from design doc §6). |

**Schema-fidelity check during content fill.** Before writing the manifest templates, I confirmed against [`plutus_verify/spec/schema.py`](../../plutus_verify/spec/schema.py) that `DataSource` requires exactly `kind`, `url`, `expected_layout`, `satisfies` (with `secrets_required` optional). The Skill's runtime version probe will discover the live constraints; the templates are starting scaffolds, not authoritative.

## Pass C — Rename

Goal: align the skill name with the user's "skill should be a verb" preference and ship a clean `/plutus-transform` slash form.

| Step | What happened |
|---|---|
| **Old symlink removed** | `~/.claude/skills/plutus-transformer` deleted before the rename so it wouldn't dangle. |
| **Directory renamed** | `skills/plutus-transformer/` → `skills/plutus-transform/`. |
| **String references updated** | 5 occurrences across 3 files: `install.sh` (TARGET path), `README.md` (title + install description), `SKILL.md` (frontmatter `name:` + H1 title). `grep -rn plutus-transformer` post-rename returns nothing. |
| **README status refreshed** | Updated from "Scaffold only" to "Content-complete" while in the file. |
| **New symlink installed** | `bash install.sh` re-ran cleanly; `~/.claude/skills/plutus-transform` → repo dir. |

## Pass D — Branch isolation

Goal: keep the maintainer's `main` branch untouched and make the entire transformation reviewable as a single branch diff. Surfaced during post-completion review.

Phase 3 step 1 (new, renumbering the prior 1-6 to 2-7): before any disk writes,
- If the target is not a git repo, `git init` + baseline commit of the current state.
- `git checkout -b plutus-verify-v2` (falls back to `plutus-verify-v2-<date>` if the branch already exists).
- Subsequent steps (venv install, instrumentation, manifest authoring, .gitignore update) all land on this branch.

Pre-flight step 4 also tightened — instead of just "warn on dirty tree", it now tells the maintainer Phase 3 will branch off `HEAD` so uncommitted work is preserved on the new branch.

SKILL.md grew 138 → 145 lines. Phase 3 step count: 6 → 7.

## Decisions made (and why)

| Decision | Choice | Why |
|---|---|---|
| Where to host the skill | In this repo at `skills/plutus-transform/`, not a separate repo | Case study + design doc already live here; repo is the natural home for plutus tooling. Splitting into its own repo later is mechanical if it becomes shareable beyond `algotrade-research`. |
| Skill name | `plutus-transform` (verb), generic (no version qualifier) | Verb form is consistent with skill-naming convention; generic name survives future Plutus spec evolutions (v2 → v3) without rename. Frontmatter `description` carries current-version specifics. Resolves design doc §9 questions 1 (final name) and 2 (slash vs autoload — `/<skill-name>` works inherently). |
| SKILL.md length | 138 lines (budget was ≤200) | Phase bodies cite into `references/` rather than inlining. Keeps the entry document scannable. |
| Manifest templates | Three full templates with `<PLACEHOLDER>` markers, plus header comments documenting each placeholder | Skill fills placeholders during Phase 3 instead of constructing manifests from scratch. Placeholders are grep-able so the Skill can detect unfilled fields before validating. |
| Slash command vs custom command alias | Inherent slash invocation only; no `~/.claude/commands/plutus-transform.md` alias | `/plutus-transform` matches the skill name and triggers the Skill tool inherently. Custom command alias deferred per design doc §9 — adds maintenance for no clear benefit while the skill name is already terse. |

## Verification (final state)

- **Layout**: 11 files under `skills/plutus-transform/`, structure matches the plan.
- **Symlink**: `~/.claude/skills/plutus-transform` → repo dir; idempotent install confirmed.
- **No stale references**: `grep -rn plutus-transformer skills/` → empty.
- **YAML parses cleanly**: SKILL.md frontmatter, all 3 manifest templates (all `schema_version: '2.0'`, correct top-level keys, 4/4/3 steps respectively).
- **Git status**: only `skills/` is newly added at the repo level; no verifier-package files touched.

## Invocation

Three equivalent entry paths in a Claude Code session:

```text
/plutus-transform                                            # slash invocation
"make this repo plutus-compliant"                            # description autoload
"integrate plutus-verify into this repo"                     # description autoload
```

The Skill probes `plutus_verify.__version__` on entry and loads the matching `references/v<minor>.md` — body targets 0.2.6+, legacy versions noted in their respective reference docs.

## Out of scope (deferred to future sessions)

- **End-to-end dry-run on a real repo.** SKILL.md hasn't been exercised against an actual v1-ish repo since the content fill; first real invocation may surface phase-prompt rough edges to refine.
- **Custom command alias** (`~/.claude/commands/plutus-transform.md`). Skill is invocable by name; alias would only matter if we wanted a different shortcut form.
- **PyPI / plugin packaging.** Skill ships via local symlink today. If the skill becomes useful beyond this repo, packaging as a Claude Code plugin is the canonical distribution path.
- **Multi-language target repos.** Current templates assume Python; v2 of the Skill (or a sibling) handles Python+Rust / Python+R hybrids.
- **Schema/template auto-evolution.** The Skill's runtime version probe handles 0.2.x deltas via `references/v<minor>.md` drop-ins. A future 0.3.0 or 1.0 spec change may require new templates or new decision-tree options — additive, no Skill-body churn.

## Where to look first when iterating

- Phase prompts feel wrong on real use → [`SKILL.md`](../../skills/plutus-transform/SKILL.md)
- New gotcha discovered → append to [`references/known-gotchas.md`](../../skills/plutus-transform/references/known-gotchas.md) (Symptom/Diagnosis/Fix format)
- New plutus-verify version released → drop a `references/v<minor>.md` with the deltas; no Skill-body edit needed
- New repo shape (different data-tier flavor) → add a template under `references/manifest-templates/` and a new D1 option in [`decision-tree.md`](../../skills/plutus-transform/references/decision-tree.md)
- Scoring rubric needs tuning → [`references/compliance-rubric.md`](../../skills/plutus-transform/references/compliance-rubric.md) (bucket-by-bucket; rounds to 5%)

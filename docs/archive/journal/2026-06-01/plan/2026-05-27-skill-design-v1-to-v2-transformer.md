# Design: `plutus-v1-to-v2-transformer` Claude Skill

> **For the Claude Code session that will implement this Skill.** High-level design only. The companion case study at [`../others/zbounce-v1-to-v2-upgrade.md`](../others/zbounce-v1-to-v2-upgrade.md) is the source data — every concrete decision, gotcha, schema constraint, and version-migration detail referenced below is fully expanded there.
>
> This document deliberately leaves implementation details (final naming, exact prompt wording, the inside of each phase's prompt) to your judgment. The goal here is shape: what the Skill is, what it isn't, and what its phases produce.

## §1 — Mission & non-goals

**Mission.** Standardize the transformation of "old" Plutus v1-ish trading-research repos into v2-verifiable repos, automated through Claude Code, anchored on `plutus check` as the verification gate. The Skill is the recommended workflow for any maintainer or downstream user who needs to land plutus-verify on a repo they didn't author.

**Non-goals.**

- **(a)** Does not modify business logic in the target repo. SDK instrumentation is purely additive at the tail of `__main__` blocks; metric/risk/return calculations are never altered.
- **(b)** Does not retroactively re-derive metrics. The Skill emits values the script already computes, casting `Decimal → float` where needed.
- **(c)** Does not gate `visual_similarity` artifact checks by default. They remain opt-in via `plutus check --visual-check` (0.2.5+ contract).
- **(d)** Does not pin to a single plutus-verify minor. Each supported version has notes in `references/v<minor>.md`; the main body is version-agnostic.
- **(e)** Does not handle non-Python repos (Rust extensions, R notebooks, hybrid stacks). Out of scope for v1; revisit when a concrete non-Python repo appears.
- **(f)** Does not silently fix architectural smells in the target repo. The Skill flags them in the final report so the maintainer can choose to fix at source on a separate PR.

## §2 — Skill discovery & invocation

**Proposed name (placeholder).** `plutus-v1-to-v2-transformer`. The next session may shorten to `plutus-transform` or similar — but the qualifier "v1-to-v2" is load-bearing for the future-extensibility story (§5).

**Trigger phrases the description should match.** Examples observed and likely:

- "make this repo plutus-compliant"
- "transform this into plutus v2"
- "integrate plutus-verify into this repo"
- "add reproducibility verification"
- "set up plutus check for this project"
- "score this repo's plutus compliance"

The Skill's frontmatter `description` should weave these into a single sentence so it autoloads when any close paraphrase appears in the conversation.

**Slash command vs. description autoload.** Recommendation: ship **both**.

- The description-based autoload is the primary entry — discoverable, no incantation needed.
- A `/plutus-transform` slash command shortcut serves power users who already know they want this workflow and want to skip the autoload heuristic.

The slash command should accept an optional repo-path argument (`/plutus-transform ~/algotrade-research/<repo>`) so it can be aimed without prior `cd`.

## §3 — Workflow phases (overview)

Five phases. Each phase has explicit entry conditions, body, and exit criteria. The phases are sequential — Phase 4 doesn't start until Phase 3's exit criteria pass. **Phase 2 is the only interactive phase**; the rest run to completion.

### Phase 1 — Survey

Inventory the target repo via parallel `Explore` subagents. Captures:

- Pipeline shape (top-level scripts, their roles)
- README-claimed metrics with verbatim values
- `requirements.txt` (and check for internal conflicts — pin compatibility, Python-version implications)
- `.env` / `.env.example` keys (grep `os.environ` / `os.getenv` across `*.py`)
- Architectural smells: module-level connections, eager imports, broken data-source paths

**Exit criteria.** Survey report present in the conversation with: pipeline diagram, full metric tables, declared env vars, smell list. Survey is a noun the Skill can produce and the user can read.

### Phase 2 — Decide

Present the (up to 5) mutually-exclusive choices via a **single `AskUserQuestion` call** with multiple questions. The questions (with recommended defaults marked):

1. **Data sourcing tier** — DB-backed loader / Drive folder / commit CSVs / layered. Default: DB-backed for repos with a working data loader script.
2. **Optimization verification mode** — `artifact_check` / `execute`. Default: `artifact_check` for stochastic optimizers (Optuna, Hyperopt, etc.) with seed pins.
3. **Paper trading inclusion** — skip / artifact_check against frozen report. Default: skip (live entrypoints aren't reproducibly verifiable).
4. **README vs. script as truth** — path A / path B. Default: path A (README authoritative).
5. **Conditional: `requirements.txt` fix-up** — only ask if Phase 1 detected pin conflicts. Options: strip all pins / pin narrowly / user fixes separately. Default: strip all pins + latest stable Python.

**Exit criteria.** Five decisions on record (or four, if no requirements.txt conflicts). Each decision is short-lived state the Skill can quote back later.

### Phase 3 — Instrument & manifest

Sequential within the phase, no further user interaction:

1. **Install wheel** into the target repo's venv (create venv if missing, install `requirements.txt`, then `pip install <wheel>[runner,charts]`).
2. **Smoke-import**: `python -c "import plutus_verify; print(plutus_verify.__version__)"`.
3. **Light-instrument scripts.** For each metric-emitting step (typically `backtesting.py` and `evaluation.py`):
   - Add `import plutus_verify as pv` to imports.
   - Append a `with pv.step("<step_id>") as r:` block at the very end of `__main__`, after existing plot calls. Use `unit="ratio"` for unbounded metrics (Sharpe, Sortino), `unit="fraction"` for `[0,1]` / `[-1,0]` metrics (drawdown, returns), `float(...)` cast every value.
4. **Author `.plutus/manifest.yaml`** from README values (path A) or script outputs (path B). The Skill picks the right manifest template from `references/manifest-templates/`.
5. **Update `.gitignore`** with the 5 plutus-verify ephemera lines.

**Exit criteria.** `.plutus/manifest.yaml` validates via `plutus_verify.spec.loader.load_manifest(...)`. Scripts have their `pv.step` blocks. `.gitignore` updated.

### Phase 4 — Verify

1. **Smoke-run on host** (not Docker): `python <data-loader-if-applicable>.py`, then each instrumented script. Confirms `.plutus/run/<step_id>/results.json` files materialize and (eyeball) values are within tolerance of README claims.
2. **Optional snapshot** for `visual_similarity` artifacts. **Required only pre-0.2.6**; in 0.2.6+ the missing-snapshot SKIP is non-blocking. When run, *always* `--no-metrics --no-run` to preserve README values.
3. **`plutus check . --secrets-from-env`.** Capture full output. Confirm exit=0.

**Exit criteria.** `plutus check` exits 0. All required metrics show `ok` in the report. If FAIL appears, the Skill diagnoses (see §5 of the case study) and *either* fixes the manifest *or* surfaces the discrepancy to the user — never silently widens tolerance or flips path A → path B.

### Phase 5 — Score & report

Compute the 50/25/10/15 score from the rubric in `references/compliance-rubric.md` and present to the user:

- Per-bucket reasoning (what's there, what's missing)
- Total score rounded to 5%
- Concrete "what would push your score higher" suggestions
- A list of "architectural smells we worked around but didn't fix" — pointing the maintainer at proper-fix candidates for a separate PR

**Exit criteria.** Score message printed. Skill declares done.

## §4 — Interaction model

**Interactive by design, not autonomous.** The Skill is paired with a human, not a batch job. Two design rules:

1. **Decision dialogue is confined to Phase 2.** Once decisions are made, Phases 3 / 4 / 5 run without interruption unless a hard error appears. No "and one more question" mid-execution; no decisions hidden inside long phases.

2. **Confirm before crossing the "modify repo code/config" boundary.** SDK instrumentation in `__main__` tails is bounded enough to be in scope without per-instance confirmation. But:
   - Stripping `requirements.txt` pins: ask first (it's a tracked-file edit; was the user-driven mid-stream decision in the Z-Bounce case).
   - Quoting `<placeholder>` values in `.env.example`: ask first.
   - Deleting module-level connections (e.g. `database/data_service.py:77` in Z-Bounce): always defer to the maintainer; surface as a smell, never fix.

**Surface, don't silently refactor.** Phase 5's report includes a "we worked around X; the proper fix is Y in the repo source" section. This is the bridge between automated transformation and proper repo-side cleanup — the Skill makes the gap visible without forcing the user's hand.

## §5 — Version tolerance & extensibility

The Skill should outlive `plutus-verify` 0.2.6 with minimal churn.

**Schema is the source of truth, not the Skill body.** Concretely:

- Phase 3's manifest authoring imports `plutus_verify.spec.schema` and `plutus_verify.sdk.schema` at runtime via a small Python probe script. Allowed `UNIT_KINDS`, `ARTIFACT_KINDS`, `NINE_STEP_KEYS`, and the `expected[]` shape are discovered, not hardcoded.
- The Skill probes `plutus_verify.__version__` at Phase 3 start and loads the matching `references/v<minor>.md` — e.g. `v0.2.6.md` today, `v0.3.0.md` tomorrow. Each per-version doc encodes only the *differences from the previous version* (manifest field renames, new unit kinds, new CLI flags). The Skill body doesn't change.

**Future-proofing for new Plutus standards.** When v3 of the spec lands (post-2026):

- The 5 workflow phases (Survey / Decide / Instrument / Verify / Report) almost certainly remain.
- New decisions might land in Phase 2's `AskUserQuestion` call (e.g. a new data-tier).
- New manifest templates live in `references/manifest-templates/` as drop-in additions.
- New per-version notes in `references/v<minor>.md`.

The Skill name's `v1-to-v2` qualifier could become a lie if v3 lands and the same Skill handles v2-to-v3 — but the rename is mechanical and the next-next session can decide whether to ship a sibling skill or evolve this one.

## §6 — Bundled references structure

Proposed `references/` subdirectory (next session refines):

```
~/.claude/skills/plutus-v1-to-v2-transformer/
├── SKILL.md                                    # ≤200 lines: phases, interaction model, version probe
└── references/
    ├── known-gotchas.md                        # the catalogue from case study §5
    ├── compliance-rubric.md                    # the 50/25/10/15 scoring
    ├── decision-tree.md                        # Phase 2's questions w/ defaults & rationale
    ├── manifest-templates/
    │   ├── db-backed-loader.yaml               # Tier 3 — Z-Bounce shape
    │   ├── drive-backed.yaml                   # Tier 2 — ProtoMarketMaker shape
    │   └── processed-csv-shipped.yaml          # Tier 1
    ├── v0.2.5.md                               # plutus-verify 0.2.5 quirks (artifacts: rename, unit=fraction, --visual-check)
    └── v0.2.6.md                               # 0.2.6 deltas (artifact_compare rename, non-blocking SKIP)
```

The main `SKILL.md` stays short (≤200 lines): high-level workflow, version-probe logic, pointers into references. The bulk lives in `references/` so adding a new version or a new manifest template is a drop-in operation.

## §7 — Hooks & tools the Skill needs

The Skill is a workflow, not a custom tool. It composes existing Claude Code primitives. No new MCP servers required.

| Tool | Phases | Purpose |
|---|---|---|
| `Bash` | 3, 4 | `pip install`, `plutus check`, occasional `docker run` for crash repro |
| `Read` | 1, 3, 4 | Repo inventory, schema probing, log parsing |
| `Edit` | 3 | Surgical SDK instrumentation in scripts; `.gitignore` append |
| `Write` | 3 | `.plutus/manifest.yaml` from template |
| `AskUserQuestion` | 2 | The decision dialogue |
| `Agent` (subagent_type=`Explore`) | 1 | Parallel Phase-1 inventory (README + scripts + deps + env in one round) |
| `TaskCreate` / `TaskUpdate` | all | Per-phase progress visibility |

Optionally:

- Hook into `superpowers:verification-before-completion` (if available) before Phase 5 declares done.
- Hook into `superpowers:brainstorming` if the user asks for help framing innovative-bucket improvements (Phase 5 score commentary).

## §8 — Verification before completion

The Skill must mechanically verify before declaring done:

1. `plutus check . --secrets-from-env` exits 0
2. The check report shows `ok` for every required step
3. The check report shows `ok` for every declared `expected.metrics[]` entry
4. The compliance score is emitted with per-bucket reasoning
5. The "what would push your score higher" section is present
6. A second `plutus check` invocation produces the identical exit code (no flakiness — sanity check for nondeterministic steps that snuck through)

If any check fails, the Skill does *not* declare done. It surfaces the failure, diagnoses (per `references/known-gotchas.md`), and either fixes manifest-side or asks the user for direction.

## §9 — Open questions for the next session

Deliberately deferred. The next Claude Code session that implements this Skill decides:

1. **Final Skill name.** `plutus-v1-to-v2-transformer` is descriptive but long. `plutus-transform` is terser at the cost of dropping the version qualifier.
2. **Slash command shipped or autoload only?** Recommendation in §2 is both; the next session may decide to start with autoload and add a slash command in a follow-up.
3. **`requirements.txt` rewriter — opinionated or advisory?** The Skill could automatically strip pins and re-pin to resolver output (opinionated) *or* just surface the conflict and ask (advisory). The Z-Bounce case suggests advisory-with-recommendation: tell the user "stripping pins will fix this; want me to?" — and obey their choice.
4. **`plutus bootstrap` vs. hand-authoring as the default Phase-3 manifest path.** Z-Bounce was hand-authored (path A). ProtoMarketMaker was bootstrap-then-fill. The two paths produce equivalent final manifests but differ in cognitive flow. Recommendation: hand-author for repos where the README has *all* the metric claims (path A is obvious); bootstrap for repos where some metrics aren't documented and need to be discovered from script output (path B).
5. **Skill should auto-detect "this should be fixed at source" patterns** — module-level connections, broken pins, unquoted env placeholders — and surface them in Phase 5's report. Where's the line between detection (good) and lecturing (annoying)?
6. **Multi-language target repos.** When (not if) a hybrid Python+Rust or Python+R repo shows up, the manifest's `env` block is no longer sufficient. Defer to a "v2 of the Skill" rather than retrofit now.

---

End of design draft. The next session reading this should feel they have the shape but not the recipe — that's intentional. Implementation specifics (prompt wording, exact phase boundaries, which subagent prompts) should be informed by the case study, not pre-specified here.

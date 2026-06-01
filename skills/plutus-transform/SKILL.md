---
name: plutus-transform
description: Use when transforming a Plutus v1-ish trading-research repo into a v2-verifiable repo — recognises phrases like "make this repo plutus-compliant", "transform this into plutus v2", "integrate plutus-verify", "set up plutus check", "add reproducibility verification". Runs a four-phase workflow (Survey → Decide → Instrument → Verify) anchored on `plutus check` exiting 0, then auto-chains into the `plutus-scoring` skill for the rubric score and re-run command. For scoring an already-v2-compliant repo without transforming, invoke `plutus-scoring` directly.
---

# plutus-transform

Standardize the transformation of v1-ish Plutus trading-research repos into v2-verifiable repos. Anchored on `plutus check .` exiting 0 with all README-claimed metrics matching script output within declared tolerance.

The workflow runs four sequential phases (Survey → Decide → Instrument → Verify), then a short Phase 4.5 (Transform summary), then Phase 6 (Consolidate knowledge — silent unless this session required substantive deviation from the documented workflow), then a final hand-off step that invokes the [`plutus-scoring`](../plutus-scoring/SKILL.md) skill for the compliance score and re-run command. Phase 2 is the only interactive phase; the rest run to completion unless a hard error appears. Body targets `plutus-verify` 0.2.7+; legacy-version deltas live in `references/v<minor>.md`.

## Pre-flight (before Phase 1)

1. Confirm target repo path. Default to CWD; accept an explicit path argument.
2. Confirm `plutus_verify` is importable in the target's venv. If missing, install via `pip install plutus-verify` (or symlink the local wheel from this repo's `dist/` if working off-tree).
3. Probe version: `python -c "import plutus_verify; print(plutus_verify.__version__)"`. Load the matching `references/v<minor>.md` and apply its rules to Phases 3-4.
4. Warn (don't block) if the target repo has uncommitted changes. Phase 3 will branch off `HEAD`, so any in-progress work is preserved on the new branch — but the maintainer should know. Also: a clean working tree is load-bearing for Phase 3 step 5's chart-baseline copy (the v1-committed bytes need to be on disk).

## Phase 1 — Survey

Dispatch parallel `Explore` subagents (single message, multiple `Agent` calls):

- **Pipeline shape**: top-level scripts, their roles, invocation pattern (`if __name__ == "__main__"` blocks)
- **README claims**: verbatim metric tables, chart references (markdown image links + HTML `<img>` tags), IS/OOS date ranges, risk-free rate assumptions
- **Dependencies**: probe **`pyproject.toml` first**, then `requirements.txt` as fallback. The skill writes whichever it found into `env.requirements_file`; on 0.2.8+ the framework emits the right `pip install` invocation per file kind (`pip install .` for pyproject.toml, `pip install -r <file>` for requirements.txt). Pin conflicts (G2 in `references/known-gotchas.md`), implicit Python version.
- **Secrets & env**: `grep -rn 'os.environ\|os.getenv' --include='*.py'`; cross-reference with `.env.example`
- **Architectural smells**: module-level connections (G1), broken data paths (e.g. missing F2M leg), `.env` placeholders (G3), CSVs vs Drive vs DB sourcing

Synthesize a Survey Report with all five sections. Carry smells forward to Phase 4.5's "architectural smells we worked around" list.

**Exit criteria**: report present in the conversation; pin-conflict flag set if Phase 1 found one (drives D5 below); chart-reference list captured for Phase 3 step 5.

## Phase 2 — Decide

Single `AskUserQuestion` call with the questions from `references/decision-tree.md`:

- **D1**: data sourcing tier — DB-backed / Drive / processed CSVs / layered
- **D2**: optimization verification mode — `artifact_check` / `execute`
- **D3**: paper-trading inclusion — skip / artifact_check
- **D4**: README vs script as truth — path A / path B
- **D5**: requirements.txt fix-up — strip all / narrow / keep as-is. Defaulted to **strip all** because pin conflicts are common in v1-ish repos (Z-Bounce hit this; ProtoMarketMaker hit this). Always asked, regardless of whether Phase 1 detected a conflict — pre-empting the conflict is cheaper than diagnosing it mid-install.

Record the answers as a Decision Block; quote back in Phase 4.5.

**Exit criteria**: 5 decisions on record.

## Phase 3 — Instrument & manifest

Sequential, no further user interaction except the "boundary" cases below.

1. **Branch isolation** — **before any disk writes**, isolate the transformation on its own branch so the maintainer's `main` stays untouched and the changes are easy to review or discard:
   - If the target is not a git repo (`git rev-parse --is-inside-work-tree` fails): `git init`, then `git add -A && git commit -m "initial state before plutus-verify integration"` to create a baseline commit.
   - Create the working branch: `git checkout -b plutus-verify-v2`. If it already exists, fall back to `plutus-verify-v2-<YYYY-MM-DD>` to avoid clobbering prior work.
   - Confirm the branch is current: `git branch --show-current` should print the new branch name.

   All subsequent edits in Phases 3-4 land on this branch. The maintainer reviews the final diff before merging to `main`.

2. **Venv install**:
   - Create venv if missing (`python -m venv .venv`). Hidden dotfile so it stays out of plain `ls` output and aligns with the common `.venv` convention.
   - **If the repo has `pyproject.toml`** (preferred — Phase 1 already established this):
     - Apply D5 to the `dependencies` / `[tool.poetry.dependencies]` / `[tool.uv.sources]` block: same options (strip all / narrow / keep as-is). Strip-all on pyproject.toml means removing version specifiers from the dependency list, leaving bare package names.
     - `pip install .` then `pip install plutus-verify`.
   - **Else (requirements.txt only)**:
     - Apply D5 to `requirements.txt`:
       - **strip all** (default) — overwrite the file with all `==`/`~=`/`>=` pins removed, leaving bare package names. Pip's resolver picks a consistent set. Commit the rewritten file on the branch so the change is visible in the final diff.
       - **narrow** — only re-pin packages the maintainer named (e.g. `numpy<2.3`); leave others bare.
       - **keep as-is** — leave the file untouched; install will likely surface **G2** mid-stream.
     - `pip install -r requirements.txt` then `pip install plutus-verify`.
   - If install fails despite D5 = strip-all (rare — usually means a transitive needs an OS package), surface **G2** and ask the maintainer for direction.
3. **Schema probe** — discover allowed values at runtime, don't hardcode:
   ```python
   from plutus_verify.sdk.schema import UNIT_KINDS, ARTIFACT_KINDS
   from plutus_verify.spec.schema import MANIFEST_SCHEMA   # or equivalent
   ```
4. **Light-instrument metric-emitting scripts** (typically `backtesting.py`, `evaluation.py`):
   - Add `import plutus_verify as pv` to the third-party imports group.
   - Append `with pv.step("<step_id>") as r:` at the very end of `if __name__ == "__main__":`, after existing plot calls.
   - `unit="ratio"` (default) for unbounded ratios; `unit="fraction"` for `[0,1]` / `[-1,0]` values (drawdown, returns).
   - Wrap every `r.metric()` value in `float(...)` — see G6.
   - **Never modify existing lines**. Instrumentation is additive only.
5. **Author `.plutus/manifest.yaml`** from `references/manifest-templates/<tier>.yaml` (selected by D1). Fill all `<PLACEHOLDER>` markers. Set `env.requirements_file` to whatever Phase 1 detected (`pyproject.toml` if present, else `requirements.txt`) — the template ships with `requirements.txt` as a placeholder. **This step has two parallel LLM-extraction sub-steps for D4 = path A:**

   a. **Metric values from README.** `expected.metrics[].value` entries come verbatim from the README's reported numbers (the public claim the verifier exists to check). Match metric names by canonical snake_case (Sharpe → `sharpe_ratio`, etc.). For D4 = path B, defer values to Phase 4's smoke-run output.

   b. **Chart baselines from README.** For each declared `expected.artifacts[].path`, search the README for a chart reference at that path — markdown `![alt](path)` or HTML `<img src="path">`. If the referenced file exists at `<repo>/<path>`, copy it (mechanical `cp`) into `.plutus/expected/<step_id>/<path>`. This captures the v1-published chart as the verification baseline **before any new execution overwrites the file**. The operation is symmetric with sub-step (a): both extract README-claimed truth into the verification spec, at the same point in the workflow. Declared artifacts with no README reference: leave the baseline empty — the comparator's missing-expected SKIP path handles it. For D4 = path B, defer the baseline to Phase 4's smoke-run output (via `plutus snapshot`).

6. **Validate** the manifest:
   ```python
   from plutus_verify.spec.loader import load_manifest
   load_manifest(".plutus/manifest.yaml")   # raises on invalid
   ```
7. **Update `.gitignore`** — append (skip lines already present):
   ```
   # python venv (created in Phase 3 step 2)
   .venv/

   # plutus-verify ephemera
   .plutus/run/
   .plutus/build/
   .plutus/Dockerfile.generated
   .plutus/manifest.yaml.draft
   .plutus/manifest_TODO.md
   ```

**Boundary asks** (require user confirmation before applying):
- Stripping/rewriting `requirements.txt` or the `dependencies` block in `pyproject.toml` (D5).
- Quoting `<placeholder>` values in `.env.example`.
- Deleting module-level connections (G1 source fix) — **always defer**; surface in Phase 4.5 instead.

**Exit criteria**: manifest validates; every metric-emitting script has its `pv.step` block; `.plutus/expected/<step>/<chart_path>` is populated for every README-referenced chart that's declared as an artifact (D4 = path A); `.gitignore` updated.

## Phase 4 — Verify

1. **Smoke-run on host** (not Docker yet). For each instrumented step:
   ```bash
   python <script>.py
   ls .plutus/run/<step_id>/results.json
   ```
   Eyeball values against README (path A) or capture for filling the manifest (path B). Note: the smoke-run overwrites any chart files at the script's declared output paths — for D4 = path A, Phase 3 step 5b already snapshotted the v1 versions to `.plutus/expected/`, so this overwrite is fine.

2. **For D4 = path B only**: `plutus snapshot --no-run --no-metrics .` to capture the smoke-run's output as the verification baseline (D4 path B means "script is truth"). Skip for D4 = path A — the baseline was already copied from README references in Phase 3 step 5b.

3. **`plutus check . --secrets-from-env`** and confirm exit=0. Capture full output. On 0.2.7+, expect `ok byte_identical` lines for deterministic charts and `WARN byte_identical` lines for charts with timestamp / font / floating-point jitter — both are non-blocking.

4. **On FAIL**, match the symptom against `references/known-gotchas.md`:
   - `FAIL <step>: exit=1`, no stderr → **G1** (module-level connection) or **G5** (swallowed stderr) → manual `docker run` repro
   - `ValueError: metric value must be a number; got Decimal` → **G6** → cast with `float(...)`
   - `psycopg2.OperationalError: could not translate host name` → **G1** → `network: bridge` + secret routing
   - `.env: parse error near '\n'` → **G3** → `eval "$(grep ... | sed)"` instead of `source .env`
   - `FAIL visual_similarity ... [produced file not found]` (the only artifact comparator that can hard-FAIL on 0.2.7+) → script didn't write its declared chart; surface as a code bug in Phase 4.5

Fix manifest-side. **Never silently widen tolerance, flip path A → path B, or refactor target-repo source.**

**Exit criteria**: `plutus check` exits 0; every declared `expected.metrics[]` entry shows `ok` in the report; every declared `expected.artifacts[]` shows `ok` / `SKIP` / `WARN` (never `FAIL`).

## Phase 4.5 — Transform summary

A brief, non-interactive transcript section that captures transform-specific context the downstream `plutus-scoring` chain consumes:

1. **Decisions made** — quote back the 5 D-block answers from Phase 2.
2. **Architectural smells we worked around but didn't fix** — surface from Phase 1's smell list and any Phase 4 fixes that papered over a real issue. Examples: "Module-level DB connection at `database/data_service.py:102` — manifest workaround routes DB secrets to backtest steps; clean fix is to make the connection lazy." These are detection-only pointers for a separate maintainer-side PR. **Never silent fix.**
3. **Workarounds applied to the manifest** — `network: bridge` routing, secret routing to non-DB steps, etc., with the smell they paper over.

This summary feeds Phase 2 item 4 of the `plutus-scoring` chain. When the operator invokes `plutus-scoring` standalone (no transform context), item 4 is omitted.

**Exit criteria**: summary section emitted; downstream `plutus-scoring` invocation has the context to surface item 4.

## Phase 6 — Consolidate knowledge

**Always runs, but stays silent unless this session required substantive AI-agent navigation beyond the documented workflow.** The point of Phase 6 isn't to file paperwork on every successful run — it's to catch divergence-worth-promoting so the Skill keeps learning, without making the operator review a non-finding every time.

**Trigger threshold — emit a substantive report only if at least one of the following happened during Phases 1-4.5**:

- A failure pattern was diagnosed that didn't pattern-match to G1-G7 in [`references/known-gotchas.md`](references/known-gotchas.md) (cost: 3+ exchanges of investigation, or a manual `docker run` repro that surfaced something new).
- A Phase-2 decision didn't fit D1-D5 cleanly — the AI improvised an option, merged options, or had to invent a new branch.
- The chosen manifest template needed structural reshape beyond placeholder filling (added a new top-level key, a step type, a `data_source.kind` value, etc.).
- Plutus-verify behavior diverged from what `references/v<minor>.md` documents (a flag, a field, an error message that the version notes don't cover).
- Phase 4 took 3+ revisions of the manifest before `plutus check` exited 0 (signal that something subtle didn't fit the standard playbook).

If **none** of these fired, Phase 6 emits one line: `Phase 6: no divergence detected — Skill shape worked cleanly for this repo.` That's the whole output. Don't write `.plutus/skill-feedback.md`; the absence of the file is itself the "all clean" signal.

If **any** of them fired, write `.plutus/skill-feedback.md` with one section per category above. Each section captures:

- **What happened** — the divergence, with concrete excerpts (failure message, decision the AI made, manifest reshape applied)
- **What the Skill's current shape said** — the closest documented gotcha / decision / template / version-note, and *why* it didn't fit
- **Draft promotion** — a ready-to-paste block (a new G8 in `known-gotchas.md` format, or a 4th option for D1 in `decision-tree.md` format, etc.) the operator can lift into the Skill verbatim if they choose

Present the file path and a one-paragraph summary to the user, then continue to the final hand-off. The user decides whether to harness the findings (fold them into `~/.claude/skills/plutus-transform/references/` in a follow-up session) or leave them as repo-local notes. The Skill does not auto-promote.

This phase is harness-able: across N transformed repos, `find . -name skill-feedback.md` surfaces every divergence the Skill has ever encountered. Patterns that repeat across multiple repos are the strongest candidates for promotion.

**Exit criteria**: either `Phase 6: no divergence detected` printed (silent path), or `.plutus/skill-feedback.md` written with the user notified (substantive path).

## Final step — Hand off to plutus-scoring

Invoke the [`plutus-scoring`](../plutus-scoring/SKILL.md) Skill via the `Skill` tool, passing the target repo path as the argument. This produces:

- Per-bucket compliance score (50/25/10/15)
- Total, rounded to 5%
- Ranked improvement paths
- Architectural smells worked around (item 4) — populated from this skill's Phase 4.5 summary
- Re-run command block

The hand-off is mandatory — the Skill is not "done" until the score has been emitted. If `plutus-scoring` fails to invoke (e.g., the user has not installed it), surface the install instruction (`bash skills/plutus-scoring/install.sh`) and stop.

## Verification before completion

Mechanical checks before declaring done:

- `plutus check . --secrets-from-env` exits 0.
- The check report shows `ok` for every required step and every declared `expected.metrics[]` entry; artifacts show `ok` / `SKIP` / `WARN` (no `FAIL`).
- Phase 4.5 summary is emitted (decisions + worked-around smells + manifest workarounds).
- A second `plutus check` invocation produces the same exit code (sanity check for non-determinism).
- Phase 6 produced one of: a `Phase 6: no divergence detected` line, or `.plutus/skill-feedback.md` in the target repo with a one-paragraph user-facing summary.
- `plutus-scoring` Skill has been invoked and its three outputs (score, improvement paths, re-run command) are visible in the transcript.

If any check fails, do **not** declare done. Diagnose per `references/known-gotchas.md` and either fix manifest-side or surface for user direction.

## Interaction model

- Phase 2 is the only interactive phase. Phases 3/4/4.5 run without user interruption unless a hard error appears. Phase 6 always runs but is non-interactive — it either prints a one-line "no divergence" or emits `.plutus/skill-feedback.md` and notifies the user; the user decides whether to act on the file in a follow-up session. The final hand-off invokes `plutus-scoring`, which is also non-interactive.
- The "modify repo source/config" boundary requires confirmation: requirements.txt edits, .env.example edits, source-level refactors. SDK instrumentation in `__main__` tails is in-scope without per-instance confirmation. The Phase 3 step 5b chart-baseline copy is read-only on the source tree (just copies committed files into `.plutus/expected/`) and is in-scope without confirmation.
- Architectural smells are **surfaced, never silently fixed**. The Skill is the bridge between automated transformation and proper repo-side cleanup — it makes the gap visible without forcing the maintainer's hand.

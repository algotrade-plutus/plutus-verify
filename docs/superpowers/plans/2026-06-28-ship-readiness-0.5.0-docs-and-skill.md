# Ship-readiness for 0.5.0 — CHANGELOG, docs & skill updates — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Bring the project's docs and the `plutus-standardize` / `plutus-scoring` skills into consistency with the already-shipped 0.5.0 behavior so the release is coherent.

**Architecture:** Documentation + Claude-skill (prompt-markdown) edits only. No runtime code changes. "Tests" are mechanical verification (grep / structural checks).

**Tech Stack:** Markdown (`CHANGELOG.md`, `docs/feature/*`, `skills/**`).

## Global Constraints

- The 0.5.0 behavior to reflect (already implemented): `check` is read-only (produced artifacts → gitignored `.plutus/results/`, compared there); `snapshot` runs in-container by default and writes `.plutus/expected/` + `result/`; step `stdout`/`stderr` persist to `.plutus/run/<step>/` + stderr tail in report; data sources fetch into gitignored `.plutus/cache/`; `gdown` is in the `runner` extra; `plutus init` scaffolds `.dockerignore`; opt-in `env.install_project` (uv-only) installs the repo's package; dev workflow is uv (`uv sync` + `uv run pytest`).
- Do NOT touch `docs/archive/**` (historical).
- Skills must keep producing repos that gitignore **all** ephemeral dirs: `.plutus/run/`, `.plutus/results/`, `.plutus/cache/`, `.plutus/build/`.
- One commit per task. Verify before each commit.

---

### Task 1: CHANGELOG.md — add the 0.5.0 entry

**Files:** Modify `CHANGELOG.md` (insert a `## [0.5.0]` block above `## [0.4.3]`).

- [ ] **Step 1:** Insert a `## [0.5.0] — 2026-06-28` block immediately before `## [0.4.3]`, mirroring the existing Added/Changed/Fixed style. Cover, grouped:
  - **Changed — `check` is read-only; `snapshot` runs in-container.** Produced artifacts harvest to gitignored `.plutus/results/<step>/` and compare there (never overwrite `result/`); the inter-step bus runs through that buffer. `snapshot` builds + runs in-container by default and writes the groundtruth (`.plutus/expected/` + `manifest.yaml` values) plus a human-facing `result/` copy; `--no-run` keeps the local-bytes path.
  - **Added — `env.install_project`** (opt-in, uv-only): install the repo's own package so its console scripts / importable package work in step commands (src-layout repos). Default false.
  - **Added — failure diagnostics**: step `stdout`/`stderr` persist to `.plutus/run/<step>/`; the report prints a stderr tail on failure.
  - **Fixed — `check` no longer dirties the working tree with downloads**: data sources fetch into the gitignored `.plutus/cache/` (persisted across runs) and overlay into each step's sandbox.
  - **Fixed — `gdown` is a declared dependency** (in the `runner` extra).
  - **Changed — `plutus init` scaffolds `.dockerignore`** at setup time (read-only `check` no longer surprise-writes it).
  - **Changed — dev workflow adopts uv** (`uv sync` + `uv run pytest`; `uv.lock` committed; dev tooling in a PEP 735 group).
  - **Changed — skills**: `plutus-transform` renamed to `plutus-standardize`; new `plutus-document` skill renders the standard README from groundtruth + narrative (chain: standardize → scoring → document).

- [ ] **Step 2: Verify**

```bash
grep -n '## \[0.5.0\]' CHANGELOG.md
grep -A40 '## \[0.5.0\]' CHANGELOG.md | grep -E "install_project|.plutus/results|.plutus/cache|gdown|plutus-document|in-container"
awk '/^## \[/{print; n++} n==2{exit}' CHANGELOG.md   # 0.5.0 then 0.4.3, in order
```
Expected: 0.5.0 heading present; the key terms appear; 0.5.0 precedes 0.4.3.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add 0.5.0 entry"
```

---

### Task 2: `references/v0.5.0.md` for plutus-standardize (new version note)

**Files:** Create `skills/plutus-standardize/references/v0.5.0.md` (mirror the `v0.2.10.md` shape).

**Interfaces:** Produces the version note the SKILL body points at for 0.5.0 behavior; later tasks reference it.

- [ ] **Step 1:** Write the note with sections: header ("Deltas from 0.4.x. When `__version__` reports `0.5.0`+…", source link to CHANGELOG `[0.5.0]`); **Changed — read-only check + harvest buffer** (produced outputs → `.plutus/results/`, compared there; `result/` no longer overwritten — so the old "snapshot before check overwrites the file" concern is gone); **Changed — in-container snapshot** (default; writes `.plutus/expected/` + `result/`; `--no-run` is the local-bytes opt-out); **Added — data cache** (`.plutus/cache/`, gitignored, persisted); **Added — `env.install_project`** (uv-only, needs root `pyproject.toml`; for console-script/src-layout repos — see D6); **Changed — `plutus init` scaffolds `.dockerignore`**; **Skill behavior on 0.5.0** (gitignore must include `.plutus/results/` + `.plutus/cache/`; Phase 3 step 5b note that `check` is read-only so chart baseline copy is still done for path A but no longer races an overwrite; `gdown` ships in the `runner` extra so Drive sources work out of the box); **Backward compatibility** (existing manifests unchanged; `install_project` defaults false).

- [ ] **Step 2: Verify**

```bash
for t in "read-only" ".plutus/results" ".plutus/cache" "install_project" "in-container" ".dockerignore" "gdown"; do grep -q "$t" skills/plutus-standardize/references/v0.5.0.md && echo "ok: $t" || echo "MISSING: $t"; done
```
Expected: all `ok:`.

- [ ] **Step 3: Commit**

```bash
git add skills/plutus-standardize/references/v0.5.0.md
git commit -m "feat(skill): plutus-standardize v0.5.0 version notes"
```

---

### Task 3: plutus-standardize SKILL.md — gitignore + snapshot/check semantics + version floor

**Files:** Modify `skills/plutus-standardize/SKILL.md`.

- [ ] **Step 1: Gitignore block (Phase 3 step 7).** Add `.plutus/results/` and `.plutus/cache/` to the appended `.gitignore` list (alongside `.plutus/run/` and `.plutus/build/`), with a one-line comment that they're the 0.5.0 read-only-check buffers.

- [ ] **Step 2: Version floor + pointer.** In the intro line "Body targets `plutus-verify` 0.2.7+; legacy-version deltas live in `references/v<minor>.md`", append that 0.4.x/0.5.0 deltas (read-only check, data cache, `install_project`) are in `references/v0.5.0.md`, and load it when `__version__` ≥ 0.5.0.

- [ ] **Step 3: Phase 3 step 5b reasoning.** Update the parenthetical that says the chart copy must happen "before any new execution overwrites the file" — on 0.5.0 `check` is read-only and `snapshot` writes `result/` itself, so for path A the README→`.plutus/expected/` copy is still done, but note the overwrite race is gone (cite `references/v0.5.0.md`).

- [ ] **Step 4: Phase 4 snapshot/check.** Update step 2 (path B baseline): on 0.5.0 prefer in-container `plutus snapshot .` (writes `.plutus/expected/` + `result/`) over `--no-run`; keep `--no-run` as the local-bytes note. Note `plutus init` scaffolds `.dockerignore` so the skill no longer needs to hand-write it (Phase 3).

- [ ] **Step 5: Verify**

```bash
grep -n ".plutus/results/" skills/plutus-standardize/SKILL.md
grep -n ".plutus/cache/" skills/plutus-standardize/SKILL.md
grep -n "v0.5.0" skills/plutus-standardize/SKILL.md
```
Expected: gitignore lines present; v0.5.0 referenced.

- [ ] **Step 6: Commit**

```bash
git add skills/plutus-standardize/SKILL.md
git commit -m "feat(skill): plutus-standardize reflects 0.5.0 read-only check + cache + gitignore"
```

---

### Task 4: install_project decision (D6) + Phase 3 wiring + template hints

**Files:** Modify `skills/plutus-standardize/references/decision-tree.md`, `skills/plutus-standardize/SKILL.md`, and the three `references/manifest-templates/*.yaml`.

- [ ] **Step 1: Add D6 to decision-tree.md.** New "## D6 — Project install (src-layout / console-script repos)" section after D5: when the repo is an installable package whose steps invoke console scripts (e.g. `pmm-backtest`) or `python -m <pkg>`, set `env.install_project: true` (uv-only; requires a `pyproject.toml` at the repo root). Default false. Phase 1 can pre-detect (`[project.scripts]` in pyproject, or `src/` layout + step commands that aren't `python <file>.py`) and recommend the answer. Add the D6 line to "Output of Phase 2" (→ `env.install_project`).

- [ ] **Step 2: Reference D6 in SKILL Phase 2 + Phase 3.** Add D6 to the Phase 2 decision list and the Phase 3 env step: when D6 = yes, set `env.install_project: true` in the manifest (requires the uv port + root `pyproject.toml`); surface in Phase 4.5.

- [ ] **Step 3: Template hints.** In each `manifest-templates/*.yaml` env block, add a commented line under `lockfile: uv.lock`:
  `# install_project: true     # uv-only: also install THIS repo's package (src-layout / console-script repos)`

- [ ] **Step 4: Verify**

```bash
grep -n "D6" skills/plutus-standardize/references/decision-tree.md
grep -rn "install_project" skills/plutus-standardize/references/manifest-templates/
grep -n "install_project" skills/plutus-standardize/SKILL.md
```
Expected: D6 present; install_project in all three templates + SKILL.

- [ ] **Step 5: Commit**

```bash
git add skills/plutus-standardize
git commit -m "feat(skill): plutus-standardize D6 install_project decision + template hints"
```

---

### Task 5: plutus-scoring — v0.5.0 scoring note

**Files:** Create `skills/plutus-scoring/references/v0.5.0.md`; add a pointer in `skills/plutus-scoring/SKILL.md` if the version-probe step enumerates notes.

- [ ] **Step 1:** Write `v0.5.0.md` (mirror `v0.2.9.md`): on 0.5.0, `check` is read-only — the Reproducible bucket's "were any tracked config files modified?" check now expects a **clean** tree after `check` (produced artifacts live in gitignored `.plutus/results/`; downloads in `.plutus/cache/`). A dirty tree after `check` is now a real smell (missing gitignore entries), not expected churn. Note `install_project` repos: a passing check means the package built + console scripts ran in-container.

- [ ] **Step 2: Verify**

```bash
for t in "read-only" ".plutus/results" "install_project" "tracked"; do grep -q "$t" skills/plutus-scoring/references/v0.5.0.md && echo "ok: $t" || echo "MISSING: $t"; done
```
Expected: all `ok:`.

- [ ] **Step 3: Commit**

```bash
git add skills/plutus-scoring/references/v0.5.0.md skills/plutus-scoring/SKILL.md
git commit -m "feat(skill): plutus-scoring v0.5.0 scoring notes (read-only check)"
```

---

### Task 6: docs/feature/reproducible-env.md — install_project + 0.5.0 note

**Files:** Modify `docs/feature/reproducible-env.md`.

- [ ] **Step 1:** In the `### Options` / `## Configuration` area, add an `env.install_project` bullet (uv-only opt-in: also installs the repo's own package so console scripts / `import <pkg>` work in steps; requires a root `pyproject.toml`; default false; link `v2-manifest.md`). In `## Limitations & Caveats`, extend the "Requires 0.4.2+ in practice" note: `env.install_project` requires **0.5.0+**.

- [ ] **Step 2: Verify**

```bash
grep -n "install_project" docs/feature/reproducible-env.md
grep -n "0.5.0" docs/feature/reproducible-env.md
```
Expected: both present.

- [ ] **Step 3: Commit**

```bash
git add docs/feature/reproducible-env.md
git commit -m "docs: note env.install_project (0.5.0) in reproducible-env"
```

---

### Task 7: Final verification

- [ ] **Step 1: CHANGELOG ⇄ README parity.** Both name the same 0.5.0 headline changes.

```bash
for t in "read-only" "in-container" "install_project" ".plutus/cache" "gdown"; do grep -q "$t" CHANGELOG.md && grep -q "$t" README.md && echo "ok: $t" || echo "CHECK: $t"; done
```
Expected: all `ok:` (or a deliberate `CHECK:` you accept).

- [ ] **Step 2: Skills gitignore completeness.** The skill's generated gitignore covers all four ephemeral dirs.

```bash
for d in ".plutus/run/" ".plutus/results/" ".plutus/cache/" ".plutus/build/"; do grep -q "$d" skills/plutus-standardize/SKILL.md && echo "ok: $d" || echo "MISSING: $d"; done
```
Expected: all `ok:`.

- [ ] **Step 3: No stale version floor.** `install_project` is consistently described as uv-only + 0.5.0 across skill, templates, and docs.

```bash
grep -rln "install_project" skills/ docs/feature README.md GUIDELINE.md
```
Expected: appears in standardize SKILL, decision-tree, templates, v0.5.0 note, reproducible-env, v2-manifest, README, GUIDELINE.

## Self-Review

- **Coverage:** #1 CHANGELOG → Task 1; #2 skill 0.5.0 (gitignore/semantics/version note/install_project) → Tasks 2-4; #3 scoring note → Task 5; #4 template hints → Task 4 Step 3; #5 reproducible-env → Task 6. All covered.
- **Placeholders:** verification steps are concrete commands; prose edits name exact sections/fields.
- **Consistency:** `env.install_project` (uv-only, 0.5.0), `.plutus/results/` + `.plutus/cache/` (gitignored), and the chain `standardize → scoring → document` are used consistently across tasks.

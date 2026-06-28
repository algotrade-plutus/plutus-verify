# plutus-document skill + plutus-standardize rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rename the `plutus-transform` skill to `plutus-standardize` and add a new `plutus-document` skill that renders the standard Plutus-Reproducible README from blessed groundtruth + narrative, chained `standardize → scoring → document`.

**Architecture:** Pure Claude-skill (prompt-markdown) authoring. No runtime code. "Tests" are mechanical verification checks (grep / file-existence / structural inspection against the reference repo `ProtoMarketMaker/README.md`).

**Tech Stack:** Markdown skill files under `skills/`, mirroring the existing `plutus-transform` / `plutus-scoring` skills.

## Global Constraints

- Reference standard README: `/Users/nadan/algotrade-research/proto/ProtoMarketMaker/README.md` (the target structure to reproduce).
- Spec: `docs/superpowers/specs/2026-06-28-plutus-document-and-standardize-rename-design.md`.
- **Do NOT touch `docs/archive/**`** — historical record; rename only updates *live* docs/skills.
- README facts render from groundtruth (`expected.metrics`, declared artifact paths, `env`, pinned wheel) — never the ephemeral `results.json`.
- Metric tables come from `expected.metrics[]` (value + `display_name`); chart embeds use `result/…` working-tree paths.
- New skill files mirror the existing skills' frontmatter/install/README conventions.
- Use `git mv` for renames so history follows. One commit per task.

---

### Task 1: Rename the skill directory and its own files

**Files:**
- Rename: `skills/plutus-transform/` → `skills/plutus-standardize/` (via `git mv`)
- Modify: `skills/plutus-standardize/SKILL.md` (frontmatter `name` + `description`; body self-references)
- Modify: `skills/plutus-standardize/README.md` (title, intent table, install block)
- Modify: `skills/plutus-standardize/install.sh` (`TARGET` path)

**Interfaces:**
- Produces: skill name `plutus-standardize`; its SKILL.md still chains to `plutus-scoring`.

- [ ] **Step 1: Move the directory**

```bash
git mv skills/plutus-transform skills/plutus-standardize
```

- [ ] **Step 2: Update `install.sh` target**

In `skills/plutus-standardize/install.sh`, change:
`TARGET="$HOME/.claude/skills/plutus-transform"` → `TARGET="$HOME/.claude/skills/plutus-standardize"`

- [ ] **Step 3: Update SKILL.md frontmatter**

Set `name: plutus-standardize`. Rewrite `description:` to lead with "Use when bringing a trading-research repo up to the Plutus Reproducibility Standard" and KEEP recognizing the old phrasings so muscle memory still triggers it: "make this repo plutus-compliant", "transform this into plutus v2", "integrate plutus-verify", "set up plutus check", "add reproducibility verification". Keep the description's note that it runs Survey → Decide → Instrument → Verify and auto-chains into `plutus-scoring`.

- [ ] **Step 4: Update SKILL.md + README body self-references**

Replace remaining `plutus-transform` self-mentions with `plutus-standardize` in `SKILL.md` and `README.md` (titles, the "Companion skills" table row, the install block `bash install.sh`). Leave links to `plutus-scoring` intact. Do NOT rewrite historical links under `docs/archive/**` (none are in these two files; the `Source data` links in README point at archived design docs — leave those paths as-is, they're historical).

- [ ] **Step 5: Verify**

```bash
grep -rn "plutus-transform" skills/plutus-standardize/ ; echo "exit=$?"
grep -n "name: plutus-standardize" skills/plutus-standardize/SKILL.md
grep -n "plutus-standardize" skills/plutus-standardize/install.sh
```
Expected: first grep prints nothing (exit=1); the other two match.

- [ ] **Step 6: Commit**

```bash
git add -A skills/plutus-standardize
git commit -m "refactor(skill): rename plutus-transform -> plutus-standardize"
```

---

### Task 2: Update plutus-scoring references + add hand-off to plutus-document

**Files:**
- Modify: `skills/plutus-scoring/SKILL.md` (refs to `plutus-transform` → `plutus-standardize`; add final hand-off to `plutus-document`)
- Modify: `skills/plutus-scoring/README.md` (ref)
- Modify: `skills/plutus-scoring/references/compliance-rubric.md` (ref)

**Interfaces:**
- Consumes: `plutus-standardize` (Task 1).
- Produces: scoring's terminal hand-off invokes `plutus-document`, passing the computed compliance score.

- [ ] **Step 1: Swap the rename references**

In the three files, replace `plutus-transform` → `plutus-standardize` and the link `../plutus-transform/SKILL.md` → `../plutus-standardize/SKILL.md`. (Leave `references/v0.2.9.md` — it is a historical version note; check it and only update if it's a live cross-ref, otherwise skip.)

- [ ] **Step 2: Add the hand-off section to scoring SKILL.md**

After the "Verification before completion" section, add a "## Hand-off — document the repo" section: once the score is emitted, invoke the `plutus-document` skill (link `../plutus-document/SKILL.md`), passing the rounded compliance score for the README badge and noting the chain origin (`plutus-standardize` Decisions + Phase 4.5 smells if present). Keep scoring itself read-only — the hand-off is an invocation, not a write.

- [ ] **Step 3: Verify**

```bash
grep -rn "plutus-transform" skills/plutus-scoring/ ; echo "exit=$?"
grep -n "plutus-document" skills/plutus-scoring/SKILL.md
```
Expected: first grep prints nothing (exit=1) OR only a historical `references/v0.2.9.md` line you deliberately left; second matches the new hand-off.

- [ ] **Step 4: Commit**

```bash
git add -A skills/plutus-scoring
git commit -m "feat(skill): chain plutus-scoring -> plutus-document; update rename refs"
```

---

### Task 3: Update live docs cross-references + rename the feature doc

**Files:**
- Rename: `docs/feature/plutus-transform-skill.md` → `docs/feature/plutus-standardize-skill.md` (via `git mv`) + update its content
- Modify: `README.md` ("Scoring & skills" section — rename + add `plutus-document`)
- Modify: `docs/feature/plutus-scoring-skill.md`, `docs/feature/authoring-tools.md`, `docs/feature/legacy-migration.md`, `docs/feature/reproducible-env.md`
- Modify: `docs/design/skill-layer.md`, `docs/design/secret-and-leak-hardening.md`

**Interfaces:**
- Consumes: skill names from Tasks 1-2.

- [ ] **Step 1: Rename the feature doc**

```bash
git mv docs/feature/plutus-transform-skill.md docs/feature/plutus-standardize-skill.md
```

- [ ] **Step 2: Update all live cross-references**

In every file listed above, replace `plutus-transform` → `plutus-standardize`. In `README.md`'s "Scoring & skills" section, rename the bullet and add a third bullet for **`plutus-document`** ("renders the standard Plutus-Reproducible README from the verified groundtruth; chained after scoring"). In `docs/design/skill-layer.md`, add `plutus-document` to the skill-layer description and the chain (`standardize → scoring → document`).

- [ ] **Step 3: Verify (live tree only; archive excluded)**

```bash
grep -rln "plutus-transform" README.md docs/feature docs/design ; echo "exit=$?"
ls docs/feature/plutus-standardize-skill.md
grep -n "plutus-document" README.md docs/design/skill-layer.md
```
Expected: first grep prints nothing (exit=1); the file exists; `plutus-document` appears.

- [ ] **Step 4: Commit**

```bash
git add -A README.md docs/feature docs/design
git commit -m "docs: rename plutus-transform -> plutus-standardize; add plutus-document refs"
```

---

### Task 4: plutus-document — `references/section-map.md`

**Files:**
- Create: `skills/plutus-document/references/section-map.md`

**Interfaces:**
- Produces: the authoritative G/N section map + `nine_step`→heading bridge + micro-decisions that `SKILL.md` (Task 6) and `readme-template.md` (Task 5) reference.

- [ ] **Step 1: Write the section map**

Author `section-map.md` containing, verbatim from the spec: (1) the G/N section table (Badges, Title, Abstract, Introduction, §1 Hypothesis, §2 Data Preparation, §3 Rules+Metrics, Implementation & Reproducibility, §4/§5/§6, Reference) with Kind and Source columns; (2) the bridge `step_2_data_preparation→§2`, `step_4_in_sample→§4`, `step_5_optimization→§5`, `step_6_out_of_sample→§6`; (3) the three micro-decisions (tables from `expected.metrics`; charts from `result/…`; non-score badges from decision/config). For each G-section, name the exact manifest field(s) it reads.

- [ ] **Step 2: Verify**

```bash
grep -nE "expected.metrics|nine_step|result/|data_sources|steps\[\].command" skills/plutus-document/references/section-map.md
```
Expected: all five field references present.

- [ ] **Step 3: Commit**

```bash
git add skills/plutus-document/references/section-map.md
git commit -m "feat(skill): plutus-document section map (groundtruth->README)"
```

---

### Task 5: plutus-document — `references/readme-template.md`

**Files:**
- Create: `skills/plutus-document/references/readme-template.md`

**Interfaces:**
- Consumes: the section map (Task 4).
- Produces: the standard README skeleton the skill fills in.

- [ ] **Step 1: Write the template**

Author a README skeleton mirroring the reference repo's structure, in order: badges line; `# <Title>` + `> <tagline>`; `## Abstract`; `## Introduction`; `## 1. Forming Algorithm Hypothesis`; `## 2. Data Preparation` (with "Obtaining the data": Drive option + data tree, DB option + console cmd); `## 3. Forming Set of Rules` + `### Evaluation Metrics`; `## Implementation & Reproducibility` (package + console scripts, `### Environment setup` uv, `.env` from secrets, `### Reproducibility` `plutus check` block with the pinned wheel URL); `## 4. In-sample Backtesting` (command + metric table + chart embeds); `## 5. Optimization` (command + optimized params + seed); `## 6. Out-of-sample Backtesting` (command + table + charts); `## Reference`. Mark each placeholder with `{{G:...}}` (groundtruth-filled) or `{{N:...}}` (narrative) tags so the skill knows which to render vs author. Include a sample metric table header (`| Metric | Value |`) and a sample chart embed line (`![<alt>](result/.../x.svg)`).

- [ ] **Step 2: Verify against the reference structure**

```bash
for h in "## Abstract" "## 1. Forming Algorithm Hypothesis" "## 2. Data Preparation" "### Evaluation Metrics" "## Implementation & Reproducibility" "## 4. In-sample" "## 5. Optimization" "## 6. Out-of-sample" "## Reference"; do grep -q "$h" skills/plutus-document/references/readme-template.md && echo "ok: $h" || echo "MISSING: $h"; done
grep -q "plutus check" skills/plutus-document/references/readme-template.md && echo "ok: repro block"
grep -qE "\{\{G:|\{\{N:" skills/plutus-document/references/readme-template.md && echo "ok: G/N tags"
```
Expected: all `ok:` lines, no `MISSING:`.

- [ ] **Step 3: Commit**

```bash
git add skills/plutus-document/references/readme-template.md
git commit -m "feat(skill): plutus-document standard README template"
```

---

### Task 6: plutus-document — `SKILL.md` (six-phase workflow)

**Files:**
- Create: `skills/plutus-document/SKILL.md`

**Interfaces:**
- Consumes: `section-map.md` (Task 4), `readme-template.md` (Task 5); the score from `plutus-scoring` (Task 2).
- Produces: the skill the scoring hand-off invokes.

- [ ] **Step 1: Write frontmatter**

`name: plutus-document`. `description:` triggers on "write/generate the plutus README", "document this repo for plutus", "produce the standard readme", "make the README plutus-compliant", and notes it renders the standard README from blessed groundtruth + narrative, runs standalone or chained after `plutus-scoring`.

- [ ] **Step 2: Write the body — the six phases**

Author the workflow from the spec: Pre-flight (confirm repo path, manifest loads, plutus-verify version + wheel URL resolvable); Phase 1 Gather groundtruth; Phase 2 Gather narrative material (+ classify has-source/draft/needs-user); Phase 3 Render G-sections (point at `references/section-map.md` + `references/readme-template.md`); Phase 4 Produce N-sections (preserve & restructure; draft gaps marked `⚠ review`; interactive co-author when no source); Phase 5 Assemble & write `README.md` + emit a review checklist; Phase 6 Consolidate knowledge (silent unless divergence). State the consistency guarantee and that it writes only `README.md` (author reviews + commits). Note standalone vs chained score sourcing.

- [ ] **Step 3: Verify**

```bash
grep -n "name: plutus-document" skills/plutus-document/SKILL.md
for p in "Pre-flight" "Phase 1" "Phase 2" "Phase 3" "Phase 4" "Phase 5" "Phase 6" "section-map" "readme-template"; do grep -q "$p" skills/plutus-document/SKILL.md && echo "ok: $p" || echo "MISSING: $p"; done
```
Expected: name matches; all `ok:`.

- [ ] **Step 4: Commit**

```bash
git add skills/plutus-document/SKILL.md
git commit -m "feat(skill): plutus-document SKILL (six-phase README authoring)"
```

---

### Task 7: plutus-document — `install.sh` + `README.md`

**Files:**
- Create: `skills/plutus-document/install.sh`
- Create: `skills/plutus-document/README.md`

- [ ] **Step 1: Write `install.sh`**

Copy `skills/plutus-standardize/install.sh` verbatim, changing `TARGET` to `$HOME/.claude/skills/plutus-document`.

- [ ] **Step 2: Write `README.md`**

Short human-facing overview: what `plutus-document` does (render the standard README from groundtruth + narrative), a "Companion skills" table (`plutus-standardize`, `plutus-scoring`, `plutus-document`), the chain `standardize → scoring → document`, and an install block.

- [ ] **Step 3: Verify**

```bash
grep -n "plutus-document" skills/plutus-document/install.sh
bash -n skills/plutus-document/install.sh && echo "install.sh syntax ok"
grep -q "standardize → scoring → document" skills/plutus-document/README.md && echo "ok: chain documented"
```
Expected: target matches; syntax ok; chain documented.

- [ ] **Step 4: Commit**

```bash
git add skills/plutus-document/install.sh skills/plutus-document/README.md
git commit -m "feat(skill): plutus-document installer + README"
```

---

### Task 8: Final verification (no live transform refs; chain resolves; template fits reference)

**Files:** none (verification only)

- [ ] **Step 1: No live `plutus-transform` references remain**

```bash
grep -rln "plutus-transform" . --exclude-dir=docs/archive --exclude-dir=.git ; echo "exit=$?"
```
Expected: prints nothing (exit=1). If any live file matches, fix it and amend the relevant task's commit.

- [ ] **Step 2: Chain resolves end-to-end**

```bash
grep -q "plutus-scoring" skills/plutus-standardize/SKILL.md && echo "standardize->scoring ok"
grep -q "plutus-document" skills/plutus-scoring/SKILL.md && echo "scoring->document ok"
```
Expected: both ok.

- [ ] **Step 3: Template fits the reference repo (manual inspection)**

Open `/Users/nadan/algotrade-research/proto/ProtoMarketMaker/README.md` beside `skills/plutus-document/references/readme-template.md`. Confirm every section heading in the reference has a corresponding template section, the metric-table and chart-embed shapes match, and the `plutus check` repro block matches. Note any gaps; fix the template (Task 5) and re-commit.

- [ ] **Step 4: Final commit (only if Step 3 required fixes)**

```bash
git add -A skills/plutus-document
git commit -m "fix(skill): align plutus-document template with reference README"
```

## Self-Review

- **Spec coverage:** D-A (groundtruth render) → Tasks 4-6; D-B (adaptive narrative) → Task 6 Phase 4; D-C (separate chained skill) → Tasks 2,6,7; D-D (names) → Tasks 1-3. Rename scope → Tasks 1-3. New-skill layout → Tasks 4-7. Acceptance → Task 8. All covered.
- **Placeholder scan:** verification steps use concrete grep/commands; new-file tasks specify exact sections/fields to author (prose authored at execution to the named structure — appropriate for skill-markdown).
- **Type consistency:** skill names (`plutus-standardize`, `plutus-document`), reference filenames (`section-map.md`, `readme-template.md`), and the chain order are consistent across all tasks.

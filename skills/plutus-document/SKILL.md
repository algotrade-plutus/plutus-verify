---
name: plutus-document
description: Use when producing or refreshing a repo's standard Plutus-Reproducible README — recognises phrases like "write the plutus README", "generate the standard readme", "document this repo for plutus", "produce the plutus-standard readme", "make the README plutus-compliant", "update the readme after re-snapshot". Renders the standard README from the blessed groundtruth (metric tables, chart embeds, data section, reproduction block) plus strategy narrative. Runs standalone on any compliant repo, or auto-chained from `plutus-scoring` (which passes the compliance score for the badge). Requires a loadable `.plutus/manifest.yaml`.
---

# plutus-document

Render/refresh the repo's `README.md` to the Plutus Reproducibility Standard. Every
**verified fact** (metric tables, chart embeds, data section, environment + `plutus
check` reproduction block, score badge) is sourced from the blessed groundtruth, so
the README is consistent with `plutus check` / `plutus snapshot` **by construction**.
**Narrative** (Abstract, Introduction, Hypothesis, Rules, Reference) is preserved
from existing material, drafted from code, or co-authored with the user.

The skill writes only `README.md`; the author reviews and commits it. It is the
final step of the chain **`plutus-standardize` → `plutus-scoring` → `plutus-document`**,
and also runs standalone. Reference exemplar of the target structure:
`ProtoMarketMaker/README.md`. The two authoritative references are
[`references/section-map.md`](references/section-map.md) (groundtruth → section
mapping) and [`references/readme-template.md`](references/readme-template.md) (the
skeleton to fill).

## Pre-flight (before Phase 1)

1. **Confirm target repo path.** Default to CWD; accept an explicit path argument.
2. **Confirm compliance.** `<repo>/.plutus/manifest.yaml` must exist and load:
   ```python
   from plutus_verify.spec.loader import load_manifest
   load_manifest("<repo>")   # raises if invalid
   ```
   If missing/invalid, fail fast: "No loadable `.plutus/manifest.yaml`. Run
   `plutus-standardize` first, or `plutus init` to scaffold."
3. **Resolve the verifier version + wheel URL** for the reproduction block: probe the
   installed `plutus_verify.__version__`; the release wheel URL is
   `https://github.com/algotrade-plutus/plutus-verify/releases/download/v<version>/plutus_verify-<version>-py3-none-any.whl`.
4. **Detect chain context.** If invoked from `plutus-scoring`, capture the rounded
   compliance score (for the badge) and any `plutus-standardize` Decisions / Phase 4.5
   summary from the transcript. Standalone: read the score from the latest scoring
   output if present, else ask (or leave the existing badge); infer the data tier
   from `data_sources`.
5. **Warn (don't block) on uncommitted changes** and confirm the working branch — the
   skill overwrites `README.md`; git is the safety net (the author reviews the diff).

## Phase 1 — Gather groundtruth

Load and read from the manifest and the working tree (no LLM yet):

- `steps[]` — id, `nine_step`, `command`, `outputs` (→ console commands, section
  ordering via the `nine_step`→heading bridge in `section-map.md`).
- `data_sources` — kind, url, `expected_layout`, `satisfies` (→ §2).
- `env` — `manager`, `lockfile`, `install_project` (→ environment setup + repro
  paragraph).
- `secrets[].key` (→ `.env` block; omit the block if none).
- `expected.metrics[]` — `name`, `display_name`, `value` (→ metric tables; **the only
  source of table numbers**).
- `expected.artifacts[].path` (→ chart embeds at those `result/…` paths).
- the resolved verifier version + wheel URL; the compliance score.

**Exit criteria:** a structured groundtruth bundle covering every G-row of
`section-map.md`.

## Phase 2 — Gather narrative material

Read the existing `README.md` (if any) and module docstrings / top-of-file comments
of the metric-emitting scripts. Classify each **N** section as:

- **has-source** — existing prose to preserve & restructure into the standard layout;
- **draft-from-code** — no prose, but recoverable from code (reconstruct, mark
  `⚠ review`);
- **needs-user** — strategy intent not recoverable (hypothesis, rules, abstract on a
  bare repo) → queue for Phase 4 interactive co-authoring.

**Exit criteria:** every N section labelled with its source class.

## Phase 3 — Render the groundtruth sections

Fill the **G** placeholders of `references/readme-template.md` from the Phase 1
bundle, following `references/section-map.md` exactly:

- metric tables ← `expected.metrics` (`display_name` | `value`) — never
  `results.json`;
- chart embeds ← `expected.artifacts[].path` verbatim (`![alt](path)`);
- §2 data section ← `data_sources` (Drive tree from `expected_layout`, collect
  command from the data step);
- console commands ← `steps[].command`; env setup ← `env`; `.env` ← `secrets`;
- reproduction block ← pinned version + wheel URL;
- badges ← score + project type.

This phase is deterministic — no invention. If a G source is absent (e.g. no
optimization step), drop that section.

## Phase 4 — Produce the narrative sections

- **has-source:** restructure existing prose into the standard section, preserving the
  author's wording; don't paraphrase needlessly.
- **draft-from-code:** write a faithful draft from the code; prefix the section with an
  HTML comment `<!-- ⚠ plutus-document draft: review -->`.
- **needs-user:** ask the author for each such section, one prompt at a time
  (hypothesis → rules → abstract), then format the answer into the standard. Keep it
  to the genuinely-unrecoverable sections — don't interrogate when source exists.

## Phase 5 — Assemble & write README.md

1. Compose the full document in the standard order from the filled template; strip all
   `{{G:}}` / `{{N:}}` tags.
2. Write `<repo>/README.md` (overwrite; git preserves the prior version).
3. Emit a **review checklist** to the transcript: which sections were drafted
   (`⚠ review`) or co-authored, which numbers/charts came from groundtruth (and thus
   are `plutus check`-backed), and a reminder to run `plutus check .` if any baseline
   changed. Do not commit — the author reviews and commits.

**Exit criteria:** `README.md` written; checklist emitted; every metric table /
chart / repro detail traceable to groundtruth.

## Phase 6 — Consolidate knowledge

Silent unless this run diverged from the documented shape (mirrors
`plutus-standardize` Phase 6). Emit a substantive note only if, e.g., the manifest had
a step shape the section-map/template didn't cover, the reference structure needed a
new section, or narrative classification repeatedly failed. Otherwise emit one line:
`Phase 6: no divergence — template + section map fit this repo cleanly.`

## Interaction model

- Mostly non-interactive: interactive only for `needs-user` narrative sections
  (Phase 4) and the standalone no-score case (Pre-flight).
- Writes exactly one file: `README.md`. Read-only on everything else. Never runs
  `plutus check`/`snapshot` itself — it consumes their committed groundtruth.

## Verification before completion

- Every `expected.metrics` entry across steps appears in a rendered table with its
  `value`; every `expected.artifacts[].path` is embedded.
- The reproduction block names the correct pinned version + wheel URL.
- The score badge matches the `plutus-scoring` result (or was deliberately left).
- No `{{G:}}` / `{{N:}}` tags remain in the output.
- Drafted/co-authored sections are flagged in the review checklist.

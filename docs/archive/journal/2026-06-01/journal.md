---
archive-date: 2026-06-01
features: [plutus-verify, plutus-spec-v2, plutus-transform-skill, plutus-scoring-skill, leak-closure-arc]
captures: "none (0 captures — this cycle predates /journal:capture)"
plans: 16
legacy-reports: 11
---

# Development Journal — Archived 2026-06-01

> No `/journal:capture` files exist for this cycle. The timeline below is
> reconstructed from 16 plans (`docs/plan/`) and 10 legacy completion reports
> (`docs/completion-report/`, plus its README index). Neither carried YAML
> frontmatter, so entries are sorted by the **date embedded in each filename**
> with time defaulting to `00:00`; within a day, plans are ordered by their
> plan number and reports follow.

## Timeline

### 2026-05-15 00:00 — plutus-verify: Plan created — Design Plan
The originating design for the automated reproducibility verifier: ingest →
extract → build → execute → compare → report, with a local LLM used only as a
structured-output extractor and chart judge, and every stage persisted to disk.

### 2026-05-20 00:00 — plutus-spec-v2: Plan created — Foundation (Plan 1 of 4)
Introduces the declarative `.plutus/manifest.yaml` v2 format and the adapter
that bridges a manifest into the legacy `ExtractedPlan`, so existing v1 code can
run a manifest-driven repo unchanged.

### 2026-05-21 00:00 — plutus-spec-v2: Plan created — Native Execution (Plan 2 of 4)
The native v2 runtime: build the env from `env`, resolve data tiers, run each
step, and compare without going through the v1 LLM path.

### 2026-05-21 00:00 — plutus-spec-v2: Plan created — Scaffold CLI (Plan 3 of 4)
The author-facing `plutus init` / `check` / `snapshot` tooling around the manifest.

### 2026-05-21 00:00 — plutus-spec-v2: Plan created — Legacy Transfer (Plan 4 of 4)
`plutus transfer`: run the LLM extractor over a legacy README and reverse-map the
result into a v2 draft manifest with `# TODO(plutus-transfer):` markers.

### 2026-05-21 00:00 — plutus-spec-v2: Plan created — Live Verification Gap Closure (Plan 5)
Closes the gaps that surfaced when running the native v2 path end-to-end against
a real repo (beyond the original four-plan scope).

### 2026-05-21 00:00 — plutus-spec-v2: Plan created — Output-Side Standardization (Plan 6)
The results contract: each step writes a strict `.plutus/run/<step_id>/results.json`
(via the SDK); the verifier reads metrics by name, and output locators are removed.

### 2026-05-21 00:00 — plutus-spec-v2: Plan — Plans 1–10 complete (summary marker)
A consolidation note recording that the v2 spec plan series (Plans 1–10) had
landed.

### 2026-05-22 00:00 — plutus-spec-v2: Plan created — Package + Auto-inject SDK in Docker (Plan 7)
Packages `plutus-verify` and auto-bundles the SDK wheel into the build context so
instrumented scripts can `import plutus_verify` inside the container.

### 2026-05-22 00:00 — plutus-spec-v2: Plan created — `plutus snapshot --metrics` (Plan 8)
`snapshot` captures a passing run's outputs and writes `expected.metrics[].value`
back into the manifest — the commit becomes the verification claim.

### 2026-05-22 00:00 — plutus-spec-v2: Plan created — `plutus bootstrap` (Plan 9)
Deterministically generates a draft manifest from an already-instrumented run's
`results.json` + filesystem signals, leaving greppable `TODO_*` sentinels.

### 2026-05-25 00:00 — plutus-spec-v2: Plan created — Verifier Output Integrity + SDK Bundling (Plan 10)
Closes the false-positive where FAILED steps still reported `ok` metrics: wipe
`.plutus/run/` on start, skip metric compare on failed steps, loud SDK-bundle
failure, vendored prebuilt wheel.

### 2026-05-25 00:00 — plutus-verify: Plan created — MVP Simplify Pass (A + B + C)
A three-part consolidation pass over the MVP to remove duplication and tighten
the pipeline and types.

### 2026-05-25 00:00 — plutus-spec-v2: Complete — Phase A: the v2 manifest format
The manifest format and adapter shipped (covering Plans 1–5); manifests load,
validate, and adapt into the legacy plan shape.

### 2026-05-25 00:00 — plutus-spec-v2: Complete — Phase B: output-side standardization
The results contract landed (Plan 6 + the `reference_outputs`→`artifacts`
rename): metrics are read by name from `results.json`, locators removed.

### 2026-05-25 00:00 — plutus-spec-v2: Complete — Phase C: production polish
Packaging, SDK-in-Docker bundling, `snapshot`, and `bootstrap` shipped (Plans 7–9).

### 2026-05-25 00:00 — plutus-spec-v2: Complete — Phase D: integrity hardening
Plan 10 shipped; the FAILED-step false-positive is structurally closed; 485 tests
passing.

### 2026-05-26 00:00 — plutus-verify: Complete — Schema polish + packaging fixes (v0.2.5 / 0.2.6)
`UNIT_KINDS`, the `artifacts` rename, and the `--visual-check` opt-in; missing
visual-similarity snapshots become a non-blocking SKIP; first `CHANGELOG.md`.

### 2026-05-26 00:00 — plutus-verify: Complete — Simplify pass (post-MVP)
A `/simplify` consolidation pass (3 commits on `refactor`) following the MVP.

### 2026-05-27 00:00 — plutus-transform-skill: Plan created — v1-to-v2 transformer Skill design
Designs the Claude skill that drives the four-phase Survey → Decide → Instrument
→ Verify transformation workflow.

### 2026-05-27 00:00 — plutus-verify: Plan created — v0.2.7 artifact baseline + byte fallback
Plans the byte-comparison fallback for `visual_similarity`, the LLM-driven
artifact baseline, and the split of the skill into transform + scoring.

### 2026-05-27 00:00 — plutus-transform-skill: Complete — initial ship
The `plutus-transform` skill shipped: four-phase workflow, the G-numbered gotcha
catalogue, and the auto-chain into scoring.

### 2026-05-27 00:00 — plutus-verify: Complete — v0.2.7 byte fallback + skill split
Byte-identical / `WARN byte_identical` fallback for visual artifacts when no
vision endpoint is configured; the skill duo (transform/scoring) split out.

### 2026-05-29 00:00 — leak-closure-arc: Plan created — v0.2.10 per-step staging
Plans the per-step staging dir that closes the runtime-mount leak: each step runs
against a filtered tempdir copy instead of a live `-v cwd:/srv/repo` mount.

### 2026-05-29 00:00 — leak-closure-arc: Complete — v0.2.10 per-step staging
Staging shipped: host `.env` and stale `data/cache/*.parquet` are no longer
visible to a step container; manifest secret routing is now genuinely
authoritative; 518 tests passing.

### 2026-06-01 00:00 — leak-closure-arc: Complete — v0.2.x leak-closure arc pause marker
Development on the framework + skill duo is paused. The arc closed three leak
channels across 0.2.5→0.2.10, driven by a downstream feedback loop; a 7-item
parking lot records where to resume.

## Per-feature summary

### plutus-verify
The framework began 2026-05-15 with the verifier design (LLM-as-extractor,
disk-backed resumable stages). After the v2 spec work, an MVP simplify pass
(2026-05-25) and a post-MVP `/simplify` pass (2026-05-26) consolidated the code,
and v0.2.5/0.2.6 added schema polish, the `artifacts` rename, and the
`--visual-check` opt-in.

### plutus-spec-v2
The dominant thread: a 10-plan series (2026-05-20 → 2026-05-25) that inverted v1's
"extract a plan from prose" into a declarative manifest + strict `results.json`
contract. It shipped in four phases — manifest format (A), output standardization
(B), production polish incl. packaging/snapshot/bootstrap (C), and integrity
hardening (D) — ending at 485 tests passing with an end-to-end ProtoMarketMaker
validation.

### plutus-transform-skill / plutus-scoring-skill
Designed and shipped 2026-05-27: a Claude skill duo split out of the v0.2.7 work.
`plutus-transform` runs the four-phase Survey → Decide → Instrument → Verify
workflow with a numbered gotcha catalogue and auto-chains into `plutus-scoring`,
which applies the 50/25/10/15 compliance rubric.

### leak-closure-arc
The closing arc (planned + shipped 2026-05-29, paused 2026-06-01). v0.2.9's
`.dockerignore` closed the image-layer secret leak; v0.2.10's per-step staging
closed the runtime-mount `.env` leak and the cache short-circuit, making the
"a bridge step really queries the DB or fails exit=1" claim load-bearing. Driven
by five iterations of a downstream test-bench (Group09-BuyHighSellLow); 518 tests
passing at the pause.

## Summary

This archive covers the design and build-out of `plutus-verify` — an automated
reproducibility verifier for PLUTUS-standard trading-research repos — from its
2026-05-15 design plan through the 2026-06-01 leak-closure pause. Over ~2.5
weeks, 16 plans and 10 completion reports were produced (no `/journal:capture`
files; this cycle predates that workflow). The narrative arc: a v1 LLM-extraction
MVP → a declarative v2 manifest + results-contract spec (10 plans, 4 phases) → a
Claude skill duo to automate transformation and scoring → a hardening arc that
closed real secret/cache leak channels.

Notable lessons (from the reports):

- **Declared posture must be enforced, not advisory.** A `.dockerignore` is a
  build-context concept; a runtime bind-mount silently overrode it. Per-step
  staging was the minimal change that made the manifest's secret routing real.
- **Stale state causes false positives.** A FAILED step compared against a stale
  host-side `results.json` reported `ok`; wiping `.plutus/run/` on start and
  skipping metric compare on failed steps closed that loop (defense in depth).
- **Positive allowlists are sharp.** `step.inputs` is a complete-coverage
  allowlist (it must include the script binary), surfaced as gotcha G12; the fix
  was documentation (recommend `inputs: []` then tighten), not a framework change.
- **A downstream feedback loop drives real fixes.** Running the skill against a
  real Tier 3 repo once per release surfaced one genuine defect each iteration
  until the only remaining gap was a doc tightening — the signal to pause.

## Archived Files

### Plans
- plan/2026-05-15-plutus-verify-design.md
- plan/2026-05-20-plutus-spec-v2-foundation.md
- plan/2026-05-21-plutus-spec-v2-DONE.md
- plan/2026-05-21-plutus-spec-v2-legacy-transfer.md
- plan/2026-05-21-plutus-spec-v2-live-verification.md
- plan/2026-05-21-plutus-spec-v2-native-execution.md
- plan/2026-05-21-plutus-spec-v2-results-contract.md
- plan/2026-05-21-plutus-spec-v2-scaffold-cli.md
- plan/2026-05-22-plutus-bootstrap.md
- plan/2026-05-22-plutus-package-and-sdk-in-docker.md
- plan/2026-05-22-plutus-snapshot-metrics.md
- plan/2026-05-25-plutus-verifier-integrity.md
- plan/2026-05-25-plutus-verify-mvp-simplify-pass.md
- plan/2026-05-27-skill-design-v1-to-v2-transformer.md
- plan/2026-05-27-v0.2.7-artifact-baseline-byte-fallback.md
- plan/2026-05-29-v0.2.10-runtime-mount-staging.md

### Legacy completion reports
- completion-report/2026-05-25-phase-a-v2-manifest-format.md
- completion-report/2026-05-25-phase-b-output-side-standardization.md
- completion-report/2026-05-25-phase-c-production-polish.md
- completion-report/2026-05-25-phase-d-integrity-hardening.md
- completion-report/2026-05-26-schema-polish-and-fixes.md
- completion-report/2026-05-26-simplify-pass.md
- completion-report/2026-05-27-plutus-transform-skill.md
- completion-report/2026-05-27-v0.2.7-byte-fallback-and-skill-split.md
- completion-report/2026-05-29-v0.2.10-runtime-mount-staging.md
- completion-report/2026-06-01-v0.2.x-leak-closure-arc-pause.md
- completion-report/README.md
</content>

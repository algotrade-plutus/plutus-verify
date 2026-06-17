---
subject: v2-spec-and-execution
date: 2026-06-01
version: 1.0
status: current
---

# v2 Spec & Native Execution — Architecture & Design

## Overview

The v2 spec is the declarative replacement for v1's LLM-extracted plan. A repo
ships `.plutus/manifest.yaml`, the verifier reads it directly, and a **native v2
runtime** builds the environment, resolves data, runs each step in a filtered
staging dir, and compares declared `expected` values against the strict
`results.json` each step emits. No LLM is on the hot path.

This area covers four concerns: the **manifest schema** (`spec/`), the
**results contract** and **SDK** (`sdk/`), the **adapter** that bridges a
manifest to the legacy `ExtractedPlan` for auditing, and the relationship to the
native runtime (`spec/runtime/`). It exists because v1's "extract a plan from
prose" approach had two structural weaknesses the spec was designed to remove:
the manifest had to grow locator vocabulary mirroring each script's output
internals, and metric units were ambiguous (README `29.92%` vs script `0.2992`).

The fix was an inversion: instead of the verifier inferring the plan from
freeform output, the author *declares* the plan, and the script *emits* a strict
machine contract the verifier reads verbatim.

## Architecture

```
.plutus/manifest.yaml
        │ load_manifest
        ▼
  spec/loader.py ── jsonschema (spec/schema.py) ── spec/validator.py
        │ frozen dataclasses (spec/manifest.py)        (cross-field invariants)
        ▼
   Manifest ──┬─► spec/adapter.py → ExtractedPlan → plan.json   (audit only)
              │
              └─► spec/runtime/  (native execution; build, data resolve,
                                  staging, run, artifact_compare)
                        ▲
                        │ reads
              .plutus/run/<step_id>/results.json
                        ▲
                        │ written by
              sdk/run.py  (pv.step(...).metric/.artifact)  ── sdk/schema.py
```

### Components

#### Manifest dataclasses — `plutus_verify/spec/manifest.py`
- **Purpose:** frozen, method-free 1:1 mirror of the YAML. `Manifest` (`:103`),
  `Env` (`:22`), `Secret` (`:31`), `DataSource`/`DataSourceTiers` (`:38`/`:48`),
  `Step` (`:54`), `ExpectedMetric`/`Artifact`/`ExpectedBlock` (`:75`/`:83`/`:90`),
  `Tolerance` (`:69`), `NineStepCoverage` (`:97`). `NINE_STEP_KEYS` re-exported
  from `constants.py`.

#### Schema — `plutus_verify/spec/schema.py`
- **Purpose:** JSON Schema Draft 2020-12 (`MANIFEST_SCHEMA`, `:99`),
  `additionalProperties: false` everywhere, `schema_version` const `"2.0"`.
  Injects `NINE_STEP_KEYS` into both the step `nine_step` enum and the
  `nine_step_coverage` keys.

#### Loader — `plutus_verify/spec/loader.py`
- **Purpose:** the single funnel into a validated `Manifest`. `load_manifest`
  (`:40`) reads the file; `load_manifest_from_dict` (`:58`) runs schema
  validation → builds dataclasses → runs invariants. All failures become
  `ManifestLoadError`.

#### Validator — `plutus_verify/spec/validator.py`
- **Purpose:** cross-field invariants JSON Schema can't express:
  unique step ids; the `data_preparation` step must carry a `command`;
  `depends_on`, `expected.step_id`, and `satisfies` must reference real steps;
  `secrets[].used_by` must reference real steps (except `data_sources.`-prefixed
  qualifiers). Raises `ManifestInvariantError`. `check_invariants` (`:23`).

#### Adapter — `plutus_verify/spec/adapter.py`
- **Purpose:** `to_extracted_plan` (`:32`) maps a `Manifest` into the legacy v1
  `ExtractedPlan` shape. **Off the hot path** — only used to emit an auditable
  `plan.json`. Intentionally lossy; every loss appends an `extraction_notes`
  entry. It even fabricates a synthetic `json_file`/jsonpath locator
  (`:160`) so the v1 `ExpectedMetric` stays constructible — that locator is
  never executed by the v2 path.

#### SDK — `plutus_verify/sdk/`
- **Purpose:** the author-facing producer of `results.json`. `step(step_id)`
  (`run.py:190`) returns a `Run` (`:80`) context manager; `.metric` / `.artifact`
  / `.metadata` accumulate, and `flush` (`:173`) atomically writes
  `.plutus/run/<step_id>/results.json` — but only on clean exit of the `with`
  block. `RESULTS_SCHEMA` + `validate_results` (`schema.py:44`/`:62`).

## Design Principles

- **The manifest is the plan.** Declarative, deterministic, no LLM on the hot path.
- **The script's output is a contract.** A strict `results.json` per step, read
  by name — not scraped from stdout.
- **Canonical decimal units.** `fraction` / `ratio` / `count` / `currency_usd` /
  `seconds`; `percent` is rejected to kill unit ambiguity at the source.
- **Validation centralized.** Structure in `schema.py`, relationships in
  `validator.py`; dataclasses stay dumb and frozen.

## Design Decisions

### Manifest-is-the-plan (inversion of v1 extraction)
- **Context:** v1 LLM-extracted an `ExtractedPlan` from README prose.
- **Decision:** authors hand-write `.plutus/manifest.yaml`; the verifier reads
  it directly.
- **Rationale:** declarative, deterministic, types the runtime env, makes
  step I/O a hard contract, and tiers data acquisition.
- **Trade-offs:** authoring burden moves to the human; legacy repos need
  `plutus transfer` + hand-cleaning.

### A results contract instead of output locators
- **Context:** v1 grew locator kinds (`stdout_table`, `json_file`, `file_regex`)
  that mirrored each script's output internals, and metric units were ambiguous.
- **Decision:** make each step write `.plutus/run/<step_id>/results.json` to a
  strict schema; the verifier reads exactly that file by metric name. Locators
  were removed entirely — a clean break, no deprecation path.
- **Rationale:** smaller code surface; a simple mental model ("what metric, what
  value, what tolerance"); the unit-ambiguity bug class is eliminated by
  rejecting `percent`.
- **Trade-offs (accepted):** sharp upgrade pain — legacy/transferred manifests
  can't `plutus check` until their scripts are instrumented with the SDK.

### Bridge-then-native
- **Context:** a proven v1 build/execute/compare codebase existed.
- **Decision:** Plan 1 adapted Manifest→ExtractedPlan so legacy code ran
  unchanged; Plan 2 built the native runtime and demoted the adapter to an
  audit-trail producer.
- **Trade-offs:** the adapter is intentionally lossy; full v1 retirement is
  deferred.

### Verifier-owned results namespace
- **Decision:** `results.json` lives at `.plutus/run/<step_id>/`, in the
  verifier's home, by convention — so steps need no `results:` field.

## Data Model

### Data tiers
`data_sources` has two required arrays: `processed` (ready-to-run) and `raw`
(needs processing). Each `DataSource` carries `kind` (the backing store —
`google_drive`/`github_release`/`http`/`s3`/`manual`), `url`, `expected_layout`
(glob the download must produce), and `satisfies` (step ids). The native
runtime's resolver tries `processed`, then `raw`, then runs the step's
`command` — which is why data steps must always carry a runnable command. The
informal Tier 1/2/3 vocabulary (committed CSV / Drive-backed / DB-backed) is not
named in code; it's expressed by processed-vs-raw + `kind` + (for DB) a
`bridge` step with secrets.

### Results contract
```
{schema_version: "1.0", step_id, metrics[], artifacts[], metadata{}}   # all required
  metric:   {name (snake_case), value (number), unit (UNIT_KINDS)}
  artifact: {name (snake_case), path, kind (ARTIFACT_KINDS)}
```
`UNIT_KINDS = (fraction, ratio, count, currency_usd, seconds)`;
`ARTIFACT_KINDS = (chart, csv, json, image, other)`. The results schema version
(`"1.0"`) is independent of the manifest `schema_version` (`"2.0"`).

## Error Handling & Edge Cases

- Every load failure (missing file, schema violation, invariant violation)
  funnels into one `ManifestLoadError`.
- The SDK validates at call time *and* re-validates the assembled payload at
  `flush` (defense in depth); a `with pv.step(...)` block that raises writes
  nothing — partial results never persist.
- `git_commit` metadata is skipped when there's no `.git`; user-supplied
  metadata always wins over auto-injected values.

## Performance Considerations

- No LLM on the hot path — the dominant cost is Docker build + per-step
  execution, not extraction.
- The adapter (`to_extracted_plan`) runs once per v2 run purely to emit
  `plan.json`; it does no execution.

## Future Considerations

- **Adapter losses** (only relevant to the audit `plan.json`): `env.os_packages`,
  `env.gpu_required`, `steps[].inputs`, multi-step `data_sources.processed`, and
  non-`visual_similarity` artifacts; free-form steps collapse to a
  `step_4_in_sample` placeholder.
- **`kind` / `primary_language` are free-form strings**, so typos pass schema
  validation.
- **Out of scope:** non-Python SDKs (R/Julia/shell), a canonical metrics
  library, GPU support, an S3 downloader.

## Features Covered

- [v2-manifest](../feature/v2-manifest.md) — authoring the manifest + results contract.
- [authoring-tools](../feature/authoring-tools.md) — `init`/`check`/`snapshot`/`bootstrap`.
- [legacy-migration](../feature/legacy-migration.md) — `transfer` (uses the adapter direction in reverse).

## Source Materials

- Plans: `docs/plan/2026-05-20-plutus-spec-v2-foundation.md`,
  `docs/plan/2026-05-21-plutus-spec-v2-results-contract.md`
- Report: `docs/completion-report/2026-05-25-phase-a-v2-manifest-format.md`
- Code: `plutus_verify/spec/{manifest,schema,loader,validator,adapter}.py`,
  `plutus_verify/sdk/{run,schema}.py`
</content>

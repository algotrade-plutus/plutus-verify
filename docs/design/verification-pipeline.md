---
subject: verification-pipeline
date: 2026-06-01
version: 1.0
status: current
---

# Verification Pipeline — Architecture & Design

## Overview

The verification pipeline is the spine of `plutus-verify`: it takes a repo and
produces a reproducibility verdict. It is responsible for orchestrating the six
stages (ingest → extract → build → execute → compare → report), persisting each
stage's artifact to disk so any stage can be re-run independently, and routing
between the two execution paths — the **v1 LLM-extraction path** (README →
`plan.json`) and the **v2 native path** (`.plutus/manifest.yaml`).

The design principle that shaped everything else: the LLM is kept *out of the
control loop*. It is used only as a structured-output extractor (v1) and a
vision judge (charts); all orchestration, execution, comparison, and reporting
is plain, deterministic Python. The stable boundary between "what to run" and
"how to run it" is the `ExtractedPlan` / `plan.json` schema.

This document covers stage orchestration, the run-directory layout, the resume
machinery, and the v1↔v2 routing decision. The subsystems each stage delegates
to have their own design docs: [extraction](extraction.md),
[build-and-execute](build-and-execute.md),
[comparison-and-reporting](comparison-and-reporting.md),
[v2-spec-and-execution](v2-spec-and-execution.md).

## Architecture

```
                      plutus_verify/__main__.py  (Click CLI)
                                  │  builds injectable adapters
                                  ▼
            plutus_verify/pipeline.py :: run_pipeline(inputs, *, adapters...)
                                  │
  ingest ── extract ──┬── (manifest present?) ──────────────► v2 native path
   git    README→plan │                                       run_v2_pipeline
   clone  OR manifest  │  no manifest                          (spec/runtime/)
          → plan.json  ▼                                              │
                 build → fetch → execute → compare → report          │
                 (v1 stages, plain Python)                           │
                                  │                                   │
                                  ▼                                   ▼
                       out/<run_id>/{plan,meta,report}.json + report.md + run.log
```

All external dependencies — the git runner, LLM client, builder, runner, vision
client, metric-match client — are **injected** into `run_pipeline`. The CLI
constructs the real adapters; tests pass fakes. This is why the same pipeline
serves production and the unit/integration suites unchanged.

### Components

#### CLI entrypoint — `plutus_verify/__main__.py`
- **Purpose:** parse flags, build adapters, map the pipeline result to an exit code.
- **Key interfaces:** the `cli` Click group (`__main__.py:77`); `main()` compat
  shim that injects `verify` for the legacy `plutus-verify <url>` form
  (`__main__.py:639`); `verify_cmd` (`:146`) and `_run_one` (`:233`).
- The subcommands `init`/`check`/`snapshot`/`transfer`/`bootstrap` live here too
  but delegate into `scaffold/` (see [v2-spec-and-execution](v2-spec-and-execution.md)).

#### Orchestrator — `plutus_verify/pipeline.py`
- **Purpose:** run the ordered stages, persist artifacts, append a verification
  trail, route v1 vs v2.
- **Key interfaces:** `run_pipeline` (`pipeline.py:153`), `PipelineInputs`
  (`:56`), `PipelineResult` (`:85`); stage order constant `_STAGE_ORDER`
  (`:94`); `_run_v2_native_path` (`:755`); `_run_extract_via_llm` (`:570`);
  `_run_compare_stage` (`:661`).

#### Ingest — `plutus_verify/ingest.py`
- **Purpose:** `git clone --depth=1` (optionally `--branch <ref>`), write
  `meta.json`, support resuming an existing run dir.
- **Key interfaces:** `ingest` (`ingest.py:68`), `resume_existing_run` (`:40`),
  `IngestResult` (`:19`).

#### Execute — `plutus_verify/execute.py`
- **Purpose:** topologically sort steps, run them in dependency order with
  cascade-skip on failed deps, honor `artifact_check` mode, persist per-step logs.
- **Key interfaces:** `run_plan` (`execute.py:97`), the `Runner` protocol (`:28`),
  `ExecResult` (`:18`), `_choose_alternative` (`:72`), `_topo_sort` (`:52`).

#### Fetch — `plutus_verify/fetch.py`
- **Purpose:** opt-in (`--auto-fetch`) download of missing `manual_download`
  data; each download surfaces as a `Finding`. Dispatch is a deterministic
  URL→tool map (Google Drive only today).

#### Config — `plutus_verify/config.py`
- **Purpose:** a tree of frozen dataclasses with defaults; `plutus-verify.yaml`
  merges onto it key-for-key.
- **Key interfaces:** `Config` (`config.py:70`), `load_config` (`:92`).

## Design Principles

- **LLM out of the loop.** Determinism and model-swappability come first; the
  LLM produces structured data that deterministic code consumes.
- **Disk-backed stages.** Every stage writes its artifact under
  `out/<run_id>/`, making runs inspectable and resumable.
- **Injectable adapters.** One pipeline, many backends (real vs test).
- **Network isolation by default.** Steps run `network: none`; only the
  data-collection step opts into `bridge`.
- **Required-only gating.** Optional steps never change the exit code.

## Design Decisions

### Disk-backed stages + `--resume-from`
- **Context:** extraction is LLM-driven, slow, and occasionally wrong; reviewers
  run batch audits.
- **Decision:** persist each stage's output (`meta.json`, `plan.json`, build
  logs, per-step captures, reports) and let `--resume-from <stage>` skip earlier
  stages. `_should_skip` (`pipeline.py:97`) compares stage indices; on resume,
  extract reloads `plan.json` from disk instead of re-calling the LLM (`:249`).
- **Rationale:** a reviewer can hand-edit a bad `plan.json` and re-run from
  `execute` without re-cloning or paying for extraction again.
- **Trade-offs:** extra disk I/O and a multi-knob resume matrix — `--resume-from`
  vs `--use-plan` (pre-loaded plan) vs `--skip-build` (pre-built image) vs an
  existing run dir detected by `meta.json`.

### v2 native path as a parallel pipeline, not an adapter upgrade
- **Context:** a large, proven v1 build/execute/compare codebase existed when v2
  manifests were introduced.
- **Decision:** route by manifest presence *inside extract* (`pipeline.py:208`).
  If `.plutus/manifest.yaml` exists, load it, adapt it to an `ExtractedPlan`
  *only to emit an auditable `plan.json`*, then return early through
  `_run_v2_native_path` (`:298`, `:755`), which delegates build/execute/compare
  to `spec.runtime.run_v2_pipeline` and **bypasses the v1 stages entirely**.
- **Rationale:** clean separation during migration; v1 retires later (Plan 4).
- **Trade-offs:** a few hundred lines of duplication, and a current report
  fidelity gap on the v2 path (see below).

### Topo-sorted execution with cascade-skip
- **Context:** steps have `depends_on` edges; a failed dependency shouldn't run
  its dependents against missing inputs.
- **Decision:** `run_plan` topo-sorts and cascade-skips dependents of a failed
  step (`execute.py:52`, `:97`); `artifact_check` steps short-circuit to "verify
  the file exists" rather than executing.

## Data Model

### Run-directory layout (`out/<run_id>/`)
run_id from the CLI is `%Y%m%dT%H%M%SZ` (UTC); batch mode appends `-<source>`.

| File | Written by |
|------|-----------|
| `meta.json` | ingest (read back by `resume_existing_run`) |
| `repo/` | ingest clone target |
| `plan.json` | extract (v1 LLM, or v2 adapter from the manifest) |
| `extract_<label>_<tag>.txt` / `.err` | v1 extract per-attempt raw output |
| `validator_fixes.json` | v1 extract, when the validator applied fixes |
| `build/attempt_*.log`, `build/attempt_*.fixers.json` | build |
| `execute/<step_id>.stdout` / `.stderr` / `.meta.json` | execute (v1) |
| `report.json`, `report.md` | report |
| `run.log` | the progress trail (all stages) |

### The verification trail
Each stage appends a `TrailEntry` (stage / outcome / duration / summary /
artifacts) which the report renders into a "Verification Trail" table — the
human-auditable record of what ran and how long it took.

## Error Handling & Edge Cases

- **Pipeline can't start** → exit 2 (also the catch-all for an unhandled
  pipeline exception, and for `verify` invoked with no SOURCE and no `--batch`).
- **Extract-only / dry-run** short-circuit before either path and return
  `overall=None`, exit 0, printing the `plan.json` path.
- **Batch mode** runs each source under its own run dir and returns the worst
  (max) exit code.
- **`fetch` is not in `_STAGE_ORDER`**, so it can't be a `--resume-from` target;
  it runs between build and execute only when `--auto-fetch` is set.

## Performance Considerations

- The slowest stages are extract (LLM round-trips) and build (Docker). The
  resume machinery exists precisely so a reviewer doesn't repeat them.
- Network defaults to `none` per step, bounding the blast radius and keeping
  runs reproducible.

## Future Considerations

- **v2 report fidelity gap** — the v2 native path currently emits no per-step
  metrics/charts in `report.md`/`report.json` and always sets
  `nine_step_coverage` to `{}` (`TODO(plan2-task6-report-synthesis)` at
  `pipeline.py:773–916`). The v2 verdict reflects exec outcomes + metric
  pass/fail counts, not the full per-metric detail the v1 report carries.
- **v1 retirement** — `extract/plan.py` and the LLM pipeline branch are still
  living code the v2 path never touches; deletion is deferred (parking-lot item 7).
- **`--dry-run`** is mislabeled (behaves like `--extract-only`) and should be
  reconciled.

## Features Covered

- [repo-verification](../feature/repo-verification.md) — the CLI + exit-code contract.
- [v2-manifest](../feature/v2-manifest.md) — the manifest that triggers the native path.

## Source Materials

- Plans: `docs/plan/2026-05-15-plutus-verify-design.md`,
  `docs/plan/2026-05-21-plutus-spec-v2-native-execution.md`
- Code: `plutus_verify/{__main__,pipeline,config,constants,fetch,ingest,execute}.py`
</content>

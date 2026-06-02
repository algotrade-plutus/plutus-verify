---
subject: comparison-and-reporting
date: 2026-06-01
version: 1.0
status: current
---

# Comparison & Reporting — Architecture & Design

## Overview

This area answers "does the actual output match the claim, and within
tolerance?" and then renders the verdict. It has two distinct comparison
subsystems that should not be conflated:

- **The v1 comparison path** (`plutus_verify/compare/` + `plutus_verify/report/`)
  — used when an LLM-extracted plan drives the run. Metrics are *located* in
  freeform output (stdout tables, JSON files, regex) and checked against a
  tolerance; charts are judged by an LLM vision model; results aggregate into a
  verdict + exit code and render to `report.json`/`report.md`.
- **The v2 comparison path** (`plutus_verify/spec/runtime/artifact_compare.py`,
  surfaced by `plutus check`) — used when a manifest drives the run. Metrics are
  read by name from `results.json` (no locators), and artifacts are compared by
  `json_numeric_tolerance` / `visual_similarity` / `byte_exact`. The
  `--visual-check` flag and the byte-fallback live here, *not* in `compare/`.

This doc focuses on the v1 path's comparison + reporting machinery (the richer,
older surface) and notes where the v2 path differs. The verdict vocabulary and
exit-code contract are shared.

## Architecture

```
exec outputs (stdout, files)            ExpectedMetric / ExpectedChart (from plan)
        │                                          │
        ▼                                          ▼
compare/metrics.py  ── locate ── within_tolerance ──► MetricComparison(pass_)
   │  (stdout_table | json_file | file_regex)            │
   │  LLM fallback (stdout_table only) via llm_match     │
compare/charts.py ── rasterize ── vision judge ─────► ChartVerdict
   │  (shape/scale/structure; confidence threshold)      │
        ▼                                                ▼
compare/rubric.py :: aggregate_step → StepReport ── aggregate_overall → OverallReport
        │                                                (verdict, exit_code)
        ▼
report/__init__.py :: write_reports → report.json + report.md
```

### Components

#### Metric comparison — `plutus_verify/compare/metrics.py`
- **Purpose:** locate the actual value, then apply tolerance.
- **Locate kinds** (`_locate`, `:237`): `stdout_table` (markdown-pipe row/col),
  `json_file` (path + jsonpath; strings pass through for categorical params),
  `file_regex` (named `(?P<value>...)` group).
- **Tolerance** (`within_tolerance`, `:44`): `exact` (via `math.isclose`,
  tolerating IEEE-754 drift), `absolute`, `relative` (degrades to absolute when
  expected is 0); a categorical guard requires `exact` for string values.
- **LLM fallback** (`compare_step_metrics`, `:71`): when a `stdout_table` locate
  fails and a match client is provided, all failed metrics are packed into one
  LLM call to *parse* (not judge) the number; the deterministic tolerance check
  still runs on what it returns.

#### Chart comparison — `plutus_verify/compare/charts.py` + `vision_client.py`
- **Purpose:** judge a produced chart against a reference image.
- `compare_charts` (`:51`): disabled → `skipped`; produced file missing →
  `missing_file`; no reference → `match` (existence-only); both present →
  rasterize (PNG direct, SVG via `cairosvg`) and call the vision client.
- Vision judging is three-axis (shape / scale — within ~30% / structure) with an
  `overall.confidence`; a `match` below `match_threshold` (default 0.7) is
  downgraded to `partial`.

#### Verdict aggregation — `plutus_verify/compare/rubric.py`
- **Purpose:** the per-step verdict + exit-code aggregator (this is *not* the
  50/25/10/15 scoring rubric — that's the `plutus-scoring` skill).
- `aggregate_step` (`:56`): exec failed/timeout → `FAILED`; chart
  missing/mismatch → `FAILED`; else any failing metric or partial chart →
  `PARTIAL`; else `REPRODUCED`.
- `aggregate_overall` (`:93`): any required step failed → exit 2; any required
  partial → exit 1; else exit 0. **Only required steps gate.**

#### Reporting — `plutus_verify/report/__init__.py`
- `write_reports` (`:132`) emits `report.json` (schema_version 1.0;
  verdict/exit_code/repo/run/findings/trail/nine_step_coverage/steps) and
  `report.md` (verdict badge, run metadata, findings table, verification trail,
  9-step coverage, per-step detail, extraction notes).

## Design Principles

- **Deterministic decision, smart parsing.** Even when an LLM is used (metric
  fallback, chart vision), the *pass/fail* logic stays deterministic and
  auditable.
- **Tolerance reflects science, not bits.** Float noise is expected;
  `exact` means "indistinguishable," not `==`.
- **Producer/consumer split.** `report.json` for CI/scoring, `report.md` for
  humans.

## Design Decisions

### Tolerance philosophy
- **Context:** real strategy metrics carry float noise (ordering, BLAS).
- **Decision:** three explicit kinds + a categorical guard; `exact` uses
  `math.isclose(rel_tol=1e-9)`.
- **Trade-offs:** the tolerance value is chosen upstream (LLM/config); the
  comparator can't tell whether a too-loose tolerance is masking real drift.

### LLM as a parser for metrics, not a judge
- **Context:** the README may claim a stdout format the script doesn't actually
  emit.
- **Decision:** on `stdout_table` locate failure, let the LLM extract the number,
  then re-run the deterministic tolerance check on it.
- **Trade-offs:** fallback is `stdout_table`-only (json/regex failures are
  structural); stdout is truncated to the last 12K chars; any LLM/JSON failure
  degrades to `unverifiable` (which counts as not-passing).

### LLM vision for charts, opt-in for the v2 visual check
- **Context:** charts have no numeric ground truth to diff; pixel-diff is brittle.
- **Decision:** three-axis qualitative judgment with a confidence threshold.
  In the v2 path, `visual_similarity` is opt-in behind `--visual-check` (+ vision
  env vars) — because a CLI that hardcoded `vision_client=None` could never exit
  0 on a repo declaring visual charts.
- **Trade-offs:** non-deterministic and endpoint-dependent; default runs don't
  actually verify charts (a regression passes silently unless enabled).

### Exit code gated on required steps only
- **Decision:** optional steps (paper trading, optimization) never fail an
  otherwise-reproduced repo; they still appear in the report.

## Data Model

| Type | File:line | Notes |
|------|-----------|-------|
| `MetricComparison` | metrics.py:31 | `name, expected, actual, tolerance, pass_, unverifiable_reason` |
| `ChartVerdict` | rubric.py:28 | `name, produced_path, verdict, confidence?, rationale?` |
| `StepVerdict` | rubric.py:14 | `reproduced / partial / failed / skipped` |
| `StepReport` | rubric.py:37 | per-step roll-up |
| `OverallReport` | rubric.py:49 | `verdict, exit_code, steps` |
| `Finding` | report/__init__.py:96 | severity (`BLOCKER/PARTIAL/NOTE`) + kind |
| `TrailEntry` | report/__init__.py:37 | stage / outcome / duration / summary / artifacts |
| `RunMeta` | report/__init__.py:121 | repo/run metadata for the report |

Verdict badges: `reproduced=✅`, `partial=⚠️`, `failed=❌`, `skipped=⏭`.

The v2 path adds a `CompareResult` with a `skipped` flag and the artifact
4-state matrix (`ok` / `SKIP` / `WARN` / `FAIL`) rendered by
`scaffold/check_report.py`.

## Error Handling & Edge Cases

- A missing chart reference is treated as a **match** (existence-only) — a green
  chart verdict can mean "file exists, never compared."
- Missing `cairosvg` downgrades a chart to `partial` (an environment gap
  masquerading as a content judgment).
- `relative` tolerance against `expected == 0` silently degrades to `absolute`
  with the same value.
- The v2 path's integrity hardening skips metric comparison entirely on a failed
  step (renders `actual=None`, "metric not evaluated") to prevent false-positive
  `ok` rows — see [secret-and-leak-hardening](secret-and-leak-hardening.md).

## Performance Considerations

- The metric LLM fallback batches all failed `stdout_table` metrics into one
  call rather than one-per-metric.
- Chart rasterization is lazy (`cairosvg` imported only for SVGs).

## Future Considerations

- **`NINE_STEP_LABELS` defines only 7 of the "nine" steps** — the coverage table
  silently omits any key not in the label map.
- **v2 report fidelity gap** — the v2 native path emits metric pass/fail counts
  but no per-metric/per-chart detail in `report.json`/`report.md` yet (tracked
  in [verification-pipeline](verification-pipeline.md)).
- **Documentation hazard:** keep v1 (`compare/`) and v2
  (`spec/runtime/artifact_compare.py`) comparison clearly separated — the
  `byte_exact`/`json_numeric_tolerance`/`visual_similarity` vocabulary is v2-only.

## Features Covered

- [repo-verification](../feature/repo-verification.md) — v1 compare + report.
- [authoring-tools](../feature/authoring-tools.md) — `plutus check`'s v2 comparison + report.
- [plutus-scoring-skill](../feature/plutus-scoring-skill.md) — the separate 50/25/10/15 rubric (not `compare/rubric.py`).

## Source Materials

- Reports: `docs/completion-report/2026-05-25-phase-c-production-polish.md`,
  `docs/completion-report/2026-05-26-schema-polish-and-fixes.md`
- Code: `plutus_verify/compare/{metrics,charts,llm_match,vision_client,rubric}.py`,
  `plutus_verify/report/__init__.py`, `plutus_verify/spec/runtime/artifact_compare.py`,
  `plutus_verify/scaffold/check_report.py`
</content>

# Phase B — Output-side standardization

**Plan 6 + the `headline → metric` rename.** Phase A solved the *input
side* of verification (author writes a manifest, verifier reads it).
Phase B solves the *output side*: scripts now emit a canonical
`results.json` file, the verifier reads metrics by name, and the
freeform-output translation layer (locator vocabulary) is deleted.

## The inversion

**Before (Phase A):** The manifest's `expected.headlines` carried a
`locate:` block per headline telling the verifier *where* to find that
metric in the script's stdout / JSON output:

```yaml
- name: Sharpe Ratio
  value: 0.9516
  locate: {kind: stdout_regex, pattern: "Sharpe ratio:\\s*([-\\d.]+)"}
  tolerance: {kind: relative, value: 0.05}
```

Authors had to know what their script's output looks like AND describe
that shape in the manifest. Two surfaces had to agree: the script's
print format and the manifest's regex. Tight coupling, easy to break.

**After (Phase B):** Scripts emit a canonical
`.plutus/run/<step_id>/results.json` via the new SDK. The verifier reads
metrics by snake_case name. The manifest's headline collapses to:

```yaml
- name: sharpe_ratio
  display_name: "Sharpe Ratio"
  value: 0.9516
  tolerance: {kind: relative, value: 0.05}
```

Three fields: what to claim, what value, with what tolerance. No
locators.

## What shipped

### The SDK (`plutus_verify/sdk/`)

A new package for authors to instrument their scripts:

```python
import plutus_verify as pv

with pv.step("in_sample_backtest") as r:
    r.metric("sharpe_ratio",     sharpe,   unit="ratio")
    r.metric("sortino_ratio",    sortino,  unit="ratio")
    r.metric("maximum_drawdown", mdd,      unit="ratio")
    r.artifact("equity_curve",   "result/backtest/hpr.svg", kind="chart")
    r.metadata(seed=2025)
# Context manager flushes .plutus/run/in_sample_backtest/results.json
# on clean __exit__. If the with-block raises, no file is written.
```

- **`sdk/schema.py`** — `RESULTS_SCHEMA` (JSON Schema), `UNIT_KINDS` (`ratio | count | currency_usd | seconds`), `ARTIFACT_KINDS` (`chart | csv | json | image | other`), `NAME_PATTERN` (`^[a-z][a-z0-9_]*$`). `validate_results(payload)` validates via Draft 2020-12.
- **`sdk/run.py`** — `Run` class + `step()` factory. Enforces snake_case names, finite numeric values, canonical unit enum, unique metric/artifact names. Auto-injects `duration_seconds` (wall clock) and `git_commit` (best-effort if `.git` present). User-supplied `r.metadata(...)` values win over auto-injection.
- **Atomic write** — `.tmp + os.replace` pattern. Verifier never sees a half-written file.

### The reader (`plutus_verify/spec/runtime/results.py`)

```python
results: ResultsFile = load_results(repo_path, step_id="in_sample_backtest")
metrics_by_name = {m.name: m for m in results.metrics}
```

- **Dataclasses:** `Metric`, `Artifact`, `ResultsFile`
- **Errors:** `MissingResultsError`, `MalformedResultsError`, `MetricNotProducedError` — three failure modes the orchestrator differentiates
- **Validation:** delegates to `sdk.schema.validate_results` — single source of truth shared between SDK writer and verifier reader

### Manifest schema collapse

**Removed entirely:** `Locate` dataclass + locator schema + the four kinds (`stdout_table`, `stdout_regex`, `json_file`, `file_regex`). No more dispatch on locator kind in the orchestrator. The runtime now has exactly one comparison strategy: load results.json, look up by name, compare with tolerance.

**Added:** optional `Headline.display_name` field for human-readable report labels (`sharpe_ratio` matches by name; `"Sharpe Ratio"` shows up in reports).

**Tightened:** schema rejects `locate:` properties (`additionalProperties: false`), enforces snake_case on `name`, narrows `value` to numeric (was previously `float | str`).

The v2→v1 adapter (`spec/adapter.py`) synthesizes a json_file locator pointing at `.plutus/run/<step_id>/results.json` so the v1 `ExtractedPlan` audit artifact stays constructible. It's never executed in v2 mode (native runtime takes over) but downstream tools that read `plan.json` still work.

### Orchestrator rewrite

`_compare_metrics` (formerly `_compare_headlines`) now:
1. Loads `.plutus/run/<step_id>/results.json` via `load_results`
2. Builds `{name: metric}` lookup
3. Per declared headline: lookup by name, compare with tolerance, produce `ExpectedMetricResult`

Three explicit failure modes:
- `MissingResultsError` → every declared metric fails with "results.json missing"
- `MalformedResultsError` → every metric fails with "results.json malformed"
- Name not in lookup → that single metric fails with "metric '<name>' not produced"

### `plutus transfer` updates

The legacy on-ramp now emits v2-valid YAML:
- Drops `locate:` blocks
- Canonicalizes v1 metric names to snake_case (`"Sharpe Ratio"` → `sharpe_ratio`); original goes into `display_name`
- Falls back to `value: 0.0  # TODO(plutus-transfer): could not parse "<original>" as float` for unparseable v1 values
- Generates a companion `.plutus/instrument_TODO.md` with copy-paste `pv.step(...)` snippets per step that has declared headlines (since the LLM can't reach inside the author's scripts to instrument them)

### `plutus init` updates

`MANIFEST_SKELETON` updated (no locators; example headline uses display_name). A new `.plutus/example_script.py` is scaffolded showing real `pv.step(...)` SDK usage with realistic Plutus-style metric names. Documents the contract for new authors.

### `headline → metric` rename

Coherent vocabulary rename done in commit `e9d9aa9` (43 files, 419 substitutions, 1:1):

- `Headline` → `ExpectedMetric` (manifest dataclass; disambiguates from the OBSERVED `Metric` in `results.py`)
- `HeadlineResult` → `ExpectedMetricResult`
- `headlines:` YAML field → `metrics:`
- `r.headline(...)` SDK call → `r.metric(...)`
- `--no-headlines` CLI flag → `--no-metrics`
- `_compare_headlines` → `_compare_expected_metrics`
- `headline_results` on `V2RuntimeResult` → `metric_results`

Rationale: scientific framing for what amounts to scientific reproducibility verification, not financial-report-style "headline" summaries.

## Workflow this phase enabled

```
Author:
  plutus init .                          # scaffold (now includes example_script.py)
  (instrument scripts with pv.step(...).metric(...))
  (write manifest with simple name+value+tolerance, no locators)
  plutus check .                         # build, run, compare results.json by name

Legacy on-ramp:
  plutus transfer <legacy-repo>          # → manifest.yaml.draft + instrument_TODO.md
  (hand-clean draft; instrument scripts per the TODO doc)
  plutus check .
```

## Key files

```
plutus_verify/
  sdk/                                  # NEW
    __init__.py
    run.py                              # Run + step() factory
    schema.py                           # RESULTS_SCHEMA + validate_results
  spec/
    manifest.py                         # Locate deleted; Headline → ExpectedMetric
    schema.py                           # _LOCATE deleted; expected.metrics tightened
    loader.py                           # locator parsing removed
    adapter.py                          # synthesize v1 locate pointing at results.json
    runtime/
      results.py                        # NEW: load_results + dataclasses + errors
      orchestrator.py                   # _compare_metrics rewritten; all _locate_* deleted
  scaffold/
    extract_to_v2.py                    # snake_case rename + no-locator YAML + TODO companion
    templates.py                        # MANIFEST_SKELETON + EXAMPLE_SCRIPT
    init.py                             # writes example_script.py too
  __main__.py                           # bootstrap subcommand pending Phase C
docs/plan/
  2026-05-21-plutus-spec-v2-results-contract.md  (Plan 6)
```

## Tests

End of phase: **429 tests passing.**

| Test surface | Coverage |
|---|---|
| `test_sdk_run.py`, `test_sdk_schema.py` | Run class, schema validation, atomic write, finite-value guard, NaN rejection, snake_case enforcement, git_commit auto-injection, duration_seconds auto-injection, user-override priority |
| `test_runtime_results.py` | `load_results` happy path + 3 error types + round-trip via SDK |
| `test_spec_*.py` | Locate-related tests removed; display_name positive + locate-rejection negative tests added; schema strictness verified |
| `test_runtime_orchestrator.py` | locator-dispatch tests deleted; 8 new tests for name-lookup, missing results.json, metric-not-produced, tolerance pass/fail in both directions |
| `test_extract_to_v2.py` | Canonicalization, value-parse fallback, no-locate emission, `instrument_todo_markdown` generation, force-flag semantics |
| `test_scaffold_init.py` | example_script.py written + compiles + idempotent + force overwrites |

## Integration evidence

`out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` was hand-cleaned to use the new shape (no locators, snake_case names). Scripts were instrumented to write `results.json` (initially via a hand-rolled `_plutus_emit_results` helper since the SDK wasn't yet in the container — that was fixed in Phase C). Pass pattern stable: 6/6 in-sample, 3/6 OOS.

The full chain — SDK writes file → load_results reads file → orchestrator compares against manifest — exercised by `tests/integration/test_v2_runtime_e2e.py`.

## Why this matters

The script's output is now a strict machine contract. Two consequences:

1. **Unit ambiguity eliminated at the source.** The schema rejects `unit: "percent"`. All ratios are decimals. Authors can't accidentally claim 17.1 when they meant 0.171.
2. **Non-Python authors supported by construction.** Anyone — R, Julia, shell — can write results.json directly. The SDK is just an ergonomic Python wrapper around the same file contract.

This is the inversion the user named in the original brainstorm: "the script's output is a contract, not a thing the verifier has to interpret."

# Plutus v2 Spec — Output-Side Standardization (Plan 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Standardize what reproducible scripts *produce* so the verifier
never has to parse stdout, regex over markdown, or guess units. Every step
emits a canonical `.plutus/run/<step_id>/results.json` with strict schema
(ratio-decimals only, no percent). The manifest's `expected.headlines` becomes
a name → value+tolerance lookup. All locator vocabulary
(`stdout_table`, `stdout_regex`, `json_file`, `file_regex`) is removed.

**Architecture:** Layered — a strict file contract (the wire format the
verifier reads) + an ergonomic Python SDK (`plutus_verify.sdk`) that authors
instrument scripts with. Non-Python authors can hand-write the file in any
language; the verifier only ever reads JSON.

**Tech Stack:** No new deps. SDK is `dataclasses` + `json` + `pathlib`.

---

## Why this plan exists

Plans 1–5 solved the **input side**: the author writes
`.plutus/manifest.yaml` and the verifier reads it directly — no LLM
extraction on the hot path. But the **output side** of every step is still
freeform: stdout, README, files, percentages, decimals, markdown tables,
ad-hoc JSON. The v2 manifest grew four locator kinds
(`stdout_table`, `stdout_regex`, `json_file`, `file_regex`) just to bridge
the freeform output back into something the verifier can compare. Plan 5
added `stdout_regex` because real scripts print plain-text lines instead
of tables — a translation layer expanding to fit reality.

That translation layer is the wrong place to spend complexity. Two
recurring bugs make this clear:

1. **Unit ambiguity.** README documents HPR as `29.92` (percent) and the
   script prints `0.29926` (ratio). Manifest must mirror the script, not
   the README, or comparisons fail silently for "wrong" reasons. The author
   has to know which surface they're targeting.
2. **Output venue drift.** Some scripts print to stdout, some write JSON,
   some only update the README. Adding a new script type means adding a
   new locator. The verifier's complexity grows monotonically.

**Fix:** make the script's output a strict machine contract. The script
writes a known file, in a known schema, with known units. The verifier
reads exactly that file. Locators vanish. Authors instrument once with a
small SDK (or hand-roll JSON); the manifest stops mirroring script
implementation details (regex patterns, table column indices) and
collapses to "what do I claim, to what value, with what tolerance."

---

## Architectural decisions (recorded)

These decisions were made interactively during the design conversation
(see `/Users/dan/.claude/plans/hmm-okay-i-think-wondrous-sundae.md` for
context). User explicitly chose each one.

1. **Layered contract: file + SDK.** The canonical `results.json` is the
   wire format the verifier reads — language-agnostic, debuggable by `cat`.
   The Python SDK is the recommended ergonomic producer. Authors in any
   language can hand-roll the same JSON.
2. **Strict canonical units — ratios as decimals only.** Ratio-shaped
   metrics (returns, drawdowns, Sharpe, Sortino) must be written as
   decimals. `17.1%` is `0.171`, never `17.1`. The schema *rejects* a
   `percent` unit. Kills the bug class at the source. Non-ratio metrics
   (counts, currency, seconds) use explicit non-ratio units.
3. **Verifier namespace: `.plutus/run/<step_id>/results.json`.** The file
   lives in the verifier's home (`.plutus/`), not author space. Authors
   don't need a `results:` field on each step — the path is convention.
4. **Schema scope: metrics + artifacts + metadata.** Largest reasonable
   scope. Each field beyond `metrics` is optional. Metadata fields
   (`seed`, `duration_seconds`, `git_commit`) are conventional but not
   required.
5. **Clean break, no `locate:` deprecation.** The entire locator vocabulary
   is removed. No fallback path. Legacy/transferred manifests can't
   `plutus check` until the author instruments their scripts to emit
   `results.json`. The author trade-off was explicit: sharp upgrade pain
   in exchange for a smaller code surface and a simpler mental model.
6. **`plutus transfer` produces a TODO file alongside the manifest draft.**
   Since the v1 LLM extractor can't predict which `pv.headline(...)` calls
   to add where, the transfer tool now writes a companion
   `instrument_TODO.md` listing the headlines the LLM inferred from the
   README. The human adds the SDK calls.

---

## File Structure

**New module — `plutus_verify/sdk/`:**

- `__init__.py` — re-exports `step`, expose as `plutus_verify.sdk.step` and
  via top-level `plutus_verify.step` for the `import plutus_verify as pv;
  with pv.step(...)` ergonomic
- `run.py` — `Run` class (context manager + headline/artifact/metadata
  collectors + `flush()`); `step(step_id, *, repo_path=Path.cwd())` factory
- `schema.py` — `RESULTS_SCHEMA` (JSON Schema for results.json) + canonical
  enums (`UNIT_KINDS`, `ARTIFACT_KINDS`)

**New module — `plutus_verify/spec/runtime/results.py`:**

- `ResultsFile` dataclass: `{schema_version, step_id, metrics, artifacts, metadata}`
- `load_results(repo_path, step_id) -> ResultsFile`
- `MissingResultsError`, `MalformedResultsError`, `MetricNotProducedError`

**Modified — `plutus_verify/spec/manifest.py`:**

- Remove `Locate` dataclass entirely
- `Headline` collapses to `{name: str, value: float, tolerance: Tolerance,
  display_name: str | None}` — no `locate` field
- Optional `display_name` is for human reports only; matching is always
  by `name` (snake_case)

**Modified — `plutus_verify/spec/schema.py`:**

- Remove `_LOCATE` and the `locate` property from headline schema
- Add `display_name` (optional, string) to headline schema

**Modified — `plutus_verify/spec/runtime/orchestrator.py`:**

- Delete `_locate_value`, `_locate_stdout_table`, `_locate_stdout_regex`
  (and the JSON-file/file-regex variants if they exist)
- Delete `_TABLE_ROW_RE`
- `_compare_headlines(er, repo_path, step_results)` rewritten:

  ```python
  def _compare_headlines(er, repo_path, step_results):
      try:
          results = load_results(repo_path, er.step_id)
      except MissingResultsError as exc:
          return {h.name: HeadlineResult(name=h.name, ok=False, actual=None,
                                          expected=h.value, detail=str(exc))
                  for h in er.headlines}
      metrics_by_name = {m.name: m for m in results.metrics}
      out = {}
      for h in er.headlines:
          m = metrics_by_name.get(h.name)
          if m is None:
              out[h.name] = HeadlineResult(name=h.name, ok=False, actual=None,
                                            expected=h.value,
                                            detail=f"metric '{h.name}' not produced")
              continue
          ok, detail = _within_tolerance(m.value, h.value, h.tolerance)
          out[h.name] = HeadlineResult(name=h.name, ok=ok, actual=m.value,
                                        expected=h.value, detail=detail)
      return out
  ```

**Modified — `plutus_verify/scaffold/extract_to_v2.py`:**

- Drop locator emission from `to_v2_manifest_yaml`
- Emit headlines with `name + value + tolerance` only; no `locate:` block
- Generate companion `instrument_TODO.md` listing headlines that the human
  must wire `pv.headline(...)` calls for

**Modified — `plutus_verify/scaffold/transfer.py`:**

- Write `instrument_TODO.md` alongside `manifest.yaml.draft`

**Tests added — `tests/unit/`:**

- `test_sdk_run.py` — context manager flushes correctly, validates units,
  rejects duplicate names, atomic write
- `test_sdk_schema.py` — schema validation accepts good results, rejects
  percent unit, rejects missing required fields
- `test_runtime_results.py` — `load_results`, error types
- `test_runtime_orchestrator_results.py` — name-lookup comparison,
  missing results.json → headline failures, missing metric → headline
  failure
- `test_extract_to_v2_no_locators.py` — emitted YAML has no `locate:`

**Tests removed:**

- All `Locate`-related unit tests in `test_manifest.py`, `test_schema.py`,
  `test_runtime_orchestrator.py`
- `_locate_stdout_*` tests
- The hand-cleaned ProtoMarketMaker manifest at
  `out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` must be
  re-cleaned to remove locators and re-verified after the scripts are
  instrumented

---

## The `results.json` schema

```json
{
  "schema_version": "1.0",
  "step_id": "in_sample_backtest",
  "metrics": [
    {"name": "sharpe_ratio",     "value": 0.9517,  "unit": "ratio"},
    {"name": "sortino_ratio",    "value": 1.3490,  "unit": "ratio"},
    {"name": "maximum_drawdown", "value": -0.2011, "unit": "ratio"},
    {"name": "hpr",              "value": 0.29926, "unit": "ratio"},
    {"name": "annual_return",    "value": 0.17101, "unit": "ratio"}
  ],
  "artifacts": [
    {"name": "equity_curve",  "path": "result/backtest/hpr.svg",      "kind": "chart"},
    {"name": "drawdown_chart","path": "result/backtest/drawdown.svg", "kind": "chart"}
  ],
  "metadata": {
    "seed": 2025,
    "duration_seconds": 12.4,
    "git_commit": "900b459"
  }
}
```

### Field reference

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | String. `"1.0"` initially. Schema bumps version. |
| `step_id` | yes | Must match the step that wrote the file. Verifier cross-checks against `.plutus/run/<step_id>/...` directory name. |
| `metrics` | yes (may be empty) | List. Each entry: `{name (snake_case), value (number), unit (enum)}`. |
| `metrics[].unit` enum | — | `ratio \| count \| currency_usd \| seconds`. `percent` is **rejected**. |
| `artifacts` | no (default `[]`) | List. Each entry: `{name, path (repo-relative), kind (enum)}`. |
| `artifacts[].kind` enum | — | `chart \| csv \| json \| image \| other`. |
| `metadata` | no (default `{}`) | Free-form object. Conventional keys: `seed`, `duration_seconds`, `git_commit`. |

### Invariants

- Metric names are unique within a `results.json`.
- All `metrics[].value` values are finite numbers (no NaN, no Infinity).
- `artifacts[].path` must resolve to an existing file under `repo_path`
  at compare time (verifier checks).
- Schema mismatches are hard failures; the file must validate strictly.

---

## The Python SDK API

```python
import plutus_verify as pv

# inside backtesting.py
with pv.step("in_sample_backtest") as r:
    # ... existing backtest code computes sharpe, sortino, mdd, hpr, ... ...
    r.headline("sharpe_ratio",     sharpe,   unit="ratio")
    r.headline("sortino_ratio",    sortino,  unit="ratio")
    r.headline("maximum_drawdown", mdd,      unit="ratio")
    r.headline("hpr",              hpr,      unit="ratio")
    r.headline("annual_return",    ann_ret,  unit="ratio")
    r.artifact("equity_curve",   "result/backtest/hpr.svg",      kind="chart")
    r.artifact("drawdown_chart", "result/backtest/drawdown.svg", kind="chart")
    r.metadata(seed=2025)
# context manager flushes JSON to .plutus/run/in_sample_backtest/results.json
```

### Surface

- `pv.step(step_id: str, *, repo_path: Path | None = None) -> Run` —
  context manager factory. `repo_path` defaults to the script's `cwd()`
  resolved upward to the nearest `.plutus/` directory; explicit override
  is supported for tests and ad-hoc invocation.
- `Run.headline(name: str, value: float, *, unit: str = "ratio") -> None` —
  raises `DuplicateMetricError` on collision, `ValueError` on non-finite
  value or unsupported unit.
- `Run.artifact(name: str, path: str | Path, *, kind: str = "chart") -> None` —
  raises on duplicate name or invalid kind. Path is stored repo-relative.
- `Run.metadata(**kwargs: Any) -> None` — accumulates. Last-write-wins
  per key. Non-JSON-serializable values raise at flush time.
- `Run.flush()` is called automatically on `__exit__` (when the context
  manager exits without an exception). If the `with` block raised, the
  file is **not** written — partial results are not persisted.

### Atomic write

The SDK writes to `<results>.tmp` and renames to `<results>` after the
JSON has been serialized successfully. The verifier never sees a
half-written file.

---

## Manifest changes (concrete)

**Before (today):**

```yaml
expected:
  - step_id: in_sample_backtest
    headlines:
      - name: Sharpe Ratio
        value: 0.9516
        locate: {kind: stdout_regex, pattern: "Sharpe ratio:\\s*([-\\d.]+)"}
        tolerance: {kind: relative, value: 0.05}
      - name: Sortino Ratio
        value: 1.3490
        locate: {kind: stdout_regex, pattern: "Sortino ratio:\\s*([-\\d.]+)"}
        tolerance: {kind: relative, value: 0.05}
```

**After:**

```yaml
expected:
  - step_id: in_sample_backtest
    headlines:
      - name: sharpe_ratio
        display_name: "Sharpe Ratio"   # optional, for human reports
        value: 0.9516
        tolerance: {kind: relative, value: 0.05}
      - name: sortino_ratio
        display_name: "Sortino Ratio"
        value: 1.3490
        tolerance: {kind: relative, value: 0.05}
```

Raw line count is similar, but the headline no longer carries a regex
pattern that has to mirror script output verbatim. The mental model
collapses to "what metric do I claim, to what value, with what
tolerance" — three fields. Authoring errors (wrong regex, wrong column
index, wrong unit) become impossible by construction.

---

## Verifier flow (after)

```
1. Build image (Plan 5 — real_image_builder)
2. Resolve data tiers (Plan 2 — data_resolver)
3. For each step (topo sorted):
     a. Preflight inputs (Plan 2)
     b. Run step (or skip per artifact_check / satisfied_by_data_source)
     c. Preflight outputs (Plan 2)
4. For each expected block:
     a. load_results(repo_path, step_id)                                    ◄── NEW
     b. for each headline: lookup metric by name → compare tolerance         ◄── NEW
     c. for each reference_output: compare against .plutus/expected/         (unchanged)
5. Emit report
```

The compare phase no longer reads stdout, doesn't parse markdown tables,
doesn't run regex. The orchestrator's locator code is gone.

---

## Migration impact

**`plutus transfer`** (legacy on-ramp) gets a companion file:

```
.plutus/manifest.yaml.draft        # draft manifest with TODO markers (existing)
.plutus/instrument_TODO.md         # NEW — headlines the human must instrument
```

`instrument_TODO.md` contents (template):

```markdown
# Instrumentation TODO

To complete the transfer, instrument these scripts to emit results.json.
Run `plutus check` after each script is updated to verify.

## in_sample_backtest (`backtesting.py`)

Add at the end of the script:

```python
import plutus_verify as pv

with pv.step("in_sample_backtest") as r:
    r.headline("sharpe_ratio",     sharpe,   unit="ratio")
    r.headline("sortino_ratio",    sortino,  unit="ratio")
    # ... full list from README ...
```

## out_of_sample_backtest (`evaluation.py`)
...
```

The headlines list in `instrument_TODO.md` is generated from the LLM's
extracted metrics. The human can copy-paste the suggested code and adjust
variable names to match their scripts.

---

## Verification (how we'll know it works)

**Unit:** ~25 new tests across SDK, results loader, orchestrator
rewrite, schema. Locator tests deleted (~15 tests removed).

**Integration:** ProtoMarketMaker re-verification:

1. Add `pv.step(...)` blocks to `backtesting.py` and `evaluation.py`
2. Update the hand-cleaned manifest at
   `out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` to remove
   `locate:` from headlines, keep names as snake_case
3. Run `plutus check out/transfer-test/ProtoMarketMaker`
4. Expected: 6/6 in-sample headlines pass; 3/6 OOS headlines pass — same
   pass/fail pattern as Plan 5's verification (since the underlying
   reproducibility problem is unchanged). Exit code 1 (verdict, not
   pipeline bug).

**Regression:** all 303 existing unit tests pass after locator-related
ones are removed and SDK/results tests are added. Net test count likely
≈310–320.

---

## Out of scope

- **Non-Python SDKs (R, Julia, shell).** The file contract supports them
  by design; ergonomic libraries can come later as separate plans.
- **How authors write the manifest in the first place.** Still a separate
  thread (the LLM-extraction problem). For now, transferred legacy repos
  start from the LLM-generated draft + the new `instrument_TODO.md`.
- **A `plutus.metrics` canonical implementation library.** Future:
  `plutus.metrics.sharpe(returns)` returns a value and auto-registers it
  as a headline. Out of scope for this plan.
- **GPU support, S3 downloader, `plutus render-readme`** — these were
  deferred from earlier plans and remain deferred.

---

## Implementation breakdown (high-level)

Detailed TDD task breakdown will be written by the writing-plans skill
when this design is approved. Roughly:

1. **Task 1** — SDK skeleton: `Run`, `step()`, schema validation. TDD.
2. **Task 2** — `results.py` loader + error types. TDD.
3. **Task 3** — Manifest schema collapse: drop `Locate`, drop locator
   enum, add `display_name`. TDD. (Breaking change to the v2 manifest
   schema; the schema version stays at `2.0` because the v2 spec is not
   yet released externally.)
4. **Task 4** — Orchestrator rewrite: delete locator dispatch, plug in
   `load_results` + name lookup. TDD.
5. **Task 5** — Update `plutus init` skeleton template: example with
   `pv.step(...)` in a placeholder script.
6. **Task 6** — `plutus transfer` reverse adapter: emit no-locator
   headlines + `instrument_TODO.md`. TDD.
7. **Task 7** — End-to-end integration: re-instrument ProtoMarketMaker;
   re-verify; commit golden manifest + golden results.json under
   `out/transfer-test/`.

---

## Open questions (none blocking)

- **Should `metadata.duration_seconds` be auto-injected by the SDK?**
  Probably yes — the context manager knows when it entered and exited.
  Decide in Task 1.
- **Should `metadata.git_commit` be auto-injected?** Requires `git` to be
  available in the Docker image. Plutus repos generally have a git
  checkout, but not guaranteed inside a `docker run`. Decide in Task 1;
  default to "only if a `.git` directory is present."
- **Naming: snake_case enforced by schema?** The schema accepts any
  string. The convention is snake_case. Should the schema enforce
  `^[a-z][a-z0-9_]*$`? Lean: yes — names are machine identifiers and
  enforcing convention prevents downstream surprises. Decide in Task 1.

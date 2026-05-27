# Changelog

All notable changes to `plutus-verify` are recorded here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project is pre-1.0 and uses calendar-driven minor bumps.

## [0.2.6] — 2026-05-26

A same-session follow-up to 0.2.5 that closed three items the 0.2.5
report had explicitly flagged as deferred ("the silent skip is real
but invisible," "`CompareResult.ok=True` for skipped is semantically
loose"), plus a previously-unnoticed blocking bug in the comparator
dispatcher.

### Breaking — Python API

If you import from `plutus_verify.spec.runtime`:

| 0.2.5 | 0.2.6 |
|---|---|
| `from plutus_verify.spec.runtime.refcompare import compare_artifact` | `from plutus_verify.spec.runtime.artifact_compare import compare_artifact` |
| `from plutus_verify.spec.runtime.refcompare import CompareResult` | `from plutus_verify.spec.runtime.artifact_compare import CompareResult` |

The module was renamed `refcompare.py` → `artifact_compare.py` for the
same noun-honesty motivation as the 0.2.5 `reference_outputs` →
`artifacts` rename, and to match the codebase's snake_case module
convention.

No YAML / manifest changes in this release. The 0.2.5 manifest schema
(`expected[].artifacts:`) is unchanged.

### Fixed

- **`visual_similarity` no longer blocks on a missing snapshot.** In
  0.2.5 the comparator dispatcher (`compare_artifact`) hard-failed
  with `ok=False, "expected file not found"` if `.plutus/expected/`
  was empty — **before** dispatching on `ref.compare`. This silently
  contradicted the 0.2.5 promise that `visual_similarity` is fully
  opt-in: a user who declared `compare: visual_similarity` but hadn't
  yet run `plutus snapshot` got the same blocking exit=1 the
  pre-0.2.5 missing-vision-client case had given.

  Fix: existence checks moved into each comparator. `byte_exact` and
  `json_numeric_tolerance` keep the strict gate (missing reference =
  real failure for deterministic comparators). `visual_similarity`
  now treats missing-expected as a non-blocking skip, symmetric to
  missing-vision-client. Missing-*produced* still fails for all
  kinds (means the script didn't write its declared output — not
  something `plutus snapshot` can solve).

  New skip detail: `"skipped (no reference at <path>; run `plutus
  snapshot` to enable)"`.

### Added

- **`CompareResult.skipped: bool`.** Distinguishes "not verified" from
  "verified pass" honestly. Previously the two states both used
  `ok=True` and were disambiguated by string-matching `"skipped"` in
  `detail`. Both skip sites in `_visual_similarity` now set
  `skipped=True`.
- **`CompareResult.path: str`.** Stamped by the dispatcher with
  `ref.path`. Lets the renderer label each artifact line without
  re-walking the manifest.
- **Artifact rendering in `plutus check` report.** Per-step lines like:
  ```
    ok in_sample_backtest: exit=0
        ok sharpe_ratio: actual=0.95 expected=0.95
        SKIP visual_similarity result/backtest/hpr.svg  [skipped (no reference at …; run `plutus snapshot` to enable)]
        FAIL byte_exact result/data.csv  [bytes differ (data.csv vs data.csv)]
  ```
  Markers: `ok` / `SKIP` / `FAIL`. Closes the silent-fail and
  silent-skip UX gap from 0.2.0 and 0.2.5 — every artifact result is
  now visible alongside metric results.

### Migration

For any repo that pinned `plutus-verify==0.2.5` and imports the runtime
module directly (most downstream users don't — they only invoke the
CLI):

```bash
# in your Python code, replace the module path
sed -i.bak 's/plutus_verify.spec.runtime.refcompare/plutus_verify.spec.runtime.artifact_compare/g' your_module.py
```

YAML manifests, CLI flags, and SDK calls are unchanged from 0.2.5.

## [0.2.5] — 2026-05-26

A naming-honesty + packaging pass on top of the v2 MVP. **Schema-level
breaking changes for any repo that already shipped a v2 `manifest.yaml`**
— migration is mechanical and described below.

### Breaking — manifest YAML

The `expected[].reference_outputs` key was renamed to
`expected[].artifacts`. This mirrors the SDK side (`results.json`
already uses `artifacts:`), so the producer and verifier sides now share
one noun.

```yaml
# 0.2.0
expected:
  - step_id: in_sample_backtest
    metrics: [...]
    reference_outputs:
      - path: result/hpr.svg
        compare: visual_similarity

# 0.2.5
expected:
  - step_id: in_sample_backtest
    metrics: [...]
    artifacts:
      - path: result/hpr.svg
        compare: visual_similarity
```

A one-liner that fixes any repo's manifest:

```bash
# from the repo root containing .plutus/manifest.yaml
sed -i.bak 's/reference_outputs:/artifacts:/g' .plutus/manifest.yaml
```

Schema validation rejects the old key — manifests with
`reference_outputs:` will fail `plutus check` with a clear schema error.

### Breaking — Python API

If you import from `plutus_verify.spec` or pass kwargs to the scaffold
helpers, these symbol names changed:

| 0.2.0 | 0.2.5 |
|---|---|
| `from plutus_verify.spec import ReferenceOutput` | `from plutus_verify.spec import Artifact` |
| `ExpectedBlock.reference_outputs` | `ExpectedBlock.artifacts` |
| `compare_reference_output(...)` | `compare_artifact(...)` |
| `V2RuntimeResult.reference_results` | `V2RuntimeResult.artifact_results` |
| `scaffold_snapshot(..., update_reference_outputs=...)` | `scaffold_snapshot(..., update_artifacts=...)` |

### Breaking — CLI

```
plutus snapshot --no-reference-outputs   →   plutus snapshot --no-artifacts
```

### Breaking — `visual_similarity` is now opt-in

In 0.2.0, manifests declaring `compare: visual_similarity` for a
reference output would **fail** `plutus check` when no vision client was
configured (which was the only public state — the CLI never wired one
up). That failure mode is gone.

- **Default (no flag):** `visual_similarity` comparisons are skipped
  with a non-blocking note. `plutus check` exits 0 if everything else
  passes.
- **Opt-in:** pass `--visual-check` to `plutus check`. The CLI will
  instantiate an `OpenAIVisionClient` from env vars
  `PLUTUS_VISION_ENDPOINT`, `PLUTUS_VISION_MODEL`, and (optional)
  `PLUTUS_VISION_API_KEY`. If `--visual-check` is set but either of the
  first two env vars is missing, the CLI exits 2 with a clear error
  before doing any work.

Downstream consumers that were relying on the implicit "no client → fail
the run" behavior to gate visual checks should switch to
`--visual-check` explicitly.

### Added

- **New unit kind: `fraction`.** The dimensionless bucket was split.
  Use `unit="fraction"` for percent-like metrics (write 42% as
  `0.42` — win rate, max drawdown, annual return); keep `unit="ratio"`
  for unbounded dimensionless numbers (Sharpe, Sortino, profit factor).
  `"percent"` is still rejected.
  - The existing `unit="ratio"` value remains valid, so any 0.2.0
    `results.json` files keep validating against the new schema.
  - The default for `r.metric(name, value)` (no `unit=`) is still
    `"ratio"`.
- **`--visual-check` flag** for `plutus check` (see above).
- **`httpx>=0.27` is now a declared dependency** of the wheel. In 0.2.0
  the wheel imported `httpx` at module load (via
  `plutus_verify.extract.client`) but never declared it, so a fresh
  `pip install plutus-verify` crashed on `plutus --help` until the user
  separately ran `pip install httpx`.

### Fixed

- **`__version__` drift.** `plutus_verify.__version__` was `"0.1.0"`
  while `pyproject.toml` shipped `0.2.0`. Both are now sourced
  consistently. (Test fixtures that hard-coded the version string were
  updated too.)
- **Honest `UNIT_KINDS` docs and error message.** The old wording told
  authors to "normalize to a ratio," which read as "convert percent → a
  fraction in [0, 1]" — but the same bucket also held Sharpe = 1.7.
  Docs and the `ValueError` raised on bad `unit=` now name both buckets.

### Internal / non-shipping

- **`USER_GUIDES.md`** had a stale enum list naming `"percentage"`,
  `"absolute"`, `"currency"` (none of which existed). Corrected.
- **ProtoMarketMaker upgrade applied:** module-level
  `data_service = DataService()` at the bottom of
  `database/data_service.py` was unused dead code that opened a DB
  connection at import time. Removed. The only caller already
  instantiates `DataService()` locally. This is in the
  `ProtoMarketMaker` repo, not `plutus-verify` itself — included here
  because it's the canonical reference implementation that downstream
  users mirror.

### Migration checklist

For any repo that already shipped a v2 manifest under 0.2.0:

1. Rename the YAML key in `.plutus/manifest.yaml`:
   ```bash
   sed -i.bak 's/reference_outputs:/artifacts:/g' .plutus/manifest.yaml
   ```
2. Re-label percent-like metrics from `unit="ratio"` to
   `unit="fraction"` in your `pv.step()` script (drawdowns, returns,
   win rates). Optional — `"ratio"` still validates — but recommended
   for honesty.
3. Bump your pinned `plutus-verify` to `0.2.5`.
4. If you were relying on `visual_similarity` checks to actually run,
   add `--visual-check` to your CI invocation and set
   `PLUTUS_VISION_ENDPOINT` + `PLUTUS_VISION_MODEL` env vars.
5. Run `plutus check .` — exit 0 expected.

## [0.2.0] — 2026-05-25

The v2 MVP. Released as four phases (A–D) over the
`feat/spec-v2-foundation` branch, then a `/simplify` consolidation pass
on `refactor`. See [completion reports](docs/completion-report/README.md)
for the detailed history.

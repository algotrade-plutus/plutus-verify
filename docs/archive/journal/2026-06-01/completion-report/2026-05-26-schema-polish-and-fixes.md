# Schema polish and packaging fixes (v0.2.5 + 0.2.6)

A reading-the-schema-aloud session with the user surfaced two latent
honesty problems, two packaging bugs, and one premature failure mode in
the CLI. Each was small in isolation; together they justified a 0.2.5
bump and the project's first `CHANGELOG.md`. A follow-up pass in the
same session closed three deferred items (rendering, the `skipped`
field, plus a previously-unnoticed missing-snapshot blocking bug) and
renamed the comparator module to match the broader naming pass; that
shipped as **0.2.6**.

## TL;DR

| Theme | Change |
|---|---|
| **Honesty — units** | `UNIT_KINDS` widened from `("ratio", ...)` to `("fraction", "ratio", ...)`. `fraction` is for percent-like metrics (write 42% as 0.42); `ratio` keeps unbounded dimensionless (Sharpe, Sortino, etc.). `percent` still rejected. |
| **Honesty — artifacts** | Manifest YAML `reference_outputs:` → `artifacts:` (and `ReferenceOutput` → `Artifact`, etc.). Mirrors the SDK side which already used `artifacts:`. |
| **Packaging** | `httpx>=0.27` added to required deps (was imported by `extract/client.py` at module load but undeclared in the wheel). |
| **Packaging** | `plutus_verify.__version__` was `"0.1.0"` while `pyproject.toml` shipped `0.2.0`. Both now `"0.2.6"`. |
| **CLI** | `visual_similarity` reference checks are now opt-in via `--visual-check`. Default behavior is skip-with-note instead of fail. |
| **Sibling repo** | Removed dead module-level `data_service = DataService()` from ProtoMarketMaker that opened a DB connection at import time. Single-line delete; the only caller already instantiates locally. |
| **0.2.6 — opt-in symmetry** | Missing-expected file for `visual_similarity` is now a non-blocking skip (was a hard fail before dispatch). `byte_exact` / `json_numeric_tolerance` keep their strict gate. Existence checks moved into each comparator. |
| **0.2.6 — rendering** | `plutus check` report now prints one line per artifact (`ok` / `SKIP` / `FAIL` + kind + path + detail). Closes the silent-skip UX gap. |
| **0.2.6 — module rename** | `plutus_verify/spec/runtime/refcompare.py` → `artifact_compare.py` (and its test file). Same naming-honesty motivation as the `reference_outputs` → `artifacts` rename; also snake_case-consistent with the rest of the codebase. |

**Test posture:** 493 → **497** (4 new tests for the 0.2.6 follow-up
landings; existing test files had fixtures or identifiers updated to
match the new names).

## Why each landed

### The unit-kinds split

The trigger was a Socratic question — "what is `ratio`?" — that
exposed two contradictory mental models living in one label:

- Docstring at [`schema.py:5`](../../plutus_verify/sdk/schema.py#L5) read
  "normalize to a ratio," implying *fraction in [0, 1]*.
- Same bucket also held Sharpe (1.7) and Sortino, which are not
  fractions.

After confirming the schema enum is not consumed by any downstream
branch (it's metadata, not control flow — see
`grep "unit" plutus_verify/spec/runtime plutus_verify/verifier plutus_verify/scorer`),
the split cost was just one enum entry and a docstring rewrite. Future
chart renderers now have the signal needed to render `0.42` as `"42%"`
vs. `1.70` as `"1.70"` without inferring from the value range.

Tuple order: `("fraction", "ratio", "count", "currency_usd", "seconds")`
— dimensionless siblings adjacent, then counting → money → time.

Default for `r.metric(name, value)` (no explicit `unit=`) stays
`"ratio"` because it's the more permissive bucket. Templates set the
right label explicitly, which is where the teaching happens.

### The `reference_outputs` → `artifacts` rename

Same trigger style: "but metrics are also referenced — the word
'reference' is doing double duty." Confirmed by examining the SDK
schema, which already writes `artifacts: [{name, path, kind}]` to
`results.json`. The manifest's `reference_outputs: [{path, compare,
threshold}]` was the verification side of the same concept under a
different noun.

Renaming gives a clean parallel: `metrics` (numeric scalars) ↔
`artifacts` (file outputs), producer ↔ verifier symmetry. The two
shapes have different fields (the producer declares `kind`, the
verifier declares `compare`), but that's the natural difference between
"I made this" and "verify this."

**Why this is a hard break, not a soft one:** the schema rejects
unknown YAML keys. Manifests still using `reference_outputs:` will fail
loud on `plutus check` with a JSON-Schema error. That's the right
posture for pre-1.0 — no silent dual-key compatibility shim that rots
later.

### `visual_similarity` becoming opt-in

In 0.2.0 the CLI hardcoded `vision_client=None` at the call site, and
`_visual_similarity()` in `artifact_compare.py` (then named
`refcompare.py`; see the rename below) returned `ok=False` with detail
`"vision_client required"` for any `compare: visual_similarity` entry.
So ProtoMarketMaker's manifest — which declares `visual_similarity` for
6 SVG charts — could *never* exit 0 under default `plutus check`.

The flip:

1. [`artifact_compare.py::_visual_similarity`](../../plutus_verify/spec/runtime/artifact_compare.py) —
   when `vision_client is None`, return `ok=True` with detail
   `"skipped (no vision client configured; pass --visual-check to enable)"`.
   (A second symmetric skip-axis — missing reference image — was added
   in the follow-up pass; see below.)
2. [`__main__.py:368-411`](../../plutus_verify/__main__.py#L368-L411) — added
   `--visual-check` to `plutus check`. When passed, builds an
   `OpenAIVisionClient` from `PLUTUS_VISION_ENDPOINT` /
   `PLUTUS_VISION_MODEL` (+ optional `PLUTUS_VISION_API_KEY`). Missing
   env vars → exit 2 at startup, before any Docker build.

The user's exact framing: "only do similarity where LLMs presented; if
the similarity check flag is turned on, need to have LLMs presented."
The default is now a non-blocking skip; opting in via the flag
**requires** the LLM be wired.

### The two packaging fixes

Both were noted in a review comment that arrived as the
`/simplify`-pass branch was being prepped for merge:

- **`httpx` undeclared.** `plutus_verify/__main__.py:29` imports
  `OpenAIVisionClient`, which lives in `plutus_verify.compare.vision_client`
  but more critically the CLI module also imports
  `from plutus_verify.extract.client import OpenAIVisionClient` —
  `extract/client.py` does `import httpx` at module top. A fresh `pip
  install plutus-verify` (no extras) installed every other dep but not
  httpx, so `plutus --help` crashed with `ModuleNotFoundError: httpx`
  before printing anything. Reported by a user who tried the wheel
  cold. One-line fix: added `"httpx>=0.27"` to required
  `dependencies` in [`pyproject.toml`](../../pyproject.toml).
- **`__version__` drift.** The package's `__version__` constant was
  set to `"0.1.0"` since the v1 era and never updated when
  `pyproject.toml` moved to `0.2.0`. Now both are `"0.2.5"`. Updated
  two test fixtures that hard-coded the string for completeness.

### The Path B refactor in ProtoMarketMaker

A separate review comment about the canonical-PLUTUS-shape manifest
flagged that ProtoMarketMaker had been routing DB secrets to all three
executable steps and `network: bridge` to all three — a workaround for
`database/data_service.py` opening a connection at module import time.
That workaround was *guidance only*; the actual manifest committed to
the repo was already canonical (DB secrets only on `data_collection`,
backtest steps on `network: none`).

Root cause is at the bottom of
`ProtoMarketMaker/database/data_service.py`:

```python
data_service = DataService()   # ← line 102, runs at module import
```

`DataService.__init__` calls `psycopg2.connect()`, so any import chain
that touches `data_service` opens a DB connection — even
`backtesting.py`, which only reads CSVs. Path A would have been to
re-introduce the bridge/secrets workaround in the manifest. Path B
(preferred) deletes the line.

Verification: `grep -rn "from database.data_service import data_service"`
in ProtoMarketMaker returned zero hits. The only caller of the module
already does `data_service = DataService()` locally inside
`data_loader.py:23`. The module-level binding was orphaned dead code.
One-line delete; nothing else needed to move.

This is the canonical reference implementation that downstream users
mirror, so the fix is documented in the changelog under the
`Internal / non-shipping` section.

### Follow-up landings (same session, 0.2.6)

After the 0.2.5 work shipped, two latent items the report itself had
flagged as "still latent" turned out to be load-bearing for the
ProtoMarketMaker flow — and a third bug surfaced reading the comparator
dispatcher more carefully. All three landed in the same session and
bumped to **0.2.6**.

**1. The opt-in contract had an asymmetric hole.** The dispatcher at
the top of `compare_artifact()` did `if not expected_path.exists():
return ok=False, …` *before* dispatching on `ref.compare`. For
`visual_similarity` this contradicted 0.2.5's "non-blocking opt-in"
contract: a user who declared `compare: visual_similarity` but hadn't
yet run `plutus snapshot` got the same blocking exit=1 the
missing-vision-client case had given in 0.2.0 — just with a different
reason in the (un-rendered) detail.

Fix: move the existence checks **into each comparator** so each kind
owns its semantics. `byte_exact` and `json_numeric_tolerance` keep the
strict gate — those are deterministic, a missing reference is a real
failure. `_visual_similarity` now returns a non-blocking skip for
missing-expected, symmetric with the missing-vision-client skip already
in place. Missing-*produced* still fails: that means the script didn't
write its declared output, which is not a snapshot question.

**2. `CompareResult` got `skipped: bool` and `path: str`.** The
previous design used `ok=True` + `"skipped"` in `detail` to encode
skip, conflating "verified pass" with "not verified" — which the
original report explicitly flagged as semantically loose. Adding the
field lets the renderer pick the marker honestly (`SKIP` vs. `ok` vs.
`FAIL`) without string-matching the detail. `path` is stamped by the
dispatcher via `dataclasses.replace` so every result carries its
repo-relative path back to the renderer — no need for the renderer to
re-walk the manifest to label lines.

**3. `check_report.py` now renders artifact results.** Per-step lines
like:

```
  ok in_sample_backtest: exit=0
      ok sharpe_ratio: actual=0.95 expected=0.95
      SKIP visual_similarity result/backtest/hpr.svg  [skipped (no reference at …; run `plutus snapshot` to enable)]
      FAIL byte_exact result/data.csv  [bytes differ (data.csv vs data.csv)]
```

Before this, `runtime.artifact_results` was read only by
`scaffold/check.py` to compute the exit code — a step could exit 1
from an artifact failure with the user seeing no clue why. ~15-line
addition to `_render_step`.

**4. Module renamed `refcompare.py` → `artifact_compare.py`.** Same
reasoning as the broader 0.2.5 `reference_outputs` → `artifacts`
rename: the noun "reference" is doing double duty when expected metric
values are also references. Snake_case matches the codebase's
`check_report.py` / `manifest_edit.py` convention (`refcompare.py` was
the outlier). The test file followed the source:
`tests/unit/test_runtime_refcompare.py` →
`tests/unit/test_runtime_artifact_compare.py`. Used `git mv` to
preserve history.

Four new tests for the comparator changes:
`test_visual_similarity_missing_expected_returns_skip`,
`test_visual_similarity_missing_produced_fails`,
`test_visual_similarity_missing_vision_client_returns_skip` (locks the
new `skipped=True` invariant), and `test_compare_artifact_populates_path`.

**Test posture after the follow-up:** 493 → **497 passing**, 0 skipped,
0 xfailed.

## Files touched

### Source

[`plutus_verify/sdk/schema.py`](../../plutus_verify/sdk/schema.py),
[`plutus_verify/sdk/run.py`](../../plutus_verify/sdk/run.py),
[`plutus_verify/spec/manifest.py`](../../plutus_verify/spec/manifest.py),
[`plutus_verify/spec/__init__.py`](../../plutus_verify/spec/__init__.py),
[`plutus_verify/spec/schema.py`](../../plutus_verify/spec/schema.py),
[`plutus_verify/spec/loader.py`](../../plutus_verify/spec/loader.py),
[`plutus_verify/spec/adapter.py`](../../plutus_verify/spec/adapter.py),
[`plutus_verify/spec/runtime/artifact_compare.py`](../../plutus_verify/spec/runtime/artifact_compare.py) (renamed from `refcompare.py` in the follow-up pass),
[`plutus_verify/spec/runtime/orchestrator.py`](../../plutus_verify/spec/runtime/orchestrator.py),
[`plutus_verify/scaffold/check.py`](../../plutus_verify/scaffold/check.py),
[`plutus_verify/scaffold/check_report.py`](../../plutus_verify/scaffold/check_report.py) (artifact-line rendering),
[`plutus_verify/scaffold/snapshot.py`](../../plutus_verify/scaffold/snapshot.py),
[`plutus_verify/scaffold/bootstrap.py`](../../plutus_verify/scaffold/bootstrap.py),
[`plutus_verify/scaffold/extract_to_v2.py`](../../plutus_verify/scaffold/extract_to_v2.py),
[`plutus_verify/scaffold/templates.py`](../../plutus_verify/scaffold/templates.py),
[`plutus_verify/__main__.py`](../../plutus_verify/__main__.py),
[`plutus_verify/__init__.py`](../../plutus_verify/__init__.py),
[`pyproject.toml`](../../pyproject.toml).

### Tests (12 files, fixtures + identifier renames only)

`test_sdk_schema.py`, `test_sdk_run.py`,
`test_runtime_artifact_compare.py` (renamed from
`test_runtime_refcompare.py`; gained 4 new tests for the follow-up
landings), `test_runtime_orchestrator.py`, `test_scaffold_bootstrap.py`,
`test_scaffold_snapshot.py`, `test_scaffold_check.py`,
`test_extract_to_v2.py`, `test_spec_validator.py`, `test_spec_adapter.py`,
`test_spec_manifest.py`, `test_spec_loader.py`, `test_spec_schema.py`,
`test_cli_snapshot.py`, `test_pipeline_routes_v2_runtime.py`,
`test_check_report.py`, `test_report.py`. Plus the integration fixture
[`tests/integration/fixtures/spec_v2_minimal/.plutus/manifest.yaml`](../../tests/integration/fixtures/spec_v2_minimal/.plutus/manifest.yaml).

### Live docs

[`docs/others/USER_GUIDES.md`](../others/USER_GUIDES.md) (fixed enum
list + snippet labels), [`docs/others/protomarketmaker-upgrade.md`](../others/protomarketmaker-upgrade.md)
(one mention). New [`CHANGELOG.md`](../../CHANGELOG.md) at repo root with
a migration recipe.

### Sibling repo

[`ProtoMarketMaker/.plutus/manifest.yaml`](../../../ProtoMarketMaker/.plutus/manifest.yaml)
(2 occurrences of `reference_outputs:` → `artifacts:`),
[`ProtoMarketMaker/database/data_service.py`](../../../ProtoMarketMaker/database/data_service.py)
(deleted the module-level `data_service = DataService()` singleton).

### Out of scope (intentionally untouched)

- `docs/plan/*` and prior `docs/completion-report/*` are dated archives.
  References to `reference_outputs` / `ReferenceOutput` in those files
  are historically accurate and don't need rewriting. Searching them
  with `grep` after a rename will still surface — that's correct
  archeology.

## What's still latent (suggested follow-ups)

The first two items from the original 0.2.5 follow-up list landed in
the same session as part of the 0.2.6 pass — see "Follow-up landings"
above. The remaining item:

- **Re-test the wheel install cold.** `httpx` is now declared; worth a
  `pip install` from a fresh venv to confirm `plutus --help` works
  without any pre-installed deps.

# Phase D — Integrity hardening

**Plan 10.** Surfaced by the first real-world upstream ProtoMarketMaker
upgrade run (executed by a separate Claude Code session following the
handoff doc). Three bugs got the verifier to a state where it
silently produced false-positive "ok" metric lines under FAILED steps.
This phase closes those bugs and makes the output scannable.

## The bug that motivated this phase

The other Claude session ran `plutus check .` after instrumenting the
upstream repo and got this:

```
building image from .plutus/Dockerfile.generated...
image: plutus-v2:33d77ec3d2df
data tier: raw
  ok data_collection: exit=0 (skipped: satisfied_by_data_source)
  ok optimization: exit=0 (skipped: artifact_check ...)
  FAIL in_sample_backtest: exit=1
  FAIL out_of_sample_backtest: exit=1
  ok in_sample_backtest.sharpe_ratio: actual=0.9517 expected=0.9517
  ok in_sample_backtest.sortino_ratio: actual=1.3490 expected=1.3490
  ... (every metric "ok")
```

Steps FAIL but every metric matches perfectly? That can't be right.

**Diagnosis chain:**

1. The container crashed with `ModuleNotFoundError: No module named 'plutus_verify'` at `backtesting.py:12` (the `import plutus_verify as pv` line). Plan 7's SDK auto-injection silently failed — the generated Dockerfile had no `plutus_verify` install lines.
2. The orchestrator caught the `SdkBundleError` and noted it in `result.notes` — but the note was buried under the per-step output and missed by the operator.
3. Because the container crashed BEFORE the `pv.step(...)` block ran, no new `results.json` was written.
4. **But** the operator had run their scripts locally (Phase B handoff workflow's Step 4) before `plutus check`, leaving `.plutus/run/<step>/results.json` on disk from the host-side run.
5. The verifier read those stale files and compared against the manifest. Both came from the same host run, so all 12 metrics matched perfectly → false-positive "ok".

Three latent problems compounded:

| # | Problem | Where it lived |
|---|---|---|
| 1 | SDK auto-injection failed silently | `orchestrator.run_v2_pipeline` swallowed `SdkBundleError` |
| 2 | Verifier compared against stale `results.json` | No wipe between runs |
| 3 | Flat output buried the diagnostic notes | Per-step output not grouped |

## What shipped

### Fix 1 — Loud `SdkBundleError` when the manifest needs the SDK

`run_v2_pipeline` now detects "does this manifest declare scripts that
will need the SDK?" via `any(er.metrics for er in manifest.expected)`.
If yes AND bundling fails, the pipeline raises `SdkBundleError` instead
of degrading silently. The exception is wrapped with a clear message
("cannot bundle plutus-verify into image and the manifest declares
scripts that need the SDK ... Refusing to build a degraded image") and
the underlying cause chained.

Manifests with no expected metrics (scripts that hand-roll JSON or just
produce artifacts) keep the previous graceful-degrade behavior — they
genuinely don't need the SDK in the image.

### Fix 2 — Wipe `.plutus/run/` at the start of every check

`scaffold_check` (the CLI wrapper, not the orchestrator engine) clears
`<repo>/.plutus/run/` at the start of every run. The comparison phase
then reads ONLY what this run wrote. False positives from stale files
are structurally impossible.

The wipe lives in `scaffold_check`, not `run_v2_pipeline`, so direct
programmatic callers of the orchestrator (tests, future advanced
integrations) control hygiene themselves.

### Fix 3 — Skip metric comparison when step failed

`_compare_metrics` checks `step_results[er.step_id]` first. If the step
exited non-zero or had a preflight error, every declared metric is
reported as:

```
FAIL sharpe_ratio: step 'in_sample_backtest' failed (step exited 1); metric not evaluated
```

Even if a stale `results.json` somehow exists (e.g., test setup, future
edge cases), the verifier no longer compares against it when the step
itself failed. Belt + suspenders alongside Fix 2.

### Fix 4 — Vendor a prebuilt wheel inside the package

Plan 7's `ensure_plutus_wheel` relied on `importlib.metadata` to locate
the plutus-verify source on disk, then ran `python -m build` at image-
build time. Setuptools' default editable install produced `.egg-info`
metadata that the lookup chain handled poorly — that's where the silent
failure originated.

New approach: ship a prebuilt copy of the wheel inside the package
itself at `plutus_verify/_bundled/plutus_verify-X.Y.Z-py3-none-any.whl`.
`ensure_plutus_wheel` checks this location FIRST via
`importlib.resources.files`. If found, `shutil.copy2`'s the wheel into
the build context — no source-locate, no subprocess. The dev/editable
fallback (build from source) still exists for plutus-verify maintainers
working out of an editable install.

The vendoring is populated by `scripts/release-build.sh`, which does a
two-pass build:

1. With empty `_bundled/`, build the inner wheel
2. Copy that wheel into `plutus_verify/_bundled/`
3. Re-build → the final wheel contains the inner wheel

After install, the production wheel's `plutus_verify/_bundled/`
directory contains a copy of itself, ready to be staged into Docker
build contexts.

Combined with Fix 1 (loud failure), this makes "container can't
`import plutus_verify`" a surfaced error at the verifier layer instead
of a buried step failure.

### Fix 5 — 9-step framework output renderer

`plutus_verify/scaffold/check_report.py:render_check_report(manifest, runtime) -> list[str]`. Pure function returning a list of lines (Click iterates them). Three layout rules:

- Each framework step (1–7) gets a section header (`Step 4: In-sample Backtesting`)
- Manifest steps map under their declared `nine_step`; status indented 2 spaces
- Metric comparisons indent 6 spaces under each step
- Free-form steps (`nine_step: null`) appear under a final `Other steps:` section (omitted entirely when none)
- Runtime notes (SDK bundle status, data-tier choices) move to a `Notes:` section at the bottom

Before:

```
image: plutus-v2:33d77ec3d2df
data tier: raw
  ok data_collection: exit=0 (skipped: satisfied_by_data_source)
  ok in_sample_backtest: exit=0
  ok optimization: exit=0 (skipped: artifact_check ...)
  ok out_of_sample_backtest: exit=0
  ok in_sample_backtest.sharpe_ratio: actual=0.9517 expected=0.9516
  ok in_sample_backtest.sortino_ratio: actual=1.3490 expected=1.3490
  ... (12 more lines)
```

After:

```
image: plutus-v2:33d77ec3d2df
data tier: raw

Step 1: Hypothesis
  (no step in this manifest)

Step 2: Data Collection
  ok data_collection: exit=0 (skipped: satisfied_by_data_source)

Step 3: Data Processing
  (no step in this manifest)

Step 4: In-sample Backtesting
  ok in_sample_backtest: exit=0
      ok sharpe_ratio: actual=0.9517 expected=0.9516
      ok sortino_ratio: actual=1.3490 expected=1.3490
      ok maximum_drawdown: actual=-0.2011 expected=-0.2010
      ok hpr: actual=0.2993 expected=0.2992
      ok monthly_return: actual=0.0181 expected=0.0181
      ok annual_return: actual=0.1710 expected=0.1710

Step 5: Optimization
  ok optimization: exit=0 (skipped: artifact_check (no execution; outputs verified by preflight))

Step 6: Out-of-sample Backtesting
  ok out_of_sample_backtest: exit=0
      FAIL sharpe_ratio: actual=0.0815 expected=0.1105
      FAIL sortino_ratio: actual=0.1183 expected=0.1605
      ok maximum_drawdown: actual=-0.1029 expected=-0.1028
      FAIL hpr: actual=0.0802 expected=0.0848
      ok monthly_return: actual=0.0057 expected=0.0056
      ok annual_return: actual=0.0621 expected=0.0620

Step 7: Paper Trading
  (no step in this manifest)

Notes:
  - SDK wheel staged: plutus_verify-0.2.0-py3-none-any.whl
```

If a step fails, its metrics now render with the "step failed" diagnostic instead of a fake "ok":

```
Step 4: In-sample Backtesting
  FAIL in_sample_backtest: exit=1
      FAIL sharpe_ratio: step 'in_sample_backtest' failed (step exited 1); metric not evaluated
      ... (every declared metric, same diagnostic)
```

## Key files

```
plutus_verify/
  _bundled/                              # NEW: vendored wheel home
    __init__.py
    .gitignore                           # *.whl never committed
  spec/runtime/
    orchestrator.py                      # loud sdk_required gate + skip on failed step
    sdk_bundle.py                        # vendored-wheel branch FIRST, source-build fallback
  scaffold/
    check.py                             # wipe .plutus/run/ at start
    check_report.py                      # NEW: render_check_report pure function
  __main__.py                            # check_cmd iterates render_check_report lines
scripts/release-build.sh                 # MODIFIED: two-pass build with _bundled/ population
pyproject.toml                           # [tool.setuptools.package-data] for _bundled/*.whl
.gitignore                               # plutus_verify/_bundled/*.whl ignored
docs/plan/
  2026-05-25-plutus-verifier-integrity.md  (Plan 10)
docs/handoff/
  protomarketmaker-upgrade.md             # Step 1 patched: wheel install, not editable
```

## Tests

| Coverage | Tests |
|---|---|
| `test_check_report.py` (NEW) | 10 tests: grouping by nine_step, metric indentation, FAIL rendering, skipped_reason, free-form/"Other steps:" section presence + absence, Notes, suppression of `actual=None` lines, header content, framework-order |
| `test_runtime_orchestrator.py` | +2 new (loud-failure path, skip-on-failed-step), 1 renamed (graceful-degrade now scoped to "no expected metrics") |
| `test_scaffold_check.py` | +1 new (wipe-on-start prevents stale-results false positive) |
| `test_sdk_bundle.py` | +3 new (vendored wheel branch — used when present, falls back when absent, helper returns None in dev install) |

End of phase: **485 tests passing.**

## Workflow integrity guarantees this phase added

Combining Phase D's fixes:

1. **If the SDK can't be bundled and scripts need it** → `plutus check` exits 2 with a clear `SdkBundleError`. Operator sees the message immediately.
2. **If a step fails** → its metric comparisons render as `step '<id>' failed; metric not evaluated`. No fake "ok" lines.
3. **If stale `results.json` exists on disk** → wiped at the start. Verifier reads only this run's artifacts.
4. **If the operator scrolls past the diagnostic** → the 9-step layout puts step status visually next to its metrics. Failure pattern is one-look-and-obvious.

## Updated handoff

`docs/handoff/protomarketmaker-upgrade.md` Step 1 was patched: install
plutus-verify from a built wheel (`scripts/release-build.sh` → install
the resulting wheel via `pip install <path>.whl --force-reinstall`)
instead of `pip install -e`. The editable-install path was the
underlying trigger of the original incident.

## Branch state at end of phase

- `feat/spec-v2-foundation`: 65 commits ahead of `main`
- 485 tests passing, 0 xfailed
- `docs/plan/`: 11 plan docs (Plans 1–10 + DONE.md wrap-up)
- `docs/completion-report/`: this directory
- `docs/handoff/protomarketmaker-upgrade.md`: current handoff for the upstream upgrade
- `docs/runbook/publishing-to-pypi.md`: release runbook

## What this phase didn't close

A real-world re-run on the upstream ProtoMarketMaker (using the patched
handoff Step 1 with wheel install) is the next integration test. The
user confirmed Phase D's fixes by walking through the flow and getting
clean results.

The user's overall assessment after Phase D: **"90% confirmed that the
MVP works fine (discounted 10% for any flow that we do not test)."**
That's a defensible end-of-MVP posture.

## Suggested follow-ups (none in scope of this phase)

- **Run a fresh real-world upgrade** on an unrelated Plutus strategy repo to surface flows the ProtoMarketMaker test didn't exercise.
- **Publish to PyPI** following `docs/runbook/publishing-to-pypi.md`; flip `dockerfile_gen` to install from PyPI by version pin.
- **Delete the v1 LLM-extraction pipeline branch** in `pipeline.py` and `plutus_verify/extract/` once the legacy on-ramp (`plutus transfer`) can be replaced or retired.
- **GPU support** in `env.base` (currently rejected).
- **S3 data-source downloader** (currently only `google_drive`, `github_release`, `http`).
- **`plutus render-readme`** — template-fill a README.md from the manifest as the canonical documentation surface.

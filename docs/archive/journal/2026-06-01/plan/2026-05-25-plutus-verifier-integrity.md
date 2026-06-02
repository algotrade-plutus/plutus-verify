# Plutus v2 Spec — Verifier output integrity + SDK bundling robustness (Plan 10)

> **Retrospective plan.** This work was surfaced by the first real-world
> ProtoMarketMaker upgrade attempt (the handoff in
> `docs/handoff/protomarketmaker-upgrade.md`), where `plutus check`
> silently produced false-positive "ok" metric lines under FAILED steps
> because the verifier compared against stale host-side `results.json`
> from a prior local run.

**Goal:** Make `plutus check`'s output trustworthy in the presence of
(a) silent SDK-bundling failures and (b) stale `results.json` files on
disk. Plus reformat the report to group by the 9-step framework so the
12+ metric lines per run are scannable instead of a flat block.

**Commits:** `0aa39b4` (orchestrator integrity), `8853c26` (vendor wheel),
`daaac4a` (output reformat).

**Architecture:** Targeted surgical changes — no new modules of significance
beyond `_bundled/` (package directory) and `scaffold/check_report.py`
(pure-function renderer).

---

## Why this plan exists

End-to-end upgrade against ProtoMarketMaker produced this output:

```
FAIL in_sample_backtest: exit=1
FAIL out_of_sample_backtest: exit=1
  ok in_sample_backtest.sharpe_ratio: actual=0.95 expected=0.95
  ok in_sample_backtest.sortino_ratio: actual=1.34 expected=1.35
  ... (every metric "ok")
```

Two bugs surfaced:

1. **SDK auto-injection failed silently.** `ensure_plutus_wheel` couldn't
   find plutus-verify's source on the host (setuptools' editable install
   produced an `egg-info` layout that the lookup chain didn't handle
   robustly). The orchestrator caught the `SdkBundleError` and noted it
   in `result.notes` — but the note was buried under the per-step output
   and missed. The Dockerfile got no SDK install lines, the container
   crashed on `import plutus_verify` (line 12 of `backtesting.py`),
   step exited 1.

2. **Stale `results.json` produced false positives.** Bootstrap workflow
   has the author run their script locally to produce `.plutus/run/<step>/results.json`
   BEFORE running `plutus check`. After the container crash above, the
   container produced nothing new, but the host-side `results.json` from
   the local run was still on disk. The verifier read it and compared
   against the manifest — both came from the same host run, so all 12
   metrics matched perfectly. Exit code FAIL on steps, "ok" on every
   metric. A textbook false positive.

Plus a third, smaller UX issue:

3. **Flat output is hard to scan.** 12+ metric lines in a single block
   under the step results gets lost when scrolling. The 9-step framework
   already structures the manifest; the report should mirror it.

---

## Architectural decisions (recorded)

1. **Verifier owns the bundling. Loud on failure when SDK is required.**
   If `manifest.expected` has any non-empty `metrics:` block, scripts will
   call `pv.step(...)` and need `plutus_verify` in the container. A
   bundling failure for such manifests is fatal — the pipeline refuses
   to build a degraded image. Manifests that don't use `pv.step` (no
   expected metrics — e.g., hand-rolled JSON or artifact-only) keep the
   previous graceful-degrade behavior.
2. **Wipe-on-start belongs in `scaffold_check`, not in `run_v2_pipeline`.**
   `run_v2_pipeline` is the engine; its callers (the CLI via
   `scaffold_check`, and direct programmatic users) decide on hygiene.
   The CLI path wipes `.plutus/run/` at the start of every check;
   direct callers of `run_v2_pipeline` (tests, plus future programmatic
   users) manage that themselves.
3. **Skip metric compare on failed step.** Even if a stale `results.json`
   exists, if `step_results[er.step_id].exit_code != 0` (or there's a
   preflight error), every declared metric is reported as
   `step '<id>' failed (...); metric not evaluated`. Belt + suspenders
   alongside the wipe.
4. **Vendor a prebuilt wheel inside the package.** Production installs
   (a real release wheel) carry a copy of themselves at
   `plutus_verify/_bundled/plutus_verify-X.Y.Z-py3-none-any.whl`. The
   bundling helper finds it via `importlib.resources` and copies it into
   the Docker build context — no source-locate, no on-demand `python -m
   build`. Closes the lookup-fragility class entirely.
5. **Two-pass release build.** Chicken-and-egg: to ship a wheel-with-bundled-
   wheel-inside, build twice. First pass with empty `_bundled/` produces
   the inner wheel; copy it into `_bundled/`; second pass produces the
   final wheel containing the inner wheel. `scripts/release-build.sh`
   automates this.
6. **Renderer is a pure function.** `plutus_verify/scaffold/check_report.py:
   render_check_report(manifest, runtime) -> list[str]` returns lines;
   `__main__.py:check_cmd` just iterates and `click.echo`s. Keeps Click
   out of the renderer so the output shape is unit-testable.

---

## File structure

**New:**
- `plutus_verify/_bundled/__init__.py` — package directory for the vendored wheel
- `plutus_verify/_bundled/.gitignore` — prevents committing `*.whl`
- `scripts/release-build.sh` — two-pass build invocation
- `plutus_verify/scaffold/check_report.py` — pure-function renderer
- `tests/unit/test_check_report.py` — 10 unit tests for the renderer

**Modified:**
- `plutus_verify/spec/runtime/orchestrator.py` — loud-on-SDK-bundle-error when metrics required; skip-metric on failed step in `_compare_metrics`
- `plutus_verify/spec/runtime/sdk_bundle.py` — vendored-wheel branch (strategy #1 before the existing source-build path)
- `plutus_verify/scaffold/check.py` — wipe `.plutus/run/` at the start of each check
- `plutus_verify/__main__.py` — `check_cmd` uses `render_check_report` for output
- `pyproject.toml` — `[tool.setuptools.package-data] "plutus_verify._bundled" = ["*.whl"]`
- `.gitignore` — include `plutus_verify/_bundled/*.whl`
- `tests/unit/test_runtime_orchestrator.py` — new tests for the loud-failure and skip-on-failed-step paths; rename old test for the graceful-degrade case
- `tests/unit/test_scaffold_check.py` — new test for wipe-on-start
- `tests/unit/test_sdk_bundle.py` — new tests for the vendored-wheel branch

---

## What landed

### Commit `0aa39b4` — orchestrator integrity

Three changes to `run_v2_pipeline` + `_compare_metrics`:

**1. Loud SdkBundleError when manifest needs the SDK:**

```python
sdk_required = any(er.metrics for er in manifest.expected)
try:
    wheel = ensure_plutus_wheel(build_ctx)
    sdk_wheel_basename = wheel.name
except SdkBundleError as exc:
    if sdk_required:
        raise SdkBundleError(
            "cannot bundle plutus-verify into image and the manifest declares "
            "scripts that need the SDK ... Refusing to build a degraded image. "
            f"Underlying error: {exc}"
        ) from exc
    sdk_wheel_basename = None
    _sdk_bundle_error = str(exc)
```

**2. Wipe `.plutus/run/` at the start of `scaffold_check`:**

```python
run_dir = repo_path / ".plutus" / "run"
if run_dir.exists():
    shutil.rmtree(run_dir, ignore_errors=True)
```

The wipe lives in `scaffold_check` (CLI path), NOT in `run_v2_pipeline`. Tests of the orchestrator pre-stage `results.json` directly; the wipe would clobber that. CLI users get hygiene; programmatic users control it themselves.

**3. Skip metric compare on failed step:**

```python
def _compare_metrics(er, repo_path, step_results):
    sr = step_results.get(er.step_id)
    if sr is not None and (sr.exit_code != 0 or sr.preflight_error):
        reason = (
            f"preflight error: {sr.preflight_error}"
            if sr.preflight_error
            else f"step exited {sr.exit_code}"
        )
        detail = f"step '{er.step_id}' failed ({reason}); metric not evaluated"
        return {
            h.name: ExpectedMetricResult(
                name=h.name, ok=False, actual=None, expected=h.value, detail=detail
            )
            for h in er.metrics
        }
    # ... existing load_results / lookup logic continues
```

### Commit `8853c26` — vendor prebuilt wheel

`plutus_verify/_bundled/` is a Python subpackage. In dev (`pip install -e .`) it's empty — the existing source-build fallback covers it. In production (`pip install plutus_verify-X.Y.Z.whl`) it contains a vendored copy of the wheel itself, dropped there by `scripts/release-build.sh`'s two-pass build.

`ensure_plutus_wheel` checks the vendored path FIRST via `importlib.resources.files("plutus_verify._bundled")` and `shutil.copy2`'s the wheel into the build context if present. No subprocess invocation, no `python -m build`, no source-finding.

The release script:

```bash
# Pass 1: empty _bundled/, build inner wheel
rm -rf dist/ && find plutus_verify/_bundled -name '*.whl' -delete
python -m build --wheel
# Pass 2: copy pass-1 wheel into _bundled/, rebuild
cp dist/plutus_verify-*.whl plutus_verify/_bundled/
rm -rf dist/
python -m build --wheel
# Pass-2 wheel contains the pass-1 wheel inside; clean up _bundled/
find plutus_verify/_bundled -name '*.whl' -delete
```

### Commit `daaac4a` — 9-step output reformat

`plutus_verify/scaffold/check_report.py:render_check_report` is a pure function returning a list of lines. `check_cmd` iterates them via `click.echo`.

Output shape:

```
image: plutus-v2:33d77ec3d2df
data tier: raw

Step 1: Hypothesis
  (no step in this manifest)

Step 2: Data Collection
  ok data_collection: exit=0 (skipped: satisfied_by_data_source)

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
      ...

Notes:
  - SDK wheel staged: plutus_verify-0.2.0-py3-none-any.whl
  - data tier: raw (4/4 files satisfied via google_drive)
```

Free-form steps (`nine_step: null`) appear under a final `Other steps:` section (omitted entirely when none).

Metric lines with `actual=None` (the new "step failed, metric not evaluated" diagnostic) suppress the `actual=...` clause and lead with the detail:

```
      FAIL sharpe_ratio: step 'in_sample' failed (step exited 1); metric not evaluated
```

---

## Verification

**Unit:** 485 tests passing (475 baseline + 10 new in `test_check_report.py` + 3 new in `test_sdk_bundle.py` + 3 new + 1 renamed in `test_runtime_orchestrator.py` + 1 new in `test_scaffold_check.py`).

**Manual:** `scripts/release-build.sh` produces a wheel whose `unzip -l` listing contains both `plutus_verify/_bundled/__init__.py` AND `plutus_verify/_bundled/plutus_verify-0.2.0-py3-none-any.whl`. Confirmed.

**Integration (deferred):** end-to-end re-run against ProtoMarketMaker upstream is the actual customer test; the user will run it after the handoff doc is patched (a follow-up to this plan).

---

## Out of scope

- Vendoring works for the current local-wheel install pattern. PyPI publish flips
  `dockerfile_gen` to `pip install plutus-verify==<version>`; the runbook at
  `docs/runbook/publishing-to-pypi.md` covers that switch.
- The runtime's `Other steps:` rendering when free-form steps have metric
  comparisons (currently rare — `nine_step: null` is the escape hatch for
  ML training, custom pre-passes, etc.). Works structurally but no
  dedicated test coverage.

---

## Critical files referenced

- `plutus_verify/spec/runtime/orchestrator.py` — sdk_required gate, `_compare_metrics` skip logic
- `plutus_verify/spec/runtime/sdk_bundle.py` — vendored-wheel branch
- `plutus_verify/scaffold/check.py` — wipe at start
- `plutus_verify/scaffold/check_report.py` — renderer (NEW)
- `plutus_verify/_bundled/` — vendored wheel home (NEW)
- `scripts/release-build.sh` — two-pass build (NEW)
- `plutus_verify/spec/manifest.py:NINE_STEP_KEYS` — reused for ordering

# Plutus v2 spec — Plans 1-10 complete

Ten plans landed the v2 manifest format and got it running against a real
Plutus repo:

- **Plan 1** — foundation: `plutus_verify/spec/` (dataclasses, schema, loader,
  validator, adapter), pipeline branch on `.plutus/manifest.yaml`.
- **Plan 2** — native execution: `plutus_verify/spec/runtime/` (Dockerfile
  generator, data-tier resolver, I/O preflight, reference-output comparators,
  orchestrator). Pipeline routes v2 manifests to the native runtime.
- **Plan 3** — author CLI: `plutus_verify/scaffold/` (init/check/snapshot
  templates + commands), Click group restructure of `__main__.py`.
- **Plan 4** — legacy transfer: `plutus transfer` repurposes the LLM extractor
  to emit a draft v2 manifest for hand-cleaning.
- **Plan 5** — [live verification gap closure](2026-05-21-plutus-spec-v2-live-verification.md):
  real Docker image builder, locator gap fixes, `artifact_check` mode,
  `repo_path.resolve()`, data-resolver common-parent-dir, transfer prewarm +
  per-call progress. Surfaced and fixed by the first end-to-end run against
  ProtoMarketMaker (retrospective plan). The locator vocabulary it added
  (`stdout_regex`, `stdout_table`) was subsequently deleted in Plan 6.
- **Plan 6** — [results.json contract](2026-05-21-plutus-spec-v2-results-contract.md):
  inverted the comparison model. Scripts now emit
  `.plutus/run/<step_id>/results.json` (SDK or hand-rolled JSON); the verifier
  reads it and looks up metrics by snake_case name. `Locate` was deleted from
  the manifest model. Task 7 re-verified the contract end-to-end against
  ProtoMarketMaker — pass pattern matches Plan 5 baseline (6/6 in-sample,
  3/6 OOS; OOS divergence is an upstream reproducibility finding, not a
  pipeline regression). Golden manifest + results.json live under
  `out/transfer-test/ProtoMarketMaker/` (gitignored working copy).
- **Plan 7** — [package + SDK-in-Docker](2026-05-22-plutus-package-and-sdk-in-docker.md):
  packaged `plutus_verify` as a wheel and wired the Dockerfile generator to
  bundle + install that wheel inside every generated image, so author scripts
  can `import plutus_verify as pv` and call `pv.step(...)` without
  `requirements.txt` plumbing. Task 4 re-verified ProtoMarketMaker end-to-end
  with real SDK calls inside the container — same pass pattern as Plan 6 / Task
  7 (6/6 in-sample, 3/6 OOS), confirming the SDK install path is correct and
  is not a regression vector.
- **Plan 8** — [snapshot --metrics](2026-05-22-plutus-snapshot-metrics.md):
  `plutus snapshot` now extracts metric values from
  `.plutus/run/<step_id>/results.json` and writes them into
  `expected.metrics[].value` via a ruamel.yaml round-trip editor that
  preserves comments, indentation, and key order. Author workflow becomes
  *write skeleton → snapshot → review `git diff manifest.yaml` → commit*; the
  commit IS the verification claim. Integration-verified against
  ProtoMarketMaker (corrupted sharpe_ratio to 999.0/-42.0 → snapshot
  restored both to the real script values; diff contains only the 12 value
  changes, all other bytes identical).
- **Plan 9** — [plutus bootstrap](2026-05-22-plutus-bootstrap.md):
  `plutus bootstrap` reads `.plutus/run/<step_id>/results.json` files and
  the filesystem (`.python-version`, `pyproject.toml`, `requirements.txt`),
  emits a ~70%-filled `manifest.yaml.draft` plus a companion
  `manifest_TODO.md` with author-facing guidance for the ~8 fields that
  require domain knowledge (env.os_packages, secrets, data_sources,
  steps[].command/nine_step/inputs/depends_on, nine_step_coverage). Closes
  the new-repo author flow: write code → instrument with `pv.step(...)` →
  run → `plutus bootstrap` → fill TODO_* markers (grep-able) → `plutus
  check` → commit. Integration-verified against ProtoMarketMaker — draft
  regenerated from the sandbox's results.json contains both expected blocks
  with all 12 metrics auto-filled + snake_case → display_name conversions
  applied; guidance doc is 302 lines walking the author through each TODO.
- **Plan 10** — [verifier integrity + SDK bundling robustness](2026-05-25-plutus-verifier-integrity.md):
  surfaced by the first real-world upstream ProtoMarketMaker upgrade
  attempt. Closes three bugs: (a) SDK auto-injection silently failed and
  the verifier compared against stale host-side `results.json`, reporting
  false-positive "ok" metric lines under FAILED steps; (b) flat output
  hid the 12+ metric lines in a single block. Three fixes: loud
  `SdkBundleError` when the manifest needs the SDK; wipe `.plutus/run/`
  at the start of every `plutus check`; skip metric comparison when the
  step failed. Plus vendor a prebuilt wheel inside the package
  (`plutus_verify/_bundled/`) populated by `scripts/release-build.sh`, so
  production installs no longer rely on the fragile source-locate-then-
  build path. Plus a 9-step output renderer (`scaffold/check_report.py`)
  that groups manifest steps under their framework parent, indents
  metric comparisons under each step.

## End-state architecture

```
plutus-verify <git_url>          # legacy LLM path (still works)
plutus init <repo_path>          # scaffold .plutus/manifest.yaml + CI workflow
plutus check <repo_path>         # native v2 verification (Plan 2 runtime)
plutus snapshot <repo_path>      # capture run outputs into .plutus/expected/
plutus transfer <repo_path>      # legacy README → draft v2 manifest
plutus verify <git_url>          # explicit equivalent of bare `plutus-verify <git_url>`
```

## Still deferred (not in any of these 10 plans)

- Deletion of v1 `extract/plan.py` — the transfer tool depends on it; full
  schema retirement is a follow-up cleanup.
- The legacy "no manifest" pipeline branch in `pipeline.py` — still routes
  through LLM extract + v1 build/execute/compare for repos without `.plutus/`.
- GPU support (`env.gpu_required`, `env.base=python-cuda`).
- S3 downloader in the data-tier resolver.
- `plutus render-readme` (generate README from manifest).

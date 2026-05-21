# Plutus v2 spec — Plans 1-4 complete

Four plans landed the v2 manifest format:

- **Plan 1** — foundation: `plutus_verify/spec/` (dataclasses, schema, loader,
  validator, adapter), pipeline branch on `.plutus/manifest.yaml`.
- **Plan 2** — native execution: `plutus_verify/spec/runtime/` (Dockerfile
  generator, data-tier resolver, I/O preflight, reference-output comparators,
  orchestrator). Pipeline routes v2 manifests to the native runtime.
- **Plan 3** — author CLI: `plutus_verify/scaffold/` (init/check/snapshot
  templates + commands), Click group restructure of `__main__.py`.
- **Plan 4** — legacy transfer: `plutus transfer` repurposes the LLM extractor
  to emit a draft v2 manifest for hand-cleaning.

## End-state architecture

```
plutus-verify <git_url>          # legacy LLM path (still works)
plutus init <repo_path>          # scaffold .plutus/manifest.yaml + CI workflow
plutus check <repo_path>         # native v2 verification (Plan 2 runtime)
plutus snapshot <repo_path>      # capture run outputs into .plutus/expected/
plutus transfer <repo_path>      # legacy README → draft v2 manifest
plutus verify <git_url>          # explicit equivalent of bare `plutus-verify <git_url>`
```

## Still deferred (not in any of these 4 plans)

- Real Docker `image_builder` wired to `plutus check` (today raises
  `NotImplementedError`; you must call `scaffold_check` programmatically with a
  custom builder for CI runs).
- Deletion of v1 `extract/plan.py` — the transfer tool depends on it; full
  schema retirement is a follow-up cleanup.
- The legacy "no manifest" pipeline branch in `pipeline.py` — still routes
  through LLM extract + v1 build/execute/compare for repos without `.plutus/`.
- GPU support (`env.gpu_required`, `env.base=python-cuda`).
- S3 downloader in the data-tier resolver.
- `plutus render-readme` (generate README from manifest).
- `plutus_verify` SDK for in-code instrumentation (`pv.headline(...)`,
  `pv.export_manifest()`).

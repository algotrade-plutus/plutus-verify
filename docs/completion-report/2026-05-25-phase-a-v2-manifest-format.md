# Phase A — The v2 manifest format

**Plans 1–5.** The foundational inversion: stop extracting plans from
README prose via LLM; have authors write a machine-readable manifest
directly. The verifier reads the manifest, runs steps in Docker,
compares against author-declared expected results.

## What shipped

### Core surface

A new `plutus_verify.spec` package holding the v2 model end-to-end:

- **Data model** — 14 frozen dataclasses mirroring the v2 YAML structure: `Manifest`, `Repo`, `Env`, `Secret`, `DataSource`, `DataSourceTiers`, `Step`, `Locate`, `Tolerance`, `Headline`, `ReferenceOutput`, `ExpectedBlock`, `NineStepCoverage`, plus `NINE_STEP_KEYS` tuple. (`Locate` and `Headline` later evolved in Phase B — see report.)
- **Schema** — `RESULTS_SCHEMA` JSON Schema Draft 2020-12, validated via `jsonschema.Draft202012Validator`. Rejects unknown fields, enforces required keys, enums for `env.base`, `data_source.kind`, `step.network`, `step.verification_mode`, and the headline locator kinds.
- **Loader** — `load_manifest(repo_path)` reads `.plutus/manifest.yaml`, schema-validates, runs cross-field invariant checks (`validator.py`), returns the typed `Manifest`. Errors carry their cause and the offending YAML location.
- **Adapter** — `to_extracted_plan(manifest)` translates the v2 model into the v1 `ExtractedPlan` shape, so the existing `pipeline.py` can still produce the `plan.json` audit artifact downstream tools rely on.

### Native runtime

A new `plutus_verify.spec.runtime` package executing the manifest directly (no v1 adapter on the hot path):

- **`dockerfile_gen.generate_dockerfile`** — emits a deterministic `Dockerfile.generated` from the manifest's `env` block. Pins base image, copies `requirements.txt`, installs deps.
- **`data_resolver.resolve_data_tiers`** — implements the tiered data acquisition: try `data_sources.processed` first, fall through to `data_sources.raw`, fall through to running the step's command. Honors `expected_layout` and computes the common-parent directory for downloads (so Google Drive folders with nested layouts land in the correct place under the repo).
- **`preflight.assert_inputs_present` / `assert_outputs_present`** — checks each step's declared inputs exist before execution and outputs appear after. Glob support included.
- **`refcompare.compare_reference_output`** — compares produced artifacts against committed `.plutus/expected/` ground-truth files. Three strategies: `json_numeric_tolerance`, `byte_exact`, `visual_similarity` (chart comparison via Gemma).
- **`orchestrator.run_v2_pipeline`** — topologically sorts steps by `depends_on`, runs each in Docker (or skips per data-tier satisfaction / `artifact_check` mode), compares expected metrics, runs reference-output comparisons. Returns a `V2RuntimeResult` with structured step + metric + reference results.
- **`real_image_builder.build_image`** — actual Docker invocation. Writes `Dockerfile.generated` to `.plutus/`, tags by content hash (`plutus-v2:<sha256[:12]>`), runs `docker build`. Was the missing piece between "manifest exists" and "real run." (Added in Plan 5.)

### Author CLI

A new `plutus_verify.scaffold` package providing the four core author commands:

- **`plutus init <repo>`** — scaffolds `.plutus/manifest.yaml` skeleton + `.plutus/expected/` dir + `.github/workflows/plutus.yml`. Idempotent unless `--force`.
- **`plutus check <repo>`** — runs the native v2 pipeline locally with a real Docker daemon. Exits 0 (all pass), 1 (soft fail — metric/reference drift), or 2 (hard fail — required step failed).
- **`plutus snapshot <repo>`** — captures step outputs into `.plutus/expected/`. Refuses to snapshot from a failing run.
- **`plutus transfer <repo>`** — repurposes the v1 LLM extractor to emit a draft `manifest.yaml.draft` from a legacy README-based repo. Best-effort; emits `# TODO(plutus-transfer):` markers for fields the LLM couldn't fill confidently. Author hand-cleans the draft.

### CLI structure

`plutus_verify/__main__.py` restructured as a Click command group:

```
plutus init / check / snapshot / transfer / verify
```

`plutus verify` is the explicit equivalent of the legacy `plutus-verify <git_url>` entry point.

## Workflow this phase enabled

```
Author:
  plutus init .                          # scaffold manifest skeleton + CI
  (hand-write manifest fields, including expected.headlines[] with
   locate: blocks pointing at where metrics live in stdout/JSON files)
  plutus check .                         # build image, run steps, compare

Legacy on-ramp:
  plutus transfer <legacy-repo>          # LLM-extract a draft manifest
  (hand-clean the draft)
  plutus check .

Verifier:
  plutus verify <git_url>                # clone + run
```

## Key files

```
plutus_verify/
  spec/
    manifest.py          # 14 dataclasses + NINE_STEP_KEYS
    schema.py            # JSON Schema Draft 2020-12
    loader.py            # YAML → Manifest with cross-field validation
    validator.py         # invariant checks (no duplicate IDs, dep graph, etc.)
    adapter.py           # Manifest → v1 ExtractedPlan (audit-trail bridge)
    runtime/
      dockerfile_gen.py
      data_resolver.py
      preflight.py
      refcompare.py
      orchestrator.py
      real_image_builder.py  (added in Plan 5)
  scaffold/
    init.py              # plutus init
    check.py             # plutus check
    snapshot.py          # plutus snapshot
    transfer.py          # plutus transfer
    templates.py         # MANIFEST_SKELETON + WORKFLOW_YAML
    extract_to_v2.py     # v1 ExtractedPlan → draft v2 YAML
  __main__.py            # Click group
docs/plan/
  2026-05-20-plutus-spec-v2-foundation.md       (Plan 1)
  2026-05-21-plutus-spec-v2-native-execution.md  (Plan 2)
  2026-05-21-plutus-spec-v2-scaffold-cli.md      (Plan 3)
  2026-05-21-plutus-spec-v2-legacy-transfer.md   (Plan 4)
  2026-05-21-plutus-spec-v2-live-verification.md (Plan 5 — retrospective)
```

## Plan 5 — the retrospective patch

Plans 1–4 were unit-tested with fake in-process runners. The first
end-to-end run against `out/transfer-test/ProtoMarketMaker/` surfaced
five distinct gaps in 90 minutes:

| Gap | Fix |
|---|---|
| CLI couldn't actually build images | `real_image_builder.py` + wired into `check_cmd` via `make_image_builder()` |
| Real scripts print plain-text metrics, not markdown tables | Added `stdout_regex` locator kind alongside the existing `stdout_table` |
| Orchestrator rejected `verification_mode: artifact_check` | Branch in `_run_step` honors it: no execution, just preflight outputs |
| Docker mounts failed on relative `repo_path` | `repo_path = repo_path.resolve()` at orchestrator entry + in `build_image` |
| `gdown` downloaded to wrong location | `_common_parent_dir(expected_layout)` in `default_downloader` |
| `plutus transfer` looked hung on slow LLM | Prewarm + per-attempt progress via `on_attempt` callback; new `--config` / `--no-prewarm` flags |

These were retrospectively documented in [Plan 5](../plan/2026-05-21-plutus-spec-v2-live-verification.md). The locator vocabulary added here (`stdout_regex`, `stdout_table`) was later deleted in Phase B once the SDK + results.json contract made it obsolete.

## Test coverage

End of phase: **303 unit + integration tests passing** (303 → 310 by the
end of Plan 5).

Notable test surfaces:
- `test_spec_manifest.py`, `test_spec_loader.py`, `test_spec_schema.py`, `test_spec_validator.py`, `test_spec_adapter.py` — the v2 model
- `test_runtime_*` — runtime modules (orchestrator, data_resolver, preflight, refcompare, real_image_builder)
- `test_scaffold_*` — CLI commands
- `test_cli_group.py`, `test_cli_transfer.py` — Click integration
- `test_extract_to_v2.py` — reverse adapter
- `test_pipeline_routes_v2_runtime.py` — `pipeline.py` correctly routes v2 manifests to the native runtime
- `tests/integration/test_v2_runtime_e2e.py` — full-pipeline integration test with the `spec_v2_minimal` fixture

## Integration evidence

`out/transfer-test/ProtoMarketMaker/` exercised end-to-end via real Docker.
6/6 in-sample headlines passed; 3/6 OOS passed (Sharpe/Sortino/HPR drift
~26% — a real reproducibility issue in the upstream repo, surfaced by
the verifier doing its job). Pass pattern stable across re-runs.

## Limitations (carried into Phase B)

- The manifest had to mirror script implementation details (regex patterns, table column indices) because outputs were freeform. Each new script type meant a new `Locate.kind`.
- Unit ambiguity: README documented HPR as `29.92` (percent) but the script printed `0.29926` (ratio). Manifest had to match the script, not the README — confusing for authors.
- Locator vocabulary grew monotonically with each new script style encountered.

Phase B (Plan 6) collapses this by making the SCRIPT'S output canonical
instead of trying to bridge from freeform output to a structured manifest.

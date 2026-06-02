# Phase C — Production polish

**Plans 7, 8, 9.** With the input contract (Phase A) and output contract
(Phase B) settled, this phase made the package shippable, the SDK
reachable in the container, and the manifest-authoring flow ergonomic.
Three plans, each a separate user-visible capability.

## Plan 7 — Package + SDK in Docker

### Goal

Author scripts now `import plutus_verify as pv`. For that import to
work inside the verifier's generated Docker container, the SDK must be
present in the image. Plan 7 makes that happen invisibly — the author
never touches `requirements.txt` for the verifier.

### What shipped

- **PyPI-ready packaging.** `pyproject.toml` hardened: description, README pointer, license (MIT), authors, classifiers (10 entries, all valid against PyPI's trove_classifiers), keywords, urls. Version bumped 0.1.0 → 0.2.0 to mark the v2 spec inversion. `python -m build` produces a clean wheel + sdist; `twine check` PASSES on both.
- **`scripts/release-build.sh`** — two-pass build (later upgraded in Phase D to bundle a copy of the wheel inside itself).
- **`plutus_verify/spec/runtime/sdk_bundle.py`** — `ensure_plutus_wheel(build_context_dir)`. Locates the plutus-verify source via `importlib.metadata.distribution("plutus-verify")` (with `Path(plutus_verify.__file__)` fallback for setuptools editable installs), runs `python -m build` to produce a wheel, copies it into the build context. Idempotent — reuses a fresh wheel of the matching version.
- **`dockerfile_gen` auto-inject.** Generated `Dockerfile.generated` now contains:
  ```
  COPY .plutus/build/plutus_verify-0.2.0-py3-none-any.whl /tmp/...
  RUN pip install --no-cache-dir /tmp/plutus_verify-0.2.0-py3-none-any.whl
  ```
- **`orchestrator` stages the wheel.** Calls `ensure_plutus_wheel` into `<repo>/.plutus/build/`, threads the basename into `generate_dockerfile`. Builds the image. Author's `requirements.txt` stays clean.
- **PyPI publish runbook.** `docs/runbook/publishing-to-pypi.md` walks through prereqs (account + tokens + `.pypirc`), release procedure (version bump → tag → build → twine check → TestPyPI smoke → real PyPI), flipping the dockerfile_gen to `pip install plutus-verify==<version>` once published, and rollback (yank a broken release).

### Integration evidence

Re-verified the ProtoMarketMaker sandbox with real `import plutus_verify` in the scripts (replacing the hand-rolled JSON emitter from Phase B's first cut). Pass pattern unchanged: 6/6 in-sample, 3/6 OOS.

### Limitation that emerged

Plan 7 introduced graceful degradation on `SdkBundleError`: if the bundling helper couldn't find the source, the orchestrator emitted a note and proceeded without the SDK in the image. In the upstream ProtoMarketMaker test (Phase D's bug surface), this silently produced false positives. **Plan 10 fixed it by making the failure loud when the manifest needs the SDK.**

## Plan 8 — `plutus snapshot` fills metric values

### Goal

Kill the typing toil: the author shouldn't have to copy 12 numbers from
terminal output into manifest YAML.

### What shipped

- **`plutus_verify/scaffold/manifest_edit.py`** — `update_metric_values(manifest_path, updates)`. Uses `ruamel.yaml` round-trip mode to edit `expected.metrics[].value` entries in place. **Preserves comments, blank lines, indentation, key order.** The `git diff` after a snapshot shows only the value changes — nothing else.
- **`scaffold_snapshot` extended.** Two new kwargs: `update_reference_outputs` (default True; existing behavior) and `update_metric_values` (default True; new). Reads `.plutus/run/<step_id>/results.json` for every step that declared headlines and writes the values back into the manifest.
- **CLI flags** — `plutus snapshot --no-headlines` (later renamed `--no-metrics` in the Phase B rename) and `--no-reference-outputs` let authors opt out of either side.
- **`SnapshotResult.metrics_updated`** — counter surfaced in CLI output alongside `files_copied`.
- **Fail-safe semantics** — refuses to snapshot from a check that exit-code 2'd (a required step failed). Missing or malformed `results.json` for a particular step adds a note instead of crashing.

### Workflow this enabled

```
write manifest skeleton (just structure: name + tolerance, value=0.0 placeholder)
  → plutus check . (will fail values)
  → plutus snapshot --no-run .         # fills value: slots from results.json
  → git diff manifest.yaml             # review what got filled in
  → git commit manifest.yaml           # the commit IS the verification claim
```

The commit gate preserves the verification property — the manifest is the *committed* claim, not a fresh-derived one. Re-snapshot to update; the new diff is "I changed something."

### Integration evidence

Sandbox manifest corrupted (sharpe_ratio: 0.9516 → 999.0, OOS sharpe_ratio: 0.1105 → -42.0). Ran `plutus snapshot --no-run`; diff afterward contained EXACTLY the 12 value-line changes — comments, indentation, all other lines byte-identical. ✅

### A small wrinkle that took two attempts

First implementation of `manifest_edit` left ruamel.yaml at its defaults: emitted flush-left dashes on top-level sequences and wrapped long URLs at column 80. That churned the entire file on snapshot — defeating the "review-and-commit" workflow. Fixed by `yaml.indent(mapping=2, sequence=4, offset=2)` + `yaml.width = 4096`. Now the diff is clean.

## Plan 9 — `plutus bootstrap`

### Goal

Even with snapshot filling values, the author still had to write ~30
manifest fields by hand. Plan 9 auto-fills the ~70% that's derivable
from the script's `results.json` + the filesystem, leaving only the ~8
truly-unknowable fields as grep-able TODO_* markers.

### What shipped

- **`plutus_verify/scaffold/bootstrap.py`** — `scaffold_bootstrap(repo_path, *, force=False) -> BootstrapResult`. Discovers `.plutus/run/<step_id>/results.json` files, reads each via `load_results`, builds a manifest dict with TODO sentinels for unknowables, emits via the same ruamel.yaml config as Plan 8.
- **Filesystem detection helpers:**
  - `_detect_python_version(repo)` — `.python-version` > `pyproject.toml [project] requires-python` > `"3.11"`
  - `_detect_requirements_file(repo)` — `"requirements.txt"` if present, else None
  - `_detect_repo_name(repo)` — `Path.cwd().name`
  - `_to_display_name(snake_case)` — `"sharpe_ratio"` → `"Sharpe Ratio"`
  - `_artifact_compare_kind(artifact_kind)` — `chart|image → visual_similarity`; `json → json_numeric_tolerance`; `csv|other → byte_exact`
- **`plutus_verify/scaffold/manifest_template_todo.py`** — 250-line `MANIFEST_TODO_MD` template. One section per TODO field (env.os_packages, secrets, data_sources, free-form steps, command, nine_step, inputs, depends_on, nine_step_coverage). Each section: what it is, why the verifier needs it, worked example, common pitfalls. Closes with a "after filling in" troubleshooting block and a pointer at the ProtoMarketMaker sandbox manifest as the canonical worked example.
- **`plutus bootstrap` CLI** — refuses to overwrite `manifest.yaml` (author past this stage); refuses `manifest.yaml.draft` or `manifest_TODO.md` without `--force`; refuses with helpful error when no `results.json` files exist (author hasn't run scripts yet).

### Field automation tier

| Tier | Fields | Auto-fill source |
|---|---|---|
| 🟢 Fully derived | `schema_version`, `expected.metrics[].{name,value,unit,display_name}`, `expected.reference_outputs[]` | `results.json` directly |
| 🟡 Sensible defaults | `repo.{name,primary_language}`, `env.{base,python_version,requirements_file}`, `steps[].{network,timeout_seconds,verification_mode}`, `expected.metrics[].tolerance` | filesystem + constants |
| 🔴 TODO_* sentinels | `env.os_packages`, `secrets[]`, `data_sources[]`, free-form `steps[].id`, per-step `command`/`nine_step`/`inputs`/`depends_on`, `nine_step_coverage` | author writes; manifest_TODO.md walks them through it |

Author runs `grep TODO_ .plutus/manifest.yaml.draft` to find every spot still needing input. ~8 markers in a typical Plutus repo.

### Workflow this enabled (the canonical new-author flow)

```
write strategy code
  → instrument scripts with `with pv.step(...) as r: r.metric(...)`
  → run scripts locally → produces .plutus/run/<step>/results.json
  → plutus bootstrap .                   # generates manifest.yaml.draft + manifest_TODO.md
  → grep TODO_ .plutus/manifest.yaml.draft  # find spots to fill
  → fill in by hand using manifest_TODO.md guidance
  → mv .plutus/manifest.yaml.draft .plutus/manifest.yaml
  → plutus check .                       # verify
  → commit
```

### Integration evidence

Sandbox manifest moved aside; ran `plutus bootstrap`. Output:
- `.plutus/manifest.yaml.draft`: 119 lines, 14 TODO_* markers, both `in_sample_backtest` and `out_of_sample_backtest` expected blocks with all 12 metrics auto-filled (snake_case → display_name applied, artifact `kind: chart → compare: visual_similarity` mapped)
- `.plutus/manifest_TODO.md`: 302 lines of author-facing guidance

## Key files (this phase)

```
plutus_verify/
  spec/runtime/
    sdk_bundle.py                       # NEW (Plan 7): ensure_plutus_wheel
    dockerfile_gen.py                   # MODIFIED: SDK install lines
    orchestrator.py                     # MODIFIED: stages wheel + threads basename
    real_image_builder.py               # unchanged
  scaffold/
    manifest_edit.py                    # NEW (Plan 8): ruamel.yaml round-trip editor
    snapshot.py                         # MODIFIED: metric-value update + new kwargs
    bootstrap.py                        # NEW (Plan 9): scaffold_bootstrap
    manifest_template_todo.py           # NEW (Plan 9): MANIFEST_TODO_MD
  __main__.py                           # MODIFIED: snapshot flags, bootstrap subcommand
pyproject.toml                          # PyPI-ready metadata, version 0.2.0, ruamel.yaml dep
scripts/release-build.sh                # NEW: two-pass build (extended in Phase D)
docs/runbook/publishing-to-pypi.md      # NEW: release procedure
docs/plan/
  2026-05-22-plutus-package-and-sdk-in-docker.md  (Plan 7)
  2026-05-22-plutus-snapshot-metrics.md           (Plan 8)
  2026-05-22-plutus-bootstrap.md                  (Plan 9)
docs/handoff/
  protomarketmaker-upgrade.md           # 12-step playbook for upgrading the upstream repo
```

## Tests

| Plan | Tests added | Cumulative |
|---|---|---|
| Plan 7 | sdk_bundle (7), dockerfile_gen extensions (3), orchestrator extensions (2), CLI bootstrap (4) — ~16 net | 405 |
| Plan 8 | manifest_edit (12), scaffold_snapshot (7), CLI snapshot (5) — 24 net | 429 |
| Plan 9 | bootstrap (36), CLI bootstrap (4) — 40 net | 469 |

End of phase: **469 tests passing.**

## Integration evidence (end-to-end)

Sandbox `out/transfer-test/ProtoMarketMaker/` re-verified after Plan 7
with real `import plutus_verify` calls in scripts (running inside the
container). Pass pattern unchanged: 6/6 in-sample, 3/6 OOS. Confirms
the SDK install path works.

## Author-facing artifacts shipped

Three new docs for outside-the-team readers:

1. **`docs/runbook/publishing-to-pypi.md`** — release runbook
2. **`docs/handoff/protomarketmaker-upgrade.md`** — 12-step playbook for upgrading the upstream ProtoMarketMaker repo, with the exact manifest content, script diffs, troubleshooting, and ground-truth references
3. **The `manifest_TODO.md` template** itself — written by every `plutus bootstrap` invocation, walks new authors through filling in the 8 domain-knowledge fields

## What was left open at the end of Phase C

The first real-world run against the upstream ProtoMarketMaker repo
(executed by a separate Claude Code session following the handoff doc)
surfaced two bugs:

- **SDK bundling silently failed** on editable install metadata; orchestrator's "graceful degrade" hid the error
- **Stale results.json** from the local pre-bootstrap run produced false-positive "ok" lines under FAILED steps

Both are addressed by Phase D (Plan 10).

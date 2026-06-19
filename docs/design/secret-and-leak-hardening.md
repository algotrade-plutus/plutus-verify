---
subject: secret-and-leak-hardening
date: 2026-06-19
version: 1.1
status: current
---

# Secret & Leak-Channel Hardening — Architecture & Design

## Overview

This document records the **v0.2.5 → v0.2.10 leak-closure arc**: the work that
moved the v2 verifier from "works on the upstream reference repo" to "the
manifest's declared posture is *actually enforced* when run against a real
downstream Tier 3 (DB-backed) repo." It is as much a design narrative as a
component description, because the central insight is a *correctness* property,
not a feature.

The property: a step declared `network: bridge` with `secrets: [DB_*]` must
**either really query the declared database via routed env vars, or fail
exit=1 with "missing credentials."** Before this arc there was a silent third
path — "appeared to verify, actually short-circuited on host state" — where a
container quietly read the host's `.env` or a cached `.parquet` and "passed"
without doing the work. Closing that third path is what makes the verifier's
verdict trustworthy.

A parallel thread (Phase D, "integrity hardening") closed a related
false-positive: steps that FAILed but still reported `ok` metrics.

## Architecture — the three leak channels

```
host repo:  .env (DB creds) , data/cache/*.parquet (stale) , source , requirements
                 │                      │
       build context (COPY . .)    runtime mount (-v cwd:/srv/repo)
                 │                      │
   ≤0.2.8:  baked into image       overlaid live in container
   0.2.9:   .dockerignore excludes    (still overlaid — mount ignores .dockerignore)
   0.2.10:  excluded                per-step staging copy (filtered) — host invisible
```

| Channel | ≤ 0.2.8 | 0.2.9 | **0.2.10** |
|---|---|---|---|
| `.env` recoverable from image layers (docker-pull leak) | leaks via `COPY . .` | **closed** | closed |
| `.env` readable inside the running container | leaks via `COPY . .` | still leaks via mount | **closed** by staging |
| `data/cache/*.parquet` short-circuits the bridge step | leaks via `COPY . .` | still leaks via mount | **closed** by staging |

### Components involved

- **`.dockerignore` auto-emit** (0.2.9) — when a repo lacks one, the builder
  emits a conservative baseline excluding `.env`, `.env.local`, `.env.*.local`.
  A user-authored `.dockerignore` is preserved. This closes the *build-context*
  (image-layer) channel.
- **Per-step staging** (`plutus_verify/spec/runtime/staging.py`, 0.2.10) — each
  step runs against a `tempfile.TemporaryDirectory` populated from cwd through
  the `.dockerignore` filter (plus `step.inputs` if declared). The runner mounts
  the *staging dir*, never the live repo. Implemented with `pathspec`
  (gitwildmatch) so ignore matching is Docker-compatible. See
  [build-and-execute](build-and-execute.md).
- **`extract_outputs`** — pulls back `.plutus/run/<step_id>/` (always) plus
  `step.outputs`; nothing else survives the tempdir cleanup.
- **Integrity fixes** (Phase D) — `scaffold/check.py` wipe-on-start;
  `_compare_metrics` skip-on-failed-step; loud `SdkBundleError`; vendored
  prebuilt wheel under `plutus_verify/_bundled/`; the 9-step check-report renderer.

## Design Principles

- **Declared posture must be enforced, not advisory.** If the manifest says a
  step needs the DB, the run must prove it does.
- **No silent third path.** A step either does the work or fails loudly.
- **Defense in depth.** The wipe-on-start and skip-on-failed-step fixes overlap
  deliberately so a single regression can't resurrect a false positive.
- **Backward compatibility by safe default.** Tightening is opt-in; existing
  manifests keep working.

## Design Decisions

### Per-step staging copy replaces the live cwd mount
- **Context:** 0.2.9 closed the image-layer leak, but `.dockerignore` is a
  build-context concept — the runtime `-v {cwd}:/srv/repo` mount overlaid the
  host's full tree anyway, so host `.env` and stale cache still reached the
  container. Surfaced by the Group09 downstream feedback on 0.2.9.
- **Decision:** run each step in a filtered tempdir copy; copy declared outputs
  back; leave the `Runner` contract (`cwd=`) untouched.
- **Rationale:** the minimal change that makes `.dockerignore` exclusions hold at
  runtime. Inter-step state still flows through cwd (step N's outputs are copied
  back and picked up by step N+1's staging) — the mount is no longer the
  shared-state mechanism; cwd is.
- **Trade-offs:** it's a *copy*, not a mount restriction — the container still
  sees its whole staging filesystem; only what staging *contains* is limited
  (the tighter inputs-only-mount is a non-goal/parking-lot item). O(repo size)
  per step. Undeclared writes are dropped. It does not validate that scripts only
  *read* declared inputs (that would need ptrace/LSM); authors are trusted to
  declare honestly.

### Safe default: copy-everything-not-in-`.dockerignore` when `step.inputs` is empty
- **Context:** existing 0.2.9-era manifests have empty `inputs`/`outputs`. A hard
  switch to inputs-only filtering would break all of them.
- **Decision:** empty `step.inputs` → keep v0.2.9 behavior (copy everything not
  excluded). Non-empty `step.inputs` → a *positive complete-coverage allowlist*
  (only matching paths reach staging). Empty `step.outputs` → only
  `.plutus/run/<step_id>/` comes back.
- **Rationale:** zero-migration backward compatibility plus a gradual opt-in
  tightening path.
- **Trade-offs:** the allowlist semantics are a sharp edge — declaring narrow
  `inputs:` without listing the script binary silently breaks the step with
  `exit=2`. This is **gotcha G12**. The resolution was a *documentation* fix
  (recommend `inputs: []` as the new-manifest default, tighten step-by-step),
  not a framework change — `inputs` as a positive filter is held to be the
  correct verification primitive.

### Integrity: wipe-on-start in the CLI layer, not the engine
- **Context:** a real ProtoMarketMaker run reported `ok` metrics under FAILED
  steps. Root cause: the container crashed before writing a fresh `results.json`,
  and the verifier compared against a *stale* host-side `results.json` left from
  an earlier local run — which matched the manifest exactly (it had been
  snapshotted from those same files).
- **Decision:** `scaffold_check` deletes `.plutus/run/` before running, so the
  comparison reads only what *this* run produced. Placed in the CLI wrapper, not
  `run_v2_pipeline`, so programmatic callers/tests manage their own hygiene.
- **Plus:** `_compare_metrics` skips comparison on a failed step; a loud
  `SdkBundleError` refuses to build a degraded image when scripts need the SDK;
  a prebuilt wheel is vendored in `_bundled/` to make SDK-locate robust.

## Data Model

- `.plutus/run/<step_id>/` is the verifier-owned namespace for `results.json`,
  `stdout`, `stderr`, `meta.json` — always staged back out.
- `.dockerignore` (gitignore semantics) is the exclude filter; `step.inputs` is
  the positive allowlist; `step.outputs` is the copy-back allowlist.

## Error Handling & Edge Cases

- **The load-bearing test:** the e2e regression asserts host `.env` and
  `data/cache/stale.parquet` are invisible to the step container even when
  present on the host.
- A step that needs the DB but isn't given credentials fails exit=1 — never
  passes by reading cached data.
- A failed step renders every declared metric as `FAIL … metric not evaluated`
  rather than comparing against possibly-stale output.

## Performance Considerations

- `populate_staging` is O(repo size) per step; acceptable (<1s/step) for the
  ~100-file strategy repos targeted. Cache-reuse across steps for multi-GB repos
  is deferred (parking-lot item 3).

## The downstream feedback loop

The arc was driven by a real DB-backed student strategy,
`cs408-2026/Group09-BuyHighSellLow`, used as a **test-bench**. Each release, the
`plutus-transform` skill ran against it and the operator wrote findings to
`<repo>/.plutus/skill-feedback.md`. Five consecutive iterations (0.2.7, 0.2.8,
0.2.8 cleanroom, 0.2.9, 0.2.10) each surfaced one real upstream defect or doc
gap — until 0.2.10, where the only remaining gap was a Skill-doc tightening
(G12), not a framework bug. That convergence is the signal the line of work hit a
reasonable parking point.

## Release-by-release summary

| Version | Headline |
|---|---|
| 0.2.5 / 0.2.6 | Schema polish + packaging (`UNIT_KINDS`, `artifacts` rename, `--visual-check`; missing visual snapshot → non-blocking SKIP; per-step artifact rendering) |
| 0.2.7 | Byte fallback for `visual_similarity`; Skill split (transform/scoring); LLM-driven artifact baseline |
| 0.2.8 | `pyproject.toml` first-class as a dependency spec |
| 0.2.9 | Auto-emit conservative `.dockerignore`; closes the image-layer secret leak |
| 0.2.10 | Per-step staging dir; closes the runtime-mount `.env` leak + cache short-circuit; manifest secret routing genuinely authoritative (518 tests passing) |
| 0.4.2 | `--secrets-from-env` now resolves **only** the manifest's declared secret keys, scoped per secret `used_by`; previously it forwarded the whole host `os.environ` (incl. `PATH`) to every container — a fourth leak channel that contaminated the "reproducible" env and shadowed the uv venv. See "Per-step declared-secret resolution" below. |

### Per-step declared-secret resolution (0.4.2)

A fourth leak channel, distinct from the three mount/build-context channels above:
`plutus check --secrets-from-env` set `secrets = dict(os.environ)` and the v2
orchestrator forwarded that whole dict to **every** step as docker `-e KEY=VALUE`.
That both contaminated the container with the maintainer's host env (PATH, HOME,
editor/agent vars — so two machines produced different "reproducible" runs) and
re-broke uv repos: the injected `-e PATH=<host>` overrode the image's
`ENV PATH=/opt/venv/bin:$PATH`, hiding the venv (same symptom as the 0.4.1
login-shell bug). The fix is the pure helper
`orchestrator._resolve_step_secrets(declared, pool, step_id)`, which keeps only
declared secret keys whose `used_by` names the step — mirroring the v1 path's
`{k: secrets[k] for k in alt.needs_secrets if k in secrets}` (`execute.py`). The
incoming dict is now a *candidate pool*; with `secrets: []` nothing is injected.
A reserved-key denylist (`RESERVED_SECRET_KEYS` in `spec/manifest.py`: `PATH`,
`HOME`, `LD_LIBRARY_PATH`, …) is rejected by the validator and dropped by the
resolver, so a secret literally named `PATH` can't re-open the channel.

## Future Considerations (parking lot)

Ordered by how load-bearing the next decision is:

1. **Inputs-only mount (or `inputs:` exhaustiveness tooling).** Static analysis
   that suggests an `inputs:` set, or a `plutus check --strict-inputs` mode
   (needs ptrace/strace or LSM hooks — bigger).
2. **"Files left in staging" warning** in the check report.
3. **Staging cache reuse** across steps for very large repos.
4. **PyPI publish** (runbook ready; decision pending).
5. **GPU support** (`env.base=python-cuda`) — out of scope; raises `UnsupportedEnvError`.
6. **S3 / object-store data source** — deferred.
7. **Deletion of the v1 `extract/plan.py` / legacy LLM branch.**

When work resumes, the recommended next step is to run the skill against a
*different* downstream repo type (Tier 1 committed CSVs, or Tier 2 Drive-backed)
to surface the next class of gaps — Tier 3 has been the lens for this entire arc.

## Features Covered

- [authoring-tools](../feature/authoring-tools.md) — `plutus check` (where wipe-on-start and staging run).
- [v2-manifest](../feature/v2-manifest.md) — `inputs`/`outputs`/`secrets` semantics.
- [plutus-transform-skill](../feature/plutus-transform-skill.md) — gotchas G11/G12 that surfaced these issues.

## Source Materials

- Reports: `docs/completion-report/2026-06-01-v0.2.x-leak-closure-arc-pause.md`,
  `docs/completion-report/2026-05-29-v0.2.10-runtime-mount-staging.md`,
  `docs/completion-report/2026-05-25-phase-d-integrity-hardening.md`
- Plan: `docs/plan/2026-05-29-v0.2.10-runtime-mount-staging.md`
- Code: `plutus_verify/spec/runtime/{staging,orchestrator}.py`,
  `plutus_verify/scaffold/{check,check_report}.py`, `plutus_verify/_bundled/`,
  `scripts/release-build.sh`
</content>

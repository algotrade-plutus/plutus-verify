---
subject: build-and-execute
date: 2026-06-01
version: 1.0
status: current
---

# Build & Execution Subsystem — Architecture & Design

## Overview

This subsystem turns a checked-out repo into a runnable Docker image and then
runs each plan step inside a container, capturing outputs. It has three layers:
the **auto-fixing builder** (`builder/`) that generates a slim-Python image and
repairs common build failures; the **low-level Docker runner** (`runner_docker.py`)
that spawns containers; and the **per-step staging mechanism** (`spec/runtime/`)
that, since v0.2.10, isolates each step from the host filesystem so the
manifest's declared posture is genuinely enforced.

It exists because reproducibility verification has two adversaries: build
fragility (a repo's `requirements.txt` won't install cleanly on a fresh image)
and *leakage* (the container quietly reading host state — `.env`, cached data —
and "passing" without actually doing the work). The builder addresses the first;
the staging mechanism addresses the second. The leak story is large enough to
have its own doc: [secret-and-leak-hardening](secret-and-leak-hardening.md).

## Architecture

```
repo checkout
     │  build_with_fixers
     ▼
generate Dockerfile (python:3.11-slim) ──► docker build (attempt 1)
     │ fail                                       │
     ▼                                            │
pre-build fixers (deterministic) ─┐               │
post-build fixers (parse log)  ───┼─► regenerate + attempt 2
LLM fixer (constrained ops)    ───┘─► regenerate + attempt 3 ─► BuildError
     │ success → image tag
     ▼
per step:  TemporaryDirectory(staging)
           populate_staging(repo, staging, step)   # .dockerignore + step.inputs filter
           DockerRunner.run(image, command, cwd=staging, network, env=secrets)
           extract_outputs(staging, repo, step)     # .plutus/run/<id>/ + step.outputs
```

### Components

#### Builder — `plutus_verify/builder/`
- **`build_with_fixers`** (`runner.py:108`) — the default. Generates a minimal
  `python:3.11-slim` Dockerfile (`dockerfile.py:10`), builds, and runs the fixer
  loop (up to 3 attempts; Dockerfile regenerated each attempt from the
  accumulated apt list). **`build_image`** (`runner.py:46`) — the legacy
  repo2docker path, kept for back-compat (slow/fragile on macOS arm64).
- **Deterministic fixers** (`fixers.py`): pre-build (UTF-16 BOM→UTF-8,
  CRLF→LF, `psycopg`→`psycopg[binary]`) and post-build (parse three error
  signatures — unsatisfiable requirement → binary variant; missing C header →
  apt dev package; `ModuleNotFoundError` → append to requirements).
- **LLM fixer** (`llm_fixer.py`): a closed enum of typed ops
  (`add_to_requirements`, `pin_version`, `replace_in_requirements`,
  `add_apt_package`, `give_up`). The LLM only *suggests* JSON; Python validates
  against strict regexes (rejecting shell metacharacters / path traversal) and
  applies. Sends only `requirements.txt` + the last 40 log lines.

#### Docker runner — `plutus_verify/runner_docker.py`
- `DockerRunner.run(*, image, command, cwd, network, timeout_seconds, env)`
  (`:36`) builds `docker run --rm --network=<net> --memory=8g --cpus=4
  -v {cwd}:/srv/repo -w /srv/repo [-e K=V …] <image> bash -lc <command>`.
  Secrets are injected at runtime via `-e`, never baked into the image. On
  timeout → `ExecResult(exit_code=-1, outcome=TIMEOUT)`.

#### Staging — `plutus_verify/spec/runtime/staging.py`
- `populate_staging(cwd, staging, step)` (`:29`) copies cwd into a per-step
  tempdir through two filters: a `.dockerignore` exclude filter (parsed with
  `pathspec`, gitignore semantics) and, if `step.inputs` is non-empty, a
  positive allowlist. `extract_outputs(staging, cwd, step)` (`:56`) copies back
  `.plutus/run/<step_id>/` (always) plus paths matching `step.outputs`;
  everything else the script wrote is dropped.

#### Orchestrator — `plutus_verify/spec/runtime/orchestrator.py`
- `_run_step` (`:190`) wraps each executing step in a
  `tempfile.TemporaryDirectory`, calls `populate_staging`, runs against the
  staging path (the real repo is never mounted), then `extract_outputs`.

#### Progress — `plutus_verify/util/progress.py`
- Tees every event to stderr *and* `out/<run_id>/run.log`.

## Design Principles

- **Fast, predictable base image.** A slim Python image + targeted fixers beats
  repo2docker's slow auto-detection for the strategy repos this targets.
- **Every adjustment is a finding.** Build fixes surface in the report, not
  silently.
- **The LLM never runs code.** It proposes typed ops; Python validates and applies.
- **Isolation is the default.** `network: none`, runtime secrets via `-e`, and
  (v0.2.10+) a filtered staging copy so the container can't read host state.

## Design Decisions

### repo2docker → slim-Python auto-fixer
- **Context:** repo2docker auto-detects requirements/environment/Dockerfile/
  pyproject but is slow and stalls (30+ min) on macOS arm64.
- **Decision:** default to a hand-rolled `python:3.11-slim` Dockerfile + a
  deterministic-then-LLM fixer loop; keep repo2docker as `build_image`.
- **Rationale:** fast, predictable, and every fix is reportable.
- **Trade-offs:** the slim path is `requirements.txt`-centric (the manifest's
  `env` drives a separate v2 Dockerfile generator); the slim image lacks system
  libs, which is exactly why the psycopg/header fixers exist.

### Constrained-op LLM fixer
- **Context:** deterministic fixers can't cover everything; raw LLM shell access
  is an injection risk.
- **Decision:** a closed enum of typed ops, Python-validated and applied; the
  LLM only emits JSON.
- **Trade-offs:** the LLM can't do anything outside the enum; `give_up` is an
  explicit, honest outcome.

### Per-step staging copy instead of a live cwd mount
- **Context:** the `-v {cwd}:/srv/repo` mount bypassed `.dockerignore` at
  runtime, leaking host `.env` and letting cached data short-circuit recompute.
- **Decision:** each step runs against a filtered tempdir copy; declared outputs
  flow back. The `Runner` contract (`cwd=`) is unchanged — the orchestrator just
  hands it the staging path.
- **Rationale:** the minimal change that makes `.dockerignore` exclusions
  actually hold at runtime; inter-step state still flows through cwd (step N's
  outputs are copied back and picked up by step N+1's staging).
- **Trade-offs:** a full per-step copy is more I/O than a mount; undeclared
  writes are dropped; it restricts what staging *contains*, not what the
  container can read (the tighter inputs-only-mount is a parking-lot item).

## Data Model

- `BuildResult` (`runner.py:28`): `image`, `adjustments` (each a `BuildAdjustment`
  with `phase`/`kind`/`description` for the report).
- `ExecResult` (`execute.py:18`): `exit_code`, `stdout`, `stderr`,
  `duration_seconds`, `outcome` (`OK`/`FAILED`/`TIMEOUT`), `alternative_used`.
- `DockerRunnerConfig` (`runner_docker.py:19`): `memory_limit="8g"`,
  `cpu_limit="4"`, optional `user`/`extra_args`.
- v2 runtime results (`orchestrator.py:46`): `StepRuntimeResult`,
  `ExpectedMetricResult`, `V2RuntimeResult`.

## Error Handling & Edge Cases

- Build: three signatures handled deterministically; the LLM fixer is best-effort
  (any exception → `[]`); exhausting attempts → `BuildError` with the log tail.
- The generated `Dockerfile.plutus-verify` is unlinked in a `finally` so it
  doesn't persist across runs.
- Execution: timeout → `TIMEOUT`; non-zero exit → `FAILED`.
- SDK bundling: when any `expected` block declares metrics (so scripts
  `import plutus_verify`), a wheel-bundle failure is **fatal** rather than a
  buried note — the verifier refuses to build a degraded image.

## Performance Considerations

- `populate_staging` is O(repo size) per step. For the ~100-file strategy repos
  this targets it's well under a second/step; profiling for multi-GB repos is
  deferred (parking-lot item 3).
- Build caching is on by default (`Repo2DockerConfig.cache`).

## Future Considerations

- **Inputs-only mount** — bind-mount only declared inputs read-only (no copy).
  Requires `step.inputs` to be exhaustive; deferred. The developer-pain side of
  exhaustive inputs is gotcha G12.
- **"Files left in staging" warning** — undeclared writes are silently dropped;
  a per-path warning in the check report would close the loop (parking-lot item 2).
- **Legacy `run_plan`** (`execute.py`, the v1 path) still mounts cwd directly and
  is not leak-closed; only the v2 orchestrator path uses staging.
- **Slim builder is requirements.txt-only** — no environment.yml/pyproject branch
  in `build_with_fixers` (the v2 path's `env` drives its own generator).

## Features Covered

- [repo-verification](../feature/repo-verification.md) — the build/execute stages of the v1 pipeline.
- [authoring-tools](../feature/authoring-tools.md) — `plutus check` drives the v2 orchestrator + staging.

## Source Materials

- Reports: `docs/completion-report/2026-05-29-v0.2.10-runtime-mount-staging.md`,
  `docs/completion-report/2026-05-27-v0.2.7-byte-fallback-and-skill-split.md`
- Code: `plutus_verify/builder/{__init__,dockerfile,fixers,llm_fixer,runner}.py`,
  `plutus_verify/runner_docker.py`, `plutus_verify/spec/runtime/{staging,orchestrator}.py`,
  `plutus_verify/util/progress.py`
</content>

# Changelog

All notable changes to `plutus-verify` are recorded here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the
project is pre-1.0 and uses calendar-driven minor bumps.

## [0.2.10] — 2026-05-29

Closes the runtime-mount verification-correctness gap left open by
0.2.9. Each `plutus check` step now runs in an isolated staging copy
of the repo (filtered by `.dockerignore`), not against a live volume
mount of the maintainer's cwd. Host `.env` and stale `data/cache/`
files can no longer reach the container at runtime — the
manifest-declared posture is now actually authoritative.

### Changed — per-step staging dir replaces direct cwd mount

Before (0.2.9 and earlier):

```
docker run --rm -v {cwd}:/srv/repo plutus-v2:<tag> bash -lc "<cmd>"
```

The mount overlaid the host's full working tree onto the container
verbatim — `.dockerignore` (a build-context concept) didn't apply.

After (0.2.10):

```
1. populate_staging(cwd, staging, step) → copies cwd into a tempdir,
   respecting .dockerignore (and step.inputs, if declared)
2. docker run --rm -v {staging}:/srv/repo plutus-v2:<tag> bash -lc "<cmd>"
3. extract_outputs(staging, cwd, step) → copies back .plutus/run/<step>/
   (always) and any path matching step.outputs (if declared)
4. staging dir is removed
```

Inter-step state still flows via cwd: step N writes outputs back to
cwd; step N+1's staging dir picks them up at populate time. The mount
is no longer the shared-state mechanism; cwd is.

Implementation lives in
[`plutus_verify/spec/runtime/staging.py`](plutus_verify/spec/runtime/staging.py).
The orchestrator's `_run_step` is the wrap point; the `Runner`
contract stays duck-typed and manifest-unaware.

New runtime dep: `pathspec>=0.12` (gitignore-style matching).

### Implication for Tier 3 bridge steps

- Host `.env` is invisible to the container — `--secrets-from-env`
  routing is now actually authoritative.
- Host `data/cache/*.parquet` from prior runs no longer
  short-circuits the bridge step. `data_collection` either connects
  to the DB for real or fails with "missing credentials" — both are
  the correct outcome.

### Implication for authors

- Existing manifests with empty `step.inputs` continue to work
  unchanged — populate copies everything not in `.dockerignore`.
- Existing manifests with empty `step.outputs` get only
  `.plutus/run/<step>/` back. Scripts that wrote useful files
  elsewhere will lose them. Declare those paths in `step.outputs:`.
- Declaring `step.inputs:` opts into tighter filtering — only
  paths matching those patterns reach staging. Recommended for new
  manifests; optional for existing ones.

### Migration

Most repos: none. Re-run `plutus check` and observe whether bridge
steps still pass. If `data_collection` now fails where it used to
succeed, your prior runs were short-circuiting on host state — wire
real env vars or a real DB connection and re-run. If a downstream
step fails because a file it expects in cwd isn't there, declare the
file in the producing step's `step.outputs`.

### Non-goals

- **Inputs-only mount in the runner.** Per-step staging is a copy,
  not a mount restriction. The container still sees its entire
  staging filesystem; only what staging *contains* is restricted.
- **Validate that scripts only read declared inputs.** Out of scope
  for 0.2.10; would require ptrace or LSM hooks. Authors are trusted
  to declare honestly.
- **Per-step staging cache reuse.** Each step gets a fresh staging
  dir. Repos where staging is expensive (very large) may want a
  shared base + per-step diff; deferred until profiling shows real
  cost.

## [0.2.9] — 2026-05-28

Fixes a cache-leak / secret-leak class of issue surfaced by two real
incidents on a downstream Tier 3 repo (see
`docs/completion-report/` for the diagnosis). Without an explicit
`.dockerignore`, Docker's `COPY . .` pulled `.env`, `.git/`, and
prior-run caches into every image — masking verification gaps and
leaking secrets into image layers.

### Added — auto-emit `.dockerignore` baseline

The framework now writes a conservative `.dockerignore` to the repo
root as part of build-context preparation, **iff the repo doesn't
already have one** (user-authored `.dockerignore` always wins).

```
.git/
.gitignore
.env
.env.local
.env.*.local
.venv/
venv/
env/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.plutus/run/
.plutus/build/
!.plutus/build/plutus_verify-*.whl
.plutus/Dockerfile.generated
.DS_Store
.vscode/
.idea/
```

The `!.plutus/build/plutus_verify-*.whl` negate is load-bearing: the
generated Dockerfile COPYs the SDK wheel from `.plutus/build/`, so
excluding the parent dir without a re-include would cause every fresh
`plutus check` to fail at build time with `CopyIgnoredFile`. The
negate keeps build-cache junk out of the image while letting the
wheel through.

Implementation lives in
[`plutus_verify/spec/runtime/real_image_builder.py`](plutus_verify/spec/runtime/real_image_builder.py)
next to the existing `Dockerfile.generated` write. New public helper:
`ensure_dockerignore(repo_path)` returns `True` if a baseline was
written, `False` if an existing file was preserved.

### Why now — the two real incidents

1. **Cache leak.** A `data/cache/*.parquet` left over from a prior
   `plutus check` got `COPY . .`'d into the next image. The
   `data_collection` step short-circuited on cache before reaching
   the bridge-connection code → exit 0 without exercising the
   declared `network: bridge` posture.
2. **Secret leak.** With the cache wiped, the same step still passed
   without DB env vars actually being forwarded. The repo's gitignored
   `.env` was baked into the image and the container's
   `pydantic-settings` config read it directly from `/srv/repo/.env`,
   bypassing manifest secret routing entirely. This is also a real
   security regression — the DB password becomes recoverable from any
   image layer.

Both failures share the same root cause: gitignored ≠ Docker-ignored.

### Known limitation — runtime volume mount bypasses `.dockerignore`

`runner_docker.py` runs each step with `-v {cwd}:/srv/repo`. Docker
volume mounts are unfiltered by design — they overlay the host's
working directory verbatim, ignoring `.dockerignore` (which is a
build-context concept, not a runtime one).

Consequence: 0.2.9 closes the **image-layer** leak (a `docker pull`
consumer can no longer recover `.env` from image layers), but the
**runtime** leak remains. A Tier 3 bridge step can still:

- Read DB credentials from a host `.env` at runtime, bypassing
  manifest `--secrets-from-env` routing.
- Short-circuit on a host `data/cache/*.parquet` left over from a
  prior `plutus check` run.

If `data_collection` exits 0 suspiciously fast on the second run,
compare the cache file's mtime pre- and post-check:

    stat -f '%Sm' data/cache/<symbol>/1min/<month>.parquet

Unchanged mtime = bridge short-circuited via the volume mount.
Workaround until the mount is reworked: `rm -rf data/cache/` between
runs and verify `--secrets-from-env` routing is wired (no `.env`
readable on the host, real env vars exported in the shell).

Fixing the mount itself (per-step staging dir, inputs-only mount, or
no-mount + `docker cp`) is deferred to a future release — it's a
larger architectural change than 0.2.9's scope.

### Non-goals

- **Not tier-aware.** Tier 1 repos (committed CSVs) need
  `data/` *kept* in the build context; Tier 3 repos that fetch
  DB→disk want it excluded. The framework ships a safe universal
  baseline; the `plutus-transform` Skill appends per-tier exclusions
  in Phase 3.
- **No BuildKit `--ignore-file`.** Writing to `.dockerignore` at the
  conventional location keeps Docker semantics simple and avoids
  BuildKit-version coupling.
- **Runtime volume-mount rework.** See "Known limitation" above —
  out of scope for 0.2.9.

### Migration

No action required. Existing repos with a user-authored
`.dockerignore` are unaffected — the framework detects it and skips
the write. Repos without one get the baseline added on next
`plutus check`; commit it (or `.gitignore` it) as you see fit. Either
choice is supported.

## [0.2.8] — 2026-05-28

`pyproject.toml` is now a first-class dependency-spec option for the
generated Docker build. Previously the framework only knew how to do
`pip install -r <file>` (requirements.txt-style); a manifest pointing
`env.requirements_file` at `pyproject.toml` would crash at build time.

### Added — pyproject.toml support

- `env.requirements_file` may now be `pyproject.toml`. The Dockerfile
  generator detects this and emits `RUN pip install --no-cache-dir .`
  against the project directory (the PEP-518 invocation), rather than
  `pip install -r pyproject.toml` (which is invalid).
- `plutus bootstrap`'s file detection now prefers `pyproject.toml`
  over `requirements.txt` when both exist. Repos with only
  `requirements.txt` are unchanged.
- The `plutus-transform` Skill probes pyproject.toml first during
  Phase 1 and writes the detected filename into the manifest in Phase
  3. See [skills/plutus-transform/references/v0.2.8.md](skills/plutus-transform/references/v0.2.8.md).

### Schema (unchanged)

`env.requirements_file` was already typed `string | null` in the
manifest schema; no schema bump needed. The value range just gained
one more recognised filename. Existing manifests with
`requirements_file: requirements.txt` continue to build identically.

### Migration

No action required for existing repos. Repos that want to migrate
from `requirements.txt` to `pyproject.toml` simply replace the file
and update `.plutus/manifest.yaml`:

```yaml
env:
  base: python
  python_version: "3.11"
  requirements_file: pyproject.toml   # was: requirements.txt
```

The Docker build picks up `pip install .` automatically. The strict
`requirements.txt → pip install -r` path is preserved for backward
compatibility.

## [0.2.7] — 2026-05-27

Closes a 0.2.6 latent issue (the missing-snapshot strict gate was at
the dispatcher level, not the comparator level — and even after the
0.2.6 SKIP fix, `visual_similarity` with no LLM was a pure no-op).
This release adds a byte-comparison fallback when no vision client is
configured, plus a new WARN result state for inconclusive divergences.

### Behavior change — `visual_similarity` without an LLM

In 0.2.6, `compare: visual_similarity` with `vision_client=None`
returned a uniform SKIP, regardless of whether the produced and
expected files happened to match. 0.2.7 falls back to byte
comparison:

| Files | 0.2.6 result | 0.2.7 result |
|---|---|---|
| byte-identical | `SKIP visual_similarity [no vision client]` | `ok byte_identical [bytes match (no LLM check needed)]` |
| byte-different | `SKIP visual_similarity [no vision client]` | `WARN byte_identical [bytes differ; pass --visual-check for LLM judgment]` |

The `byte_identical` kind is **internal only** — never declarable in
the manifest schema (which still accepts only `json_numeric_tolerance`,
`visual_similarity`, `byte_exact`). It's a result-side label that
surfaces what the comparator actually did, so the user can tell at a
glance which path executed. Distinct from the user-declarable
`byte_exact` (which has strict exit-1-on-mismatch semantics for
deterministic outputs like CSVs).

Exit-code impact: byte-match raises a previously-silent SKIP to a
real `ok`; byte-mismatch promotes the SKIP to a visible `WARN` but
remains non-blocking (exit code unchanged at 0). Users who were
relying on "no LLM always SKIPs" will see `ok byte_identical` lines
appear in their reports — that's verification value, not a
regression.

### Added — `CompareResult` 4-state matrix

The `(ok, skipped)` field combination now distinguishes four outcomes:

| `ok` | `skipped` | meaning | marker | exit-code |
|---|---|---|---|---|
| `True` | `False` | verified pass | `ok` | 0 |
| `True` | `True` | not verified, no evidence of issue | `SKIP` | 0 |
| `False` | `True` | divergence detected but inconclusive (new) | `WARN` | 0 |
| `False` | `False` | verified divergence | `FAIL` | 1 |

`WARN` is the new state. It's emitted only by the byte-mismatch
fallback above. The exit-code logic in
[`scaffold/check.py`](plutus_verify/scaffold/check.py) was updated:
`skipped=True` is now non-blocking regardless of `ok`. Previously the
check was `if not r.ok: return 1`; now it's
`if not r.ok and not r.skipped: return 1`.

### Added — artifact rendering distinguishes WARN

The `plutus check` report's per-step lines now pick the marker based
on the full `(ok, skipped)` matrix:

```
ok   byte_identical    result/backtest/hpr.svg      [bytes match (no LLM check needed)]
WARN byte_identical    result/backtest/hpr.svg      [bytes differ; pass --visual-check for LLM judgment]
SKIP visual_similarity result/backtest/hpr.svg      [skipped (no reference at …; run `plutus snapshot`)]
FAIL visual_similarity result/backtest/hpr.svg      [score=0.42: divergent layout]
```

### Migration

No manifest, CLI, or SDK changes. No code updates required by
downstream users. The user-visible diff is purely in the rendered
report output, and exit codes only change in the direction of
"previously-silent reports now show useful detail" — not in the
direction of new failures.

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

---
feature: reproducible-env
date: 2026-06-18
version: 1.0
status: current
---

# Reproducible Environments (uv + lockfile)

## What It Does

Lets a repo declare an environment that `plutus check` restores **exactly**,
instead of one that pip re-resolves at build time. You commit a `pyproject.toml`
plus a `uv.lock`, point the manifest at them, and the verifier rebuilds the same
dependency graph the author had — closing the single biggest reproducibility hole:
"it passed because the verifier happened to resolve the same versions."

A repo that isn't reproducibly locked still runs, but the report flags it
`env: NOT reproducible` so the gap is visible.

## How It Works

`env.manager` selects how the verifier materializes the environment:

- **`uv`** (recommended) — the verifier installs a pinned uv, then runs
  `uv sync --frozen` against your committed lockfile. `--frozen` restores the exact
  locked graph and fails the build if the lock and `pyproject.toml` disagree.
- **`pip`** (default, deprecated) — dependencies are re-resolved at build time from
  `requirements_file`, so the restored env may drift from yours.

With `manager: uv`, `env.lockfile` is required. The verifier builds the locked env
into a venv outside the repo working dir and runs each step inside it; the SDK
(`plutus_verify`) is injected automatically, so it stays out of your dependencies.

## Configuration

Set these under `env` in `.plutus/manifest.yaml` (full env schema:
[v2-manifest](v2-manifest.md)):

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `manager` | `uv` \| `pip` | `pip` | `uv` restores a committed lockfile; `pip` re-resolves (deprecated). |
| `lockfile` | string \| null | `null` | Path to the committed lockfile (e.g. `uv.lock`). **Required when `manager: uv`.** |
| `requirements_file` | string \| null | `null` | pip path only; `requirements.txt` or `pyproject.toml`. |

## Usage Examples

### Basic (recommended)

```yaml
env:
  base: python
  python_version: "3.11"
  manager: uv
  lockfile: uv.lock
```

Generate the lock once and commit it alongside `pyproject.toml`:

```bash
uv lock
git add pyproject.toml uv.lock
plutus check . --secrets-from-env   # builds via `uv sync --frozen`
```

`plutus init` scaffolds this uv block by default.

### Deprecated pip fallback

```yaml
env:
  base: python
  python_version: "3.11"
  manager: pip
  requirements_file: requirements.txt
```

`plutus check` runs but prints `env: NOT reproducible` with a deprecation note.

## Limitations & Caveats

- **`pip` is the back-compat default and is deprecated.** A `pip`/lockfile-less env
  is reported `env: NOT reproducible`. This is **warn-only today** (exit code
  unchanged) and is slated to become a soft fail (exit 1) in a future release.
- **Requires `plutus-verify` 0.4.0+** for the uv path.
- **The verifier pins one blessed uv version** (so the lock format itself is
  reproducible); a repo locked with a wildly different uv may need a re-lock.
- **Exact versions ≠ bit-identical floats.** A locked graph removes version drift —
  the dominant source of mismatch — but platform/BLAS differences can still cause
  tiny numeric noise, which is what metric tolerances absorb.

## Related Features

- [v2-manifest](v2-manifest.md) — the full manifest/env schema and the results contract.
- [plutus-transform-skill](plutus-transform-skill.md) — its D5 decision ports an existing repo to the uv-locked env.

## Source Materials

- Captures: [reproducible-env-uv (complete)](../capture/reproducible-env-uv/2026-06-18-1618-complete.md)
- Design: [build-and-execute](../design/build-and-execute.md) — the uv build path and why the venv lives outside the staging mount.

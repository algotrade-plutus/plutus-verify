---
feature: repo-verification
date: 2026-06-01
version: 1.0
status: current
---

# Repo Verification (`plutus-verify <git_url>`)

## What It Does

`plutus-verify` is the command that takes a PLUTUS-standard algorithmic-trading
research repo and answers one question: **do the numbers it claims actually
reproduce when you run the code?**

Given a git URL (or local path), it clones the repo, figures out how to run it,
builds a Docker image, executes each step in isolation, compares every reported
metric and chart against the actual output, and emits a verdict —
`reproduced` / `partial` / `failed` — with a machine-readable `report.json` and
a reviewer-friendly `report.md`.

This page documents the **v1 path**: repos that do *not* ship a
`.plutus/manifest.yaml`. For those repos, the plan of what-to-run is *extracted
from the README* by a local LLM. Repos that ship a manifest take the faster,
deterministic v2 native path — see [v2-manifest](v2-manifest.md) and
[authoring-tools](authoring-tools.md) — but the CLI entrypoint and exit-code
contract documented here are shared by both.

## How It Works

A run flows through six ordered stages, each writing its output to disk under
`./out/<run_id>/`:

```
ingest  →  extract  →  build  →  execute  →  compare  →  report
 git       README→     repo→     Docker      numeric +    JSON +
 clone     plan.json   image     step runs   chart judge  Markdown
```

1. **Ingest** — `git clone --depth=1` (optionally at `--ref`), writing
   `meta.json` (url / sha / branch) and the working copy under `repo/`.
2. **Extract** — if `.plutus/manifest.yaml` is present the manifest *is* the
   plan (v2 native path); otherwise a local LLM reads `README.md` and produces a
   structured `plan.json`. See [extraction](../design/extraction.md).
3. **Build** — generates a `python:3.11-slim` Dockerfile and builds it, with an
   automatic fixer loop that repairs common dependency/encoding failures (and,
   if configured, an LLM fixer for harder cases).
4. **Execute** — runs each plan step in a container in dependency order,
   capturing stdout/stderr/exit-code/artifacts. Steps default to `network: none`;
   only the data-collection step gets `bridge`.
5. **Compare** — locates each claimed metric in the actual output and checks it
   against the declared tolerance; judges chart similarity with the LLM's vision
   capability (opt-in).
6. **Report** — aggregates per-step verdicts into an overall verdict + exit code
   and writes `report.json` + `report.md`.

Because every stage persists its artifact, you can hand-edit an intermediate
file (most often `plan.json` when the extractor guessed wrong) and re-run from
that stage with `--resume-from`.

## Configuration

### CLI

```bash
plutus-verify <git_url>
              [--ref <branch|sha>]
              [--secrets path/to/.env]
              [--config path/to/plutus-verify.yaml]
              [--out ./out]
              [--resume-from extract|build|execute|compare|report]
              [--prefer-data-path google_drive|db_loader|auto]
              [--llm-endpoint http://localhost:11434/v1]
              [--llm-model gemma4:26b]
              [--no-charts]            # skip vision chart judging
              [--dry-run]              # stop after extract (see caveat)
              [--extract-only]         # ingest + extract; write plan.json and stop
              [--skip-clone]           # treat SOURCE as a local path
              [--auto-fetch]           # download missing data; each fetch logged as a finding
              [--use-plan plan.json]   # load a plan instead of extracting
              [--skip-build IMAGE_TAG] # reuse a pre-built image
              [--batch repos.txt]      # one source per line
```

`plutus-verify <git_url>` is a backward-compatible shorthand for
`plutus verify <git_url>` — the `verify` subcommand is injected automatically
when the first argument isn't another known subcommand
(`init` / `check` / `snapshot` / `transfer` / `bootstrap`).

### Flag reference

| Flag | Default | Effect |
|------|---------|--------|
| `SOURCE` | — | git URL, or local path with `--skip-clone`. Omit only with `--batch`. |
| `--ref` | `None` | git branch or SHA to check out. |
| `--secrets` | `None` | `.env`-style file (`KEY=VALUE`); a step only receives the secrets its alternative declares in `needs_secrets`. |
| `--config` | `None` | YAML config overriding defaults. |
| `--out` | `./out` | Output root. If it already contains `meta.json`, it is treated as an existing run dir and the clone is reused. |
| `--resume-from` | `None` | Skip all stages before the named one (`extract`/`build`/`execute`/`compare`/`report`). |
| `--prefer-data-path` | `auto` | Which data-source alternative to prefer. |
| `--llm-endpoint` / `--llm-model` | config | Override the extraction LLM. |
| `--no-charts` | off | Disable vision chart judging (charts recorded as `skipped`). |
| `--extract-only` | off | Stop after extract; emit `plan.json`; exit 0. |
| `--dry-run` | off | **Caveat:** documented as "ingest+extract+build" but currently behaves like `--extract-only` (stops after extract). |
| `--skip-clone` | off | `SOURCE` is a local repo path. |
| `--auto-fetch` | off | Download data for steps with a `manual_download` alternative; each download surfaces as a `Finding`. |
| `--use-plan` | `None` | Load this `plan.json` instead of running extract. |
| `--skip-build` | `None` | Skip the build and reuse this Docker image tag. |
| `--batch` | `None` | File of sources (one per line; blank/`#` lines ignored); exit code is the worst across runs. |

### Config file (`plutus-verify.yaml`)

Maps key-for-key onto the internal config tree; unknown keys are silently
ignored. Common knobs:

```yaml
llm:
  endpoint: http://localhost:11434/v1   # Ollama native /api/chat under the hood
  model: gemma4:26b
  vision_model: gemma4:26b
tolerances:
  ratio_relative: 0.05
  percentage_absolute: 1.0
  overrides:
    sharpe_ratio: {kind: relative, value: 0.05}
    max_drawdown: {kind: absolute, value: 0.02}
charts:
  enabled: true
  match_threshold: 0.7        # a "match" below this confidence is downgraded to partial
execute:
  default_network: none
  data_step_network: bridge
  default_timeout_seconds: 1800
overrides:
  artifact_only_steps: []     # force these steps to artifact_check
```

## Usage Examples

### Basic

```bash
plutus-verify https://github.com/algotrade-plutus/ProtoMarketMaker \
              --secrets ./secrets/proto-mm.env \
              --llm-endpoint http://localhost:11434/v1
```

Outputs land under `./out/<run_id>/`:

| File | Written by | Contents |
|------|-----------|----------|
| `meta.json` | ingest | repo url / sha / branch |
| `repo/` | ingest | the cloned working copy |
| `plan.json` | extract | the structured plan (hand-edit + resume to override) |
| `build/attempt_*.log`, `build/attempt_*.fixers.json` | build | per-attempt build logs and applied fixes |
| `execute/<step_id>.stdout` / `.stderr` / `.meta.json` | execute | per-step captures |
| `report.json` | report | machine-readable result |
| `report.md` | report | reviewer summary |
| `run.log` | all | the verification trail |

### Fixing a bad extraction and resuming

```bash
plutus-verify ./MyStrategy --skip-clone --extract-only   # writes out/<id>/plan.json
$EDITOR out/<id>/plan.json                                # correct the wrong step
plutus-verify out/<id> --resume-from execute              # reuse clone + edited plan
```

### Batch auditing

```bash
plutus-verify --batch repos.txt --out ./out
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Every required step reproduced. |
| `1` | Required steps ran cleanly but ≥1 metric/chart was partial. |
| `2` | A required step failed, or the pipeline couldn't start. |

(Authoring subcommands `snapshot`/`bootstrap` additionally use exit `3` for
misuse — that is not part of the verdict scale.)

## Limitations & Caveats

- **`--dry-run` is mislabeled** — it stops after extract, identical to
  `--extract-only`, despite the help text mentioning build.
- **Charts off by default in practice** — with `--no-charts`, or when no vision
  endpoint is configured, charts are recorded as `skipped`, not failed. A
  produced chart with no reference image is also counted as a `match`
  (existence-only). A green chart verdict can mean "file exists, never compared."
- **Auto-fetch is Google-Drive-only** — `--auto-fetch` dispatches only to
  Google Drive folders/files; other hosts surface a data-missing error instead.
- **Only required steps gate the exit code** — a broken optional step (e.g.
  paper trading) appears in the report but does not change the verdict.
- **The v1 README-extraction path is legacy.** It remains the fallback for
  repos without a manifest, but new repos should ship `.plutus/manifest.yaml`
  for a deterministic, LLM-free run. See [v2-manifest](v2-manifest.md).

## Related Features

- [v2-manifest](v2-manifest.md) — the declarative manifest that bypasses LLM extraction.
- [authoring-tools](authoring-tools.md) — `plutus init` / `check` / `snapshot` / `bootstrap`.
- [legacy-migration](legacy-migration.md) — `plutus transfer` from README → manifest draft.

## Source Materials

- Plan: `docs/plan/2026-05-15-plutus-verify-design.md`
- Plan: `docs/plan/2026-05-21-plutus-spec-v2-native-execution.md`
- Code: `plutus_verify/__main__.py`, `plutus_verify/pipeline.py`, `plutus_verify/config.py`,
  `plutus_verify/ingest.py`, `plutus_verify/execute.py`, `plutus_verify/fetch.py`
</content>
</invoke>

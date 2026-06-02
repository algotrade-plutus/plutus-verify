---
feature: legacy-migration
date: 2026-06-01
version: 1.0
status: current
---

# Legacy Migration (`plutus transfer`)

## What It Does

`plutus transfer` is the on-ramp for a **legacy README-based repo** that has no
`.plutus/` directory and no script instrumentation yet. It runs the same local
LLM extractor the v1 pipeline uses over the repo's `README.md`, then reverse-maps
the extracted plan into a **v2 draft manifest** (`.plutus/manifest.yaml.draft`)
sprinkled with `# TODO(plutus-transfer):` markers, plus a companion
`instrument_TODO.md` listing the exact `pv.step(...)` snippets you must add to
each script.

It is explicitly **best-effort** — it gets you most of the way from prose to a
declarative manifest, but does not promise a lossless conversion. You finish the
TODO markers, instrument the scripts, rename the draft, and verify with
[`plutus check`](authoring-tools.md).

## How It Works

```bash
plutus transfer [REPO_PATH]
                [--llm-endpoint http://localhost:11434/v1]
                [--llm-model gemma4:26b]
                [--config plutus-verify.yaml]
                [--no-prewarm]
                [--force]
```

1. Reads `README.md` (errors if missing).
2. Refuses to run if `.plutus/manifest.yaml` already exists (won't clobber a real
   manifest), or if `instrument_TODO.md` exists and `--force` wasn't passed.
3. Runs the LLM extractor (decompose → stitch) to build an `ExtractedPlan`.
4. Reverse-adapts that plan into v2 YAML and writes:
   - `.plutus/manifest.yaml.draft` — the draft manifest with `# TODO(plutus-transfer):`
     comments wherever the README shape can't fully describe v2 (env os_packages,
     Dockerfile reconstruction, step inputs/outputs, data-source layout, and any
     low-confidence nine-step entry).
   - `.plutus/instrument_TODO.md` — for each step that declares metrics, a
     copy-paste `pv.step(...)` block to wire into that step's script.

The draft uses the modern manifest shape: metrics carry `display_name` + a flat
`value` (no locators), and charts become `artifacts` with
`compare: visual_similarity` and a `threshold` you tune.

## Usage Example

```bash
plutus transfer ./LegacyStrategy --llm-endpoint http://localhost:11434/v1

# 1. Resolve every "# TODO(plutus-transfer):" marker in the draft:
$EDITOR ./LegacyStrategy/.plutus/manifest.yaml.draft

# 2. Instrument each script per the companion doc:
$EDITOR ./LegacyStrategy/.plutus/instrument_TODO.md   # gives you the pv.step(...) blocks

# 3. Rename and verify:
mv ./LegacyStrategy/.plutus/manifest.yaml.draft ./LegacyStrategy/.plutus/manifest.yaml
cd ./LegacyStrategy && plutus check . --secrets-from-env
```

## How it differs from `bootstrap`

| | `transfer` | `bootstrap` |
|---|---|---|
| Starting point | legacy README, no instrumentation | scripts already emit `results.json` |
| Uses an LLM | yes (README extraction) | no (deterministic) |
| TODO style | inline `# TODO(plutus-transfer):` comments + `instrument_TODO.md` | `TODO_*` string sentinels + `manifest_TODO.md` |
| Best when | you're starting from prose | you've already run instrumented scripts |

## Limitations & Caveats

- **Best-effort, not lossless** — the README rarely contains everything v2 needs
  (system packages, exact input/output paths, data-source layout), so expect to
  fill TODO markers by hand.
- **Depends on the v1 LLM extractor** — needs a reachable local LLM endpoint and
  carries the same extraction quirks (see [extraction](../design/extraction.md)).
- **You still have to instrument the scripts** — the draft declares expected
  metrics, but the scripts won't emit `results.json` until you add the
  `pv.step(...)` blocks from `instrument_TODO.md`.
- **`manifest_TODO.md` references a worked-example path** under `out/` that is
  gitignored and won't exist in a downstream checkout — a dangling doc pointer.

## Related Features

- [v2-manifest](v2-manifest.md) — the manifest format the draft targets.
- [authoring-tools](authoring-tools.md) — `bootstrap` (the instrumented-repo on-ramp), `check`, `snapshot`.
- [plutus-transform-skill](plutus-transform-skill.md) — the guided, end-to-end transformation workflow.

## Source Materials

- Plan: `docs/plan/2026-05-21-plutus-spec-v2-legacy-transfer.md`
- Code: `plutus_verify/scaffold/transfer.py`, `plutus_verify/scaffold/extract_to_v2.py`,
  `plutus_verify/extract/` (the shared LLM extractor)
</content>

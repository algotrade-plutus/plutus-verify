---
feature: authoring-tools
date: 2026-06-01
version: 1.0
status: current
---

# Authoring Tools (`plutus init` / `check` / `snapshot` / `bootstrap`)

## What It Does

These four `plutus` subcommands are the author-facing toolkit for making a repo
v2-verifiable and keeping it that way. They sit around the
[v2 manifest](v2-manifest.md):

- **`init`** — scaffold an empty `.plutus/` skeleton + CI workflow + example script.
- **`bootstrap`** — generate a draft manifest *from* an already-instrumented run.
- **`snapshot`** — capture a passing run's outputs/metrics as the new "expected."
- **`check`** — run the v2 native pipeline locally and return the verdict as the exit code.

(The fifth on-ramp, `plutus transfer`, converts a legacy README repo and has its
own page: [legacy-migration](legacy-migration.md).)

There are two distinct ways to reach a manifest: **`transfer`** for a legacy
README repo not yet instrumented, and **`bootstrap`** for a repo you've already
instrumented with `pv.step(...)`. Both emit a `.plutus/manifest.yaml.draft` plus
a companion TODO document; you hand-finish it, rename it to `manifest.yaml`, and
verify with `check`. The `.draft` extension is itself the gate — `check` ignores
`.draft` files, so renaming is a conscious "I reviewed this" step.

## How It Works

### `plutus init`

```bash
plutus init [REPO_PATH] [--force]
```

Scaffolds, creating dirs as needed and never overwriting without `--force`:

- `.plutus/manifest.yaml` (skeleton with inline `TODO_*` markers)
- `.plutus/example_script.py` (documents `pv.step` / `r.metric` / `r.artifact` / units)
- `.plutus/expected/` (for reference artifacts)
- `.github/workflows/plutus.yml` (CI workflow)

### `plutus check`

```bash
plutus check [REPO_PATH]
             [--secrets-from-env]
             [--data-tier processed|raw|code|auto]
             [--visual-check]
```

Runs the full native v2 pipeline against your working copy: builds the Docker
image, runs each step in a container, reads back each step's
`results.json`, and compares against the manifest's `expected` block. The exit
code is the verdict.

- `--secrets-from-env` — pass the host environment into steps as secrets.
- `--data-tier` — force a data tier instead of `auto`-resolving.
- `--visual-check` — enable `visual_similarity` artifact comparison. Requires
  `PLUTUS_VISION_ENDPOINT` + `PLUTUS_VISION_MODEL` env vars (optional
  `PLUTUS_VISION_API_KEY`); missing → exit 2. Without it, `visual_similarity`
  entries are skipped.

**Integrity guarantee:** `check` wipes `.plutus/run/` *before* running, so the
comparison only ever reads what *this* run produced — a stale `results.json` from
an earlier host run can't masquerade as a pass. See
[secret-and-leak-hardening](../design/secret-and-leak-hardening.md).

The report groups manifest steps under the nine-step framework, shows per-step
`ok`/`FAIL`, per-metric `actual=…/expected=…`, and an artifact 4-state matrix:

| state | meaning |
|-------|---------|
| `ok` | verified pass |
| `SKIP` | not verified, no evidence of a problem (e.g. visual check disabled) |
| `WARN` | divergence detected but inconclusive |
| `FAIL` | verified divergence |

Exit codes: **0** all good · **1** a metric/artifact diverged (soft fail) ·
**2** a required step hard-failed or the manifest/build errored.

### `plutus snapshot`

```bash
plutus snapshot [REPO_PATH] [--no-run] [--no-artifacts] [--no-metrics]
```

Captures a passing run as the new expected: copies each step's declared
`outputs` into `.plutus/expected/<step_id>/`, and writes
`expected.metrics[].value` in the manifest from the step's `results.json`. You
review the `git diff` and commit — **the commit is the verification claim.**

- Only updates values for metrics **already declared** in the manifest (no
  auto-creation); tolerances are never touched; values are written verbatim.
- `--no-run` is currently **required** from the CLI (running check-first isn't
  wired yet); `--no-artifacts` / `--no-metrics` scope what gets captured.
- Manifest edits preserve comments, key order, and formatting (round-trip YAML),
  so the diff shows only value changes.

### `plutus bootstrap`

```bash
plutus bootstrap [REPO_PATH] [--force]
```

Run **after** you've instrumented scripts with `pv.step(...)` and produced
`.plutus/run/<step_id>/results.json` from a local run. Deterministically (no LLM,
no README parsing) auto-fills ~70% of the manifest and leaves greppable
`TODO_*` sentinels on the rest.

- *Derived from results.json + filesystem:* `repo.name`, expected `step_id`s,
  metric names/values, `display_name`, per-step `outputs`, artifact `compare`
  strategy (chart/image → `visual_similarity`, json → `json_numeric_tolerance`,
  else `byte_exact`), python version (`.python-version` → pyproject → `"3.11"`),
  requirements file.
- *Left as TODO:* `secrets`, `data_sources`, per-step `command`, `nine_step`,
  `inputs`, `depends_on`, `nine_step_coverage`, and a prompt to add non-`pv.step`
  steps (data collection, optimization).

Writes `.plutus/manifest.yaml.draft` + `.plutus/manifest_TODO.md`. The sentinels
are designed to fail schema validation if left unresolved, so `check` against an
unfinished draft fails loudly.

## Usage Examples

### From scratch

```bash
plutus init
$EDITOR .plutus/manifest.yaml      # resolve TODO_* markers; instrument scripts with pv.step
plutus check . --secrets-from-env
```

### From an instrumented repo

```bash
# scripts already wrapped with `with pv.step(...) as r: r.metric(...)`
python -m my_strategy.backtest     # produces .plutus/run/in_sample/results.json
plutus bootstrap
$EDITOR .plutus/manifest.yaml.draft # resolve TODO_*; grep TODO_ to find them
mv .plutus/manifest.yaml.draft .plutus/manifest.yaml
plutus check . --secrets-from-env
```

### Locking in expected values

```bash
plutus check . --secrets-from-env  # confirm it passes
plutus snapshot --no-run           # write metric values + copy artifacts
git diff .plutus/                  # review, then commit — the commit is the claim
```

## Limitations & Caveats

- **`snapshot --no-run` is effectively mandatory** from the CLI; the
  run-check-first path exists in the API but isn't reachable from the command.
- **`bootstrap` is one-shot** — there's no `--refine` to update an existing
  draft; it refuses to overwrite a real `manifest.yaml`.
- **`bootstrap` silently skips malformed `results.json`** — a step with an
  unreadable results file yields empty outputs / a skipped expected block with no
  note.
- **`check` requires Docker** and a working build; manifest or build errors exit 2.
- **Snapshot can "relock" expectations** — if a script's numbers drift from the
  README's claimed values, snapshotting overwrites the expected values to match
  the script. That's correct behavior, but watch the diff.

## Related Features

- [v2-manifest](v2-manifest.md) — the manifest these tools produce and verify.
- [legacy-migration](legacy-migration.md) — `plutus transfer` for README repos.
- [plutus-standardize-skill](plutus-standardize-skill.md) — the Claude skill that drives this whole workflow.

## Source Materials

- Plans: `docs/plan/2026-05-22-plutus-bootstrap.md`,
  `docs/plan/2026-05-22-plutus-snapshot-metrics.md`,
  `docs/plan/2026-05-25-plutus-verifier-integrity.md`
- Code: `plutus_verify/scaffold/{init,check,check_report,snapshot,bootstrap,manifest_edit,manifest_template_todo,templates}.py`,
  `plutus_verify/__main__.py`
</content>

# Adopting the plutus-verify workflow

A short, practical guide to making your trading-research repo reproducible with
`plutus snapshot` / `plutus check` (0.4.4+). For the why behind it, see the
"Snapshot & check" section of [README.md](README.md); for the full reference, see
[docs/feature/v2-manifest.md](docs/feature/v2-manifest.md).

## The model in one minute

`plutus` has two verbs that share the *same* in-container pipeline and differ only
in the final move:

- **`snapshot` = bless.** Run every step in the container, then *write* the
  groundtruth you commit.
- **`check` = verify.** Run the same pipeline, then *compare* against that
  groundtruth. Read-only — it never edits your committed files.

Three stores keep those roles clean:

| Store | What it is | Who writes it | Commit? |
|---|---|---|---|
| `.plutus/expected/<step>/…` + `manifest.yaml` `value`s | frozen groundtruth (the database) | `snapshot` only | **yes** |
| `result/…` (your declared output paths) | human-facing copy for the README | `snapshot` only | **yes** |
| `.plutus/results/<step>/…` | per-run scratch + inter-step data bus | `snapshot` **and** `check` | **no — gitignore** |

The rule that makes it work: **the groundtruth is written only by `snapshot`.** A
plain `check` (or a normal local run) never touches it, so a forgotten bless is
caught (missing groundtruth → fail) and undeclared drift fails on purpose.

## Transforming an existing repo

### 1. Install the tool and ignore the scratch buffer

```bash
pip install -e "/path/to/plutus-verify[runner]"   # or: uv pip install <release-wheel>
cd your-strategy-repo
printf '.plutus/run/\n.plutus/results/\n.plutus/cache/\n' >> .gitignore
```

Three `.plutus/` subdirs are ephemeral and **must** be gitignored:
- `.plutus/results/` — per-run produced outputs (every `check` writes here).
- `.plutus/cache/` — fetched data sources (downloads land here, not your tree).
- `.plutus/run/` — per-step bookkeeping + captured `stdout`/`stderr`.

Committing any of them would put working-tree churn back (the exact thing the
read-only design removed). The framework already keeps them out of the Docker
image; the `.gitignore` line is yours to add. (`plutus init` writes a
`.dockerignore` for you — commit it.)

### 2. Scaffold the manifest (if you don't have one)

```bash
plutus init .          # writes .plutus/manifest.yaml + an example script
```

Fill in `env` (pin with **uv + a committed lockfile** to unlock `byte_exact`
baselines), `data_sources`, and one `steps[]` entry per pipeline stage.

**Installable-package repo?** If your repo is a real package whose pipeline runs
via a console script (`pmm-backtest`) or `python -m your_package.…`, set
`env.install_project: true` (uv-only; needs a `pyproject.toml` at the root). The
image then installs your package, so those entry points exist for step commands.
Without it, only your dependencies are installed and `import your_package` / the
console scripts will fail.

### 3. Instrument each step's script

Emit metrics through the SDK — the verifier reads them **by name**, never from
stdout:

```python
import plutus_verify as pv

with pv.step("in_sample") as r:
    r.metric("sharpe_ratio", float(sharpe), unit="ratio")   # canonical decimal units
    r.artifact("equity_curve", "result/equity.svg", kind="chart")
```

Write your output files to their declared paths (e.g. `result/…`) as usual — that's
what `snapshot` harvests and blesses.

### 4. Declare what gets verified

In `manifest.yaml`, list each step's `expected` metrics and artifacts. Leave metric
`value`s as placeholders; `snapshot` fills them. Pick an artifact compare mode:

```yaml
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        value: 0.0                       # snapshot overwrites this
        tolerance: {kind: relative, value: 0.05}
    artifacts:
      - path: result/trades.csv
        compare: byte_exact              # exact bytes (deterministic CSV, charts under a pinned env)
      - path: result/summary.json
        compare: json_numeric_tolerance  # numbers within tolerance; strings exact
      - path: result/equity.svg
        compare: visual_similarity       # LLM/vision compare; threshold optional
        threshold: 0.9
```

Inter-step data: if step B reads step A's output, declare it in B's `inputs:` —
the bus injects A's produced output into B's sandbox (so it works even before the
intermediate is committed).

### 5. Bless, then commit the groundtruth

```bash
plutus snapshot .
git add .plutus/expected manifest.yaml result   # the three committed stores
git commit -m "bless reproducibility baseline"
```

`snapshot` builds the image, runs every step in the container, and writes the
groundtruth from the *container's* output — so charts, `*.parquet`, `model.pkl`
etc. get baselines that actually match what `check` will reproduce.

### 6. Verify — locally and in CI

```bash
plutus check .        # exit 0 reproduced · 1 partial · 2 failed; working tree stays clean
```

Because `check` is read-only, it's safe in CI / pre-commit.

## Day-to-day

- **Output changed on purpose?** Re-run `plutus snapshot .` and commit the updated
  `.plutus/expected/` + `manifest.yaml` + `result/`. That's the explicit "I bless
  this new baseline" act.
- **`check` fails after a code change you didn't intend to change output?** That's
  the feature working — investigate the diff (`git diff` shows nothing in the tree;
  inspect `.plutus/results/<step>/` vs `.plutus/expected/<step>/`).
- **A step crashed?** The report prints a tail of its stderr, and the full
  `stdout`/`stderr` are saved at `.plutus/run/<step>/` — no need to re-run the
  container by hand.
- **Upgrading from pre-0.4.4:** your old baselines were captured from the laptop.
  Re-`snapshot` once in-container to refresh them — you can now promote fragile
  `visual_similarity` charts to `byte_exact`, and stop committing churny rendered
  outputs.

## Gotchas

- **A step must actually *produce* its declared outputs during the run.** A step
  that exits 0 but writes nothing now fails with `missing output(s)` — outputs are
  checked in `.plutus/results/`, not your (possibly stale) working tree.
- **Pin the environment.** `byte_exact` only holds under a reproducible build; use
  `env.manager: uv` + a committed lockfile. Without it, prefer `json_numeric_tolerance`
  / `visual_similarity`.
- **Secrets during `snapshot`.** The in-container `snapshot` path currently runs
  with no secrets injected. If a step needs a secret to produce its baseline, bless
  it via `plutus snapshot . --no-run` after a local run that had the secret, or run
  `plutus check . --secrets-from-env` first and snapshot from there. (First-class
  secret flags on `snapshot` are a planned follow-up.)
- **Don't hand-edit `.plutus/expected/`.** It's snapshot-managed plumbing; editing
  it defeats the "blessed only by snapshot" invariant.

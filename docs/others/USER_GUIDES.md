# User Guide — bringing a new Plutus repo under `plutus-verify`

This is the **repo-agnostic** version of the ProtoMarketMaker handoff. Use
it when you (or another agent) clone a fresh PLUTUS-standard
algorithmic-trading research repo somewhere on disk and want to make it
verifiable by `plutus check`.

For a fully-worked end-to-end example with concrete answers and edge
cases, see [`protomarketmaker-upgrade.md`](protomarketmaker-upgrade.md) —
read that side-by-side with this guide on your first time through.

---

## 0. What you're producing

By the end of this guide the target repo will have:

```
target-repo/
├── .plutus/
│   └── manifest.yaml            # author-written reproducibility contract
├── .github/workflows/plutus.yml # CI gate (optional but recommended)
├── .gitignore                   # +5 lines for plutus-verify ephemera
└── <scripts>.py                 # instrumented with `with pv.step(...) as r:` blocks
```

Running `plutus check .` against that repo will:

1. Build a Docker image from `env` in the manifest
2. Run each step in the container
3. Read `.plutus/run/<step_id>/results.json` (written by the SDK)
4. Compare every metric against `expected.metrics[]` within tolerance
5. Exit 0 if all match, 1 if any drift, 2 on infrastructure failure

---

## 1. Prerequisites

On the host where you'll do the integration work:

- **Python ≥ 3.11**
- **Docker daemon running** — `docker info` must succeed without sudo
- **`plutus-verify` wheel** built from this repo (see §2)
- The target repo's **own data accessible** — either via its own data loader
  (DB creds in env), a downloadable source (Google Drive / HTTP / GitHub
  release), or files manually placed in the expected layout

---

## 2. Install `plutus-verify` from a wheel (not editable)

**Build the wheel** in the plutus-verify source tree:

```bash
cd /Users/dan/algotrade-research/plutus-automation-scoring
source .venv/bin/activate
bash scripts/release-build.sh
# → produces dist/plutus_verify-0.2.0-py3-none-any.whl
```

The script is two-pass: the resulting wheel contains a copy of itself
inside `plutus_verify/_bundled/`. At `plutus check` time, the verifier
stages that inner wheel into the Docker build context and `pip install`s
it into the image — so authors never need to add `plutus-verify` to their
repo's `requirements.txt`.

**Install into the target repo's venv:**

```bash
cd <target-repo>
python3.11 -m venv .venv             # or whatever venv discipline the repo uses
source .venv/bin/activate
pip install -r requirements.txt      # the repo's own deps

pip install /Users/dan/algotrade-research/plutus-automation-scoring/dist/plutus_verify-0.2.0-py3-none-any.whl \
    --force-reinstall
```

**Sanity-check:**

```bash
python -c "import plutus_verify; print(plutus_verify.__version__)"
# → 0.2.0
plutus --help
# → must list: bootstrap, check, init, snapshot, transfer, verify
```

> **Do not use `pip install -e`.** Editable installs have produced false-positive
> "ok" lines in the past because the SDK auto-injection silently failed inside
> Docker. The wheel install eliminates that class of failure. See the Plan 10
> completion report ([phase-d-integrity-hardening.md](../completion-report/2026-05-25-phase-d-integrity-hardening.md))
> for the incident write-up.

---

## 3. Survey the target repo

Before instrumenting anything, build a mental model of the repo's
reproducibility surface. Open `README.md` and answer:

| Question | Where the answer typically lives |
|---|---|
| What are the **distinct stages** of the pipeline? (data → process → in-sample → optimize → OOS → paper) | README's "How to run" or "Reproduce results" section, plus the top-level script files |
| What **command** runs each stage? | README code blocks (`python backtesting.py`, `python evaluation.py`, etc.) |
| What **metrics** does the README claim? (Sharpe, Sortino, MDD, HPR, ...) | README results tables |
| Where does **data** come from? | README data section — DB, Google Drive folder, HTTP download, manual instructions |
| What **secrets** does the data step need? | `data_loader.py` or equivalent — grep for `os.environ`, `os.getenv` |
| What **artifact files** does each stage produce? (charts, JSONs) | `result/`, `parameter/`, etc. — look at what gets `git add`ed |
| Which stages are **deterministic enough** to re-run vs. need an `artifact_check` skip? | Anything stochastic with no fixed seed (e.g. optuna optimization) → `artifact_check` |

Map each stage to one of the **seven PLUTUS nine-step keys**:

```
step_1_hypothesis         (descriptive, never executable)
step_2_data_preparation
step_3_forming_set_of_rules
step_4_in_sample
step_5_optimization
step_6_out_of_sample
step_7_paper_trading      (rarely executable in a verification context)
```

A repo with no live-trading component will typically have:
`data_preparation` + `in_sample_backtest` + (`optimization` as artifact_check)
+ `out_of_sample_backtest`. Four steps total.

---

## 4. Instrument the scripts with the SDK

For **every script that should produce reportable metrics**, add:

```python
import plutus_verify as pv
```

Then wrap the metric-emitting tail of `if __name__ == "__main__":` in a
`pv.step(...)` context manager. Pattern:

```python
if __name__ == "__main__":
    # ... existing logic that computes the metrics ...

    # Bind metric values to plain Python floats (the SDK rejects Decimal).
    sharpe  = float(bt.metric.sharpe_ratio(...))
    sortino = float(bt.metric.sortino_ratio(...))
    mdd     = float(bt.metric.maximum_drawdown()[0])
    # ... etc

    # Existing prints can stay — they're useful in logs.
    print(f"Sharpe ratio: {sharpe}")
    # ...

    with pv.step("<step_id>") as r:
        r.metric("sharpe_ratio",     sharpe,  unit="ratio")
        r.metric("sortino_ratio",    sortino, unit="ratio")
        r.metric("maximum_drawdown", mdd,     unit="fraction")
        # ... one r.metric() per claim in the README ...

        r.artifact("equity_curve",   "result/.../hpr.svg",      kind="chart")
        r.artifact("drawdown_chart", "result/.../drawdown.svg", kind="chart")

        r.metadata(seed=2025)   # any fixed seeds the script uses
```

Rules:

- **`step_id` must be a stable snake_case identifier** — it's the join key
  between scripts and the manifest. Once chosen, don't rename.
- **Metric names must be snake_case** and match exactly what you'll
  declare in `expected.metrics[].name`.
- **`r.metric()` only accepts `int | float`.** If your value is a
  `Decimal`, cast with `float(...)`. The error message is loud and
  immediate if you forget.
- **One `pv.step` per executable step.** If one script produces metrics
  for multiple steps, split it or emit multiple `pv.step` blocks
  (uncommon).
- **`unit=` is one of: `"fraction"`, `"ratio"`, `"count"`, `"currency_usd"`,
  `"seconds"`.** Use `"fraction"` for percent-like metrics (write 42% as `0.42`)
  and `"ratio"` for unbounded dimensionless numbers like Sharpe. `"percent"` is
  rejected — always store decimals. See
  [`plutus_verify/sdk/schema.py`](../../plutus_verify/sdk/schema.py) for the full enum.
- **`r.artifact(name, path, kind=...)`** — paths are relative to the repo
  root; `kind` is `"chart"`, `"data"`, or `"model"`.

---

## 5. Run the scripts locally to produce `results.json`

Before bootstrap can auto-fill the manifest draft, it needs each step's
`results.json` on disk.

```bash
# Pre-flight: data in place (run the repo's data loader, or place files manually)
python <data_loader>.py            # or download/copy the data files into the layout the scripts expect

# Run each instrumented script
python <in_sample_script>.py
python <oos_script>.py
# ... etc.

# Confirm output landed
ls .plutus/run/*/results.json
# should list one file per step_id you wrapped
```

If a script crashes with `ValueError: metric '<name>' value must be a
finite number, got Decimal(...)`, you missed a `float(...)` cast. Fix and
re-run.

If a script crashes before reaching the `pv.step` block, fix the upstream
bug — bootstrap can't generate the draft without the JSON.

---

## 6. `plutus bootstrap`

```bash
plutus bootstrap .
```

Expected output:

```
draft:    .plutus/manifest.yaml.draft  (N steps, M metrics)
guidance: .plutus/manifest_TODO.md

Next: fill in TODO_* markers in the draft (see manifest_TODO.md),
      rename .draft → .yaml, then run `plutus check`.
```

**What got auto-filled (~70%):**

- `schema_version: "2.0"`, `repo.name` (from cwd)
- `env.python_version` (from `.python-version` or `pyproject.toml`)
- `env.requirements_file` (detected on disk)
- `steps[].id` for every directory under `.plutus/run/`, with defaults
  `network: none`, `timeout_seconds: 1800`, `outputs:` from the artifacts
  the SDK recorded
- `expected.metrics[]` — one entry per metric, with `name`,
  `display_name` (snake_case → Title Case), current `value`, and a default
  `tolerance: {kind: relative, value: 0.05}`
- `expected.artifacts[]` — `compare: visual_similarity` for chart
  artifacts

**What's left for you (~30%, all marked with `TODO_*` sentinels you can grep):**

```bash
grep TODO_ .plutus/manifest.yaml.draft
```

Open `.plutus/manifest_TODO.md` alongside the draft and walk it section
by section. The guidance doc has worked examples for each TODO type; the
remaining sections of this guide cover the *categories* of decisions
you'll have to make.

---

## 7. Fill in the TODOs

### 7.1 `env.os_packages`

Apt packages the Docker image needs **before** `pip install -r requirements.txt`
runs. Required for any Python dep with a native build (e.g. `psycopg2` →
`libpq-dev`, `cffi` → `libffi-dev`).

If everything in `requirements.txt` is pure-Python or has manylinux
wheels: omit the key (or `os_packages: []`).

### 7.2 `secrets[]`

Per-key declaration of env vars the steps read. Grep the scripts for
`os.environ` / `os.getenv` to find every key. Each entry:

```yaml
secrets:
  - key: DB_PASSWORD
    purpose: <one-line human description>
    used_by: [<step_id>, ...]
```

`plutus check` reads these from your host environment (or a `.env` file
via `--secrets-from-env`). They're never embedded in the image.

### 7.3 `data_sources[]`

Three tiers, in priority order:

| Tier | Field | What it means |
|---|---|---|
| 1 | `processed` | The repo ships processed data files committed to the repo — `plutus check` uses them as-is. |
| 2 | `raw` | The repo's data lives at an external URL (`google_drive`, `github_release`, `http`); `plutus check` downloads it before the data step runs. |
| 3 | (none) | The repo's `data_preparation` step is run inside the container to produce the data fresh (needs secrets). |

The verifier picks the highest tier whose layout the data step's
`outputs:` matches. Most academic repos use Tier 2 (Google Drive folder
of CSVs) with Tier 3 (DB-backed loader) as a fallback.

```yaml
data_sources:
  raw:
    - kind: google_drive
      url: https://drive.google.com/drive/folders/<id>
      expected_layout:
        - data/is/<file>.csv
        - data/os/<file>.csv
      satisfies: [data_preparation]
```

### 7.4 `steps[]` — the four-step canonical shape

Bootstrap only auto-detects steps that emitted a `results.json` (i.e.
ones you wrapped with `pv.step`). You'll typically need to **add by hand**
the steps that DON'T emit metrics — `data_preparation` and `optimization`
(when in `artifact_check` mode).

```yaml
steps:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    network: bridge        # needs internet
    timeout_seconds: 1800
    command: "python data_loader.py"
    inputs: []
    outputs:
      - data/is/<file>.csv  # what the data step produces
      # ...

  - id: optimization
    nine_step: step_5_optimization
    required: true
    network: none
    timeout_seconds: 1800
    verification_mode: artifact_check
    inputs:  [parameter/optimization_parameter.json]
    outputs: [parameter/optimized_parameter.json]
    depends_on: [data_preparation]

  # Then the auto-detected entries — fill the TODO_* fields:
  - id: in_sample_backtest      # (auto-detected from .plutus/run/)
    nine_step: step_4_in_sample
    command: "python backtesting.py"
    network: none
    inputs:
      - data/is/<file>.csv
      - parameter/backtesting_parameter.json
    depends_on: [data_preparation]
    # ... outputs (already filled by bootstrap)

  - id: out_of_sample_backtest
    nine_step: step_6_out_of_sample
    command: "python evaluation.py"
    network: none
    inputs:
      - data/os/<file>.csv
      - parameter/optimized_parameter.json
    depends_on: [optimization]
    # ... outputs (already filled)
```

Key decisions:

- **`verification_mode: artifact_check`** for steps that aren't worth
  re-running (typically optimization runs that are stochastic without a
  fixed seed). The verifier just confirms the shipped artifact file
  exists.
- **`network`**: `none` by default. `bridge` only for steps that genuinely
  need internet (data download, external API).
- **`depends_on`**: the `step_id`s that must run before this one. Forms
  the DAG the executor topologically sorts.

### 7.5 `nine_step_coverage`

Self-reported documentation: which of the seven PLUTUS steps does the
README describe in prose?

```yaml
nine_step_coverage:
  step_1_hypothesis:       {present: true,  section: "Hypothesis"}
  step_2_data_preparation:  {present: true,  section: "Data Preparation"}
  step_3_forming_set_of_rules:  {present: false, section: null}
  step_4_in_sample:        {present: true,  section: "In-sample Backtesting"}
  step_5_optimization:     {present: true,  section: "Optimization"}
  step_6_out_of_sample:    {present: true,  section: "Out-of-sample Backtesting"}
  step_7_paper_trading:    {present: false, section: null}
```

This drives the 9-step coverage table in the report. It does not gate
verification.

### 7.6 `expected.metrics[].value` — README vs. script values

Bootstrap pre-filled every `value:` with **what your script actually
produced** in §5. If your README claims *different* numbers, you have a
choice:

- **(A) Use the README-claimed values** — manually edit each
  `expected.metrics[].value` to match the README. When `plutus check`
  runs, any drift between the script's output and the README claim is
  surfaced as a `FAIL`. This is the conservative path — the verifier
  does its job of flagging reproducibility regressions.

- **(B) Use the script's actual values** — leave the bootstrap defaults
  alone. `plutus check` will PASS. You're declaring "the script's current
  output is the reproducibility target", accepting that the README's
  numbers are stale and the script is authoritative.

There's no wrong answer — it's a maintainer call. Surface this to the
human before deciding.

### 7.7 Confirm no TODOs are left

```bash
grep TODO_ .plutus/manifest.yaml.draft
# (no output)
```

If anything is left, fix it. If you're stuck, the ProtoMarketMaker
worked example at
[`protomarketmaker-upgrade.md`](protomarketmaker-upgrade.md) §6 has a
fully resolved answer for every TODO category.

---

## 8. Finalize the manifest

```bash
mv .plutus/manifest.yaml.draft .plutus/manifest.yaml
```

Validate it parses cleanly before running `check`:

```bash
plutus check . 2>&1 | head -5
# If it errors with "manifest validation failed", read the error and fix.
# If it starts "building image from .plutus/Dockerfile.generated...", you're good.
# (Ctrl-C is fine if you don't want to wait for the full run yet.)
```

---

## 9. `.gitignore`

Append:

```
# plutus-verify ephemera
.plutus/run/
.plutus/build/
.plutus/Dockerfile.generated
.plutus/manifest.yaml.draft
.plutus/manifest_TODO.md
```

**Track**: `.plutus/manifest.yaml` (the contract) and `.plutus/expected/`
(if you committed reference outputs via `plutus snapshot`).

**Ignore**: everything generated per-run.

---

## 10. End-to-end verification

```bash
plutus check . 2>&1 | tee /tmp/plutus-check.log
```

Wall-clock estimate: a few minutes (Docker build) + per-step runtime.
The verifier will:

1. Stage the bundled `plutus_verify` wheel into `.plutus/build/`
2. Generate `.plutus/Dockerfile.generated` from `env`
3. Seed `<repo>/.dockerignore` from a conservative baseline **iff one
   doesn't already exist** (added in 0.2.9 — closes a class of cache /
   secret leaks via `COPY . .`). User-authored `.dockerignore` is
   preserved unchanged; commit or edit yours to customize.
4. `docker build` an image (tagged by content hash; cached across runs)
5. Resolve data sources (download Tier 2 if needed)
6. Run each step in dependency order inside the container. Each step
   runs in a per-step staging copy of the repo (a tempdir populated
   from cwd through the `.dockerignore` filter, plus `step.inputs` if
   declared). Step outputs flow back to cwd via `step.outputs`. The
   container never mounts cwd directly — that's 0.2.10's closure of
   the runtime-mount leak.
7. Read each step's `results.json`
8. Compare every metric against `expected.metrics` within tolerance
9. Render a grouped 9-step report and exit with the appropriate code

**Read the output carefully.** A clean pass looks like:

```
  ok data_preparation: exit=0 (skipped: satisfied_by_data_source)
  ok in_sample_backtest: exit=0
  ok optimization: exit=0 (skipped: artifact_check ...)
  ok out_of_sample_backtest: exit=0
  ok in_sample_backtest.sharpe_ratio: actual=0.95... expected=0.9516
  ...
```

A failing run (path A — README-claimed values diverge from script):

```
  ok in_sample_backtest: exit=0
  ok out_of_sample_backtest: exit=0
  FAIL out_of_sample_backtest.sharpe_ratio: actual=0.0815... expected=0.1105
  ...
```

**Heads up**: if you see step FAIL lines but every metric is `ok`, that's
the false-positive class Plan 10 was built to prevent — check the recent
behavior is sound (the loud `SdkBundleError` should fire instead). If
something looks fishy, post the full log + read
[phase-d-integrity-hardening.md](../completion-report/2026-05-25-phase-d-integrity-hardening.md).

---

## 11. CI gate (recommended)

Create `.github/workflows/plutus.yml`:

```yaml
name: plutus reproducibility
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      # Until plutus-verify is on PyPI, install from a known wheel URL or git ref.
      - name: Install plutus-verify
        run: pip install git+https://github.com/<org>/plutus-automation-scoring.git@<ref>

      - name: Run reproducibility check
        run: plutus check --secrets-from-env
        env:
          # Mirror your secrets[] entries here as GitHub Action secrets.
          DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
          # ...
```

Once `plutus-verify` is on PyPI, the install step simplifies to
`pip install plutus-verify==0.2.0` (or whatever version you pin to).

---

## 12. Commit

```bash
git checkout -b feat/plutus-verify-integration

git add .plutus/manifest.yaml \
        .github/workflows/plutus.yml \
        .gitignore \
        <instrumented_script>.py \
        <other_instrumented_script>.py

git commit -m "feat: integrate plutus-verify v2 reproducibility verification"
```

Don't push without the maintainer's sign-off on the chosen path (§7.6 A
vs. B).

---

## Workflow recap

```
1. Install plutus-verify wheel (not editable)         → §2
2. Map the repo: stages, scripts, metrics, data        → §3
3. Instrument scripts with pv.step blocks             → §4
4. Run scripts locally to produce results.json        → §5
5. plutus bootstrap → draft + TODO doc                → §6
6. Fill ~8 TODOs in the draft                         → §7
7. Rename .draft → .yaml                              → §8
8. .gitignore the ephemera                            → §9
9. plutus check . — verify end-to-end                 → §10
10. Optional: add CI workflow                         → §11
11. Commit + ask maintainer to review                 → §12
```

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `ValueError: metric '<name>' value must be a finite number, got Decimal(...)` | Forgot a `float(...)` cast on a `Decimal` | Cast each metric arg in the `r.metric()` call. |
| `plutus bootstrap` says "no results.json files found" | Scripts didn't reach the `pv.step` block, or `pv.step` was misspelled | Re-run scripts; `ls .plutus/run/*/results.json` should list one file per step. |
| `MissingResultsError` during `plutus check` | The script crashed inside the container before `pv.step` exited cleanly | Read `.plutus/run/<step>/stderr` to find the upstream crash. |
| `ModuleNotFoundError: No module named 'plutus_verify'` inside the container | SDK auto-injection failed (usually editable-install issue) | Re-install with the wheel via §2. Plan 10 added a loud `SdkBundleError` for this exact class — surfacing the failure rather than silently degrading. |
| `docker build failed` permission denied | Docker daemon not running or user not in docker group | `docker info` should succeed without sudo. |
| Step `FAIL` but all metrics `ok` (pre-Plan-10 bug) | Container crashed before `pv.step` ran, leaving stale results from a prior host run | The current verifier wipes `.plutus/run/<step>/` at the start of each step. If you see this on the current version, file a bug. |

---

## Reference material in this repo

- [`docs/others/protomarketmaker-upgrade.md`](protomarketmaker-upgrade.md) — full worked example
- [`docs/plan/`](../plan/) — design docs for every feature (Plans 1–10)
- [`docs/completion-report/`](../completion-report/) — what landed per phase
- [`out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml`](../../out/transfer-test/ProtoMarketMaker/) — ground-truth manifest (gitignored, generated locally)
- [`plutus_verify/sdk/schema.py`](../../plutus_verify/sdk/schema.py) — enum of allowed `unit=` / `kind=` values
- [`plutus_verify/spec/schema.py`](../../plutus_verify/spec/schema.py) — full manifest JSON-schema, the authoritative spec

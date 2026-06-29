# Upgrade ProtoMarketMaker to plutus-verify v0.2.0 — handoff briefing

> **For the other Claude Code session reading this cold.** Self-contained.
> All paths and commands are concrete. Assume zero prior context.

## What you're doing

The `ProtoMarketMaker` repo is a Plutus-standard trading-strategy repo (Vietnamese
VN30F futures market-maker, backtest + walk-forward optimization). It currently
documents its reproducibility claims in `README.md` prose. You will land the
machine-readable `plutus-verify` v2 contract on it so the strategy can be
reproducibility-verified by anyone with Docker, without reading the README.

**This briefing exercises the "new repo" author flow end-to-end** — instrument
the scripts, run them once locally, let `plutus bootstrap` generate the
manifest draft from the run artifacts, fill in the ~8 TODOs by hand, then
verify with `plutus check`. That's the canonical workflow built across plans
1–9; this is its first real-world exercise outside the verifier's own sandbox.

## Where things live

| Thing | Path |
|---|---|
| The verifier (`plutus-verify` package, v0.2.0) | `/Users/dan/algotrade-research/plutus-automation-scoring` |
| The repo you'll modify | the upstream `ProtoMarketMaker` clone (user provides path) |
| A working reference of the end-state | `/Users/dan/algotrade-research/plutus-automation-scoring/out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` (gitignored sandbox copy with all TODOs already filled — use as ground-truth when in doubt) |

If the user hasn't told you the upstream clone path, ask. Don't assume.

## Background you need (~90 seconds)

The plutus-verify v2 model:

1. **Manifest** at `.plutus/manifest.yaml` declares env, secrets, data sources, steps, expected metrics with tolerances. Author-written, source-of-truth for verification.
2. **Scripts emit `.plutus/run/<step_id>/results.json`** via `import plutus_verify as pv` + `with pv.step("...") as r: r.metric(name, value, unit="ratio")`. The SDK validates the schema and writes the file atomically on clean exit.
3. **`plutus bootstrap`** reads `.plutus/run/<step_id>/results.json` files + the filesystem (`.python-version`, `pyproject.toml`, `requirements.txt`) and emits `.plutus/manifest.yaml.draft` (~70% complete) plus `.plutus/manifest_TODO.md` (author-facing guidance for the ~8 remaining unknowable fields).
4. **`plutus check <repo>`** builds a Docker image from the manifest env, runs each step, reads each step's `results.json`, compares metrics by name against `expected.metrics` within tolerance. Exit 0 if all match, 1 if any drift, 2 on infrastructure failure.
5. **The Dockerfile auto-injects `plutus-verify`** so scripts can `import plutus_verify` without touching `requirements.txt`.
6. **`plutus snapshot --no-run`** reads existing `results.json` and writes values into the manifest's `expected.metrics[].value` slots — ruamel.yaml round-trip, comments preserved. Author reviews the diff and commits; the git commit IS the verification claim.

The full design history is in `/Users/dan/algotrade-research/plutus-automation-scoring/docs/plan/` (nine plans, all complete).

## Prerequisites on the host

- Python 3.11+
- Local Docker daemon running (`docker info` should succeed)
- Access to the verifier source at `/Users/dan/algotrade-research/plutus-automation-scoring`
- ProtoMarketMaker's data accessible (you'll need to run `python data_loader.py` or place the four `VN30F1M_data.csv` / `VN30F2M_data.csv` files under `data/is/` and `data/os/` so the scripts can run locally for the initial bootstrap)

## Step 0 — Confirm scope with the user

Before touching anything:

1. Ask the user for the upstream `ProtoMarketMaker` path if not in this doc.
2. Confirm they want this work committed directly to a branch in that repo (and which branch — likely `feat/plutus-verify-integration` or similar).
3. Confirm whether they want a PR opened at the end or just commits on a branch.
4. Confirm they have (or can produce) the input data files locally — either via running `data_loader.py` (needs DB creds) or via downloading from the Google Drive folder at `https://drive.google.com/drive/folders/181d7JcfHilIvviLgEuaDt2VqwZLYnYUF`.

## Step 1 — Install plutus-verify into a host venv (use a wheel, not editable)

In the upstream ProtoMarketMaker clone:

```bash
cd <upstream-protomarketmaker-path>

# Use whatever venv discipline the repo already follows. If no venv exists:
python3.11 -m venv .venv
source .venv/bin/activate

# Install ProtoMarketMaker's own deps
pip install -r requirements.txt
```

**Now install plutus-verify from a built wheel — NOT `pip install -e`.**
The editable install path on setuptools sometimes produces an `.egg-info`
metadata layout that the verifier's "where am I installed?" lookup
handles poorly; the wheel install avoids the fragility entirely.

```bash
# One-time, in the plutus-verify repo: build the wheel via the release script
# (two-pass so the wheel contains a bundled copy of itself — Plan 10).
cd /Users/dan/algotrade-research/plutus-automation-scoring
source .venv/bin/activate
bash scripts/release-build.sh
# → produces dist/plutus_verify-0.2.0-py3-none-any.whl

# Back in ProtoMarketMaker's venv, install from that wheel.
cd <upstream-protomarketmaker-path>
source .venv/bin/activate
pip install /Users/dan/algotrade-research/plutus-automation-scoring/dist/plutus_verify-0.2.0-py3-none-any.whl --force-reinstall

# Sanity-checks
python -c "import plutus_verify; print(plutus_verify.__version__)"
# → 0.2.0
plutus --help
# → should list init / check / snapshot / transfer / bootstrap / verify
```

If `plutus --help` doesn't show `bootstrap` in the subcommand list, stop and fix the install (most likely Python version mismatch — 3.11+ required).

Why not `pip install -e`? See `docs/plan/2026-05-25-plutus-verifier-integrity.md` for the full incident report. Short version: a real upstream run silently produced false-positive "ok" lines under FAILED steps because the editable install caused the SDK to fail to bundle into the Docker image. The wheel install closes that hole. Plan 10 also added a loud-error guard so future failures of this class are surfaced immediately rather than silently degraded.

## Step 2 — Instrument `backtesting.py`

Find the `if __name__ == "__main__":` block (around line 350). It currently looks something like:

```python
if __name__ == "__main__":
    bt = Backtesting(capital=Decimal("5e5"))
    data = bt.process_data()
    bt.run(data, Decimal("1.8"))

    print(f"Sharpe ratio: {bt.metric.sharpe_ratio(risk_free_return=Decimal('0.00023')) * Decimal(np.sqrt(250))}")
    print(f"Sortino ratio: {bt.metric.sortino_ratio(risk_free_return=Decimal('0.00023')) * Decimal(np.sqrt(250))}")
    mdd, _ = bt.metric.maximum_drawdown()
    print(f"Maximum drawdown: {mdd}")

    monthly_df = pd.DataFrame(bt.monthly_tracking, columns=["date", "asset"])
    returns = get_returns(monthly_df)

    print(f"HPR {bt.metric.hpr()}")
    print(f"Monthly return {returns['monthly_return']}")
    print(f"Annual return {returns['annual_return']}")

    bt.plot_hpr()
    bt.plot_drawdown()
    bt.plot_inventory()
```

Two changes:

**1. Add the SDK import** near the other imports at the top:

```python
import plutus_verify as pv
```

**2. Refactor `__main__` so metric values are bound to variables, then add the `pv.step` block:**

```python
if __name__ == "__main__":
    bt = Backtesting(capital=Decimal("5e5"))
    data = bt.process_data()
    bt.run(data, Decimal("1.8"))

    sharpe = bt.metric.sharpe_ratio(risk_free_return=Decimal('0.00023')) * Decimal(np.sqrt(250))
    sortino = bt.metric.sortino_ratio(risk_free_return=Decimal('0.00023')) * Decimal(np.sqrt(250))
    mdd, _ = bt.metric.maximum_drawdown()

    print(f"Sharpe ratio: {sharpe}")
    print(f"Sortino ratio: {sortino}")
    print(f"Maximum drawdown: {mdd}")

    monthly_df = pd.DataFrame(bt.monthly_tracking, columns=["date", "asset"])
    returns = get_returns(monthly_df)

    print(f"HPR {bt.metric.hpr()}")
    print(f"Monthly return {returns['monthly_return']}")
    print(f"Annual return {returns['annual_return']}")

    bt.plot_hpr()
    bt.plot_drawdown()
    bt.plot_inventory()

    with pv.step("in_sample_backtest") as r:
        r.metric("sharpe_ratio",     float(sharpe),                    unit="ratio")
        r.metric("sortino_ratio",    float(sortino),                   unit="ratio")
        r.metric("maximum_drawdown", float(mdd),                       unit="ratio")
        r.metric("hpr",              float(bt.metric.hpr()),           unit="ratio")
        r.metric("monthly_return",   float(returns['monthly_return']), unit="ratio")
        r.metric("annual_return",    float(returns['annual_return']),  unit="ratio")
        r.artifact("equity_curve",   "result/backtest/hpr.svg",       kind="chart")
        r.artifact("drawdown_chart", "result/backtest/drawdown.svg",  kind="chart")
        r.artifact("inventory",      "result/backtest/inventory.svg", kind="chart")
        r.metadata(seed=2025)
```

**Critical:** the `float(...)` casts matter. The script's metric methods return `Decimal`, and the SDK enforces `int|float` only. Without the cast, you get `ValueError: metric 'sharpe_ratio' value must be a finite number, got Decimal(...)`.

## Step 3 — Instrument `evaluation.py`

This file is shorter (~30 lines). Replace its `__main__` block with:

```python
"""
Out-sample evaluation module
"""

from decimal import Decimal
import numpy as np
import pandas as pd

import plutus_verify as pv

from config.config import BEST_CONFIG
from backtesting import Backtesting
from metrics.metric import get_returns


if __name__ == "__main__":
    data = Backtesting.process_data(evaluation=True)
    bt = Backtesting(capital=Decimal('5e5'))

    bt.run(data, Decimal(BEST_CONFIG["step"]))
    bt.plot_hpr(path="result/optimization/hpr.svg")
    bt.plot_drawdown(path="result/optimization/drawdown.svg")
    bt.plot_inventory(path="result/optimization/inventory.svg")

    monthly_df = pd.DataFrame(bt.monthly_tracking, columns=["date", "asset"])
    returns = get_returns(monthly_df)

    sharpe = bt.metric.sharpe_ratio(risk_free_return=Decimal('0.00023')) * Decimal(np.sqrt(250))
    sortino = bt.metric.sortino_ratio(risk_free_return=Decimal('0.00023')) * Decimal(np.sqrt(250))
    mdd, _ = bt.metric.maximum_drawdown()

    print(f"HPR {bt.metric.hpr()}")
    print(f"Monthly return {returns['monthly_return']}")
    print(f"Annual return {returns['annual_return']}")
    print(f"Sharpe ratio: {sharpe}")
    print(f"Sortino ratio: {sortino}")
    print(f"Maximum drawdown: {mdd}")

    with pv.step("out_of_sample_backtest") as r:
        r.metric("sharpe_ratio",     float(sharpe),                    unit="ratio")
        r.metric("sortino_ratio",    float(sortino),                   unit="ratio")
        r.metric("maximum_drawdown", float(mdd),                       unit="ratio")
        r.metric("hpr",              float(bt.metric.hpr()),           unit="ratio")
        r.metric("monthly_return",   float(returns['monthly_return']), unit="ratio")
        r.metric("annual_return",    float(returns['annual_return']),  unit="ratio")
        r.artifact("equity_curve",   "result/optimization/hpr.svg",       kind="chart")
        r.artifact("drawdown_chart", "result/optimization/drawdown.svg",  kind="chart")
        r.artifact("inventory",      "result/optimization/inventory.svg", kind="chart")
        r.metadata(seed=2025)
```

## Step 4 — Run scripts locally to produce `results.json`

Bootstrap needs the run artifacts (`results.json`) to auto-fill the manifest. Run both scripts locally on the host:

```bash
# Ensure data is in place. Either:
#   (a) Run data_loader.py if you have DB credentials in your env:
#       python data_loader.py
#   (b) Manually download the four CSVs from
#       https://drive.google.com/drive/folders/181d7JcfHilIvviLgEuaDt2VqwZLYnYUF
#       into data/is/ and data/os/ matching the layout (VN30F1M_data.csv + VN30F2M_data.csv each).

# Run the in-sample backtest
python backtesting.py
# Should print Sharpe/Sortino/HPR/etc. and produce
#   .plutus/run/in_sample_backtest/results.json

# Run the out-of-sample evaluation (depends on optimized_parameter.json
# being already in the repo — it should ship with seed=2025)
python evaluation.py
# Produces .plutus/run/out_of_sample_backtest/results.json
```

Verify both files exist before bootstrap:

```bash
ls .plutus/run/*/results.json
# .plutus/run/in_sample_backtest/results.json
# .plutus/run/out_of_sample_backtest/results.json
```

If a script raises `ValueError: metric '...' value must be a finite number, got Decimal(...)`, you forgot a `float(...)` cast in Step 2 or Step 3. Fix and re-run.

## Step 5 — `plutus bootstrap`

```bash
plutus bootstrap .
```

Expected output:

```
draft:    .plutus/manifest.yaml.draft  (2 steps, 12 metrics)
guidance: .plutus/manifest_TODO.md

Next: fill in TODO_* markers in the draft (see manifest_TODO.md),
      rename .draft → .yaml, then run `plutus check`.
```

What got auto-filled (≈70% of the manifest):

- `schema_version: "2.0"`
- `repo.name: ProtoMarketMaker` (from your cwd)
- `env.python_version: "3.11"` (detected from `.python-version` or `pyproject.toml`)
- `env.requirements_file: requirements.txt` (detected from filesystem)
- `steps[].id` for `in_sample_backtest` and `out_of_sample_backtest` (from `.plutus/run/` directories), with `network: none`, `timeout_seconds: 1800`, `outputs:` filled from each step's artifact paths
- All 12 `expected.metrics[]` entries (6 in-sample + 6 OOS) with `name`, `display_name` (auto-converted from snake_case), current `value`, and default `tolerance: {kind: relative, value: 0.05}`
- `expected.artifacts[]` per step with `compare: visual_similarity` for chart artifacts

What needs your input (≈30% — the 8 unknowables, marked with `TODO_*` sentinels you can grep):

```bash
grep TODO_ .plutus/manifest.yaml.draft
```

## Step 6 — Fill in the TODOs

Open `.plutus/manifest_TODO.md` in one buffer and `.plutus/manifest.yaml.draft` in another. Walk through each TODO. The guidance doc has worked examples for each section; this section gives the *ProtoMarketMaker-specific answers* for each.

### 6.1 `env.os_packages`

ProtoMarketMaker's deps don't require apt packages beyond what `python:3.11-slim` ships. Delete the TODO line, leave as empty list (or omit the key entirely):

```yaml
env:
  base: python
  python_version: '3.11'
  requirements_file: requirements.txt
  # os_packages omitted — no apt deps needed
```

### 6.2 `secrets[]`

Five database keys for `data_collection`. Replace `secrets: []  # TODO_secrets: ...` with:

```yaml
secrets:
  - key: DB_NAME
    purpose: Algotrade database name
    used_by: [data_collection]
  - key: DB_USER
    purpose: Algotrade database user
    used_by: [data_collection]
  - key: DB_PASSWORD
    purpose: Algotrade database password
    used_by: [data_collection]
  - key: DB_HOST
    purpose: Algotrade database host
    used_by: [data_collection]
  - key: DB_PORT
    purpose: Algotrade database port
    used_by: [data_collection]
```

### 6.3 `data_sources[]`

Google Drive folder hosts the four CSVs. Replace `data_sources:` block with:

```yaml
data_sources:
  processed: []
  raw:
    - kind: google_drive
      url: https://drive.google.com/drive/folders/181d7JcfHilIvviLgEuaDt2VqwZLYnYUF
      expected_layout:
        - data/is/VN30F1M_data.csv
        - data/is/VN30F2M_data.csv
        - data/os/VN30F1M_data.csv
        - data/os/VN30F2M_data.csv
      satisfies: [data_collection]
```

This is the Tier 2 (raw) download. If the verifier finds the four files after gdown, it skips running `data_loader.py` (which needs DB creds).

### 6.4 `steps[]` free-form additions — `data_collection` and `optimization`

Bootstrap only auto-detected the two backtest steps (those run `pv.step`). You need to add `data_collection` and `optimization` by hand. In the `steps:` block, after the `TODO_steps` comment and before the auto-detected entries, add:

```yaml
steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge          # needs internet (DB or gdown)
    timeout_seconds: 1800
    command: "python data_loader.py"
    inputs: []
    outputs:
      - data/is/VN30F1M_data.csv
      - data/is/VN30F2M_data.csv
      - data/os/VN30F1M_data.csv
      - data/os/VN30F2M_data.csv

  - id: optimization
    nine_step: step_5_optimization
    required: true
    network: none
    timeout_seconds: 1800
    verification_mode: artifact_check
    inputs:
      - parameter/optimization_parameter.json
    outputs:
      - parameter/optimized_parameter.json
    depends_on: [data_collection]

  # then the two auto-detected backtest steps follow (next subsection)
```

`verification_mode: artifact_check` on `optimization` means the verifier skips re-running optuna — it just confirms the shipped `parameter/optimized_parameter.json` exists. The seed-2025 result is the verification artifact.

### 6.5 `steps[].command|nine_step|inputs|depends_on` for the auto-detected steps

For the two auto-detected steps (`in_sample_backtest`, `out_of_sample_backtest`), replace each TODO sentinel:

**`in_sample_backtest`:**
- `nine_step: TODO_nine_step_for_in_sample_backtest` → `nine_step: step_4_in_sample`
- `command: TODO_command_for_in_sample_backtest` → `command: "python backtesting.py"`
- `inputs: []  # TODO_inputs_for_in_sample_backtest` →
  ```yaml
  inputs:
    - data/is/VN30F1M_data.csv
    - data/is/VN30F2M_data.csv
    - parameter/backtesting_parameter.json
  ```
- `depends_on: []  # TODO_depends_on_for_in_sample_backtest` → `depends_on: [data_collection]`

**`out_of_sample_backtest`:**
- `nine_step: TODO_nine_step_for_out_of_sample_backtest` → `nine_step: step_6_out_of_sample`
- `command: TODO_command_for_out_of_sample_backtest` → `command: "python evaluation.py"`
- `inputs:` →
  ```yaml
  inputs:
    - data/os/VN30F1M_data.csv
    - data/os/VN30F2M_data.csv
    - parameter/optimized_parameter.json
    - parameter/backtesting_parameter.json
  ```
- `depends_on:` → `depends_on: [optimization]`

### 6.6 `nine_step_coverage`

Replace the `present: false, section: null` skeleton with:

```yaml
nine_step_coverage:
  step_1_hypothesis: {present: true, section: "Hypothesis"}
  step_2_data_collection: {present: true, section: "Data Collection"}
  step_3_data_processing: {present: false, section: null}
  step_4_in_sample: {present: true, section: "In-sample Backtesting"}
  step_5_optimization: {present: true, section: "Optimization"}
  step_6_out_of_sample: {present: true, section: "Out-of-sample Backtesting"}
  step_7_paper_trading: {present: false, section: null}
```

### 6.7 Verify all TODOs are resolved

```bash
grep TODO_ .plutus/manifest.yaml.draft
# should print nothing
```

If anything is left, fix it. If you're unsure how to fill a TODO, look at the ground-truth manifest at `/Users/dan/algotrade-research/plutus-automation-scoring/out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` — it has all 8 TODO sections filled with the verified-correct values.

### 6.8 Heads-up on OOS values

Bootstrap auto-filled `expected.metrics[].value` from the **script's actual output** (your current local run). For the OOS step, those values are the script's real numbers (~`sharpe_ratio: 0.0815`, `sortino_ratio: 0.118`, etc.), NOT the README's claimed values (`0.1105`, `0.1605`).

The README documents *different* numbers. There's ~26% drift on Sharpe/Sortino/HPR (likely a risk-free-rate or annualization mismatch — MDD/Monthly/Annual return match exactly, so the price path is reproducing).

**Two options:**

- **(A) Land the manifest with the README-claimed values.** Manually edit the OOS metric `value:` fields to the README numbers (`sharpe_ratio: 0.1105`, `sortino_ratio: 0.1605`, `hpr: 0.0848`). When you run `plutus check`, the 3 OOS metrics will FAIL — that's the verifier doing its job, surfacing the README-vs-script divergence.

- **(B) Land the manifest with the script's actual values (the bootstrap defaults).** The script values are what bootstrap already put in. `plutus check` will PASS all 12. You're claiming "the script's current output IS the reproducibility target," accepting that the README's claimed numbers are stale.

Ask the maintainer before choosing. Path (A) is the conservative one for a first pass — surface the divergence loudly. Path (B) is appropriate when the maintainer is the one running the verification and accepts the script as authoritative.

The verified end-state manifest in the sandbox uses **path (A)** — README-claimed values, exit-1 verdict expected.

## Step 7 — Finalize the manifest

When all TODOs are filled in and you've chosen path (A) or (B):

```bash
mv .plutus/manifest.yaml.draft .plutus/manifest.yaml
```

## Step 8 — `.gitignore`

Append:

```
# plutus-verify ephemera
.plutus/run/
.plutus/build/
.plutus/Dockerfile.generated
.plutus/manifest.yaml.draft
.plutus/manifest_TODO.md
```

Keep `.plutus/manifest.yaml` + `.plutus/expected/` (if used) under version control. Run-artifacts, the generated Dockerfile, and the draft/TODO scaffolding are all ephemeral.

## Step 9 — Run `plutus check` end-to-end

```bash
plutus check . 2>&1 | tee /tmp/plutus-check.log
```

This will:
1. Stage a `plutus-verify` wheel into `.plutus/build/`
2. Generate `.plutus/Dockerfile.generated` from the manifest's `env` block
3. `docker build` an image (tagged by content hash)
4. Download the four CSVs from Google Drive (~30s, ~10MB) — `data_collection` is satisfied by the data_source, so it doesn't run
5. Run `python backtesting.py` inside the container — produces `.plutus/run/in_sample_backtest/results.json`
6. Skip optimization (`artifact_check` mode — verifies `optimized_parameter.json` exists)
7. Run `python evaluation.py` — produces `.plutus/run/out_of_sample_backtest/results.json`
8. Compare each step's `results.json` against `expected.metrics` by name

Total wall-clock: 6–10 minutes (build ~2 min cached, backtest ~3 min, eval ~3 min).

**Expected output (path A — README values):**

```
building image from .plutus/Dockerfile.generated...
image: plutus-v2:<hash>
data tier: raw
  ok data_collection: exit=0 (skipped: satisfied_by_data_source)
  ok in_sample_backtest: exit=0
  ok optimization: exit=0 (skipped: artifact_check ...)
  ok out_of_sample_backtest: exit=0
  ok in_sample_backtest.sharpe_ratio: actual=0.95... expected=0.9516
  ok in_sample_backtest.sortino_ratio: actual=1.34... expected=1.349
  ok in_sample_backtest.maximum_drawdown: actual=-0.20... expected=-0.201
  ok in_sample_backtest.hpr: actual=0.299... expected=0.2992
  ok in_sample_backtest.monthly_return: actual=0.018... expected=0.0181
  ok in_sample_backtest.annual_return: actual=0.171... expected=0.171
  FAIL out_of_sample_backtest.sharpe_ratio: actual=0.0815... expected=0.1105
  FAIL out_of_sample_backtest.sortino_ratio: actual=0.118... expected=0.1605
  ok out_of_sample_backtest.maximum_drawdown: actual=-0.10... expected=-0.1028
  FAIL out_of_sample_backtest.hpr: actual=0.0802 expected=0.0848
  ok out_of_sample_backtest.monthly_return: actual=0.0056... expected=0.0056
  ok out_of_sample_backtest.annual_return: actual=0.062... expected=0.062
```

Exit code 1 (path A): **6/6 in-sample pass, 3/6 OOS pass**.

If path B (bootstrap values): exit 0, all 12 pass.

## Step 10 — Commit

```bash
git checkout -b feat/plutus-verify-integration
git add .plutus/manifest.yaml .gitignore backtesting.py evaluation.py
git commit -m "$(cat <<'EOF'
feat: integrate plutus-verify v2 reproducibility verification

Adds .plutus/manifest.yaml declaring the four reproducibility steps
(data_collection / in_sample_backtest / optimization / out_of_sample_backtest),
expected metrics with tolerances, and the Google Drive data source.

Instruments backtesting.py and evaluation.py with `with pv.step(...) as r:`
blocks that emit canonical `.plutus/run/<step_id>/results.json` files. The
verifier reads these by metric name and compares against the manifest's
expected.metrics within tolerance.

Workflow used: instrument scripts → run locally → `plutus bootstrap` to
auto-generate the manifest draft → fill 8 TODOs by hand using
manifest_TODO.md guidance → `plutus check`.

Verified end-to-end against plutus-verify v0.2.0:
6/6 in-sample metrics pass; 3/6 out-of-sample pass — Sharpe/Sortino/HPR
diverge ~26% from README claims (a real reproducibility finding the new
contract surfaces, not a manifest configuration error).
EOF
)"
```

Don't push without asking. Confirm the branch name and PR target with the user first.

## Step 12 — Report back to user

Include:
- Branch name + commit SHA
- Exit code from `plutus check` (1 for path A, 0 for path B)
- Pass/fail count per step
- Path to `/tmp/plutus-check.log` for raw output
- Which OOS divergence path was chosen (A or B) and why
- Any surprises during bootstrap (TODO sentinels left unresolved, unexpected metric drift, etc.)

## Troubleshooting

### `plutus bootstrap` reports "no results.json files found"

Step 4 didn't produce `.plutus/run/<step_id>/results.json`. Re-run the scripts:
```bash
python backtesting.py
python evaluation.py
ls .plutus/run/*/results.json
```

If the scripts crash with `ImportError: No module named plutus_verify`, your host venv doesn't have the verifier installed. Re-run Step 1.

### `ValueError: metric 'X' value must be a finite number`

You forgot a `float(...)` cast on a `Decimal` value in the `r.metric(...)` call. The SDK only accepts int/float.

### `ModuleNotFoundError: No module named 'plutus_verify'` inside the container

The SDK auto-injection failed. Check:
```bash
ls .plutus/build/
# should contain plutus_verify-0.2.0-py3-none-any.whl
cat .plutus/Dockerfile.generated | grep plutus_verify
# should show: COPY .plutus/build/plutus_verify-0.2.0-py3-none-any.whl /tmp/...
#              RUN pip install --no-cache-dir /tmp/plutus_verify-0.2.0-py3-none-any.whl
```

If the wheel isn't there: the verifier couldn't find its own source. Most likely `pip install -e ...` wasn't run, or was run for the wrong Python interpreter. Verify:
```bash
python -c "from importlib.metadata import distribution; d = distribution('plutus-verify'); print(d.version)"
```
Should print `0.2.0`.

### `MissingResultsError: expected .plutus/run/.../results.json`

The `pv.step(...)` block didn't reach `__exit__`. Either the script crashed before the block, or the block raised. Check:
- Did the print statements above the `pv.step` block fire?
- Did the `pv.step` block raise a `ValueError` from a `r.metric(...)` call?

### `plutus bootstrap` says "manifest.yaml already exists"

You're past the bootstrap stage. If you want to regenerate, delete `.plutus/manifest.yaml` first (or use `plutus snapshot --no-run` to refresh just the values in the existing manifest).

### Google Drive download stalls or fails

Common failures:
- Folder URL goes private — download breaks
- Rate limits (rare for ~10MB)
- Network proxy interference

Workaround: download the four CSVs by hand into the matching paths under `data/is/` and `data/os/`. The verifier will detect the files are already present and skip the download (Tier 3 fallback: run the data_collection step's command — but since you have data already, the layout check passes).

### `docker build failed` with permission denied

Docker daemon isn't running, or your user isn't in the `docker` group. On Linux: `sudo systemctl start docker` and verify `docker info` works without sudo.

## Reference: ground-truth working state

The exact same transformation was applied and verified end-to-end at:
```
/Users/dan/algotrade-research/plutus-automation-scoring/out/transfer-test/ProtoMarketMaker/
```

When in doubt about how to fill a TODO, that directory's `.plutus/manifest.yaml` is the source of truth.

## What success looks like

- Branch `feat/plutus-verify-integration` exists in the upstream repo
- Bootstrap produced `.plutus/manifest.yaml.draft` cleanly; TODOs were filled following manifest_TODO.md + the ProtoMarketMaker-specific answers in Step 6
- `.plutus/manifest.yaml` exists (renamed from `.draft`), all TODOs resolved, schema-valid
- `plutus check .` produces:
  - Path A: exit 1, 6/6 in-sample + 3/6 OOS (Sharpe/Sortino/HPR fail — the README divergence)
  - Path B: exit 0, 6/6 + 6/6
- A PR is opened (if user requested); `plutus check` is green (or red on the OOS divergence — that's a feature, not a bug)

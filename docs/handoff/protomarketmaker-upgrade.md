# Upgrade ProtoMarketMaker to plutus-verify v0.2.0 — handoff briefing

> **For the other Claude Code session reading this cold.** Self-contained.
> All paths and commands are concrete. Assume zero prior context.

## What you're doing

The `ProtoMarketMaker` repo is a Plutus-standard trading-strategy repo (Vietnamese
VN30F futures market-maker, backtest + walk-forward optimization). It currently
documents its reproducibility claims in `README.md` prose. You will land the
machine-readable `plutus-verify` v2 contract on it so the strategy can be
reproducibility-verified by anyone with Docker, without reading the README.

## Where things live

| Thing | Path |
|---|---|
| The verifier (`plutus-verify` package, v0.2.0) | `/Users/dan/algotrade-research/plutus-automation-scoring` |
| The repo you'll modify | the upstream `ProtoMarketMaker` clone (user provides path) |
| A working reference of the end-state | `/Users/dan/algotrade-research/plutus-automation-scoring/out/transfer-test/ProtoMarketMaker/` (gitignored sandbox copy with all the work already applied — use as ground truth) |

If the user hasn't told you the upstream clone path, ask. Don't assume.

## Background you need (~60 seconds)

The plutus-verify v2 model:

1. **Manifest** at `.plutus/manifest.yaml` declares env, secrets, data sources, steps, expected metrics with tolerances. Author-written, source-of-truth for verification.
2. **Scripts emit `.plutus/run/<step_id>/results.json`** via `import plutus_verify as pv` + `with pv.step("...") as r: r.metric(name, value, unit="ratio")`. The SDK validates the schema and writes the file atomically on clean exit.
3. **`plutus check <repo>`** builds a Docker image from the manifest env, runs each step, reads each step's `results.json`, compares metrics by name against `expected.metrics` within tolerance. Exit 0 if all match, 1 if any drift, 2 on infrastructure failure.
4. **The Dockerfile auto-injects `plutus-verify`** so scripts can `import plutus_verify` without touching `requirements.txt`.
5. **`plutus snapshot --no-run`** reads existing `results.json` and writes values into the manifest's `expected.metrics[].value` slots — ruamel.yaml round-trip, comments preserved. Author reviews the diff and commits; the git commit IS the verification claim.

The full design history is in `/Users/dan/algotrade-research/plutus-automation-scoring/docs/plan/` (eight plans, all complete).

## Prerequisites on the host

- Python 3.11+
- Local Docker daemon running (`docker info` should succeed)
- Access to the verifier source at `/Users/dan/algotrade-research/plutus-automation-scoring`

## Step 0 — Confirm scope with the user

Before touching anything:

1. Ask the user for the upstream `ProtoMarketMaker` path if not in this doc.
2. Confirm they want this work committed directly to a branch in that repo (and which branch — likely `feat/plutus-verify-integration` or similar).
3. Confirm whether they want a PR opened at the end or just commits on a branch.

## Step 1 — Install plutus-verify into a venv used by the repo

In the upstream ProtoMarketMaker clone:

```bash
cd <upstream-protomarketmaker-path>

# Use whatever venv discipline the repo already follows. If no venv exists:
python3.11 -m venv .venv
source .venv/bin/activate

# Install ProtoMarketMaker's own deps
pip install -r requirements.txt

# Install the verifier from local source (editable install).
# IMPORTANT: this is the verifier, not a dep of ProtoMarketMaker's runtime —
# you only need it on the host for `plutus check`. The Docker image installs
# its own copy via Plan 7's auto-injection.
pip install -e /Users/dan/algotrade-research/plutus-automation-scoring

# Sanity-check
plutus --help
```

If `plutus --help` doesn't show the subcommand list (`init`, `check`, `snapshot`, `transfer`, `verify`), stop and fix the install. Likely Python version mismatch (3.11+ required).

## Step 2 — Create the `.plutus/` directory and the manifest

```bash
mkdir -p .plutus
```

Write `.plutus/manifest.yaml` with this exact content (lifted from the verified sandbox copy at `/Users/dan/algotrade-research/plutus-automation-scoring/out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml`):

```yaml
# Plutus v2 manifest for PROTO:Market Maker.
# Notes:
# - ExpectedMetrics are matched against metrics produced into
#   .plutus/run/<step_id>/results.json by the instrumented scripts
#   (backtesting.py, evaluation.py).
# - The optimization step is artifact_check — the shipped optimized_parameter.json
#   (seed=2025) is the verification artifact; no need to re-run optuna.
schema_version: "2.0"

repo:
  name: PROTO:Market Maker
  primary_language: python

env:
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt

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

steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge
    timeout_seconds: 1800
    command: "python data_loader.py"
    inputs: []
    outputs:
      - data/is/VN30F1M_data.csv
      - data/is/VN30F2M_data.csv
      - data/os/VN30F1M_data.csv
      - data/os/VN30F2M_data.csv

  - id: in_sample_backtest
    nine_step: step_4_in_sample
    required: true
    network: none
    timeout_seconds: 1800
    command: "python backtesting.py"
    inputs:
      - data/is/VN30F1M_data.csv
      - data/is/VN30F2M_data.csv
      - parameter/backtesting_parameter.json
    outputs:
      - result/backtest/hpr.svg
      - result/backtest/drawdown.svg
      - result/backtest/inventory.svg
    depends_on: [data_collection]

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

  - id: out_of_sample_backtest
    nine_step: step_6_out_of_sample
    required: true
    network: none
    timeout_seconds: 1800
    command: "python evaluation.py"
    inputs:
      - data/os/VN30F1M_data.csv
      - data/os/VN30F2M_data.csv
      - parameter/optimized_parameter.json
      - parameter/backtesting_parameter.json
    outputs:
      - result/optimization/hpr.svg
      - result/optimization/drawdown.svg
      - result/optimization/inventory.svg
    depends_on: [optimization]

expected:
  - step_id: in_sample_backtest
    metrics:
      - name: sharpe_ratio
        display_name: "Sharpe Ratio"
        value: 0.9516
        tolerance: {kind: relative, value: 0.05}
      - name: sortino_ratio
        display_name: "Sortino Ratio"
        value: 1.3490
        tolerance: {kind: relative, value: 0.05}
      - name: maximum_drawdown
        display_name: "Maximum Drawdown"
        value: -0.2010
        tolerance: {kind: absolute, value: 0.02}
      # HPR/return values: script prints ratios (e.g. 0.299), README documents
      # percent (e.g. 29.92). Manifest mirrors the script — these are ratios.
      - name: hpr
        display_name: "HPR"
        value: 0.2992
        tolerance: {kind: relative, value: 0.05}
      - name: monthly_return
        display_name: "Monthly return"
        value: 0.0181
        tolerance: {kind: relative, value: 0.05}
      - name: annual_return
        display_name: "Annual return"
        value: 0.1710
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []
  - step_id: out_of_sample_backtest
    metrics:
      - name: sharpe_ratio
        display_name: "Sharpe Ratio"
        value: 0.1105
        tolerance: {kind: relative, value: 0.05}
      - name: sortino_ratio
        display_name: "Sortino Ratio"
        value: 0.1605
        tolerance: {kind: relative, value: 0.05}
      - name: maximum_drawdown
        display_name: "Maximum Drawdown"
        value: -0.1028
        tolerance: {kind: absolute, value: 0.02}
      - name: hpr
        display_name: "HPR"
        value: 0.0848
        tolerance: {kind: relative, value: 0.05}
      - name: monthly_return
        display_name: "Monthly return"
        value: 0.0056
        tolerance: {kind: relative, value: 0.05}
      - name: annual_return
        display_name: "Annual return"
        value: 0.0620
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []

nine_step_coverage:
  step_1_hypothesis: {present: true, section: "Hypothesis"}
  step_2_data_collection: {present: true, section: "Data Collection"}
  step_3_data_processing: {present: false, section: null}
  step_4_in_sample: {present: true, section: "In-sample Backtesting"}
  step_5_optimization: {present: true, section: "Optimization"}
  step_6_out_of_sample: {present: true, section: "Out-of-sample Backtesting"}
  step_7_paper_trading: {present: false, section: null}
```

Heads-up about the OOS values: the README claims `sharpe_ratio: 0.1105` for OOS, but the actual script produces `~0.0815` (~26% drift). This is a real upstream reproducibility issue (likely a risk-free or annualization mismatch — MDD matches exactly while Sharpe/Sortino/HPR don't). The manifest above uses the README-claimed values. After running `plutus check`, the OOS Sharpe/Sortino/HPR will fail. If the user wants the manifest to match the script (so `plutus check` passes), run `plutus snapshot` after Step 7 to overwrite — that's the snapshot-then-commit workflow.

## Step 3 — Instrument `backtesting.py`

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

Make two changes:

**1. Add the SDK import** near the other imports at the top:

```python
import plutus_verify as pv
```

**2. Refactor `__main__` so the metric values are bound to variables, then add the `pv.step` block**:

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

Critical: the `float(...)` casts matter. The script's metric methods return `Decimal`, and the SDK enforces `int|float` only. Without the cast, you get `ValueError: metric 'sharpe_ratio' value must be a finite number, got Decimal(...)`.

## Step 4 — Instrument `evaluation.py`

Find the `if __name__ == "__main__":` block (the entire file is short — ~30 lines). Replace it with:

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

## Step 5 — CI workflow

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
      - name: Install plutus-verify
        run: pip install plutus-verify  # NOTE: only works after PyPI publish; until then this CI step will fail and is informational
      - name: Run reproducibility check
        run: plutus check --secrets-from-env
        env:
          DB_NAME: ${{ secrets.DB_NAME }}
          DB_USER: ${{ secrets.DB_USER }}
          DB_PASSWORD: ${{ secrets.DB_PASSWORD }}
          DB_HOST: ${{ secrets.DB_HOST }}
          DB_PORT: ${{ secrets.DB_PORT }}
```

If the user wants CI to actually run today (before PyPI publish), change the install step to:
```yaml
      - name: Install plutus-verify (from source)
        run: pip install git+https://github.com/<org>/plutus-automation-scoring.git@feat/spec-v2-foundation
```
Ask the user for the right git URL — it depends on whether the verifier has a public remote yet.

## Step 6 — `.gitignore`

Append to `.gitignore` (create if missing):

```
# plutus-verify ephemera
.plutus/run/
.plutus/build/
.plutus/Dockerfile.generated
```

The author keeps `.plutus/manifest.yaml` + `.plutus/expected/` (if used) under version control. Run-artifacts and the generated Dockerfile are ephemeral.

## Step 7 — Run `plutus check` end-to-end

```bash
cd <upstream-protomarketmaker-path>
source .venv/bin/activate
plutus check . 2>&1 | tee /tmp/plutus-check.log
```

This will:
1. Stage a `plutus-verify` wheel into `.plutus/build/` (verifier auto-injects the SDK)
2. Generate `.plutus/Dockerfile.generated` from the manifest's `env` block
3. `docker build` an image (tagged by content hash)
4. Download data from Google Drive (~30s, ~10MB)
5. Run `python backtesting.py` inside the container — writes `.plutus/run/in_sample_backtest/results.json`
6. Skip optimization (`artifact_check` mode — verifies the shipped `optimized_parameter.json` exists)
7. Run `python evaluation.py` — writes `.plutus/run/out_of_sample_backtest/results.json`
8. Compare each step's `results.json` metrics against the manifest's `expected.metrics` by name

Total wall-clock: 6–10 minutes (build ~2 min cached, backtest ~3 min, eval ~3 min).

**Expected output:**

```
building image from .plutus/Dockerfile.generated...
image: plutus-v2:<hash>
data tier: raw
  ok data_collection: exit=0 (skipped: satisfied_by_data_source)
  ok in_sample_backtest: exit=0
  ok optimization: exit=0 (skipped: artifact_check (no execution; outputs verified by preflight))
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

Exit code 1. **6/6 in-sample pass, 3/6 OOS pass** is the expected verdict — the OOS Sharpe/Sortino/HPR divergence is a real upstream reproducibility issue, not a misconfiguration of the manifest.

## Step 8 — Decide what to do about the OOS divergence

Two options, depending on what the upstream maintainer wants:

**A. Land the manifest with the README-claimed values (recommended for first pass).**
Exit-1 surfaces the divergence as a visible failure. Either the README is wrong or the script needs a fix. Either way, the surfaced failure is the value — `plutus check` is doing its job.

**B. Snapshot the script's actual values into the manifest.**
If the maintainer accepts that the script is correct and the README is the stale party:
```bash
plutus snapshot --no-run .
git diff .plutus/manifest.yaml
git commit .plutus/manifest.yaml -m "manifest: snapshot OOS metrics to match script output"
```
After this, `plutus check` exits 0. The commit is the new claim.

Ask the maintainer before doing B. The right answer is repo-policy, not a Claude decision.

## Step 9 — Commit

```bash
git checkout -b feat/plutus-verify-integration
git add .plutus/manifest.yaml .github/workflows/plutus.yml .gitignore backtesting.py evaluation.py
git commit -m "$(cat <<'EOF'
feat: integrate plutus-verify v2 reproducibility verification

Adds .plutus/manifest.yaml declaring the four reproducibility steps
(data_collection / in_sample_backtest / optimization / out_of_sample_backtest),
expected metrics with tolerances, and the Google Drive data source.

Instruments backtesting.py and evaluation.py with `with pv.step(...) as r:`
blocks that emit canonical `.plutus/run/<step_id>/results.json` files. The
verifier reads these by metric name and compares against the manifest's
expected.metrics within tolerance.

Adds .github/workflows/plutus.yml so reproducibility is enforced on every PR.

Verified end-to-end against the local plutus-verify v0.2.0 build:
6/6 in-sample metrics pass; 3/6 out-of-sample pass (Sharpe/Sortino/HPR
diverge ~26% from README claims — a real reproducibility finding the new
contract surfaces, not a manifest configuration error).
EOF
)"
```

Don't push without asking. Confirm the branch name and PR target with the user first.

## Step 10 — Report back to user

Include:
- Branch name + commit SHA
- Exit code from `plutus check` (1 expected)
- Pass/fail count per step
- Path to `/tmp/plutus-check.log` for raw output
- The OOS divergence numbers (so they can decide on Step 8 path A vs B)

## Troubleshooting

### "ModuleNotFoundError: No module named 'plutus_verify'" inside the container

The SDK auto-injection failed. Check:
```bash
ls .plutus/build/
# should contain plutus_verify-0.2.0-py3-none-any.whl
cat .plutus/Dockerfile.generated | grep plutus_verify
# should show two lines: COPY .plutus/build/plutus_verify-0.2.0-py3-none-any.whl /tmp/...
#                       RUN pip install --no-cache-dir /tmp/plutus_verify-0.2.0-py3-none-any.whl
```

If the wheel isn't there: the verifier couldn't find its own source. Most likely `pip install -e ...` wasn't run, or was run for the wrong Python interpreter. Verify with:
```bash
python -c "from importlib.metadata import distribution; d = distribution('plutus-verify'); print(d.version)"
```
Should print `0.2.0`.

### "ValueError: metric 'X' value must be a finite number"

You forgot the `float(...)` cast on a `Decimal` value. The SDK only accepts int/float, not Decimal.

### "MissingResultsError: expected .plutus/run/.../results.json"

The `pv.step(...)` block didn't reach `__exit__`. Either the script crashed before the block, or the block raised. Check:
- Did the print statements above the `pv.step` block fire? (They appear in container stdout.)
- Did the `pv.step` block raise an exception? (Look for `ValueError` from `r.metric(...)`.)

### "docker build failed" with permission denied

Docker daemon isn't running, or your user isn't in the `docker` group. On Linux: `sudo systemctl start docker` and verify `docker info` works without sudo.

### Google Drive download stalls or fails

The data source uses `gdown`. Common failures:
- Folder URL is public; if it goes private, the download breaks
- Rate limits (rare for ~10MB)
- Network proxy interference

Workaround: download the four CSVs by hand into the matching paths under `data/is/` and `data/os/`. The verifier will detect the files are already present and skip the download.

## Reference: the ground-truth working state

The exact same transformation was applied and verified end-to-end at:
```
/Users/dan/algotrade-research/plutus-automation-scoring/out/transfer-test/ProtoMarketMaker/
```

If anything in this briefing seems wrong or incomplete, diff against that directory. It's the source of truth.

## What success looks like

- Branch `feat/plutus-verify-integration` exists in the upstream repo
- Commit lands cleanly, no merge conflicts
- `plutus check .` produces the expected 6/6 + 3/6 verdict (or, per Step 8B, 6/6 + 6/6 after snapshot)
- A PR is opened (if user requested) and CI green (or red on the OOS divergence — that's a feature, not a bug)

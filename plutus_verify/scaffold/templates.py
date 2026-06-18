"""Static template strings emitted by `plutus init`."""
from __future__ import annotations

MANIFEST_SKELETON = """\
# Plutus v2 manifest. Fill in TODO markers, then `plutus check` locally.
schema_version: "2.0"

repo:
  name: TODO_repo_name
  primary_language: python

env:
  base: python
  python_version: "3.11"
  # Recommended: lock dependencies with uv and commit uv.lock — the verifier
  # restores the exact locked env (run `uv lock` to generate it). The pip path
  # below re-resolves at build time and is deprecated (verify emits a notice).
  manager: uv
  lockfile: uv.lock
  # manager: pip                       # deprecated fallback
  # requirements_file: requirements.txt
  # os_packages: [build-essential]
  # gpu_required: false

secrets: []
  # - key: TIINGO_API_KEY
  #   purpose: market data download
  #   used_by: [data_preparation]

data_sources:
  processed: []
  raw: []
  # processed:
  #   - kind: google_drive
  #     url: https://drive.google.com/...
  #     expected_layout: ["data/processed/*.parquet"]
  #     satisfies: [data_preparation]

steps:
  # Step 2 of the Plutus process is Data Preparation — it covers both data
  # collection and processing. Use one data_preparation step.
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    network: bridge          # TODO: 'none' if no network is needed
    timeout_seconds: 1800
    command: "TODO_python_module_to_prepare_data"
    outputs: ["data/processed/"]   # TODO: list the exact file paths/globs
    # Optional: document the collection + processing sub-processes (documentation
    # only, never executed; only valid on this step). Omit if you just download data.
    # sub_processes:
    #   collection: {description: "how raw data is obtained"}
    #   processing: {description: "how raw data becomes the backtest inputs"}
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "TODO_python_module_to_backtest"
    inputs: [data/processed]
    outputs: ["out/metrics.json"]

expected:
  - step_id: in_sample
    metrics:
      # ExpectedMetrics identify metrics by snake_case `name`. The v2 runtime reads
      # values from `.plutus/run/<step_id>/results.json` (written by your
      # script via the SDK). See `.plutus/example_script.py` for a copy-paste
      # template. `display_name` is optional and used for human-readable
      # report labels.
      - name: sharpe_ratio
        display_name: "Sharpe Ratio"
        value: 0.0           # TODO: replace with the value you got
        tolerance: {kind: relative, value: 0.05}
    artifacts: []

nine_step_coverage:
  step_1_hypothesis: {present: true, section: "TODO"}
  step_2_data_preparation: {present: true, section: "TODO"}
  step_3_forming_set_of_rules: {present: false, section: null}
  step_4_in_sample: {present: true, section: "TODO"}
  step_5_optimization: {present: false, section: null}
  step_6_out_of_sample: {present: false, section: null}
  step_7_paper_trading: {present: false, section: null}
"""


EXAMPLE_SCRIPT = '''\
"""Example: how to emit `.plutus/run/<step_id>/results.json` from your script.

This file is documentation. Copy the `with pv.step(...)` block into your real
reproducibility script (e.g., the script `manifest.yaml` invokes for the
`in_sample` step) and replace the placeholder values with whatever your
backtest produced.

The `plutus check` runtime reads `.plutus/run/<step_id>/results.json` and
compares each metric (by snake_case `name`) against the manifest's
`expected.metrics`. Metrics use canonical ratio decimals — write 0.171
(not 17.1) for a 17.1% return.
"""
from __future__ import annotations

import plutus_verify as pv


def run_backtest() -> None:
    """Replace this body with your real backtest. The numbers here are placeholders."""
    # ... your computation here ...
    sharpe_ratio = 0.0
    maximum_drawdown = 0.0
    annual_return = 0.0
    equity_curve_path = "out/equity_curve.png"

    # The `pv.step` context manager writes results.json on clean exit. If
    # this block raises, no file is written (so a failed run won't leave
    # stale results behind).
    with pv.step("in_sample") as r:
        # Numeric metrics — must use snake_case names matching manifest's
        # expected.metrics[].name. Units: fraction | ratio | count | currency_usd | seconds.
        # `fraction` for percent-like metrics (write 42% as 0.42); `ratio` for
        # unbounded dimensionless like Sharpe. `percent` is rejected — always decimals.
        r.metric("sharpe_ratio",     sharpe_ratio,     unit="ratio")
        r.metric("maximum_drawdown", maximum_drawdown, unit="fraction")
        r.metric("annual_return",    annual_return,    unit="fraction")

        # Artifacts — files your script produced. Path is repo-relative.
        # Kinds: chart | csv | json | image | other.
        r.artifact("equity_curve", equity_curve_path, kind="chart")

        # Free-form metadata. Conventional keys: seed, duration_seconds,
        # git_commit. duration_seconds and git_commit are auto-injected;
        # set seed explicitly so the run is reproducible.
        r.metadata(seed=2025)


if __name__ == "__main__":
    run_backtest()
'''


WORKFLOW_YAML = """\
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
        run: pip install plutus-verify
      - name: Run reproducibility check
        run: plutus check --secrets-from-env
        env:
          # Add per-secret entries here; mirror your manifest's `secrets:` block.
          # TIINGO_API_KEY: ${{ secrets.TIINGO_API_KEY }}
          PLUTUS_PLACEHOLDER: ""
"""

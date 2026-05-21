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
  requirements_file: requirements.txt
  # os_packages: [build-essential]
  # gpu_required: false

secrets: []
  # - key: TIINGO_API_KEY
  #   purpose: market data download
  #   used_by: [data_collection]

data_sources:
  processed: []
  raw: []
  # processed:
  #   - kind: google_drive
  #     url: https://drive.google.com/...
  #     expected_layout: ["data/processed/*.parquet"]
  #     satisfies: [data_collection, data_processing]

steps:
  - id: data_collection
    nine_step: step_2_data_collection
    required: true
    network: bridge          # TODO: 'none' if no network is needed
    timeout_seconds: 1800
    command: "TODO_python_module_to_collect_data"
    outputs: ["data/raw/"]   # TODO: list the exact file paths/globs
  - id: data_processing
    nine_step: step_3_data_processing
    required: true
    command: "TODO_python_module_to_preprocess"
    inputs: [data/raw]
    outputs: ["data/processed/"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "TODO_python_module_to_backtest"
    inputs: [data/processed]
    outputs: ["out/metrics.json"]

expected:
  - step_id: in_sample
    headlines:
      # Headlines identify metrics by snake_case `name`. The v2 runtime reads
      # values from `.plutus/run/<step_id>/results.json` (written by the SDK,
      # `from plutus_verify.sdk import Run`). `display_name` is optional and
      # used for human-readable report labels.
      - name: sharpe_ratio
        display_name: "Sharpe Ratio"
        value: 0.0           # TODO: replace with the value you got
        tolerance: {kind: relative, value: 0.05}
    reference_outputs: []

nine_step_coverage:
  step_1_hypothesis: {present: true, section: "TODO"}
  step_2_data_collection: {present: true, section: "TODO"}
  step_3_data_processing: {present: true, section: "TODO"}
  step_4_in_sample: {present: true, section: "TODO"}
  step_5_optimization: {present: false, section: null}
  step_6_out_of_sample: {present: false, section: null}
  step_7_paper_trading: {present: false, section: null}
"""


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

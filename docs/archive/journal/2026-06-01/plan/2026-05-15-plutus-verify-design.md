# Plutus Automation Scoring — Design Plan

## Context

The PLUTUS Standard ([algotrade-plutus/plutus-guideline](https://github.com/algotrade-plutus/plutus-guideline)) is Algotrade's reproducibility standard for algorithmic-trading research repos. Compliance requires the project's `README.md` to map onto the [9-step development process](https://www.algotrade.vn/knowledge/9-step-process/the-9-step) (Hypothesis → Data Collection → Data Processing → In-sample Backtesting → Optimization → Out-of-sample Backtesting → Paper Trading) and to be reproducible end-to-end: a reviewer should be able to clone, follow the README's instructions, and obtain the reported numbers and charts without contacting the author.

Today this audit is manual. Sample projects (e.g., [ProtoMarketMaker](https://github.com/algotrade-plutus/ProtoMarketMaker)) score 50–80% compliance, but the scoring is qualitative; there is no automated way to test the "results match" claim.

**Goal:** Build `plutus-verify`, a CLI tool that takes a Plutus repo's Git URL and produces a structured reproducibility report. Primary user: Algotrade reviewers running batch audits; downstream goal: wrap as a GitHub Action that publishes the badge automatically. The locally-hosted Gemma 4 26B A4B model is used as a structured-output extractor and as a vision judge for chart shape similarity. All deterministic logic (execution, numeric comparison, reporting) lives in plain Python — the LLM is not in the agent loop.

## Architecture overview

Six-stage pipeline. Each stage's artifacts persisted under `./out/<run_id>/` so stages are resumable via `--resume-from`.

```
ingest  →  extract  →  build  →  execute  →  compare  →  report
  git       Gemma     repo2docker   Docker     numeric +    JSON +
  clone     →plan.json  build      step runs   Gemma chart   Markdown
                                               judging       + exit code
```

- **Sandbox:** `repo2docker` builds an image per repo (auto-detects `requirements.txt`/`environment.yml`/`Dockerfile`/etc.). Secrets injected via overlay layer.
- **LLM role:** extractor (one structured call per repo) + chart judge (one call per chart). Deterministic logic everywhere else.
- **Determinism guards:** temperature 0, JSON-schema validation with one retry, plan persisted to disk for reviewer hand-edits.

## Components

### 1. `ingest` — `clone(git_url, run_dir, ref=None) -> repo_path`
Shells out to `git clone --depth=1`. Captures commit SHA + branch into `meta.json`.

### 2. `extract` — `extract_plan(readme_text, llm_client) -> ExtractedPlan`
One Gemma call, structured JSON output (schema in §`ExtractedPlan schema` below). Temperature 0, max retries 1 on schema violation, then hard-fail with raw output preserved. Plan saved to `plan.json`; reviewer can hand-edit and `--resume-from execute`.

### 3. `build` — wraps `repo2docker --no-run --image-name plutus-run-<run_id>`
Post-build overlay layer inserts the reviewer's `--secrets` `.env` at the path the README declares (typically `/srv/repo/.env`). Image cache keyed by `(repo SHA, secrets hash)`.

### 4. `execute` — per-step Docker runner
For each step in `ExtractedPlan.steps`: `docker run --rm -v <run_dir>/artifacts:/srv/repo/<artifacts_dir> ...`. Captures stdout, stderr, exit code, wall time, peak memory to `step_<n>.log`. Per-step config: `timeout_seconds`, `expected_exit_code` (default 0), `network` (default `none`; only the data-collection step gets `bridge`). On step failure, downstream steps with declared `depends_on` are skipped; independent steps still run.

### 5. `compare` — two sub-components

**`compare.metrics`** — for each expected metric: locate it (via the plan's `locate` directive: `stdout_table` / `json_file` JSONPath / `file_regex`), apply tolerance, emit `{metric, expected, actual, tolerance, pass}`. Three default tolerance kinds: `relative` (ratios), `absolute` (percentages / drawdowns), exact (integers). Per-metric overrides in `plutus-verify.yaml`.

**`compare.charts`** — for each expected chart: verify file exists at declared path, rasterize SVG→PNG via `cairosvg` if needed, send (reference, produced) image pair to Gemma (vision) with this prompt:

> Judge along three independent axes (shape, scale, structure), each `match`/`partial`/`mismatch` + ≤25-word reason; then an `overall` verdict + 0–1 confidence. Return JSON only.

A chart "passes" when `overall.verdict == "match" AND confidence ≥ threshold` (default 0.7, configurable). `partial` is surfaced in the report but doesn't fail the step. `--no-charts` flag bypasses this entire path for graceful degradation when Gemma's vision endpoint is unavailable.

### 6. `report` — `report.json` + `report.md` + exit code
Report structured by 9-step section with ✅/⚠️/❌ per check. Includes 9-Step Coverage table (presence + section heading + Gemma's own confidence per step), per-step metric tables, chart judgment summaries, extraction notes, and a reproducibility hash line (`plan.json sha256`, image `sha256`).

## `ExtractedPlan` schema (the contract)

The single source of truth between LLM and the deterministic pipeline. Stable schema = the model can be swapped without touching downstream code.

```jsonc
{
  "schema_version": "1.0",
  "repo": {
    "name": "...",
    "primary_language": "python",
    "env_setup": {"kind": "requirements_txt|environment_yml|pipfile|dockerfile|none",
                  "path": "requirements.txt",
                  "python_version": "3.11",
                  "extra_setup_commands": []},
    "secrets_required": [{"key": "DB_NAME", "purpose": "...", "step_ids": ["data_collection"]}]
  },
  "nine_step_mapping": {
    "step_1_hypothesis":      {"present": true, "section_heading": "Hypothesis",       "confidence": 0.95},
    "step_2_data_collection": {"present": true, "section_heading": "Data Collection",  "confidence": 0.9},
    "step_3_data_processing": {"present": false, "section_heading": null,              "confidence": 0.8},
    "step_4_in_sample":       {"present": true, "section_heading": "In-sample Backtesting", "confidence": 0.95},
    "step_5_optimization":    {"present": true, "section_heading": "Optimization",     "confidence": 0.95},
    "step_6_out_of_sample":   {"present": true, "section_heading": "Out-of-sample Backtesting", "confidence": 0.95},
    "step_7_paper_trading":   {"present": false, "section_heading": null,              "confidence": 1.0}
  },
  "steps": [
    {
      "id": "data_collection",
      "nine_step": "step_2_data_collection",
      "required": false,
      "alternatives": [
        {"label": "google_drive", "kind": "manual_download", "url": "...",
         "expected_layout": ["data/is/*.csv", "data/os/*.csv"]},
        {"label": "db_loader", "kind": "command",
         "command": "python data_loader.py",
         "needs_secrets": ["DB_NAME","DB_USER","DB_PASSWORD","DB_HOST","DB_PORT"],
         "network": "bridge", "timeout_seconds": 1800,
         "produces": ["data/is/", "data/os/"]}
      ]
    },
    {"id": "in_sample_backtest", "nine_step": "step_4_in_sample", "required": true,
     "depends_on": ["data_collection"], "command": "python backtesting.py",
     "config_files": ["parameter/backtesting_parameter.json"],
     "network": "none", "timeout_seconds": 1200,
     "produces": ["result/backtest/hpr.svg","result/backtest/drawdown.svg","result/backtest/inventory.svg"]},
    {"id": "optimization", "nine_step": "step_5_optimization", "required": true,
     "depends_on": ["data_collection"], "command": "python optimization.py",
     "config_files": ["parameter/optimization_parameter.json"],
     "network": "none", "timeout_seconds": 3600,
     "produces": ["parameter/optimized_parameter.json"]},
    {"id": "out_of_sample", "nine_step": "step_6_out_of_sample", "required": true,
     "depends_on": ["data_collection","optimization"], "command": "python evaluation.py",
     "network": "none", "timeout_seconds": 1200,
     "produces": ["result/optimization/hpr.svg","result/optimization/drawdown.svg","result/optimization/inventory.svg"]}
  ],
  "expected_results": [
    {"step_id": "in_sample_backtest",
     "metrics": [
       {"name":"sharpe_ratio","value":0.9516,"locate":{"kind":"stdout_table","row":"Sharpe Ratio","col":1},
        "tolerance":{"kind":"relative","value":0.05}},
       {"name":"max_drawdown","value":-0.2010,"locate":{"kind":"stdout_table","row":"Maximum Drawdown","col":1},
        "tolerance":{"kind":"absolute","value":0.02}}
     ],
     "charts": [
       {"name":"hpr","reference_image":"result/backtest/hpr.svg","produced_path":"result/backtest/hpr.svg"}
     ]},
    {"step_id":"optimization",
     "metrics":[{"name":"step","value":3.1,
                 "locate":{"kind":"json_file","path":"parameter/optimized_parameter.json","jsonpath":"$.step"},
                 "tolerance":{"kind":"absolute","value":0.5}}],
     "charts":[]}
  ],
  "extraction_notes": ["freeform notes flagged for reviewer attention"]
}
```

Three `locate` kinds: `stdout_table` (markdown table printed by the script), `json_file` (path + JSONPath), `file_regex` (file path + regex with named group `value`).

## Rubric → exit code

| Per-step verdict | Condition                                                                  |
|------------------|----------------------------------------------------------------------------|
| ✅ `reproduced`  | All declared metrics within tolerance **and** all declared charts pass     |
| ⚠️ `partial`      | Step executed cleanly, but ≥1 metric out-of-tolerance OR ≥1 chart `partial` |
| ❌ `failed`       | Command exited non-zero, timed out, or expected artifact never produced    |
| ⏭ `skipped`      | Optional step (`required: false`) and no alternative succeeded             |

Overall exit code:
- `0` — every `required: true` step is `reproduced`
- `1` — every `required: true` step at least executed cleanly but some are `partial`
- `2` — any `required: true` step is `failed`, or pipeline couldn't start

## CLI surface

```bash
plutus-verify <git_url> [--ref <branch|sha>]
              [--secrets path/to/.env]
              [--config path/to/plutus-verify.yaml]
              [--out ./out]
              [--resume-from extract|build|execute|compare|report]
              [--prefer-data-path google_drive|db_loader|auto]
              [--llm-endpoint http://localhost:8000/v1]
              [--no-charts] [--dry-run] [--extract-only]

plutus-verify ./local/path --skip-clone
plutus-verify --batch repos.txt --out ./out
```

## `plutus-verify.yaml` (sample)

```yaml
llm:
  endpoint: http://localhost:8000/v1
  model: gemma-4-26b-a4b
  vision_model: gemma-4-26b-a4b
  temperature: 0.0
  max_retries: 1
  timeout_seconds: 120

tolerances:
  ratio_relative:      0.05
  percentage_absolute: 1.0
  pct_point_absolute:  0.02
  integer_absolute:    0
  default_relative:    0.10
  overrides:
    sharpe_ratio: {kind: relative, value: 0.05}
    max_drawdown: {kind: absolute, value: 0.02}

charts:
  enabled: true
  rasterize_dpi: 144
  match_threshold: 0.7
  treat_partial_as_pass: false

execute:
  default_timeout_seconds: 1800
  default_network: none
  data_step_network: bridge
  memory_limit: "8g"
  cpu_limit: "4"

repo2docker:
  image_prefix: plutus-run
  cache: true
```

## Failure-mode catalog (key entries)

| Failure                                | Reaction                                          | Exit |
|----------------------------------------|---------------------------------------------------|:----:|
| README missing                          | Halt at extract                                   |  2   |
| Gemma returns invalid JSON              | Retry once; then hard-fail with raw output saved   |  2   |
| Gemma confidence very low (<0.5)        | Continue, mark `low_confidence`                    |  1   |
| `repo2docker` build fails               | Halt at build, log saved                           |  2   |
| Required secret missing for alt         | Try next alternative; if none → step `failed`     |  2*  |
| Step non-zero exit / timeout            | Mark `failed`; continue independent downstream    |  2*  |
| Expected chart missing                  | Chart `failed`, step downgrades to `partial`      |  1   |
| Metric `locate` can't parse             | Metric `unverifiable`; reviewer can fix + resume  |  1   |
| Random-seed drift                       | Metric out-of-tolerance → `partial`               |  1   |
| Gemma endpoint unreachable              | Hard fail at the using stage; suggest `--no-charts`|  2   |

(* exit 2 only when the affected step has `required: true`.)

## Project layout

```
plutus-automation-scoring/
├── pyproject.toml
├── plutus_verify/
│   ├── __main__.py               # CLI entrypoint (argparse / click)
│   ├── config.py                 # plutus-verify.yaml loader + defaults
│   ├── ingest.py                 # git clone, repo metadata capture
│   ├── extract/
│   │   ├── client.py             # OpenAI-compatible Gemma client wrapper
│   │   ├── prompt.py             # extraction prompt + JSON schema
│   │   └── plan.py               # ExtractedPlan dataclasses + validation
│   ├── build.py                  # repo2docker wrapper + secrets overlay
│   ├── execute.py                # Docker step runner
│   ├── compare/
│   │   ├── metrics.py            # locate kinds + tolerance engine
│   │   ├── charts.py             # cairosvg rasterization + vision client
│   │   └── rubric.py             # per-step verdict aggregation
│   ├── report/
│   │   ├── json_report.py
│   │   └── markdown_report.py
│   └── util/
│       ├── logging.py
│       └── hashing.py
├── tests/
│   ├── unit/
│   ├── integration/
│   │   ├── fixtures/
│   │   │   ├── gold-repo/        # minimal-compliant Plutus shape
│   │   │   └── broken-repo/      # missing chart / wrong metric / timeout
│   └── e2e/                      # nightly: real Gemma, real ProtoMarketMaker
└── docs/
    └── prompts/                  # versioned extraction + chart prompts
```

## Implementation phasing

Five milestones, each independently shippable.

**M1 — Plan extraction skeleton (1–2 days)**
`ingest` + `extract` + plan-only report. `plutus-verify <url> --extract-only` produces `plan.json` for ProtoMarketMaker; hand-verified against README.

**M2 — Build + execute (2–3 days)**
`build` (repo2docker wrapper + secrets overlay) + `execute` (Docker step runner). Pipeline runs ProtoMarketMaker end-to-end and captures artifacts; comparison stubbed.

**M3 — Numeric comparison + report (1–2 days)**
`compare.metrics` with all three `locate` kinds, tolerance engine, `report.md` + `report.json`, exit codes.

**M4 — Chart visual judgment (1–2 days)**
`compare.charts`: SVG→PNG rasterization, Gemma vision prompt, threshold, wired into report. `--no-charts` graceful-degrade flag.

**M5 — Batch mode + CI polish (1–2 days)**
`--batch repos.txt` with bounded concurrency, aggregate cross-repo report, GitHub Action wrapper.

## Testing strategy

Three tiers:

1. **Unit (no external deps)** — fixture-driven `extract` with stub LLM (~10 README fixtures: ProtoMarketMaker, ideal compliant, deliberately broken); table-driven `compare.metrics` with each tolerance kind; stub-vision `compare.charts` aggregation logic; rubric/exit-code matrix.
2. **Integration (real Docker, stub LLM)** — committed `gold-repo/` (deterministic Plutus-shaped fixture) and `broken-repo/` fixtures run through the full pipeline on real Docker; assert §Failure-mode catalog reactions.
3. **E2E (nightly)** — real Gemma + real ProtoMarketMaker; assert 9-Step Coverage *structure* against committed snapshot; tolerate metric drift.

## Critical files / external pieces to reuse

- **`repo2docker`** ([jupyterhub/repo2docker](https://github.com/jupyterhub/repo2docker)) — auto-builds Docker image from any repo; handles `requirements.txt`, `environment.yml`, `Pipfile`, `Dockerfile`, `apt.txt`. Saves us reimplementing env detection.
- **`cairosvg`** — SVG→PNG rasterization for vision judge input.
- **`jsonschema`** — `ExtractedPlan` schema validation.
- **OpenAI-compatible client (e.g., `openai` Python SDK)** — talk to Gemma's local endpoint (vLLM / TGI / llama.cpp server all expose OpenAI-compatible APIs).
- **`docker` Python SDK** — programmatic container runs with timeout/network/memory limits.

## Verification (how we'll know it works end-to-end)

1. Run `plutus-verify https://github.com/algotrade-plutus/ProtoMarketMaker --secrets ./secrets/proto-mm.env` with a Gemma endpoint reachable.
2. Inspect `out/<run_id>/plan.json` — confirm the 9-step mapping matches the README and `expected_results` captures all six in-sample metrics + optimized step + six OOS metrics + six chart references.
3. Inspect `out/<run_id>/report.md` — verdict should be ✅ reproduced (or ⚠️ partial if random-seed drift) and the 9-Step Coverage table should show ✅ for steps 1, 2, 4, 5, 6 and ⚠️ missing for step 3.
4. Tamper test: pin a wrong number in the README (e.g., Sharpe 9.9516), rerun — verify the metric flags as out-of-tolerance and the step downgrades to ⚠️ partial.
5. Repeat the run against a second compliant sample (e.g., `algotrade-research/InstiFund`) to confirm the extractor generalizes to a different README structure.
6. Run the unit + integration test suite: `pytest tests/unit tests/integration` should be green.
7. Optional: a dry batch run across the 16 sample projects' URLs as a final fleet-wide smoke test (`plutus-verify --batch sample-projects.txt`).

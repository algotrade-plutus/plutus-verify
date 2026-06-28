# Standard README template

The skeleton `plutus-document` fills to produce a Plutus-Reproducible `README.md`.
Placeholders are tagged: `{{G:...}}` = render from groundtruth (see
[`section-map.md`](section-map.md)); `{{N:...}}` = narrative (preserve / draft /
co-author). Remove every tag in the final output. Drop sections that don't apply
(e.g. no Optimization step → omit §5; renumber following sections only if the source
repo does). Charts/tables repeat per step.

Reference exemplar: `ProtoMarketMaker/README.md`.

---

````markdown
{{G:badges — PLUTUS-<score>% (from plutus-scoring) + type badge(s) (Sample/PROTO)}}
![Static Badge](https://img.shields.io/badge/PLUTUS-{{G:score}}%25-{{G:color}})
![Static Badge](https://img.shields.io/badge/PLUTUS-{{G:type}}-darkblue)

# {{N:Title}}
> {{N:one-line strategy summary}}

## Abstract

{{N:2–4 sentence plain-language summary of the strategy and how it works.}}

{{N:One sentence on data + period + standard:}} developed and evaluated end-to-end on
{{G:data source + period}} following the [9-step Development Process](https://www.algotrade.vn/knowledge/9-step-process/the-9-step)
and the [Plutus Reproducibility Standard](https://github.com/algotrade-plutus/plutus-guideline).
On the in-sample period it reaches {{G:headline IS metrics, e.g. Sharpe + HPR}}; on the
out-of-sample period it reaches {{G:headline OOS metrics}}. Every reported number is
reproducible in an isolated Docker container via `plutus-verify` against a committed
groundtruth baseline (see [Implementation & Reproducibility](#implementation--reproducibility)).

## Introduction

{{N:context, motivation, the idea, grounding reference(s).}}

## 1. Forming Algorithm Hypothesis

{{N:the hypothesis, with formulas where applicable.}}

## 2. Data Preparation

- **Source:** {{G:data_sources kind/provider}}.
- **Period:** {{G:IS/OOS date ranges}}.
- **Fees:** {{N:fee model if stated in source}}.

{{N:1–2 sentences on what is collected and where it lands (data/is, data/os, ...).}}

### Obtaining the data

**Option 1 — Download from Google Drive (no database credentials needed).**
Download from {{G:data_sources[].url}}. Place the `data/` folder at the repo root:

```
{{G:expected_layout rendered as a tree}}
```

**Option 2 — Collect from the source.** {{N:credentials note}} and run:

```bash
{{G:data step console command}}
```

## 3. Forming Set of Rules

{{N:the concrete trading rules derived from the hypothesis.}}

### Evaluation Metrics

The rules are evaluated with the following metrics, which are also the `expected`
values verified by `plutus check`:

{{G:bullet list of expected.metrics display_name (+ risk-free/benchmark note if in source)}}

## Implementation & Reproducibility

The pipeline is packaged as `{{G:package name}}` with console-script entry points
({{G:steps[].command list}}); each step below shows its own command.

### Environment setup

```bash
uv sync     # create the env from the committed uv.lock
```

{{N:one line on the lockfile / pinned deps.}} {{G:if secrets declared:}} To collect data
from the source, copy `.env.example` to `.env` and fill in:

```env
{{G:secrets[].key=<...> lines}}
```

### Reproducibility

This repo ships a `.plutus/manifest.yaml` declaring the environment, data sources,
steps, and expected metrics. Reproduce every result in an isolated Docker container
with [plutus-verify](https://github.com/algotrade-plutus/plutus-verify)
**{{G:pinned version}}**, installed from the public release wheel:

```bash
# Requires Docker running and Python >= 3.11
python -m venv .plutus-venv && source .plutus-venv/bin/activate
pip install "plutus-verify[runner] @ {{G:release wheel URL}}"

plutus check .     # build -> run each step in-container -> compare vs baseline
```

{{G:one paragraph on what [runner] brings + that check builds, resolves data, installs
the package (if install_project), runs each step, compares vs .plutus/expected/.}}
Exit code `0` = reproduced (within tolerance), `1` = partial, `2` = failed.

## 4. In-sample Backtesting

{{N:one line on parameters/config file}}, then run:

```bash
{{G:in_sample step command}}
```

Charts are written to {{G:in_sample artifact dir}}.

### In-sample result ({{G:IS period}})

| Metric | Value |
|--------|-------|
{{G:one row per expected.metrics display_name | value}}

{{G:for each expected.artifacts[].path:}}
{{N:chart caption}} — `{{G:path}}`
![{{N:alt}}]({{G:path}})

## 5. Optimization

{{N:search space / config + fixed seed note}}. Run:

```bash
{{G:optimization step command}}
```

The optimized parameters are written to {{G:param-file path}}. With seed
`{{N:seed}}`, the current optimum is:

```json
{{G:optimized params}}
```

## 6. Out-of-sample Backtesting

Using the optimized parameters from Step 5, evaluate on the out-of-sample period:

```bash
{{G:out_of_sample step command}}
```

### Out-of-sample result ({{G:OOS period}})

| Metric | Value |
|--------|-------|
{{G:one row per expected.metrics display_name | value}}

{{G:for each expected.artifacts[].path:}}
{{N:chart caption}} — `{{G:path}}`
![{{N:alt}}]({{G:path}})

## Reference

{{N:citations, [1] ... }}
````

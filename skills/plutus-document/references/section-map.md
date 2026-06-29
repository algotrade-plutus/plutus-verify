# Section map — groundtruth → standard README

The authoritative mapping `plutus-document` follows. Every **G** (groundtruth)
section is rendered deterministically from the listed source; every **N** (narrative)
section is preserved / drafted / co-authored. Reference structure: the Plutus
Reproducibility Standard, as exemplified by `ProtoMarketMaker/README.md`.

## Section table

| README section | Kind | Source (exact) |
|---|---|---|
| Badges line (`PLUTUS-<score>%`, type) | G | score ← `plutus-scoring` result; type badges (`Sample`/`PROTO`) ← decision/config (see §Badges below) |
| `# <Title>` + `> <tagline>` | N | existing README title / repo name + one-line strategy summary |
| `## Abstract` | G+N | narrative summary **+** headline IS/OOS metrics from `expected.metrics` **+** the reproducibility claim (pinned `plutus-verify` version) |
| `## Introduction` | N | existing prose / module docstrings / co-author |
| `## 1. Forming Algorithm Hypothesis` | N | existing prose / code / co-author (include formulas) |
| `## 2. Data Preparation` | G | `data_sources` (kind, url, expected_layout, satisfies) → Source / Period / Fees + "Obtaining the data" (Drive option with the `expected_layout` rendered as a data tree; DB/collect option with the data step's console command) |
| `## 3. Forming Set of Rules` | N | rules prose / code / co-author |
| `### Evaluation Metrics` (under §3) | G | the metric list ← `expected.metrics[].display_name` (+ the 6%/risk-free note if present in source) |
| `## Implementation & Reproducibility` | G | package + console scripts ← each `steps[].command`; `### Environment setup` ← `env` (uv: `uv sync`); `.env` block ← `secrets[].key`; `### Reproducibility` ← the `plutus check` block with the pinned `plutus-verify` release-wheel URL |
| `## 4. In-sample Backtesting` | G | the `step_4_in_sample` step's `command` + its `expected.metrics` table + its `expected.artifacts` chart embeds |
| `## 5. Optimization` | G | the `step_5_optimization` step's `command` + optimized params (from the declared param-file output) + the seed (from source) |
| `## 6. Out-of-sample Backtesting` | G | the `step_6_out_of_sample` step's `command` + its `expected.metrics` table + its `expected.artifacts` chart embeds |
| `## Reference` | N | existing citations |

## nine_step → heading bridge

A manifest step's `nine_step` selects its README section:

- `step_2_data_preparation` → `## 2. Data Preparation`
- `step_4_in_sample` → `## 4. In-sample Backtesting`
- `step_5_optimization` → `## 5. Optimization`
- `step_6_out_of_sample` → `## 6. Out-of-sample Backtesting`

Steps with `nine_step: null` (free-form) render under their own `## <label>` heading
after the mapped sections, using the same G shape (command + any `expected.metrics`
table + `expected.artifacts` embeds).

## Micro-decisions (binding)

1. **Metric tables render from `expected.metrics` only** — value + `display_name`,
   for each step's `expected` block. This guarantees every table equals exactly what
   `plutus check` verifies. Do **not** pull numbers from the ephemeral
   `.plutus/run/<step>/results.json`. Extra display-only metrics (e.g. "Monthly
   return") that aren't in `expected` are opt-in *narrative*, never auto-rendered as
   verified facts.
2. **Charts embed from their `result/…` working-tree paths** — i.e. the
   `expected.artifacts[].path` value verbatim (what the README links and what
   `snapshot` writes into the working tree in 0.5.0). Render as
   `![<alt>](<path>)` with a short caption line above.
3. **Non-score badges come from a small decision/config**, not groundtruth: the
   project type (`Sample` / `PROTO` / …) is asked once or read from a config note;
   only the `PLUTUS-<score>%` badge is data-driven (from `plutus-scoring`).

## Badges

- `![Static Badge](https://img.shields.io/badge/PLUTUS-<score>%25-<color>)` — score
  from `plutus-scoring` (rounded to 5%); color by band (≥75 → darkgreen,
  50–74 → olive, else → grey). When run standalone without a score, leave the prior badge
  or ask.
- Type badges (`PLUTUS-Sample`, `PLUTUS-PROTO`, …) — preserved from the existing
  README if present, else set from the project-type decision/config.
- **Reference-only caveat (required).** Immediately below the badge row, render the
  `<sub>…</sub>` caveat line from the template verbatim: the score is an LLM-assessed
  *reference signal*, not a certified quality grade, and is subject to change; the only
  verified guarantee is reproducibility (`plutus check` exits 0). Keep this line even
  when the badge is left unchanged in a standalone run — it must never be dropped.

## Consistency guarantee

Because every G-section reads committed groundtruth (`manifest` + declared artifact
paths + pinned wheel), the rendered README is consistent with `plutus check` by
construction. N-sections carry author intent, not verified facts.

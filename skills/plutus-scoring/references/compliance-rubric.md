# Compliance rubric

The 50/25/10/15 scoring model the `plutus-scoring` Skill applies in
its Score phase. Score is rounded to the nearest 5%. The same rubric
is invoked automatically by `plutus-transform` as the final hand-off
step after a clean transform.

> Source: [docs/others/zbounce-v1-to-v2-upgrade.md](../../../docs/others/zbounce-v1-to-v2-upgrade.md) §7.

## Buckets

| Bucket                  | Weight | What it measures |
|-------------------------|--------|------------------|
| Reproducible            | 50%    | `plutus check` exits 0; README-claimed metrics match script output within declared tolerance |
| Tidy / well-documented  | 25%    | README structure, install hygiene, no `<placeholder>` parse traps, code-hygiene patterns, docs match reality |
| Standardized / template | 10%    | Follows canonical PLUTUS shape (7 nine-steps, predictable file paths, externalized parameters); could serve as a template |
| Innovative              | 15%    | New metrics, novel diagnostics, regime-tagged analytics, or strategy logic that's not textbook |

## Bucket-by-bucket scoring guide

### Reproducible (50)
- **50** — `plutus check` exits 0 cleanly; no workarounds applied; all required metrics inside tolerance.
- **45** — `plutus check` exits 0 but only after manifest-side workarounds (network/secret routing, snapshot seeding, etc.). Architectural smells were papered over, not fixed at source.
- **35** — `plutus check` exits 0 only after touching `requirements.txt` or other tracked config.
- **20** — Metrics match individually on host but `plutus check` cannot be made green within the session.
- **0** — Scripts don't produce the claimed metrics within tolerance.

### Tidy / well-documented (25)
Score against this checklist (~5 points each):
- README structure clean, metric tables present and consistent
- `.env.example` parses with `source .env` (no unquoted `<placeholder>` lines)
- All data inputs documented (no surprise dependencies like a missing F2M leg)
- Optimization / parameter pipeline accurately described (script behavior matches docs)
- Has `.python-version` or equivalent pin, plus CI workflow

### Standardized / template (10)
- **10** — Canonical 4-step shape (`data_preparation` → `in_sample_backtest` → `optimization` → `out_of_sample_backtest`), parameters externalized to `parameter/*.json`, charts in predictable `result/{backtest,optimization}/` paths, no module-level side effects.
- **5** — Most of the above but one significant deviation (e.g., DB-at-import anti-pattern, divergent paper-trading script shape).
- **0** — Could not serve as a template without significant rework.

### Innovative (15)
- **15** — Novel metrics (regime-tagged P&L, ADX-conditional return histograms, custom drawdown decomposition), novel diagnostics, or non-textbook strategy logic.
- **8** — Thoughtful strategy logic (regime-switching, opposite-extreme exits) but conventional analytical surface (standard Sharpe/Sortino/MDD/HPR + standard charts).
- **0** — Textbook backtest with no original instrumentation or analysis.

## Output format

The Skill emits, in order:
1. **Per-bucket score with one-line reasoning.** "Reproducible: 45/50 — `plutus check` green after manifest-side workarounds for module-level DB connection."
2. **Total**, rounded to 5%.
3. **"Cheapest paths to push the score higher"** — concrete, ranked suggestions (≤4 items).

When the Skill is invoked as a chain from `plutus-transform`, item 4 also fires:

4. **"Architectural smells we worked around but didn't fix"** — pointers for a separate maintainer-side PR. Detection only; never silent fix. Sourced from the transform skill's Phase 4.5 summary; not applicable to standalone scoring invocations.

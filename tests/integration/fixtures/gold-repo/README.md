# Gold Repo

## Abstract
A deterministic mini-Plutus repo used as the verifier's integration test fixture.

## Hypothesis
Toy strategy: always print the same metrics.

## Data
### Data Collection
Synthetic, generated at runtime.

## Implementation
```bash
python backtesting.py
python optimization.py
python evaluation.py
```

## In-sample Backtesting

| Metric         | Value  |
|----------------|--------|
| Sharpe Ratio   | 1.2345 |
| Max Drawdown   | -0.1500 |

## Optimization

Optimized parameter saved to `parameter/optimized_parameter.json`.

| Metric | Value |
|--------|-------|
| step   | 2.5   |

## Out-of-sample Backtesting

| Metric         | Value  |
|----------------|--------|
| Sharpe Ratio   | 0.6000 |
| Max Drawdown   | -0.2500 |

## Reference
n/a

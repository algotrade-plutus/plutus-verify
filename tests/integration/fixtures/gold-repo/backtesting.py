"""Deterministic in-sample script: prints metric table and writes a chart."""
from pathlib import Path

print("| Metric         | Value   |")
print("| Sharpe Ratio   | 1.2340  |")
print("| Max Drawdown   | -0.1495 |")

result = Path("result/backtest")
result.mkdir(parents=True, exist_ok=True)
(result / "hpr.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
    '<polyline points="0,80 50,40 100,60 150,20 200,30" stroke="black" fill="none"/>'
    "</svg>"
)

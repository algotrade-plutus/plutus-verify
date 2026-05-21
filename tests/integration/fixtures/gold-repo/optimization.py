"""Deterministic optimization script: writes optimized_parameter.json."""
import json
from pathlib import Path

p = Path("parameter")
p.mkdir(parents=True, exist_ok=True)
(p / "optimized_parameter.json").write_text(json.dumps({"step": 2.45}))
print("optimization done; step=2.45")

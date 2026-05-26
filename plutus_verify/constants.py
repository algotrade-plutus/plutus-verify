"""Cross-package constants. Single source of truth for values that previously
lived in multiple modules and risked drifting."""
from __future__ import annotations

NINE_STEP_KEYS: tuple[str, ...] = (
    "step_1_hypothesis",
    "step_2_data_collection",
    "step_3_data_processing",
    "step_4_in_sample",
    "step_5_optimization",
    "step_6_out_of_sample",
    "step_7_paper_trading",
)


__all__ = ["NINE_STEP_KEYS"]

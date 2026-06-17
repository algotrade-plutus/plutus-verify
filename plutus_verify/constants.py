"""Cross-package constants. Single source of truth for values that previously
lived in multiple modules and risked drifting."""
from __future__ import annotations

# The v2025 PLUTUS process taxonomy. Step 2 ("Data Preparation") merges the old
# Data Collection + Data Processing; step 3 is now "Forming Set of Rules". Steps
# 1 and 4-7 are unchanged. This is the taxonomy the v2 manifest/results contracts
# speak. The legacy LLM-extraction path is frozen on LEGACY_NINE_STEP_KEYS below.
NINE_STEP_KEYS: tuple[str, ...] = (
    "step_1_hypothesis",
    "step_2_data_preparation",
    "step_3_forming_set_of_rules",
    "step_4_in_sample",
    "step_5_optimization",
    "step_6_out_of_sample",
    "step_7_paper_trading",
)

# The v2023 taxonomy. Frozen here for the (no-longer-developed) LLM-extraction
# path, which is decoupled from the live NINE_STEP_KEYS so the two subsystems can
# evolve independently. Do not use for the v2 manifest contract.
LEGACY_NINE_STEP_KEYS: tuple[str, ...] = (
    "step_1_hypothesis",
    "step_2_data_collection",
    "step_3_data_processing",
    "step_4_in_sample",
    "step_5_optimization",
    "step_6_out_of_sample",
    "step_7_paper_trading",
)


__all__ = ["NINE_STEP_KEYS", "LEGACY_NINE_STEP_KEYS"]

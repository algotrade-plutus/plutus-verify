"""Tests for the deterministic stitcher (Iteration 4).

The stitcher takes per-call element dicts and assembles a canonical
``ExtractedPlan``. No LLM involved — these tests are pure data tests.
"""
from __future__ import annotations

import pytest

from plutus_verify.extract.plan import NINE_STEP_KEYS, PlanValidationError
from plutus_verify.extract.stitch import assemble_plan_dict, stitch


def _good_repo() -> dict:
    return {
        "name": "Demo",
        "primary_language": "python",
        "env_setup": {
            "kind": "requirements_txt",
            "path": "requirements.txt",
            "python_version": "3.11",
        },
        "secrets_required": [
            {"key": "DB_NAME", "purpose": "postgres database name"},
        ],
    }


def _all_present_nine_step() -> dict:
    return {
        k: {"present": True, "section_heading": k.replace("_", " ")}
        for k in NINE_STEP_KEYS
    }


def _good_data_step() -> dict:
    return {
        "id": "data_collection",
        "nine_step": "step_2_data_collection",
        "required": True,
        "verification_mode": "execute",
        "command": None,
        "network": "bridge",
        "config_files": [],
        "produces": ["data/is/", "data/os/"],
        "alternatives": [
            {
                "label": "google_drive",
                "kind": "manual_download",
                "url": "https://drive.google.com/abc",
            },
            {
                "label": "db_loader",
                "kind": "command",
                "command": "python data_loader.py",
                "needs_secrets": ["DB_NAME"],
                "network": "bridge",
                "timeout_seconds": 1800,
            },
        ],
    }


def _good_in_sample_step() -> dict:
    return {
        "id": "in_sample_backtest",
        "nine_step": "step_4_in_sample",
        "required": True,
        "verification_mode": "execute",
        "command": "python backtesting.py",
        "network": "none",
        "config_files": [],
        "produces": ["result/backtest/hpr.svg"],
        "alternatives": [],
    }


def _good_results_entry(step_id: str = "in_sample_backtest") -> dict:
    return {
        "step_id": step_id,
        "metrics": [
            {
                "name": "Sharpe Ratio",
                "value": 0.9516,
                "locate": {"kind": "stdout_table", "row": "Sharpe Ratio", "col": 1},
                "tolerance": {"kind": "relative", "value": 0.05},
            }
        ],
        "charts": [],
    }


# ---------- Happy path ----------


def test_stitch_assembles_valid_extracted_plan():
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_data_step(), _good_in_sample_step()],
        results=[_good_results_entry()],
    )
    assert plan.schema_version == "1.0"
    assert plan.repo.name == "Demo"
    assert len(plan.steps) == 2
    assert plan.expected_results[0].metrics[0].value == 0.9516


# ---------- depends_on derivation ----------


def test_data_collection_has_empty_depends_on():
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_data_step(), _good_in_sample_step()],
        results=[],
    )
    data_step = next(s for s in plan.steps if s.id == "data_collection")
    assert data_step.depends_on == ()


def test_in_sample_step_depends_on_data_collection():
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_data_step(), _good_in_sample_step()],
        results=[],
    )
    in_sample = next(s for s in plan.steps if s.id == "in_sample_backtest")
    assert in_sample.depends_on == ("data_collection",)


def test_llm_supplied_depends_on_is_discarded():
    """If the LLM emits depends_on we ignore it — Python owns this field."""
    in_sample = _good_in_sample_step()
    in_sample["depends_on"] = ["completely_made_up_step_id"]
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_data_step(), in_sample],
        results=[],
    )
    in_sample_built = next(s for s in plan.steps if s.id == "in_sample_backtest")
    assert in_sample_built.depends_on == ("data_collection",)


def test_in_sample_has_empty_depends_on_when_no_data_collection():
    """Without a data_collection step, downstream steps have no depends_on."""
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_in_sample_step()],
        results=[],
    )
    in_sample = plan.steps[0]
    assert in_sample.depends_on == ()


# ---------- secrets cross-linking ----------


def test_secrets_required_step_ids_cross_linked_from_alternatives():
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_data_step(), _good_in_sample_step()],
        results=[],
    )
    db_name = next(s for s in plan.repo.secrets_required if s.key == "DB_NAME")
    assert db_name.step_ids == ("data_collection",)


def test_secrets_required_accepts_bare_strings():
    """LLM slip: secrets as bare strings instead of objects. Stitcher wraps them."""
    repo = _good_repo()
    repo["secrets_required"] = ["DB_USER", "DB_PASSWORD"]
    plan = stitch(
        repo=repo,
        nine_step=_all_present_nine_step(),
        steps=[],
        results=[],
    )
    keys = {s.key for s in plan.repo.secrets_required}
    assert keys == {"DB_USER", "DB_PASSWORD"}


def test_secret_with_no_step_referencing_it_gets_empty_step_ids():
    repo = _good_repo()
    repo["secrets_required"] = [{"key": "UNUSED_SECRET", "purpose": "x"}]
    plan = stitch(
        repo=repo,
        nine_step=_all_present_nine_step(),
        steps=[_good_in_sample_step()],
        results=[],
    )
    assert plan.repo.secrets_required[0].key == "UNUSED_SECRET"
    assert plan.repo.secrets_required[0].step_ids == ()


# ---------- nine_step_mapping enrichment ----------


def test_nine_step_mapping_fills_missing_keys_as_absent():
    partial = {
        "step_1_hypothesis": {"present": True, "section_heading": "Hypothesis"},
        "step_4_in_sample": {"present": True, "section_heading": "In-sample"},
    }
    plan = stitch(
        repo=_good_repo(),
        nine_step=partial,
        steps=[],
        results=[],
    )
    assert plan.nine_step_mapping["step_7_paper_trading"].present is False
    assert plan.nine_step_mapping["step_7_paper_trading"].confidence == 0.0
    assert plan.nine_step_mapping["step_1_hypothesis"].present is True
    assert plan.nine_step_mapping["step_1_hypothesis"].confidence == 1.0


def test_nine_step_mapping_ignores_llm_confidence():
    """LLM's self-reported confidence is unreliable; stitcher overwrites it."""
    mapping = {
        k: {"present": True, "section_heading": k, "confidence": 0.123}
        for k in NINE_STEP_KEYS
    }
    plan = stitch(
        repo=_good_repo(),
        nine_step=mapping,
        steps=[],
        results=[],
    )
    for k in NINE_STEP_KEYS:
        assert plan.nine_step_mapping[k].confidence == 1.0


# ---------- additional_steps (Call 5 stub path) ----------


def test_additional_steps_are_appended_to_steps_list():
    additional = [
        {
            "id": "train_lstm",
            "nine_step": "step_3_data_processing",  # ML training maps closest here
            "required": True,
            "verification_mode": "execute",
            "command": "python train.py",
            "network": "none",
            "config_files": [],
            "produces": ["models/lstm.pt"],
            "alternatives": [],
        }
    ]
    plan = stitch(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_data_step()],
        results=[],
        additional_steps=additional,
    )
    ids = [s.id for s in plan.steps]
    assert "train_lstm" in ids
    train_step = next(s for s in plan.steps if s.id == "train_lstm")
    assert train_step.depends_on == ("data_collection",)


# ---------- Schema enforcement ----------


def test_stitch_raises_when_result_refers_to_unknown_step():
    """parse_plan rejects expected_results pointing to a step id that doesn't exist."""
    with pytest.raises(PlanValidationError):
        stitch(
            repo=_good_repo(),
            nine_step=_all_present_nine_step(),
            steps=[_good_in_sample_step()],
            results=[_good_results_entry(step_id="ghost_step")],
        )


def test_assemble_plan_dict_returns_canonical_shape_without_validation():
    """assemble_plan_dict produces a dict suitable for parse_plan — but does NOT call it."""
    out = assemble_plan_dict(
        repo=_good_repo(),
        nine_step=_all_present_nine_step(),
        steps=[_good_in_sample_step()],
        results=[],
    )
    assert out["schema_version"] == "1.0"
    assert "extraction_notes" in out
    assert out["steps"][0]["depends_on"] == []  # no data_collection so empty

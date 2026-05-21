"""Tests for v2 input/output preflight."""
from pathlib import Path

import pytest

from plutus_verify.spec.manifest import Step
from plutus_verify.spec.runtime.preflight import (
    PreflightError,
    assert_inputs_present,
    assert_outputs_present,
)


def _step(inputs=(), outputs=()) -> Step:
    return Step(
        id="s1",
        nine_step="step_4_in_sample",
        required=True,
        command="echo x",
        inputs=inputs,
        outputs=outputs,
    )


def test_inputs_present_passes_when_all_exist(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.parquet").write_text("ok")
    s = _step(inputs=("data",))
    assert_inputs_present(s, tmp_path)  # no raise


def test_inputs_glob_passes_when_at_least_one_match(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.parquet").write_text("ok")
    s = _step(inputs=("data/*.parquet",))
    assert_inputs_present(s, tmp_path)


def test_inputs_raises_when_missing(tmp_path):
    s = _step(inputs=("data/x.parquet",))
    with pytest.raises(PreflightError, match="missing input"):
        assert_inputs_present(s, tmp_path)


def test_outputs_present_passes_when_all_exist(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "m.json").write_text("{}")
    s = _step(outputs=("out/m.json",))
    assert_outputs_present(s, tmp_path)


def test_outputs_glob_passes_when_at_least_one_match(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "a.png").write_text("x")
    (tmp_path / "out" / "b.png").write_text("y")
    s = _step(outputs=("out/*.png",))
    assert_outputs_present(s, tmp_path)


def test_outputs_raises_when_missing_after_run(tmp_path):
    s = _step(outputs=("out/m.json",))
    with pytest.raises(PreflightError, match="missing output"):
        assert_outputs_present(s, tmp_path)


def test_empty_inputs_and_outputs_pass(tmp_path):
    s = _step()
    assert_inputs_present(s, tmp_path)
    assert_outputs_present(s, tmp_path)

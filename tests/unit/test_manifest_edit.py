"""Tests for `plutus_verify.scaffold.manifest_edit.update_metric_values`."""
from __future__ import annotations

from pathlib import Path

import pytest

from plutus_verify.scaffold.manifest_edit import (
    ManifestEditError,
    update_metric_values,
)


MANIFEST_WITH_COMMENTS = """\
# Hand-cleaned manifest
# Author: dan

version: 2
identity:
  name: demo

# Steps section
steps:
  - id: in_sample
    type: backtest

expected:
  - step_id: in_sample
    # ExpectedMetrics for in-sample run
    metrics:
      - name: sharpe_ratio
        display_name: Sharpe Ratio
        value: 1.23
        tolerance: 0.05
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "manifest.yaml"
    p.write_text(text)
    return p


def test_round_trip_preserves_comments_and_blank_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, MANIFEST_WITH_COMMENTS)

    count, warnings = update_metric_values(
        path, {"in_sample": {"sharpe_ratio": 0.99}}
    )

    assert count == 1
    assert warnings == []
    text = path.read_text()
    assert "# Hand-cleaned manifest" in text
    assert "# Author: dan" in text
    assert "# Steps section" in text
    assert "# ExpectedMetrics for in-sample run" in text
    # blank lines preserved
    assert "\n\nversion: 2" in text or "\n\nidentity:" in text
    # new value present, old value gone
    assert "0.99" in text
    assert "1.23" not in text


def test_overwrites_value_only(tmp_path: Path) -> None:
    manifest = """\
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        display_name: Sharpe Ratio
        value: 1.23
        tolerance: 0.05
      - name: max_drawdown
        display_name: Max Drawdown
        value: -0.15
        tolerance: 0.1
"""
    path = _write(tmp_path, manifest)
    count, warnings = update_metric_values(
        path, {"in_sample": {"sharpe_ratio": 2.5}}
    )
    assert count == 1
    assert warnings == []
    text = path.read_text()
    # sharpe updated
    assert "value: 2.5" in text
    # max_drawdown untouched
    assert "value: -0.15" in text
    # other fields untouched
    assert "display_name: Sharpe Ratio" in text
    assert "display_name: Max Drawdown" in text
    assert "tolerance: 0.05" in text
    assert "tolerance: 0.1" in text
    assert "name: sharpe_ratio" in text
    assert "name: max_drawdown" in text


def test_unknown_step_id_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, MANIFEST_WITH_COMMENTS)
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    count, warnings = update_metric_values(
        path, {"out_of_sample": {"sharpe_ratio": 0.5}}
    )

    assert count == 0
    assert len(warnings) == 1
    assert "out_of_sample" in warnings[0]
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_unknown_metric_name_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, MANIFEST_WITH_COMMENTS)
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    count, warnings = update_metric_values(
        path, {"in_sample": {"sortino_ratio": 1.3}}
    )

    assert count == 0
    assert len(warnings) == 1
    assert "sortino_ratio" in warnings[0]
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_empty_updates_is_noop(tmp_path: Path) -> None:
    path = _write(tmp_path, MANIFEST_WITH_COMMENTS)
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    count, warnings = update_metric_values(path, {})

    assert count == 0
    assert warnings == []
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_empty_per_step_dict_is_skipped(tmp_path: Path) -> None:
    path = _write(tmp_path, MANIFEST_WITH_COMMENTS)

    count, warnings = update_metric_values(path, {"in_sample": {}})

    assert count == 0
    assert warnings == []


def test_raises_on_missing_expected_key(tmp_path: Path) -> None:
    manifest = """\
version: 2
identity:
  name: demo
"""
    path = _write(tmp_path, manifest)

    with pytest.raises(ManifestEditError) as exc_info:
        update_metric_values(path, {"in_sample": {"sharpe_ratio": 1.0}})

    assert "expected" in str(exc_info.value)


def test_raises_on_invalid_yaml(tmp_path: Path) -> None:
    path = _write(tmp_path, "not: valid: yaml: [")

    with pytest.raises(ManifestEditError) as exc_info:
        update_metric_values(path, {"in_sample": {"sharpe_ratio": 1.0}})

    assert "could not parse" in str(exc_info.value)


def test_raises_on_unreadable_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.yaml"

    with pytest.raises(ManifestEditError):
        update_metric_values(missing, {"in_sample": {"sharpe_ratio": 1.0}})


def test_value_is_float_in_yaml_output(tmp_path: Path) -> None:
    path = _write(tmp_path, MANIFEST_WITH_COMMENTS)

    count, _ = update_metric_values(
        path, {"in_sample": {"sharpe_ratio": 0.123456789}}
    )

    assert count == 1
    text = path.read_text()
    assert "value: 0.123456789" in text


def test_does_not_touch_other_blocks(tmp_path: Path) -> None:
    manifest = """\
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        display_name: Sharpe Ratio
        value: 1.0
        tolerance: 0.05
  - step_id: out_of_sample
    metrics:
      - name: sharpe_ratio
        display_name: Sharpe Ratio (OOS)
        value: 0.8
        tolerance: 0.05
"""
    path = _write(tmp_path, manifest)
    count, warnings = update_metric_values(
        path, {"in_sample": {"sharpe_ratio": 1.5}}
    )

    assert count == 1
    assert warnings == []
    text = path.read_text()
    # out_of_sample block intact
    assert "step_id: out_of_sample" in text
    assert "display_name: Sharpe Ratio (OOS)" in text
    assert "value: 0.8" in text
    assert "tolerance: 0.05" in text
    # in_sample updated
    assert "value: 1.5" in text


def test_count_reflects_actual_updates(tmp_path: Path) -> None:
    manifest = """\
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe_ratio
        display_name: Sharpe Ratio
        value: 1.0
        tolerance: 0.05
      - name: max_drawdown
        display_name: Max Drawdown
        value: -0.1
        tolerance: 0.05
  - step_id: out_of_sample
    metrics:
      - name: sharpe_ratio
        display_name: Sharpe Ratio (OOS)
        value: 0.8
        tolerance: 0.05
"""
    path = _write(tmp_path, manifest)
    count, warnings = update_metric_values(
        path,
        {
            "in_sample": {"sharpe_ratio": 1.5, "max_drawdown": -0.2},
            "out_of_sample": {"sharpe_ratio": 0.9},
        },
    )

    assert count == 3
    assert warnings == []

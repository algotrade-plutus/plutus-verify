"""Tests for v2 reference-output comparators."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.manifest import ReferenceOutput
from plutus_verify.spec.runtime.refcompare import (
    CompareResult,
    compare_reference_output,
)


def test_byte_exact_pass(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("hello")
    ref = ReferenceOutput(path="a", compare="byte_exact")
    r = compare_reference_output(ref, expected_path=a, produced_path=b, vision_client=None)
    assert r.ok and r.kind == "byte_exact"


def test_byte_exact_fail(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("world")
    ref = ReferenceOutput(path="a", compare="byte_exact")
    r = compare_reference_output(ref, expected_path=a, produced_path=b, vision_client=None)
    assert not r.ok
    assert "bytes differ" in r.detail


def test_json_numeric_tolerance_pass_within_tolerance(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"sharpe": 0.85, "n_trades": 100}))
    prod.write_text(json.dumps({"sharpe": 0.86, "n_trades": 100}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok


def test_json_numeric_tolerance_fail_outside_tolerance(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"sharpe": 0.85}))
    prod.write_text(json.dumps({"sharpe": 1.20}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert not r.ok
    assert "sharpe" in r.detail


def test_json_numeric_tolerance_handles_nested(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"outer": {"inner": 1.0}}))
    prod.write_text(json.dumps({"outer": {"inner": 1.04}}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok


def test_json_numeric_tolerance_byte_equal_strings(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"name": "foo"}))
    prod.write_text(json.dumps({"name": "bar"}))
    ref = ReferenceOutput(path="p.json", compare="json_numeric_tolerance")
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert not r.ok
    assert "name" in r.detail


def test_visual_similarity_calls_vision_client(tmp_path: Path):
    exp = tmp_path / "e.png"
    prod = tmp_path / "p.png"
    exp.write_bytes(b"\x89PNG\r\n\x1a\n")
    prod.write_bytes(b"\x89PNG\r\n\x1a\n")
    vc = MagicMock()
    vc.match.return_value = MagicMock(score=0.85, match=True, reason="similar")
    ref = ReferenceOutput(path="p.png", compare="visual_similarity", threshold=0.7)
    r = compare_reference_output(ref, expected_path=exp, produced_path=prod, vision_client=vc)
    assert r.ok
    vc.match.assert_called_once()


def test_missing_files_fail_gracefully(tmp_path: Path):
    ref = ReferenceOutput(path="ghost.json", compare="byte_exact")
    r = compare_reference_output(
        ref, expected_path=tmp_path / "ghost.json", produced_path=tmp_path / "ghost.json", vision_client=None
    )
    assert not r.ok
    assert "not found" in r.detail

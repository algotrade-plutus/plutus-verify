"""Tests for v2 artifact comparators."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.manifest import Artifact
from plutus_verify.spec.runtime.artifact_compare import (
    CompareResult,
    compare_artifact,
)


def test_byte_exact_pass(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("hello")
    ref = Artifact(path="a", compare="byte_exact")
    r = compare_artifact(ref, expected_path=a, produced_path=b, vision_client=None)
    assert r.ok and r.kind == "byte_exact"


def test_byte_exact_fail(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("hello")
    b.write_text("world")
    ref = Artifact(path="a", compare="byte_exact")
    r = compare_artifact(ref, expected_path=a, produced_path=b, vision_client=None)
    assert not r.ok
    assert "bytes differ" in r.detail


def test_json_numeric_tolerance_pass_within_tolerance(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"sharpe": 0.85, "n_trades": 100}))
    prod.write_text(json.dumps({"sharpe": 0.86, "n_trades": 100}))
    ref = Artifact(path="p.json", compare="json_numeric_tolerance")
    r = compare_artifact(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok


def test_json_numeric_tolerance_fail_outside_tolerance(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"sharpe": 0.85}))
    prod.write_text(json.dumps({"sharpe": 1.20}))
    ref = Artifact(path="p.json", compare="json_numeric_tolerance")
    r = compare_artifact(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert not r.ok
    assert "sharpe" in r.detail


def test_json_numeric_tolerance_handles_nested(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"outer": {"inner": 1.0}}))
    prod.write_text(json.dumps({"outer": {"inner": 1.04}}))
    ref = Artifact(path="p.json", compare="json_numeric_tolerance")
    r = compare_artifact(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok


def test_json_numeric_tolerance_byte_equal_strings(tmp_path: Path):
    exp = tmp_path / "e.json"
    prod = tmp_path / "p.json"
    exp.write_text(json.dumps({"name": "foo"}))
    prod.write_text(json.dumps({"name": "bar"}))
    ref = Artifact(path="p.json", compare="json_numeric_tolerance")
    r = compare_artifact(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert not r.ok
    assert "name" in r.detail


def test_visual_similarity_calls_vision_client(tmp_path: Path):
    exp = tmp_path / "e.png"
    prod = tmp_path / "p.png"
    exp.write_bytes(b"\x89PNG\r\n\x1a\n")
    prod.write_bytes(b"\x89PNG\r\n\x1a\n")
    vc = MagicMock()
    vc.match.return_value = MagicMock(score=0.85, match=True, reason="similar")
    ref = Artifact(path="p.png", compare="visual_similarity", threshold=0.7)
    r = compare_artifact(ref, expected_path=exp, produced_path=prod, vision_client=vc)
    assert r.ok
    vc.match.assert_called_once()


def test_missing_files_fail_gracefully(tmp_path: Path):
    ref = Artifact(path="ghost.json", compare="byte_exact")
    r = compare_artifact(
        ref, expected_path=tmp_path / "ghost.json", produced_path=tmp_path / "ghost.json", vision_client=None
    )
    assert not r.ok
    assert "not found" in r.detail


def test_visual_similarity_missing_expected_returns_skip(tmp_path: Path):
    # Missing snapshot reference is symmetric to missing vision client:
    # a non-blocking skip, not a hard failure.
    prod = tmp_path / "p.png"
    prod.write_bytes(b"\x89PNG\r\n\x1a\n")
    ref = Artifact(path="p.png", compare="visual_similarity")
    r = compare_artifact(
        ref,
        expected_path=tmp_path / "missing.png",
        produced_path=prod,
        vision_client=MagicMock(),
    )
    assert r.ok is True
    assert r.skipped is True
    assert "plutus snapshot" in r.detail


def test_visual_similarity_missing_produced_fails(tmp_path: Path):
    # Missing produced file is a real failure — the script didn't run
    # or didn't write its declared output. Not a skip.
    exp = tmp_path / "e.png"
    exp.write_bytes(b"\x89PNG\r\n\x1a\n")
    ref = Artifact(path="p.png", compare="visual_similarity")
    r = compare_artifact(
        ref,
        expected_path=exp,
        produced_path=tmp_path / "missing.png",
        vision_client=MagicMock(),
    )
    assert r.ok is False
    assert r.skipped is False
    assert "produced file not found" in r.detail


def test_visual_similarity_missing_vision_client_returns_skip(tmp_path: Path):
    exp = tmp_path / "e.png"
    prod = tmp_path / "p.png"
    exp.write_bytes(b"\x89PNG\r\n\x1a\n")
    prod.write_bytes(b"\x89PNG\r\n\x1a\n")
    ref = Artifact(path="p.png", compare="visual_similarity")
    r = compare_artifact(ref, expected_path=exp, produced_path=prod, vision_client=None)
    assert r.ok is True
    assert r.skipped is True
    assert "--visual-check" in r.detail


def test_compare_artifact_populates_path(tmp_path: Path):
    # Every CompareResult must carry the artifact's repo-relative path
    # so the renderer can name it without re-walking the manifest.
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("x")
    b.write_text("x")
    ref = Artifact(path="result/backtest/hpr.svg", compare="byte_exact")
    r = compare_artifact(ref, expected_path=a, produced_path=b, vision_client=None)
    assert r.path == "result/backtest/hpr.svg"

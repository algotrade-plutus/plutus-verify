"""Tests for compare.charts: aggregation logic with a stub vision client."""
import json
from pathlib import Path

import pytest

from plutus_verify.compare.charts import (
    VisionClient,
    compare_charts,
)
from plutus_verify.extract.plan import ExpectedChart


class _ScriptedVision(VisionClient):
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses  # keyed by chart name
        self.calls: list[tuple[str, bytes, bytes | None]] = []

    def judge_chart(
        self, *, chart_name: str, produced_png: bytes, reference_png: bytes | None
    ) -> str:
        self.calls.append((chart_name, produced_png, reference_png))
        return self._responses[chart_name]


def _judge(verdict: str, conf: float = 0.85) -> str:
    return json.dumps(
        {
            "shape_match": {"verdict": verdict, "reason": ""},
            "scale_match": {"verdict": verdict, "reason": ""},
            "structure_match": {"verdict": verdict, "reason": ""},
            "overall": {"verdict": verdict, "confidence": conf},
        }
    )


_VALID_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
    '<rect width="200" height="100" fill="white"/>'
    '<polyline points="0,80 50,40 100,60 150,20 200,30" stroke="black" fill="none"/>'
    "</svg>"
)


def _write_dummy_svg(p: Path, body: str = _VALID_SVG) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_compare_charts_returns_match_verdict_when_vision_says_match(tmp_path: Path):
    _write_dummy_svg(tmp_path / "result" / "hpr.svg")
    _write_dummy_svg(tmp_path / "ref" / "hpr.svg")
    expected = [
        ExpectedChart(
            name="hpr",
            produced_path="result/hpr.svg",
            reference_image="ref/hpr.svg",
        )
    ]
    vision = _ScriptedVision({"hpr": _judge("match", 0.9)})
    verdicts = compare_charts(
        expected, repo_root=tmp_path, vision=vision, match_threshold=0.7
    )
    assert len(verdicts) == 1
    assert verdicts[0].verdict == "match"
    assert verdicts[0].confidence == pytest.approx(0.9)


def test_compare_charts_partial_when_confidence_below_threshold(tmp_path: Path):
    _write_dummy_svg(tmp_path / "x.svg")
    _write_dummy_svg(tmp_path / "ref.svg")
    expected = [
        ExpectedChart(name="x", produced_path="x.svg", reference_image="ref.svg")
    ]
    vision = _ScriptedVision({"x": _judge("match", 0.5)})
    verdicts = compare_charts(
        expected, repo_root=tmp_path, vision=vision, match_threshold=0.7
    )
    assert verdicts[0].verdict == "partial"


def test_compare_charts_marks_missing_file_when_produced_chart_absent(tmp_path: Path):
    expected = [
        ExpectedChart(name="x", produced_path="missing.svg", reference_image=None)
    ]
    vision = _ScriptedVision({})
    verdicts = compare_charts(
        expected, repo_root=tmp_path, vision=vision, match_threshold=0.7
    )
    assert verdicts[0].verdict == "missing_file"


def test_compare_charts_skips_vision_call_when_no_reference(tmp_path: Path):
    """File-existence-only mode for charts without a baseline reference."""
    _write_dummy_svg(tmp_path / "x.svg")
    expected = [
        ExpectedChart(name="x", produced_path="x.svg", reference_image=None)
    ]
    vision = _ScriptedVision({})  # would fail if called
    verdicts = compare_charts(
        expected, repo_root=tmp_path, vision=vision, match_threshold=0.7
    )
    assert verdicts[0].verdict == "match"  # file exists, no reference -> structural pass
    assert verdicts[0].confidence is None


def test_compare_charts_skipped_when_disabled(tmp_path: Path):
    _write_dummy_svg(tmp_path / "x.svg")
    expected = [
        ExpectedChart(name="x", produced_path="x.svg", reference_image="ref.svg")
    ]
    vision = _ScriptedVision({})
    verdicts = compare_charts(
        expected, repo_root=tmp_path, vision=vision, match_threshold=0.7, enabled=False
    )
    assert verdicts[0].verdict == "skipped"

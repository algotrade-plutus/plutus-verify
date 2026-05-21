"""Chart comparison: file existence + Gemma (vision) shape similarity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Protocol

from plutus_verify.compare.rubric import ChartVerdict
from plutus_verify.extract.plan import ExpectedChart

CHART_PROMPT = """You are comparing two financial time-series charts to judge reproducibility.

CHART_A is the reference (reported in the project README). CHART_B is the freshly reproduced output.

Judge them along three independent axes:
  1. SHAPE — Do the lines/bars follow the same overall trajectory?
  2. SCALE — Are the y-axis ranges qualitatively the same order of magnitude (within ~30% counts as same)?
  3. STRUCTURE — Same number of series, same chart type, same conceptual axes?

Reply ONLY with this JSON:
{
  "shape_match":     {"verdict": "match"|"partial"|"mismatch", "reason": "<<=25 words>"},
  "scale_match":     {"verdict": "match"|"partial"|"mismatch", "reason": "<<=25 words>"},
  "structure_match": {"verdict": "match"|"partial"|"mismatch", "reason": "<<=25 words>"},
  "overall":         {"verdict": "match"|"partial"|"mismatch", "confidence": 0.0-1.0}
}
"""


class VisionClient(Protocol):
    def judge_chart(
        self, *, chart_name: str, produced_png: bytes, reference_png: bytes | None
    ) -> str:
        """Return the assistant's JSON response (string) for the chart-judge prompt."""
        ...


def _rasterize_if_needed(path: Path) -> bytes:
    """Read PNG directly; rasterize SVG via cairosvg (lazy import)."""
    if path.suffix.lower() == ".svg":
        try:
            import cairosvg  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "cairosvg not installed. Install with: pip install 'plutus-verify[charts]'"
            ) from exc
        return cairosvg.svg2png(bytestring=path.read_bytes(), output_width=900)
    return path.read_bytes()


def compare_charts(
    expected: list[ExpectedChart],
    *,
    repo_root: Path,
    vision: VisionClient,
    match_threshold: float = 0.7,
    enabled: bool = True,
) -> list[ChartVerdict]:
    out: list[ChartVerdict] = []
    for ec in expected:
        if not enabled:
            out.append(
                ChartVerdict(
                    name=ec.name,
                    produced_path=ec.produced_path,
                    verdict="skipped",
                )
            )
            continue

        produced = repo_root / ec.produced_path
        if not produced.exists():
            out.append(
                ChartVerdict(
                    name=ec.name,
                    produced_path=ec.produced_path,
                    verdict="missing_file",
                )
            )
            continue

        if ec.reference_image is None:
            # No reference -> existence-only mode (still counts as match).
            out.append(
                ChartVerdict(
                    name=ec.name,
                    produced_path=ec.produced_path,
                    verdict="match",
                )
            )
            continue

        ref = repo_root / ec.reference_image
        if not ref.exists():
            out.append(
                ChartVerdict(
                    name=ec.name,
                    produced_path=ec.produced_path,
                    verdict="match",  # produced file exists; no comparable reference
                    rationale="reference image missing in repo",
                )
            )
            continue

        try:
            produced_png = _rasterize_if_needed(produced)
            ref_png = _rasterize_if_needed(ref)
        except RuntimeError as exc:
            out.append(
                ChartVerdict(
                    name=ec.name,
                    produced_path=ec.produced_path,
                    verdict="partial",
                    rationale=str(exc),
                )
            )
            continue

        raw = vision.judge_chart(
            chart_name=ec.name, produced_png=produced_png, reference_png=ref_png
        )
        out.append(_parse_vision_verdict(ec, raw, match_threshold))
    return out


def _parse_vision_verdict(
    ec: ExpectedChart, raw: str, match_threshold: float
) -> ChartVerdict:
    try:
        data = json.loads(raw)
        overall = data["overall"]
        verdict = overall["verdict"]
        confidence = float(overall["confidence"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return ChartVerdict(
            name=ec.name,
            produced_path=ec.produced_path,
            verdict="partial",
            rationale="vision client returned malformed JSON",
        )

    if verdict == "match" and confidence < match_threshold:
        verdict = "partial"

    rationale_parts = []
    for axis in ("shape_match", "scale_match", "structure_match"):
        if axis in data and isinstance(data[axis], dict):
            r = data[axis].get("reason")
            v = data[axis].get("verdict")
            if r and v and v != "match":
                rationale_parts.append(f"{axis.split('_')[0]}: {r}")
    rationale = "; ".join(rationale_parts) or None

    return ChartVerdict(
        name=ec.name,
        produced_path=ec.produced_path,
        verdict=verdict,
        confidence=confidence,
        rationale=rationale,
    )

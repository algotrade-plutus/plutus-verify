"""Integration smoke test: actually run scripts in the gold-repo fixture.

This test:
  - Uses ``--skip-clone`` semantics so we work on a real fixture on disk
  - Stubs the LLM (returns a hand-crafted plan tailored to the fixture)
  - Stubs the Docker builder (real Docker not required here)
  - Uses a subprocess-based runner that actually invokes ``python <script>``
  - Stubs the vision client

This catches integration bugs across stages (extract -> execute -> compare ->
report) that the per-module unit tests can't see.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from plutus_verify.compare.rubric import ExecOutcome, StepVerdict
from plutus_verify.config import Config
from plutus_verify.execute import ExecResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "gold-repo"


def _plan_for_gold_repo() -> dict:
    return {
        "schema_version": "1.0",
        "repo": {
            "name": "GoldRepo",
            "primary_language": "python",
            "env_setup": {
                "kind": "none",
                "path": None,
                "python_version": "3.11",
                "extra_setup_commands": [],
            },
            "secrets_required": [],
        },
        "nine_step_mapping": {
            "step_1_hypothesis":      {"present": True, "section_heading": "Hypothesis", "confidence": 1.0},
            "step_2_data_collection": {"present": True, "section_heading": "Data Collection", "confidence": 1.0},
            "step_3_data_processing": {"present": False, "section_heading": None, "confidence": 0.9},
            "step_4_in_sample":       {"present": True, "section_heading": "In-sample Backtesting", "confidence": 1.0},
            "step_5_optimization":    {"present": True, "section_heading": "Optimization", "confidence": 1.0},
            "step_6_out_of_sample":   {"present": True, "section_heading": "Out-of-sample Backtesting", "confidence": 1.0},
            "step_7_paper_trading":   {"present": False, "section_heading": None, "confidence": 1.0},
        },
        "steps": [
            {
                "id": "in_sample_backtest",
                "nine_step": "step_4_in_sample",
                "required": True,
                "command": f"{sys.executable} backtesting.py",
                "network": "none",
                "timeout_seconds": 60,
                "produces": ["result/backtest/hpr.svg"],
            },
            {
                "id": "optimization",
                "nine_step": "step_5_optimization",
                "required": True,
                "command": f"{sys.executable} optimization.py",
                "network": "none",
                "timeout_seconds": 60,
                "produces": ["parameter/optimized_parameter.json"],
            },
            {
                "id": "out_of_sample",
                "nine_step": "step_6_out_of_sample",
                "required": True,
                "depends_on": ["optimization"],
                "command": f"{sys.executable} evaluation.py",
                "network": "none",
                "timeout_seconds": 60,
            },
        ],
        "expected_results": [
            {
                "step_id": "in_sample_backtest",
                "metrics": [
                    {
                        "name": "sharpe_ratio",
                        "value": 1.2345,
                        "locate": {"kind": "stdout_table", "row": "Sharpe Ratio", "col": 1},
                        "tolerance": {"kind": "relative", "value": 0.05},
                    },
                    {
                        "name": "max_drawdown",
                        "value": -0.15,
                        "locate": {"kind": "stdout_table", "row": "Max Drawdown", "col": 1},
                        "tolerance": {"kind": "absolute", "value": 0.02},
                    },
                ],
                "charts": [
                    {"name": "hpr", "produced_path": "result/backtest/hpr.svg", "reference_image": None},
                ],
            },
            {
                "step_id": "optimization",
                "metrics": [
                    {
                        "name": "step",
                        "value": 2.5,
                        "locate": {
                            "kind": "json_file",
                            "path": "parameter/optimized_parameter.json",
                            "jsonpath": "$.step",
                        },
                        "tolerance": {"kind": "absolute", "value": 0.2},
                    }
                ],
                "charts": [],
            },
            {
                "step_id": "out_of_sample",
                "metrics": [
                    {
                        "name": "sharpe_ratio",
                        "value": 0.6,
                        "locate": {"kind": "stdout_table", "row": "Sharpe Ratio", "col": 1},
                        "tolerance": {"kind": "relative", "value": 0.05},
                    },
                ],
                "charts": [],
            },
        ],
        "extraction_notes": ["step_3 not present"],
    }


class _StubLLM:
    """Iteration 4 stub: decompose the full plan into the 4 per-call elements."""

    def __init__(self, payload):
        self._plan = payload if isinstance(payload, dict) else json.loads(payload)
        self._payload = json.dumps(self._plan)

    def complete_json(self, system, user, *, temperature=0.0):
        if "repo-metadata template" in user:
            return json.dumps(self._plan.get("repo", {}))
        if "7 PLUTUS standard steps" in user:
            return json.dumps(
                {
                    k: {"present": v.get("present"), "section_heading": v.get("section_heading")}
                    for k, v in self._plan.get("nine_step_mapping", {}).items()
                }
            )
        if "PLUTUS step marked present below" in user:
            return json.dumps(
                [
                    {k: v for k, v in s.items() if k != "depends_on"}
                    for s in self._plan.get("steps", [])
                ]
            )
        if "step ID below that reports results" in user:
            return json.dumps(self._plan.get("expected_results", []))
        return self._payload


class _StubBuilder:
    def build(self, *, repo_path, commit_sha):
        return "gold-repo-stub:latest"


class _SubprocessRunner:
    """Actually runs commands locally (no Docker). Each command runs with cwd=repo."""

    def run(self, *, image, command, cwd, network, timeout_seconds, env=None):
        start = time.monotonic()
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        outcome = ExecOutcome.OK if proc.returncode == 0 else ExecOutcome.FAILED
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=time.monotonic() - start,
            outcome=outcome,
        )


class _StubVision:
    def judge_chart(self, *, chart_name, produced_png, reference_png):
        return json.dumps(
            {
                "shape_match": {"verdict": "match", "reason": ""},
                "scale_match": {"verdict": "match", "reason": ""},
                "structure_match": {"verdict": "match", "reason": ""},
                "overall": {"verdict": "match", "confidence": 0.9},
            }
        )


def _seed_repo(dst: Path) -> Path:
    """Copy the read-only fixture to a writable temp location."""
    shutil.copytree(FIXTURE, dst)
    return dst


def test_gold_repo_runs_end_to_end_reproduced(tmp_path: Path):
    repo = _seed_repo(tmp_path / "repo")
    out_dir = tmp_path / "out"

    result = run_pipeline(
        PipelineInputs(
            source=str(repo),
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,  # no reference image to compare against
            skip_clone=True,
        ),
        llm_client=_StubLLM(_plan_for_gold_repo()),
        builder=_StubBuilder(),
        runner=_SubprocessRunner(),
        vision=_StubVision(),
    )

    assert result.overall is not None
    assert result.overall.verdict == StepVerdict.REPRODUCED, (
        "expected reproduced; got "
        f"{result.overall.verdict} with steps={[(s.step_id, s.verdict.value) for s in result.overall.steps]}"
    )
    assert result.overall.exit_code == 0

    payload = json.loads((out_dir / "report.json").read_text())
    assert payload["verdict"] == "reproduced"
    assert payload["exit_code"] == 0
    # Every step should report numeric metrics with pass=True
    for step in payload["steps"]:
        for m in step["metrics"]:
            assert m["pass"] is True, f"{step['step_id']}.{m['name']} failed: {m}"

    md = (out_dir / "report.md").read_text()
    assert "GoldRepo" in md
    assert "✅" in md
    assert "## 9-Step Coverage" in md
    # Generated chart file actually exists on disk
    assert (repo / "result" / "backtest" / "hpr.svg").exists()


def test_gold_repo_tampered_readme_flags_partial(tmp_path: Path):
    """Tamper test: change the README's expected Sharpe to something wildly off
    (via the plan, since the README itself is the LLM's input), and verify the
    pipeline correctly downgrades to partial.
    """
    repo = _seed_repo(tmp_path / "repo")
    out_dir = tmp_path / "out"

    bad_plan = _plan_for_gold_repo()
    # Pretend the README claimed Sharpe 9.9999 (massively out of tolerance)
    bad_plan["expected_results"][0]["metrics"][0]["value"] = 9.9999

    result = run_pipeline(
        PipelineInputs(
            source=str(repo),
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
            skip_clone=True,
        ),
        llm_client=_StubLLM(bad_plan),
        builder=_StubBuilder(),
        runner=_SubprocessRunner(),
        vision=_StubVision(),
    )

    assert result.overall is not None
    assert result.overall.verdict == StepVerdict.PARTIAL
    assert result.overall.exit_code == 1

    payload = json.loads((out_dir / "report.json").read_text())
    is_step = next(s for s in payload["steps"] if s["step_id"] == "in_sample_backtest")
    failed = [m for m in is_step["metrics"] if not m["pass"]]
    assert len(failed) == 1
    assert failed[0]["name"] == "sharpe_ratio"

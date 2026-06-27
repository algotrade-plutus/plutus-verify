"""Unit tests for plutus_verify.scaffold.check_report.render_check_report.

Pure-function tests: build fake Manifest + V2RuntimeResult objects, render
to lines, then assert on lines. No Click, no Docker, no IO.
"""
from __future__ import annotations

from plutus_verify.scaffold.check_report import render_check_report
from plutus_verify.spec.manifest import (
    DataSourceTiers,
    Env,
    ExpectedBlock,
    Manifest,
    Repo,
    Step,
)
from plutus_verify.spec.runtime.orchestrator import (
    ExpectedMetricResult,
    StepRuntimeResult,
    V2RuntimeResult,
)


def _make_manifest(steps: tuple[Step, ...] = (), expected: tuple[ExpectedBlock, ...] = ()) -> Manifest:
    return Manifest(
        schema_version="2.0",
        repo=Repo(name="T", primary_language="python"),
        env=Env(base="python", python_version="3.11", requirements_file="r.txt"),
        secrets=(),
        data_sources=DataSourceTiers(),
        steps=steps,
        expected=expected,
    )


def _make_runtime(
    step_results: dict[str, StepRuntimeResult] | None = None,
    metric_results: dict[str, dict[str, ExpectedMetricResult]] | None = None,
    notes: list[str] | None = None,
    image: str = "plutus-v2:abc123",
    data_tier: str = "raw",
) -> V2RuntimeResult:
    r = V2RuntimeResult(image=image, data_tier_used=data_tier)
    if step_results:
        r.step_results.update(step_results)
    if metric_results:
        r.metric_results.update(metric_results)
    if notes:
        r.notes.extend(notes)
    return r


def _ok_sr(step_id: str, *, skipped_reason: str | None = None) -> StepRuntimeResult:
    return StepRuntimeResult(
        step_id=step_id,
        exit_code=0,
        duration_seconds=0.1,
        skipped_reason=skipped_reason,
    )


def test_failed_step_report_includes_stderr_tail():
    """A non-zero step must surface its captured stderr in the report, not just
    `exit=N` — otherwise the user has to docker-run the image by hand to see why."""
    steps = (Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),)
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "in_sample": StepRuntimeResult(
                step_id="in_sample",
                exit_code=1,
                duration_seconds=0.1,
                stdout="loading data...\n",
                stderr="Traceback (most recent call last):\nValueError: boom\n",
            )
        }
    )
    out = "\n".join(render_check_report(manifest, runtime))
    assert "ValueError: boom" in out, f"stderr tail missing from report:\n{out}"


# ---------------------------------------------------------------------------
# 1) grouping by nine-step
# ---------------------------------------------------------------------------

def test_render_groups_by_nine_step():
    steps = (
        Step(id="data_preparation", nine_step="step_2_data_preparation", required=True, command="x"),
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
        Step(id="opt", nine_step="step_5_optimization", required=True, command="x"),
        Step(id="oos", nine_step="step_6_out_of_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "data_preparation": _ok_sr("data_preparation"),
            "in_sample": _ok_sr("in_sample"),
            "opt": _ok_sr("opt"),
            "oos": _ok_sr("oos"),
        }
    )

    lines = render_check_report(manifest, runtime)
    out = "\n".join(lines)

    assert "Step 1: Hypothesis" in out
    assert "Step 2: Data Preparation" in out
    assert "Step 3: Forming Set of Rules" in out
    assert "Step 4: In-sample Backtesting" in out
    assert "Step 5: Optimization" in out
    assert "Step 6: Out-of-sample Backtesting" in out
    assert "Step 7: Paper Trading" in out

    # The framework steps with no manifest mapping show the placeholder.
    placeholder_count = sum(1 for l in lines if l == "  (no step in this manifest)")
    # Step 1, Step 3, Step 7 -> 3 placeholders
    assert placeholder_count == 3


# ---------------------------------------------------------------------------
# 2) metrics indented under their step
# ---------------------------------------------------------------------------

def test_render_metrics_indented_under_step():
    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={"in_sample": _ok_sr("in_sample")},
        metric_results={
            "in_sample": {
                "sharpe_ratio": ExpectedMetricResult(
                    name="sharpe_ratio", ok=True, actual=0.95, expected=0.95
                ),
                "sortino_ratio": ExpectedMetricResult(
                    name="sortino_ratio", ok=True, actual=1.34, expected=1.34
                ),
                "max_dd": ExpectedMetricResult(
                    name="max_dd", ok=True, actual=-0.2, expected=-0.2
                ),
            }
        },
    )

    lines = render_check_report(manifest, runtime)

    # Find the step header line.
    step_idx = next(i for i, l in enumerate(lines) if l == "  ok in_sample: exit=0")

    # The next 3 lines should be the metrics, each indented 6 spaces.
    metric_lines = lines[step_idx + 1: step_idx + 4]
    assert len(metric_lines) == 3
    for ml in metric_lines:
        assert ml.startswith("      ok "), f"unexpected metric indent: {ml!r}"

    joined = "\n".join(metric_lines)
    assert "sharpe_ratio" in joined
    assert "sortino_ratio" in joined
    assert "max_dd" in joined


# ---------------------------------------------------------------------------
# 3) failing step shows FAIL
# ---------------------------------------------------------------------------

def test_render_step_fail_shown():
    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "in_sample": StepRuntimeResult(
                step_id="in_sample", exit_code=1, duration_seconds=0.0
            )
        }
    )

    lines = render_check_report(manifest, runtime)
    assert any(l == "  FAIL in_sample: exit=1" for l in lines), lines


# ---------------------------------------------------------------------------
# 4) skipped_reason rendered
# ---------------------------------------------------------------------------

def test_render_skipped_reason_shown():
    steps = (
        Step(
            id="opt",
            nine_step="step_5_optimization",
            required=True,
            command=None,
            verification_mode="artifact_check",
        ),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "opt": _ok_sr("opt", skipped_reason="artifact_check (no execution; outputs verified by preflight)")
        }
    )

    lines = render_check_report(manifest, runtime)
    assert any(
        "ok opt: exit=0 (skipped: artifact_check (no execution; outputs verified by preflight))" in l
        for l in lines
    ), lines


# ---------------------------------------------------------------------------
# 5) free-form steps under "Other steps:" section
# ---------------------------------------------------------------------------

def test_render_free_form_steps_under_other_steps_section():
    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
        Step(id="custom_analysis", nine_step=None, required=False, command="y"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "in_sample": _ok_sr("in_sample"),
            "custom_analysis": _ok_sr("custom_analysis"),
        }
    )

    lines = render_check_report(manifest, runtime)

    other_idx = next((i for i, l in enumerate(lines) if l == "Other steps:"), None)
    assert other_idx is not None, lines

    # The next line should be the custom step rendered with 2-space indent.
    assert lines[other_idx + 1] == "  ok custom_analysis: exit=0"


# ---------------------------------------------------------------------------
# 6) no "Other steps:" section if no free-form steps
# ---------------------------------------------------------------------------

def test_render_no_free_form_section_when_no_free_form_steps():
    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(step_results={"in_sample": _ok_sr("in_sample")})

    lines = render_check_report(manifest, runtime)
    assert not any("Other steps:" in l for l in lines), lines


# ---------------------------------------------------------------------------
# 7) runtime.notes -> "Notes:" section
# ---------------------------------------------------------------------------

def test_render_notes_appended():
    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={"in_sample": _ok_sr("in_sample")},
        notes=["SDK wheel staged: plutus_verify-0.2.10-py3-none-any.whl", "data tier: raw resolved"],
    )

    lines = render_check_report(manifest, runtime)
    notes_idx = next((i for i, l in enumerate(lines) if l == "Notes:"), None)
    assert notes_idx is not None, lines
    assert lines[notes_idx + 1] == "  - SDK wheel staged: plutus_verify-0.2.10-py3-none-any.whl"
    assert lines[notes_idx + 2] == "  - data tier: raw resolved"


# ---------------------------------------------------------------------------
# 8) metric with actual=None renders without "actual=None"
# ---------------------------------------------------------------------------

def test_render_skips_metric_without_actual_value():
    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "in_sample": StepRuntimeResult(
                step_id="in_sample", exit_code=1, duration_seconds=0.0
            )
        },
        metric_results={
            "in_sample": {
                "sharpe_ratio": ExpectedMetricResult(
                    name="sharpe_ratio",
                    ok=False,
                    actual=None,
                    expected=0.95,
                    detail="step 'in_sample' failed (step exited 1); metric not evaluated",
                )
            }
        },
    )

    lines = render_check_report(manifest, runtime)
    metric_line = next(l for l in lines if "sharpe_ratio" in l)
    assert "actual=None" not in metric_line
    assert "FAIL sharpe_ratio" in metric_line
    assert "step 'in_sample' failed" in metric_line


# ---------------------------------------------------------------------------
# 9) image + data tier in header
# ---------------------------------------------------------------------------

def test_render_includes_image_and_data_tier_header():
    manifest = _make_manifest()
    runtime = _make_runtime(image="plutus-v2:deadbeef", data_tier="processed")

    lines = render_check_report(manifest, runtime)
    assert lines[0] == "image: plutus-v2:deadbeef"
    assert lines[1] == "data tier: processed"


# ---------------------------------------------------------------------------
# 10) framework-order sections regardless of manifest order
# ---------------------------------------------------------------------------

def test_render_step_order_matches_framework_order():
    # Manifest declares step_5 BEFORE step_2 deliberately.
    steps = (
        Step(id="opt", nine_step="step_5_optimization", required=True, command="x"),
        Step(id="data_preparation", nine_step="step_2_data_preparation", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(
        step_results={
            "opt": _ok_sr("opt"),
            "data_preparation": _ok_sr("data_preparation"),
        }
    )

    lines = render_check_report(manifest, runtime)
    out = "\n".join(lines)

    step2_pos = out.index("Step 2: Data Preparation")
    step5_pos = out.index("Step 5: Optimization")
    assert step2_pos < step5_pos, "Step 2 should appear before Step 5 regardless of manifest order"


# ---------------------------------------------------------------------------
# 11) artifact lines render with the right marker per (ok, skipped)
# ---------------------------------------------------------------------------

def test_render_artifact_warn_marker():
    """ok=False + skipped=True renders as WARN, not FAIL or SKIP."""
    from plutus_verify.spec.runtime.artifact_compare import CompareResult

    steps = (
        Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),
    )
    manifest = _make_manifest(steps=steps)
    runtime = _make_runtime(step_results={"in_sample": _ok_sr("in_sample")})
    runtime.artifact_results["in_sample"] = [
        CompareResult(
            ok=False,
            skipped=True,
            kind="byte_identical",
            path="result/hpr.svg",
            detail="bytes differ; pass --visual-check for LLM judgment",
        ),
        CompareResult(
            ok=True,
            skipped=False,
            kind="byte_identical",
            path="result/dd.svg",
            detail="bytes match (no LLM check needed)",
        ),
        CompareResult(
            ok=True,
            skipped=True,
            kind="visual_similarity",
            path="result/inv.svg",
            detail="skipped (no reference at …; run `plutus snapshot` to enable)",
        ),
    ]

    lines = render_check_report(manifest, runtime)
    artifact_lines = [l for l in lines if "result/" in l]
    assert any(l.startswith("      WARN") and "result/hpr.svg" in l for l in artifact_lines), artifact_lines
    assert any(l.startswith("      ok") and "result/dd.svg" in l for l in artifact_lines), artifact_lines
    assert any(l.startswith("      SKIP") and "result/inv.svg" in l for l in artifact_lines), artifact_lines

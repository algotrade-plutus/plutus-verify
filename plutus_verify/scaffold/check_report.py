"""Renderer for `plutus check` output, grouped by the Plutus 9-step framework."""
from __future__ import annotations

from plutus_verify.spec.manifest import Manifest, NINE_STEP_KEYS, Step
from plutus_verify.spec.runtime import V2RuntimeResult


_NINE_STEP_TITLES = {
    "step_1_hypothesis": "Step 1: Hypothesis",
    "step_2_data_collection": "Step 2: Data Collection",
    "step_3_data_processing": "Step 3: Data Processing",
    "step_4_in_sample": "Step 4: In-sample Backtesting",
    "step_5_optimization": "Step 5: Optimization",
    "step_6_out_of_sample": "Step 6: Out-of-sample Backtesting",
    "step_7_paper_trading": "Step 7: Paper Trading",
}


def render_check_report(manifest: Manifest, runtime: V2RuntimeResult) -> list[str]:
    """Render the check output as a list of lines (no trailing newlines).

    Caller writes each line via click.echo (or similar) -- keeps Click out
    of this module so it can be unit-tested as pure functions.

    Groups manifest steps by their `nine_step` field. Renders one section
    per framework step (1-7), with the manifest step(s) that map to it
    indented underneath, and their metric comparisons indented further
    under each step. Free-form steps (nine_step=null) appear under a
    final "Other steps:" section if any exist.
    """
    lines: list[str] = []

    # Header
    lines.append(f"image: {runtime.image}")
    lines.append(f"data tier: {runtime.data_tier_used}")

    # Group manifest.steps by nine_step.
    by_nine_step: dict[str, list[Step]] = {key: [] for key in NINE_STEP_KEYS}
    free_form: list[Step] = []
    for step in manifest.steps:
        if step.nine_step is None:
            free_form.append(step)
        elif step.nine_step in by_nine_step:
            by_nine_step[step.nine_step].append(step)
        else:
            # Unknown nine_step value (shouldn't happen -- schema validates
            # the enum) -- treat as free-form for resilience.
            free_form.append(step)

    for key in NINE_STEP_KEYS:
        lines.append("")
        lines.append(_NINE_STEP_TITLES[key])
        steps_here = by_nine_step[key]
        if not steps_here:
            lines.append("  (no step in this manifest)")
            continue
        for step in steps_here:
            lines.extend(_render_step(step, runtime))

    if free_form:
        lines.append("")
        lines.append("Other steps:")
        for step in free_form:
            lines.extend(_render_step(step, runtime))

    # Trailing notes (SDK bundling status, data-tier notes etc.) appear below.
    if runtime.notes:
        lines.append("")
        lines.append("Notes:")
        for note in runtime.notes:
            lines.append(f"  - {note}")

    return lines


def _render_step(step: Step, runtime: V2RuntimeResult) -> list[str]:
    """Render one manifest step and any metric comparisons under it."""
    out: list[str] = []
    sr = runtime.step_results.get(step.id)
    if sr is None:
        out.append(f"  ? {step.id}: (no result captured)")
        return out

    status = "ok" if sr.exit_code == 0 and sr.preflight_error is None else "FAIL"
    skip = f" (skipped: {sr.skipped_reason})" if sr.skipped_reason else ""
    pf = f" [preflight: {sr.preflight_error}]" if sr.preflight_error else ""
    out.append(f"  {status} {step.id}: exit={sr.exit_code}{skip}{pf}")

    metrics = runtime.metric_results.get(step.id, {})
    for name, hr in metrics.items():
        marker = "ok" if hr.ok else "FAIL"
        if hr.actual is None:
            detail = f": {hr.detail}" if hr.detail else ""
            out.append(f"      {marker} {name}{detail}")
        else:
            line = f"      {marker} {name}: actual={hr.actual} expected={hr.expected}"
            if hr.detail:
                line += f"  [{hr.detail}]"
            out.append(line)

    artifacts = runtime.artifact_results.get(step.id, [])
    for r in artifacts:
        # 4-state matrix:
        #   (ok=T, skipped=F) -> "ok"   verified pass
        #   (ok=T, skipped=T) -> "SKIP" not verified, no evidence of issue
        #   (ok=F, skipped=T) -> "WARN" divergence detected but inconclusive
        #   (ok=F, skipped=F) -> "FAIL" verified divergence
        if r.skipped:
            marker = "WARN" if not r.ok else "SKIP"
        elif r.ok:
            marker = "ok"
        else:
            marker = "FAIL"
        label = f"{r.kind} {r.path}".strip()
        detail = f"  [{r.detail}]" if r.detail else ""
        out.append(f"      {marker} {label}{detail}")
    return out

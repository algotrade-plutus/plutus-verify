"""Plan validator: a second pass that catches Gemma's recurring plan defects.

Two phases. Phase 1 is deterministic and always runs:

  - Drops any metric whose ``locate.kind == "stdout_table"`` on a step with
    ``verification_mode == "artifact_check"`` (the artifact-check step doesn't
    run, so a stdout-based locate is structurally impossible).
  - Flags ``json_file`` locate directives whose ``path`` doesn't exist on
    disk; doesn't drop them (the path may be created by an earlier step), but
    records a warning that the reviewer can act on.

Phase 2 is the optional LLM pass. It receives the README + the current plan
JSON and returns a small structured corrections document. The corrections are
applied **deterministically by this module** — the LLM never rewrites the
plan freely. We only honour these operations, in this order:

  1. ``drop_metrics`` — drop a (step_id, metric_name) pair
  2. ``rename_row`` — change ``locate.row`` of a metric (for stdout_table only)
  3. ``add_metrics`` — append a new metric to a step's expected_results
  4. ``add_steps`` — append a new step (very narrow; default fields used)

Any other key in the LLM's response is **ignored** (defence against the LLM
suggesting things like rewriting `command`, `network`, or
`verification_mode`, which we never let the validator change).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Optional

from plutus_verify.extract.plan import (
    ExpectedMetric,
    ExpectedResult,
    ExtractedPlan,
    Locate,
    Step,
    Tolerance,
)


class ValidatorError(RuntimeError):
    """Raised only on unrecoverable validator state. LLM failures are not errors."""


# -------- Phase 1 (deterministic) --------


def _drop_bogus_stdout_metrics_on_artifact_check(
    plan: ExtractedPlan,
) -> tuple[ExtractedPlan, list[str]]:
    fixes: list[str] = []
    artifact_check_ids = {s.id for s in plan.steps if s.verification_mode == "artifact_check"}
    if not artifact_check_ids:
        return plan, fixes

    new_ers: list[ExpectedResult] = []
    for er in plan.expected_results:
        if er.step_id not in artifact_check_ids:
            new_ers.append(er)
            continue
        keep_metrics: list[ExpectedMetric] = []
        for m in er.metrics:
            if m.locate.kind == "stdout_table":
                fixes.append(
                    f"dropped metric {er.step_id}.{m.name!r}: "
                    "stdout_table locate is not valid on an artifact_check step"
                )
                continue
            keep_metrics.append(m)
        new_ers.append(dataclasses.replace(er, metrics=tuple(keep_metrics)))
    return dataclasses.replace(plan, expected_results=tuple(new_ers)), fixes


def _flag_missing_json_file_paths(
    plan: ExtractedPlan, repo_path: Path
) -> list[str]:
    notes: list[str] = []
    for er in plan.expected_results:
        for m in er.metrics:
            if m.locate.kind != "json_file":
                continue
            if not m.locate.path:
                continue
            target = repo_path / m.locate.path
            if not target.exists():
                notes.append(
                    f"json_file locate {er.step_id}.{m.name!r} references missing path: "
                    f"{m.locate.path}"
                )
    return notes


# -------- Phase 2 (LLM-driven, optional) --------


_SYSTEM_PROMPT = """You are validating a Plutus reproducibility plan against the README it was extracted from. Return JSON only, in this exact shape (omit empty arrays if you wish):

{
  "drop_metrics": [{"step_id": "...", "metric_name": "..."}],
  "rename_row": [{"step_id": "...", "metric_name": "...", "new_row": "..."}],
  "add_metrics": [{"step_id": "...", "name": "...", "value": <number>, "locate": {"kind": "stdout_table", "row": "...", "col": 1}, "tolerance": {"kind": "relative", "value": 0.05}}],
  "add_steps": [{"id": "...", "nine_step": "step_4_in_sample", "required": true, "command": "...", "network": "none", "timeout_seconds": 600, "verification_mode": "execute"}]
}

DEFAULT TO DOING NOTHING. If the plan is already correct, return {} (empty object). Most plans need no corrections.

Strict rules:
- NEVER suggest add_steps with an id that already appears in the plan's steps. If a step exists, don't duplicate it.
- A step with verification_mode="artifact_check" is INTENTIONAL (it skips re-running an expensive optimization). NEVER suggest replacing it with an execute-mode duplicate.
- NEVER suggest add_metrics whose name already appears on that step.
- NEVER invent metrics that aren't in the README's tables.
- NEVER modify a step's command, network, or verification_mode (those fields are not in your op set).
- Keep changes minimal. One correction per actual error, no more."""

_USER_TEMPLATE = """README:
---
{readme}
---

Current plan (JSON):
{plan_json}

Pre-detected issues (already handled deterministically, don't repeat):
{prefixes}

Return JSON only.
"""


def _safe_str_id(x: Any) -> Optional[str]:
    return x if isinstance(x, str) and x else None


def _apply_drop_metrics(plan: ExtractedPlan, ops: list[dict]) -> tuple[ExtractedPlan, list[str]]:
    fixes: list[str] = []
    by_step_drop: dict[str, set[str]] = {}
    for op in ops:
        sid = _safe_str_id(op.get("step_id"))
        mname = _safe_str_id(op.get("metric_name"))
        if not sid or not mname:
            continue
        by_step_drop.setdefault(sid, set()).add(mname)

    if not by_step_drop:
        return plan, fixes

    new_ers: list[ExpectedResult] = []
    for er in plan.expected_results:
        drops = by_step_drop.get(er.step_id, set())
        if not drops:
            new_ers.append(er)
            continue
        kept = [m for m in er.metrics if m.name not in drops]
        removed = [m.name for m in er.metrics if m.name in drops]
        for n in removed:
            fixes.append(f"LLM-suggested drop: {er.step_id}.{n!r}")
        new_ers.append(dataclasses.replace(er, metrics=tuple(kept)))
    return dataclasses.replace(plan, expected_results=tuple(new_ers)), fixes


def _apply_rename_row(plan: ExtractedPlan, ops: list[dict]) -> tuple[ExtractedPlan, list[str]]:
    fixes: list[str] = []
    # Index ops: (step_id, metric_name) -> new_row
    rename_map: dict[tuple[str, str], str] = {}
    for op in ops:
        sid = _safe_str_id(op.get("step_id"))
        mname = _safe_str_id(op.get("metric_name"))
        new_row = _safe_str_id(op.get("new_row"))
        if sid and mname and new_row:
            rename_map[(sid, mname)] = new_row

    if not rename_map:
        return plan, fixes

    new_ers: list[ExpectedResult] = []
    for er in plan.expected_results:
        new_metrics: list[ExpectedMetric] = []
        for m in er.metrics:
            key = (er.step_id, m.name)
            if key in rename_map and m.locate.kind == "stdout_table":
                new_loc = dataclasses.replace(m.locate, row=rename_map[key])
                new_metrics.append(dataclasses.replace(m, locate=new_loc))
                fixes.append(
                    f"LLM-suggested: renamed row of {er.step_id}.{m.name!r} -> {rename_map[key]!r}"
                )
            else:
                new_metrics.append(m)
        new_ers.append(dataclasses.replace(er, metrics=tuple(new_metrics)))
    return dataclasses.replace(plan, expected_results=tuple(new_ers)), fixes


def _apply_add_metrics(plan: ExtractedPlan, ops: list[dict]) -> tuple[ExtractedPlan, list[str]]:
    """Append metrics to existing expected_results entries. Skip if metric name already exists."""
    fixes: list[str] = []
    if not ops:
        return plan, fixes

    by_step: dict[str, list[dict]] = {}
    for op in ops:
        sid = _safe_str_id(op.get("step_id"))
        if not sid:
            continue
        by_step.setdefault(sid, []).append(op)

    new_ers: list[ExpectedResult] = []
    for er in plan.expected_results:
        adds = by_step.get(er.step_id, [])
        if not adds:
            new_ers.append(er)
            continue
        existing_names = {m.name for m in er.metrics}
        new_metrics = list(er.metrics)
        for op in adds:
            mname = _safe_str_id(op.get("name"))
            if not mname or mname in existing_names:
                continue
            try:
                value = float(op["value"])
            except (KeyError, TypeError, ValueError):
                continue
            loc = op.get("locate") or {}
            tol = op.get("tolerance") or {}
            try:
                new_loc = Locate(
                    kind=loc["kind"],
                    row=loc.get("row"),
                    col=loc.get("col"),
                    path=loc.get("path"),
                    jsonpath=loc.get("jsonpath"),
                    pattern=loc.get("pattern"),
                )
                new_tol = Tolerance(kind=tol["kind"], value=float(tol["value"]))
            except (KeyError, TypeError, ValueError):
                continue
            new_metrics.append(
                ExpectedMetric(name=mname, value=value, locate=new_loc, tolerance=new_tol)
            )
            existing_names.add(mname)
            fixes.append(f"LLM-suggested: added metric {er.step_id}.{mname!r}")
        new_ers.append(dataclasses.replace(er, metrics=tuple(new_metrics)))
    return dataclasses.replace(plan, expected_results=tuple(new_ers)), fixes


def _apply_add_steps(plan: ExtractedPlan, ops: list[dict]) -> tuple[ExtractedPlan, list[str]]:
    """Append new executable steps to the plan."""
    fixes: list[str] = []
    if not ops:
        return plan, fixes
    existing_ids = {s.id for s in plan.steps}
    new_steps = list(plan.steps)
    for op in ops:
        sid = _safe_str_id(op.get("id"))
        nine_step = _safe_str_id(op.get("nine_step"))
        if not sid or sid in existing_ids or not nine_step:
            continue
        try:
            step = Step(
                id=sid,
                nine_step=nine_step,
                required=bool(op.get("required", True)),
                depends_on=tuple(op.get("depends_on", []) or []),
                command=op.get("command"),
                config_files=tuple(op.get("config_files", []) or []),
                network=str(op.get("network", "none")),
                timeout_seconds=int(op.get("timeout_seconds", 1200)),
                produces=tuple(op.get("produces", []) or []),
                alternatives=None,  # validator never adds alternatives
                verification_mode=str(op.get("verification_mode", "execute")),
            )
        except (TypeError, ValueError):
            continue
        if step.verification_mode not in ("execute", "artifact_check"):
            continue
        new_steps.append(step)
        existing_ids.add(sid)
        fixes.append(f"LLM-suggested: added step {sid!r}")
    return dataclasses.replace(plan, steps=tuple(new_steps)), fixes


def _llm_pass(
    plan: ExtractedPlan,
    readme_text: str,
    repo_path: Path,
    llm_client,
    pre_findings: list[str],
) -> tuple[ExtractedPlan, list[str]]:
    """Run one LLM call and apply the returned corrections."""
    from plutus_verify.pipeline import _plan_to_dict  # local import to avoid cycle

    user = _USER_TEMPLATE.format(
        readme=readme_text,
        plan_json=json.dumps(_plan_to_dict(plan), indent=2),
        prefixes="\n".join(f"- {f}" for f in pre_findings) if pre_findings else "(none)",
    )
    fixes: list[str] = []
    try:
        try:
            raw = llm_client.complete_json(
                _SYSTEM_PROMPT, user, temperature=0.0, idle_timeout_seconds=120.0
            )
        except TypeError:
            raw = llm_client.complete_json(_SYSTEM_PROMPT, user, temperature=0.0)
        # Strip code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        ops = json.loads(raw)
        if not isinstance(ops, dict):
            raise ValueError("expected JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        fixes.append(f"validator LLM output malformed; skipping ({exc})")
        return plan, fixes

    # Apply in fixed order — drops first, then rename, then adds.
    for fn, key in (
        (_apply_drop_metrics, "drop_metrics"),
        (_apply_rename_row, "rename_row"),
        (_apply_add_metrics, "add_metrics"),
        (_apply_add_steps, "add_steps"),
    ):
        payload = ops.get(key)
        if isinstance(payload, list):
            plan, more = fn(plan, payload)
            fixes.extend(more)
    return plan, fixes


# -------- Top-level entry --------


def validate_plan(
    plan: ExtractedPlan,
    readme_text: str,
    repo_path: Path,
    *,
    llm_client=None,
) -> tuple[ExtractedPlan, list[str]]:
    """Run the two-phase validator and return the corrected plan + fix log."""
    fixes: list[str] = []

    plan, more = _drop_bogus_stdout_metrics_on_artifact_check(plan)
    fixes.extend(more)

    fixes.extend(_flag_missing_json_file_paths(plan, repo_path))

    if llm_client is not None:
        plan, more = _llm_pass(plan, readme_text, repo_path, llm_client, fixes)
        fixes.extend(more)

    return plan, fixes

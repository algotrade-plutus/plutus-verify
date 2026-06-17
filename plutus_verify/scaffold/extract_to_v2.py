"""Reverse adapter: v1 ExtractedPlan → draft v2 manifest YAML text.

Used by `plutus transfer`. Best-effort; emits TODO markers wherever the v1
shape can't fully describe what v2 needs.
"""
from __future__ import annotations

import re
from io import StringIO
from typing import TextIO

from plutus_verify.constants import NINE_STEP_KEYS
from plutus_verify.extract.plan import ExtractedPlan, Step, StepAlternative


_TODO_TAG = "# TODO(plutus-transfer):"

_NON_WORD = re.compile(r"[^\w]+")

# The input plan speaks the frozen v2023 taxonomy; the draft manifest must speak
# v2025. step 2 (Data Preparation) absorbs both old data steps, so collection and
# processing both map onto step_2_data_preparation (a 2->1 merge). v1 repos have
# no "forming set of rules" step, so step_3_forming_set_of_rules has no source.
_LEGACY_TO_V2_NINE_STEP = {
    "step_1_hypothesis": "step_1_hypothesis",
    "step_2_data_collection": "step_2_data_preparation",
    "step_3_data_processing": "step_2_data_preparation",
    "step_4_in_sample": "step_4_in_sample",
    "step_5_optimization": "step_5_optimization",
    "step_6_out_of_sample": "step_6_out_of_sample",
    "step_7_paper_trading": "step_7_paper_trading",
}


def _v2_nine_step(legacy_key: str | None) -> str:
    if legacy_key is None:
        return "null"
    return _LEGACY_TO_V2_NINE_STEP.get(legacy_key, legacy_key)


def _canonical_name(name: str) -> str:
    """Convert a v1 metric name to snake_case for v2.

    Examples: "Sharpe Ratio" -> "sharpe_ratio", "HPR" -> "hpr",
    "Maximum Drawdown (MDD)" -> "maximum_drawdown_mdd".

    If the result is empty or doesn't start with a letter, prefix "m_".
    """
    cleaned = _NON_WORD.sub("_", name.strip()).strip("_").lower()
    if not cleaned or not cleaned[0].isalpha():
        cleaned = "m_" + cleaned
    return cleaned


def _coerce_float(value) -> tuple[float, str | None]:
    """Coerce a v1 value (float | str) to a float for v2.

    Returns ``(parsed, None)`` on success, ``(0.0, original_str)`` on failure
    so the caller can emit a TODO comment with the unparseable original.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value), None
    try:
        return float(value), None
    except (TypeError, ValueError):
        return 0.0, str(value)


def to_v2_manifest_yaml(plan: ExtractedPlan) -> str:
    buf = StringIO()
    buf.write("# Draft v2 manifest produced by `plutus transfer`. Review TODOs,\n")
    buf.write("# rename to `manifest.yaml`, then run `plutus check`.\n")
    buf.write('schema_version: "2.0"\n\n')

    buf.write("repo:\n")
    buf.write(f"  name: {plan.repo.name}\n")
    buf.write(f"  primary_language: {plan.repo.primary_language}\n\n")

    _write_env(buf, plan)
    _write_secrets(buf, plan)
    _write_data_sources(buf, plan)
    _write_steps(buf, plan)
    _write_expected(buf, plan)
    _write_nine_step_coverage(buf, plan)

    return buf.getvalue()


def _write_env(buf: TextIO, plan: ExtractedPlan) -> None:
    env = plan.repo.env_setup
    buf.write("env:\n")
    if env.kind == "requirements_txt":
        buf.write("  base: python\n")
        buf.write(f"  python_version: \"{env.python_version or '3.11'}\"\n")
        if env.path:
            buf.write(f"  requirements_file: {env.path}\n")
    elif env.kind == "dockerfile":
        buf.write(f"  base: python  {_TODO_TAG} legacy used Dockerfile at {env.path}; reconstruct python_version and os_packages here\n")
        buf.write(f"  python_version: \"{env.python_version or '3.11'}\"\n")
        if env.path:
            buf.write(f"  requirements_file: requirements.txt  {_TODO_TAG} verify\n")
    else:
        buf.write(f"  base: python  {_TODO_TAG} v1 env kind was {env.kind!r}; choose v2 base\n")
        buf.write(f"  python_version: \"{env.python_version or '3.11'}\"\n")
    buf.write(f"  {_TODO_TAG} declare os_packages if your build needs apt-installed libs\n")
    buf.write("\n")


def _write_secrets(buf: TextIO, plan: ExtractedPlan) -> None:
    if not plan.repo.secrets_required:
        buf.write("secrets: []\n\n")
        return
    buf.write("secrets:\n")
    for s in plan.repo.secrets_required:
        buf.write(f"  - key: {s.key}\n")
        if s.purpose:
            buf.write(f"    purpose: {_yaml_str(s.purpose)}\n")
        if s.step_ids:
            buf.write(f"    used_by: [{', '.join(s.step_ids)}]\n")
    buf.write("\n")


def _write_data_sources(buf: TextIO, plan: ExtractedPlan) -> None:
    raw_entries: list[tuple[Step, StepAlternative]] = []
    for s in plan.steps:
        for alt in s.alternatives or ():
            if alt.kind == "manual_download" and alt.url:
                raw_entries.append((s, alt))

    buf.write("data_sources:\n")
    buf.write(f"  processed: []  {_TODO_TAG} list pre-processed download(s) (Tier 1) here if available\n")
    if not raw_entries:
        buf.write("  raw: []\n\n")
        return
    buf.write("  raw:\n")
    for s, alt in raw_entries:
        kind = "google_drive" if "drive.google.com" in alt.url else "http"
        buf.write(f"    - kind: {kind}\n")
        buf.write(f"      url: {alt.url}\n")
        if alt.expected_layout:
            buf.write(f"      expected_layout: [{', '.join(_yaml_str(p) for p in alt.expected_layout)}]\n")
        else:
            buf.write(f"      expected_layout: []  {_TODO_TAG} list expected files\n")
        buf.write(f"      satisfies: [{s.id}]\n")
    buf.write("\n")


def _write_steps(buf: TextIO, plan: ExtractedPlan) -> None:
    buf.write("steps:\n")
    buf.write(
        f"  {_TODO_TAG} v2025 step 2 (Data Preparation) merges the old data_collection\n"
        f"  {_TODO_TAG} and data_processing. If both appear below, consider merging them\n"
        f"  {_TODO_TAG} into a single data_preparation step (id + nine_step).\n"
    )
    for s in plan.steps:
        buf.write(f"  - id: {s.id}\n")
        buf.write(f"    nine_step: {_v2_nine_step(s.nine_step)}\n")
        buf.write(f"    required: {str(s.required).lower()}\n")
        if s.network != "none":
            buf.write(f"    network: {s.network}\n")
        if s.timeout_seconds and s.timeout_seconds != 1800:
            buf.write(f"    timeout_seconds: {s.timeout_seconds}\n")
        if s.command:
            buf.write(f"    command: {_yaml_str(s.command)}\n")
        buf.write(f"    inputs: []  {_TODO_TAG} declare inputs (files/dirs the step needs before run)\n")
        if s.produces:
            buf.write(f"    outputs: [{', '.join(_yaml_str(p) for p in s.produces)}]\n")
        else:
            buf.write(f"    outputs: []  {_TODO_TAG} declare outputs (files/dirs the step produces)\n")
        if s.depends_on:
            buf.write(f"    depends_on: [{', '.join(s.depends_on)}]\n")
    buf.write("\n")


def _write_expected(buf: TextIO, plan: ExtractedPlan) -> None:
    if not plan.expected_results:
        buf.write("expected: []\n\n")
        return
    buf.write("expected:\n")
    for er in plan.expected_results:
        buf.write(f"  - step_id: {er.step_id}\n")
        if er.metrics:
            buf.write("    metrics:\n")
            for m in er.metrics:
                canonical = _canonical_name(m.name)
                parsed, unparseable = _coerce_float(m.value)
                buf.write(f"      - name: {canonical}\n")
                buf.write(f"        display_name: {_yaml_str(m.name)}\n")
                if unparseable is not None:
                    buf.write(
                        f"        value: 0.0  {_TODO_TAG} could not parse "
                        f"{_yaml_str(unparseable)} as float\n"
                    )
                else:
                    buf.write(f"        value: {parsed}\n")
                tol_kind = m.tolerance.kind if m.tolerance else "relative"
                tol_value = m.tolerance.value if m.tolerance else 0.05
                buf.write(
                    f"        tolerance: {{kind: {tol_kind}, value: {tol_value}}}\n"
                )
        else:
            buf.write("    metrics: []\n")
        if er.charts:
            buf.write("    artifacts:\n")
            for c in er.charts:
                buf.write(f"      - path: {_yaml_str(c.produced_path)}\n")
                buf.write("        compare: visual_similarity\n")
                buf.write(f"        threshold: 0.7  {_TODO_TAG} tune threshold\n")
        else:
            buf.write("    artifacts: []\n")
    buf.write("\n")


def _write_nine_step_coverage(buf: TextIO, plan: ExtractedPlan) -> None:
    buf.write("nine_step_coverage:\n")
    # Translate the frozen v1 mapping into the v2025 taxonomy, merging the old
    # data_collection + data_processing coverage into step_2_data_preparation.
    merged: dict[str, tuple[bool, str | None, float]] = {}
    for k, entry in plan.nine_step_mapping.items():
        v2_key = _LEGACY_TO_V2_NINE_STEP.get(k, k)
        present, section, conf = entry.present, entry.section_heading, entry.confidence
        if v2_key in merged:
            prev_present, prev_section, prev_conf = merged[v2_key]
            present = prev_present or present
            section = prev_section or section
            conf = min(prev_conf, conf)
        merged[v2_key] = (present, section, conf)

    for key in NINE_STEP_KEYS:
        present, section, conf = merged.get(key, (False, None, 1.0))
        section_str = f'"{section}"' if section else "null"
        line = f"  {key}: {{present: {str(present).lower()}, section: {section_str}}}"
        if key == "step_3_forming_set_of_rules":
            line += f"  {_TODO_TAG} no v1 equivalent; set present:true if the README forms rules"
        elif conf < 0.6:
            line += f"  {_TODO_TAG} LLM uncertain (confidence={conf:.2f}); review"
        buf.write(line + "\n")


def _yaml_str(s: str) -> str:
    # Always double-quote so embedded special chars survive
    return '"' + s.replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# instrument_TODO.md generator
# ---------------------------------------------------------------------------


_INSTRUMENT_TODO_HEADER = """# Instrumentation TODO

`plutus transfer` produced a draft `.plutus/manifest.yaml.draft` from your
existing README, but cannot wire up the SDK calls inside your actual
scripts — that's manual. For each step below, locate the script the manifest's
`command:` invokes, and add the matching `pv.step(...)` block to its end.

Once every step's script is instrumented, rename `manifest.yaml.draft` to
`manifest.yaml` and run `plutus check` to verify.

---
"""


def instrument_todo_markdown(plan: ExtractedPlan) -> str:
    """Generate the companion .plutus/instrument_TODO.md content.

    Lists each step that has expected metrics, with a copy-paste-ready
    SDK snippet showing the ``pv.step(...)`` block the author must add to
    their reproducibility script. Steps with no expected metrics are
    skipped — there's nothing for the author to instrument there.
    """
    steps_by_id = {s.id: s for s in plan.steps}

    buf = StringIO()
    buf.write(_INSTRUMENT_TODO_HEADER)

    for er in plan.expected_results:
        if not er.metrics:
            continue

        step = steps_by_id.get(er.step_id)
        command = step.command if step and step.command else None
        header_suffix = f" (command: `{command}`)" if command else ""
        buf.write(f"\n## Step `{er.step_id}`{header_suffix}\n\n")
        buf.write("Add at the end of the script:\n\n")
        buf.write("```python\n")
        buf.write("import plutus_verify as pv\n\n")
        buf.write(f'with pv.step("{er.step_id}") as r:\n')

        # Compute column alignment so the snippet is readable
        canonical_names = [_canonical_name(m.name) for m in er.metrics]
        max_name_len = max(len(n) for n in canonical_names)

        for m, canonical in zip(er.metrics, canonical_names):
            padding = " " * (max_name_len - len(canonical))
            # The variable name on the RHS matches the canonical metric name;
            # author replaces with whatever local var holds the value.
            buf.write(
                f'    r.metric("{canonical}",{padding} {canonical},'
                f'{padding} unit="ratio")\n'
            )
        buf.write(
            "    # ... replace the RHS variables with the names you compute "
            "in this script ...\n"
        )
        buf.write("```\n")

    return buf.getvalue()

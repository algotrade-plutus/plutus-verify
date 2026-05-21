"""Reverse adapter: v1 ExtractedPlan → draft v2 manifest YAML text.

Used by `plutus transfer`. Best-effort; emits TODO markers wherever the v1
shape can't fully describe what v2 needs.
"""
from __future__ import annotations

from io import StringIO
from typing import TextIO

from plutus_verify.extract.plan import ExtractedPlan, Step, StepAlternative


_TODO_TAG = "# TODO(plutus-transfer):"


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
    for s in plan.steps:
        buf.write(f"  - id: {s.id}\n")
        buf.write(f"    nine_step: {s.nine_step}\n")
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
            buf.write("    headlines:\n")
            for m in er.metrics:
                buf.write(f"      - name: {m.name}\n")
                buf.write(f"        value: {m.value!r}\n")
                buf.write("        locate:\n")
                buf.write(f"          kind: {m.locate.kind}\n")
                if m.locate.path:
                    buf.write(f"          path: {_yaml_str(m.locate.path)}\n")
                if m.locate.jsonpath:
                    buf.write(f"          jsonpath: {_yaml_str(m.locate.jsonpath)}\n")
                if m.locate.row:
                    buf.write(f"          row: {_yaml_str(m.locate.row)}\n")
                if m.locate.col is not None:
                    buf.write(f"          col: {m.locate.col}\n")
                if m.locate.pattern:
                    buf.write(f"          pattern: {_yaml_str(m.locate.pattern)}\n")
                buf.write(f"        tolerance: {{kind: {m.tolerance.kind}, value: {m.tolerance.value}}}\n")
        else:
            buf.write("    headlines: []\n")
        if er.charts:
            buf.write("    reference_outputs:\n")
            for c in er.charts:
                buf.write(f"      - path: {_yaml_str(c.produced_path)}\n")
                buf.write("        compare: visual_similarity\n")
                buf.write(f"        threshold: 0.7  {_TODO_TAG} tune threshold\n")
        else:
            buf.write("    reference_outputs: []\n")
    buf.write("\n")


def _write_nine_step_coverage(buf: TextIO, plan: ExtractedPlan) -> None:
    buf.write("nine_step_coverage:\n")
    for k, entry in plan.nine_step_mapping.items():
        section = f'"{entry.section_heading}"' if entry.section_heading else "null"
        line = f"  {k}: {{present: {str(entry.present).lower()}, section: {section}}}"
        if entry.confidence < 0.6:
            line += f"  {_TODO_TAG} LLM uncertain (confidence={entry.confidence:.2f}); review"
        buf.write(line + "\n")


def _yaml_str(s: str) -> str:
    # Always double-quote so embedded special chars survive
    return '"' + s.replace('"', '\\"') + '"'

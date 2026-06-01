"""Per-step staging for the v2 runtime (v0.2.10+).

Closes the runtime-mount leak surfaced by Group09-BuyHighSellLow: instead
of mounting the maintainer's cwd onto the container, each step runs against
a filtered copy that respects ``.dockerignore`` (and ``step.inputs`` when
declared). Step outputs flow back to cwd via :func:`extract_outputs`.

The orchestrator's contract with the runner (a duck-typed ``Runner`` that
takes ``cwd=`` and other kwargs) is unchanged — the orchestrator just
hands the runner the staging path in place of the repo path.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pathspec

from plutus_verify.spec.manifest import Step


def _load_ignore_spec(cwd: Path) -> pathspec.PathSpec:
    dockerignore = cwd / ".dockerignore"
    if not dockerignore.exists():
        return pathspec.PathSpec.from_lines("gitignore", [])
    return pathspec.PathSpec.from_lines("gitignore", dockerignore.read_text().splitlines())


def populate_staging(cwd: Path, staging: Path, step: Step) -> None:
    """Copy ``cwd`` into ``staging``, filtered by ``.dockerignore`` and
    (when declared) ``step.inputs``.

    Empty ``step.inputs`` means ``.dockerignore`` alone governs — matches
    v0.2.9 behavior for repos that haven't tightened their manifest yet.
    Non-empty ``step.inputs`` adds a positive filter on top: only paths
    matching those patterns are copied.
    """
    spec = _load_ignore_spec(cwd)
    inputs_spec: pathspec.PathSpec | None = None
    if step.inputs:
        inputs_spec = pathspec.PathSpec.from_lines("gitignore", list(step.inputs))
    for src in cwd.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(cwd)
        rel_posix = rel.as_posix()
        if spec.match_file(rel_posix):
            continue
        if inputs_spec is not None and not inputs_spec.match_file(rel_posix):
            continue
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def extract_outputs(staging: Path, cwd: Path, step: Step) -> None:
    """Copy framework bookkeeping + manifest-declared outputs back to cwd.

    The orchestrator reads ``.plutus/run/<step_id>/{stdout,stderr,meta.json}``
    to determine step outcome — that directory always comes back. Any
    additional paths the maintainer declared via ``step.outputs`` are also
    copied back. Anything else the script wrote inside staging is dropped.
    """
    run_dir = staging / ".plutus" / "run" / step.id
    if run_dir.exists():
        dest = cwd / ".plutus" / "run" / step.id
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(run_dir, dest)

    if not step.outputs:
        return
    outputs_spec = pathspec.PathSpec.from_lines("gitignore", list(step.outputs))
    for src in staging.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(staging)
        if rel.parts[:3] == (".plutus", "run", step.id):
            continue
        if not outputs_spec.match_file(rel.as_posix()):
            continue
        dest = cwd / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

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
    """Harvest framework bookkeeping + manifest-declared outputs from staging.

    The orchestrator reads ``.plutus/run/<step_id>/{stdout,stderr,meta.json}``
    to determine step outcome — that directory always comes back to ``cwd``.

    Declared ``step.outputs`` files are harvested to the per-step results buffer
    ``cwd/.plutus/results/<step_id>/<path>`` instead of the working-tree root, so
    a *verification* run never mutates the author's committed files (L2). Anything
    else the script wrote inside staging is dropped.
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
    results_dir = cwd / ".plutus" / "results" / step.id
    outputs_spec = pathspec.PathSpec.from_lines("gitignore", list(step.outputs))
    for src in staging.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(staging)
        # Never harvest framework dirs that may exist inside staging.
        if rel.parts[:2] == (".plutus", "run"):
            continue
        if rel.parts[:2] == (".plutus", "results"):
            continue
        if not outputs_spec.match_file(rel.as_posix()):
            continue
        dest = results_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def stage_data_cache(repo_path: Path, staging: Path, step: Step) -> None:
    """Overlay downloaded data from ``.plutus/cache/`` into ``staging`` at the
    declared layout paths.

    Data sources are fetched into the gitignored ``.plutus/cache/`` (not the
    working tree, so ``check`` stays read-only — Bug 3). A step reads data at its
    declared path (e.g. ``data/raw/x.parquet``), so the cache's prefix is
    stripped on the way in: ``.plutus/cache/<path>`` → ``staging/<path>``. As with
    :func:`stage_prior_results`, a non-empty ``step.inputs`` filters what's
    injected (hermeticity); empty means inject everything cached.
    """
    cache_root = repo_path / ".plutus" / "cache"
    if not cache_root.exists():
        return
    inputs_spec: pathspec.PathSpec | None = None
    if step.inputs:
        inputs_spec = pathspec.PathSpec.from_lines("gitignore", list(step.inputs))
    for src in cache_root.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(cache_root)
        if inputs_spec is not None and not inputs_spec.match_file(rel.as_posix()):
            continue
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def harvest_committed_outputs(repo_path: Path, step: Step) -> None:
    """Mirror an ``artifact_check`` step's *committed* outputs from the working
    tree into ``.plutus/results/<step_id>/``.

    ``artifact_check`` steps ship their outputs (no execution), so the produced
    bytes already live in the working tree. Copying them into the results buffer
    lets the compare phase read uniformly from ``.plutus/results/<step>/`` for
    every step regardless of how it was produced.
    """
    if not step.outputs:
        return
    results_dir = repo_path / ".plutus" / "results" / step.id
    spec = pathspec.PathSpec.from_lines("gitignore", list(step.outputs))
    for src in repo_path.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(repo_path)
        if rel.parts[:1] == (".plutus",):
            continue
        if not spec.match_file(rel.as_posix()):
            continue
        dest = results_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def stage_prior_results(repo_path: Path, staging: Path, step: Step) -> None:
    """Inject earlier steps' harvested outputs into ``staging`` — the inter-step
    data bus (Decision 1, option a).

    Each earlier executed step's declared outputs live at
    ``repo_path/.plutus/results/<step_id>/<path>``. A later step's code reads the
    *declared* path (e.g. ``data/processed/x.parquet``), so the buffer's
    step-keyed prefix is stripped on the way in: ``.plutus/results/<step>/<path>``
    → ``staging/<path>``. This reproduces the pipeline end-to-end without writing
    the working tree, and works even for intermediates that are not committed
    (the first-snapshot case). Committed inputs arrive separately via
    :func:`populate_staging`.

    When ``step.inputs`` is declared (a non-empty positive filter), only prior
    outputs matching it are injected — the same hermeticity guarantee
    :func:`populate_staging` gives for the committed tree, so an unrelated
    earlier step's output can't leak into a step that didn't ask for it. Empty
    ``step.inputs`` means inject everything (``.dockerignore`` governs the copy).
    """
    results_root = repo_path / ".plutus" / "results"
    if not results_root.exists():
        return
    inputs_spec: pathspec.PathSpec | None = None
    if step.inputs:
        inputs_spec = pathspec.PathSpec.from_lines("gitignore", list(step.inputs))
    for step_dir in sorted(results_root.iterdir()):
        if not step_dir.is_dir():
            continue
        for src in step_dir.rglob("*"):
            if src.is_dir():
                continue
            rel = src.relative_to(step_dir)
            if inputs_spec is not None and not inputs_spec.match_file(rel.as_posix()):
                continue
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

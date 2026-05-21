"""Pre- and post-execution existence checks for declared inputs/outputs."""
from __future__ import annotations

from pathlib import Path

from plutus_verify.spec.manifest import Step


class PreflightError(RuntimeError):
    """A declared input was missing before a step, or an output after."""


def assert_inputs_present(step: Step, repo_path: Path) -> None:
    missing = [p for p in step.inputs if not _path_matches(repo_path, p)]
    if missing:
        raise PreflightError(
            f"step '{step.id}' missing input(s) before run: {missing}"
        )


def assert_outputs_present(step: Step, repo_path: Path) -> None:
    missing = [p for p in step.outputs if not _path_matches(repo_path, p)]
    if missing:
        raise PreflightError(
            f"step '{step.id}' missing output(s) after run: {missing}"
        )


def _path_matches(repo_path: Path, entry: str) -> bool:
    if any(ch in entry for ch in "*?["):
        return any(True for _ in repo_path.glob(entry.rstrip("/")))
    return (repo_path / entry).exists()

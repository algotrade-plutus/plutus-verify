"""`plutus snapshot`: capture step outputs into `.plutus/expected/`."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.scaffold.check import CheckResult, scaffold_check
from plutus_verify.scaffold.manifest_edit import (
    ManifestEditError,
    update_metric_values as _update_metric_values_in_yaml,
)
from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime.results import (
    MalformedResultsError,
    MissingResultsError,
    load_results,
)


def _copy_into(src: Path, dest: Path) -> int:
    """Copy a file or directory tree from ``src`` to ``dest`` (replacing any
    existing ``dest``). Returns the number of files written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        return sum(1 for _ in dest.rglob("*") if _.is_file())
    shutil.copy2(src, dest)
    return 1


@dataclass
class SnapshotResult:
    files_copied: int
    metrics_updated: int = 0
    check_result: Optional[CheckResult] = None
    notes: list[str] = field(default_factory=list)


def scaffold_snapshot(
    repo_path: Path,
    *,
    run_check_first: bool = True,
    image_builder: Optional[Callable[[str, Path], str]] = None,
    runner: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    secrets: Optional[dict[str, str]] = None,
    update_artifacts: bool = True,
    update_metric_values: bool = True,
) -> SnapshotResult:
    manifest = load_manifest(repo_path)

    check_result: Optional[CheckResult] = None
    if run_check_first:
        if image_builder is None or runner is None:
            raise ValueError("run_check_first=True requires image_builder and runner")
        check_result = scaffold_check(
            repo_path,
            image_builder=image_builder,
            runner=runner,
            vision_client=vision_client,
            secrets=secrets or {},
        )
        if check_result.exit_code == 2:
            raise RuntimeError(
                "plutus check failed (exit 2 — required step failed); "
                "refusing to snapshot outputs from a failing run"
            )

    notes: list[str] = []
    files_copied = 0

    if update_artifacts:
        expected_root = repo_path / ".plutus" / "expected"
        expected_root.mkdir(parents=True, exist_ok=True)

        for step in manifest.steps:
            step_dir = expected_root / step.id
            step_dir.mkdir(parents=True, exist_ok=True)
            # After an in-container run (run_check_first), produced bytes live in
            # the per-step results buffer; bless from there and also write a
            # human-facing copy back to the working tree (result/). With --no-run
            # (run_check_first=False) the author's local outputs at the declared
            # paths are the source, and there's nothing extra to write back.
            if run_check_first:
                source_base = repo_path / ".plutus" / "results" / step.id
                result_base: Optional[Path] = repo_path
            else:
                source_base = repo_path
                result_base = None

            for output in step.outputs:
                pattern = output.rstrip("/")
                src = source_base / pattern
                if src.exists():
                    matches = [src]
                elif any(ch in output for ch in "*?["):
                    matches = list(source_base.glob(pattern))
                else:
                    matches = []
                if not matches:
                    notes.append(f"step '{step.id}': output '{output}' missing — skipped")
                    continue
                for m in matches:
                    rel = m.relative_to(source_base)
                    files_copied += _copy_into(m, step_dir / rel)
                    if result_base is not None:
                        _copy_into(m, result_base / rel)

    metrics_updated = 0
    if update_metric_values:
        updates: dict[str, dict[str, float]] = {}
        for er in manifest.expected:
            if not er.metrics:
                continue
            try:
                results = load_results(repo_path, step_id=er.step_id)
            except MissingResultsError:
                notes.append(
                    f"step '{er.step_id}': no results.json — metrics not updated"
                )
                continue
            except MalformedResultsError as exc:
                notes.append(
                    f"step '{er.step_id}': malformed results.json — {exc}"
                )
                continue
            declared_names = {h.name for h in er.metrics}
            step_updates = {
                m.name: m.value for m in results.metrics if m.name in declared_names
            }
            if step_updates:
                updates[er.step_id] = step_updates

        if updates:
            manifest_path = repo_path / ".plutus" / "manifest.yaml"
            try:
                count, edit_warnings = _update_metric_values_in_yaml(
                    manifest_path, updates
                )
                metrics_updated = count
                notes.extend(edit_warnings)
            except ManifestEditError as exc:
                notes.append(f"manifest edit failed: {exc}")

    return SnapshotResult(
        files_copied=files_copied,
        metrics_updated=metrics_updated,
        check_result=check_result,
        notes=notes,
    )

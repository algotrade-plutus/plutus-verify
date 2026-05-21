"""`plutus snapshot`: capture step outputs into `.plutus/expected/`."""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.scaffold.check import CheckResult, scaffold_check
from plutus_verify.spec.loader import load_manifest


@dataclass
class SnapshotResult:
    files_copied: int
    check_result: Optional[CheckResult]
    notes: list[str] = field(default_factory=list)


def scaffold_snapshot(
    repo_path: Path,
    *,
    run_check_first: bool = True,
    image_builder: Optional[Callable[[str, Path], str]] = None,
    runner: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    secrets: Optional[dict[str, str]] = None,
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

    expected_root = repo_path / ".plutus" / "expected"
    expected_root.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []
    files_copied = 0
    for step in manifest.steps:
        step_dir = expected_root / step.id
        step_dir.mkdir(parents=True, exist_ok=True)
        for output in step.outputs:
            src = repo_path / output.rstrip("/")
            if not src.exists() and any(ch in output for ch in "*?["):
                matches = list(repo_path.glob(output.rstrip("/")))
                if not matches:
                    notes.append(f"step '{step.id}': output '{output}' missing — skipped")
                    continue
                for m in matches:
                    rel = m.relative_to(repo_path)
                    dest = step_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if m.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(m, dest)
                    else:
                        shutil.copy2(m, dest)
                    files_copied += 1
                continue
            if not src.exists():
                notes.append(f"step '{step.id}': output '{output}' missing — skipped")
                continue
            rel = Path(output.rstrip("/"))
            dest = step_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                files_copied += sum(1 for _ in dest.rglob("*") if _.is_file())
            else:
                shutil.copy2(src, dest)
                files_copied += 1

    return SnapshotResult(files_copied=files_copied, check_result=check_result, notes=notes)

"""`plutus init`: scaffold `.plutus/manifest.yaml` + `.github/workflows/plutus.yml`.

Non-interactive. Idempotent unless `force=True`. Never destroys existing files
without explicit consent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from plutus_verify.scaffold.templates import MANIFEST_SKELETON, WORKFLOW_YAML


@dataclass(frozen=True)
class InitResult:
    repo_path: Path
    created_manifest: bool
    created_workflow: bool
    created_expected_dir: bool


def scaffold_init(repo_path: Path, *, force: bool = False) -> InitResult:
    plutus_dir = repo_path / ".plutus"
    plutus_dir.mkdir(exist_ok=True)
    expected_dir = plutus_dir / "expected"
    created_expected = not expected_dir.exists()
    expected_dir.mkdir(exist_ok=True)

    manifest_path = plutus_dir / "manifest.yaml"
    created_manifest = False
    if force or not manifest_path.exists():
        manifest_path.write_text(MANIFEST_SKELETON)
        created_manifest = True

    workflow_dir = repo_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / "plutus.yml"
    created_workflow = False
    if force or not workflow_path.exists():
        workflow_path.write_text(WORKFLOW_YAML)
        created_workflow = True

    return InitResult(
        repo_path=repo_path,
        created_manifest=created_manifest,
        created_workflow=created_workflow,
        created_expected_dir=created_expected,
    )

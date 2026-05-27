"""`plutus check`: run the native v2 pipeline locally against a working copy."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime import V2RuntimeResult, run_v2_pipeline


@dataclass(frozen=True)
class CheckResult:
    runtime_result: V2RuntimeResult
    exit_code: int


def scaffold_check(
    repo_path: Path,
    *,
    image_builder: Callable[[str, Path], str],
    runner: Any,
    vision_client: Optional[Any],
    secrets: dict[str, str],
    force_data_tier: Optional[str] = None,
) -> CheckResult:
    # Wipe any stale .plutus/run/ artifacts so the comparison phase reads
    # only what THIS run wrote. Without this guard, a previous host-side or
    # container-side run can leave results.json files that match the manifest
    # exactly (because the manifest was snapshotted from them), producing
    # false-positive "ok" comparisons even when this run's step crashed.
    repo_path = Path(repo_path).resolve()
    run_dir = repo_path / ".plutus" / "run"
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)

    manifest = load_manifest(repo_path)
    runtime = run_v2_pipeline(
        manifest,
        repo_path=repo_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=vision_client,
        secrets=secrets,
        force_data_tier=force_data_tier,
    )
    return CheckResult(runtime_result=runtime, exit_code=_exit_code(manifest, runtime))


def _exit_code(manifest, runtime: V2RuntimeResult) -> int:
    """0 = all required steps + metrics pass; 1 = soft fail; 2 = required hard fail."""
    required_ids = {s.id for s in manifest.steps if s.required}

    for sid, sr in runtime.step_results.items():
        if sid in required_ids and sr.exit_code != 0 and sr.skipped_reason is None:
            return 2
        if sid in required_ids and sr.preflight_error is not None:
            return 2

    for step_id, hrs in runtime.metric_results.items():
        for name, hr in hrs.items():
            if not hr.ok:
                return 1
    for step_id, refs in runtime.artifact_results.items():
        for r in refs:
            if not r.ok:
                return 1
    return 0

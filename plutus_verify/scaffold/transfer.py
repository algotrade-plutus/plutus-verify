"""`plutus transfer`: convert a legacy README-based repo into a v2 draft manifest."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from plutus_verify.extract import extract_plan
from plutus_verify.scaffold.extract_to_v2 import to_v2_manifest_yaml


class TransferError(RuntimeError):
    """Transfer cannot proceed (missing README, existing manifest, etc.)."""


@dataclass(frozen=True)
class TransferResult:
    draft_path: Path
    plan_summary: str


_AttemptCallback = Callable[[str, str, Optional[Exception]], None]


def scaffold_transfer(
    repo_path: Path,
    *,
    llm_client: Any,
    on_attempt: Optional[_AttemptCallback] = None,
    first_attempt_idle_seconds: float = 180.0,
    retry_idle_seconds: Optional[float] = None,
    max_retries: int = 3,
) -> TransferResult:
    readme = repo_path / "README.md"
    if not readme.exists():
        raise TransferError(f"no README.md in {repo_path}")
    plutus_dir = repo_path / ".plutus"
    if (plutus_dir / "manifest.yaml").exists():
        raise TransferError(
            f"{plutus_dir / 'manifest.yaml'} already exists — refusing to overwrite. "
            "Delete it first if you want to re-transfer."
        )

    plan = extract_plan(
        readme.read_text(),
        llm_client,
        first_attempt_idle_seconds=first_attempt_idle_seconds,
        retry_idle_seconds=retry_idle_seconds,
        max_retries=max_retries,
        on_attempt=on_attempt,
    )
    draft_yaml = to_v2_manifest_yaml(plan)

    plutus_dir.mkdir(exist_ok=True)
    draft_path = plutus_dir / "manifest.yaml.draft"
    draft_path.write_text(draft_yaml)

    summary = (
        f"transferred {plan.repo.name}: {len(plan.steps)} steps, "
        f"{sum(len(er.metrics) for er in plan.expected_results)} metrics"
    )
    return TransferResult(draft_path=draft_path, plan_summary=summary)

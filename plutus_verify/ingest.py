"""Ingest stage: clone the repo (or use a local path) and capture metadata."""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

GitRunner = Callable[[list[str], Optional[Path]], str]
"""Signature: ``runner(args, cwd) -> stdout``. Injectable for tests."""


class IngestError(RuntimeError):
    """Raised when ingestion can't proceed (e.g., missing README)."""


@dataclass(frozen=True)
class IngestResult:
    git_url: str
    repo_path: Path
    readme_path: Path
    commit_sha: str
    branch: str
    meta_path: Path


def _default_git_runner(args: list[str], cwd: Optional[Path] = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def resume_existing_run(run_dir: Path) -> IngestResult:
    """Load an existing run dir's ingest state from ``meta.json``.

    Used when re-running the pipeline on an already-cloned repo: the CLI
    detects that ``out_dir`` already has meta.json + repo/ and skips a fresh
    clone. This is what makes ``--use-plan`` / ``--skip-build`` re-runs work
    on the existing run dir.
    """
    run_dir = Path(run_dir).resolve()
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        raise IngestError(f"meta.json missing in {run_dir}; cannot resume")
    meta = json.loads(meta_path.read_text())
    # Always return absolute paths — Docker -v rejects relative paths.
    repo_path = Path(meta["repo_path"]).resolve()
    readme_path = Path(meta["readme_path"]).resolve()
    if not readme_path.exists():
        raise IngestError(f"README.md missing in resumed repo: {readme_path}")
    return IngestResult(
        git_url=meta["git_url"],
        repo_path=repo_path,
        readme_path=readme_path,
        commit_sha=meta["commit_sha"],
        branch=meta["branch"],
        meta_path=meta_path,
    )


def ingest(
    source: str,
    run_dir: Path,
    *,
    ref: Optional[str] = None,
    skip_clone: bool = False,
    git_runner: GitRunner = _default_git_runner,
) -> IngestResult:
    """Clone ``source`` into ``run_dir/repo`` and capture metadata.

    If ``skip_clone`` is true, treat ``source`` as a local repo path and skip
    git entirely (used by the ``--skip-clone`` CLI flag for fast iteration).
    """
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    if skip_clone:
        repo_path = Path(source).resolve()
        if not repo_path.exists():
            raise IngestError(f"local repo path does not exist: {repo_path}")
        commit_sha = "local"
        branch = "local"
    else:
        repo_path = (run_dir / "repo").resolve()
        if repo_path.exists():
            raise IngestError(f"repo dir already exists; aborting: {repo_path}")
        clone_args = ["clone", "--depth=1"]
        if ref:
            clone_args += ["--branch", ref]
        clone_args += ["--", source, str(repo_path)]
        git_runner(clone_args, None)
        commit_sha = git_runner(["rev-parse", "HEAD"], repo_path).strip()
        branch = git_runner(["rev-parse", "--abbrev-ref", "HEAD"], repo_path).strip()

    readme_path = repo_path / "README.md"
    if not readme_path.exists():
        raise IngestError(f"README.md not found in repo: {readme_path}")

    meta_path = run_dir / "meta.json"
    result = IngestResult(
        git_url=source,
        repo_path=repo_path,
        readme_path=readme_path,
        commit_sha=commit_sha,
        branch=branch,
        meta_path=meta_path,
    )
    meta_path.write_text(
        json.dumps(
            {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(result).items()},
            indent=2,
        )
    )
    return result

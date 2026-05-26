"""Build runner: legacy repo2docker path + new auto-fixing slim-Python path."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

from plutus_verify.util.progress import NullProgress, Progress


class BuildError(RuntimeError):
    """Raised when the build can't produce an image even after fixers."""


@dataclass(frozen=True)
class BuildAdjustment:
    """One fix the builder applied to make the repo build."""
    phase: str          # "pre_build" | "post_build" | "llm"
    kind: str           # e.g. "encoding", "missing_dep", "psycopg_binary", "apt_dev_header"
    description: str    # short human-readable line for report.md


@dataclass(frozen=True)
class BuildResult:
    image: str
    adjustments: tuple[BuildAdjustment, ...] = ()


def _hash_secrets(secrets_path: Optional[Path]) -> str:
    if not secrets_path or not secrets_path.exists():
        return "nosecrets"
    h = hashlib.sha256(secrets_path.read_bytes()).hexdigest()
    return h[:12]


# ---------------------------------------------------------------------------
# Legacy entry point: repo2docker. Kept for parity but no longer the default.
# ---------------------------------------------------------------------------


def build_image(
    repo_path: Path,
    *,
    commit_sha: str,
    image_prefix: str = "plutus-run",
    secrets_path: Optional[Path] = None,
    secrets_dest: str = "/srv/repo/.env",
    extra_args: Sequence[str] = (),
    repo2docker_bin: str = "jupyter-repo2docker",
    docker_bin: str = "docker",
) -> BuildResult:
    """Legacy repo2docker-based build (unchanged behaviour for back-compat)."""
    base_tag = f"{image_prefix}-{commit_sha[:7]}-{_hash_secrets(secrets_path)}"
    cmd = [
        repo2docker_bin,
        "--no-run",
        "--image-name",
        base_tag,
        *extra_args,
        str(repo_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BuildError(
            f"repo2docker failed (exit {proc.returncode}):\n{proc.stderr or proc.stdout}"
        )

    if secrets_path is not None and secrets_path.exists():
        overlay_tag = f"{base_tag}-secrets"
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "secrets.env").write_bytes(secrets_path.read_bytes())
            (tdp / "Dockerfile").write_text(
                f"FROM {base_tag}\nCOPY secrets.env {secrets_dest}\n"
            )
            proc = subprocess.run(
                [docker_bin, "build", "-t", overlay_tag, str(tdp)],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise BuildError(
                    f"docker build (secrets overlay) failed:\n{proc.stderr or proc.stdout}"
                )
        return BuildResult(image=overlay_tag)

    return BuildResult(image=base_tag)


# ---------------------------------------------------------------------------
# New default: auto-fixing slim-Python builder.
# ---------------------------------------------------------------------------


_DockerInvoker = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
"""Allows tests to stub the docker shell-out without monkey-patching subprocess."""


def _default_docker(args: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True)


def build_with_fixers(
    repo_path: Path,
    *,
    commit_sha: str,
    image_prefix: str = "plutus-run",
    secrets_path: Optional[Path] = None,
    secrets_dest: str = "/srv/repo/.env",
    llm_fixer: Optional[Callable[[str, Path], "list[dict] | None"]] = None,
    docker_invoker: _DockerInvoker = _default_docker,
    docker_bin: str = "docker",
    max_attempts: int = 3,
    progress: Optional[Progress] = None,
    artifacts_dir: Optional[Path] = None,
) -> BuildResult:
    """Build the repo with deterministic + LLM-assisted fixers.

    Pipeline:
      1. Pre-build fixers (deterministic) — applied to repo on disk.
      2. Attempt #1.
      3. On failure: post-build fixers (deterministic, parses error log).
      4. Attempt #2.
      5. On failure: LLM fixer (constrained-op JSON).
      6. Attempt #3.
      7. Final failure -> raise BuildError with all adjustments + last log.

    Returns a :class:`BuildResult` whose ``adjustments`` lists every fix
    applied so the reporter can surface them as findings.

    If ``progress`` is given, emit a substep per attempt. If
    ``artifacts_dir`` is given, persist ``attempt_<n>.log`` (full docker
    output) and ``attempt_<n>.fixers.json`` (adjustments applied for that
    attempt) under it.
    """
    from plutus_verify.builder.dockerfile import generate_dockerfile
    from plutus_verify.builder.fixers import (
        run_pre_build_fixers,
        run_post_build_fixers,
    )

    prog = progress or NullProgress()
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)

    adjustments: list[BuildAdjustment] = []
    apt_packages: list[str] = []
    secrets_hash = _hash_secrets(secrets_path)
    base_tag = f"{image_prefix}-{commit_sha[:7]}-{secrets_hash}"

    # Phase 1 — pre-build fixers
    pre_fixes = run_pre_build_fixers(repo_path)
    adjustments.extend(pre_fixes)
    if pre_fixes:
        prog.substep(
            "build",
            f"pre-build fixers applied: {', '.join(f.kind for f in pre_fixes)}",
        )

    last_log = ""
    image_tag: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        # Always regenerate the Dockerfile from the (possibly updated) apt list
        dockerfile = generate_dockerfile(apt_packages=apt_packages)
        df_path = repo_path / "Dockerfile.plutus-verify"
        df_path.write_text(dockerfile)
        prog.substep(
            "build",
            f"attempt {attempt}/{max_attempts}: docker build (apt: {apt_packages or '—'})",
        )
        adjustments_before_attempt = len(adjustments)
        try:
            proc = docker_invoker(
                [docker_bin, "build", "-t", base_tag, "-f", str(df_path), str(repo_path)]
            )
        finally:
            # Don't leave the generated Dockerfile in the repo across runs
            try:
                df_path.unlink()
            except FileNotFoundError:
                pass
        last_log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        _persist_attempt_log(artifacts_dir, attempt, last_log)
        if proc.returncode == 0:
            image_tag = base_tag
            prog.substep("build", f"attempt {attempt}/{max_attempts}: ok — image {base_tag}")
            break

        prog.substep(
            "build",
            f"attempt {attempt}/{max_attempts}: docker build FAILED (exit {proc.returncode})",
        )

        # Build failed — figure out which fixers to run for the next attempt
        if attempt == 1:
            # First failure: run deterministic post-build fixers
            post_fixes, new_apt = run_post_build_fixers(repo_path, last_log)
            adjustments.extend(post_fixes)
            apt_packages.extend(p for p in new_apt if p not in apt_packages)
            if post_fixes or new_apt:
                summary = (
                    [f.kind for f in post_fixes]
                    + [f"apt:{p}" for p in new_apt]
                )
                prog.substep("build", f"post-build fixers applied: {', '.join(summary)}")
            if not post_fixes and not new_apt:
                # Nothing deterministic to try — skip directly to LLM
                if llm_fixer is None:
                    _persist_attempt_fixers(
                        artifacts_dir,
                        attempt,
                        adjustments[adjustments_before_attempt:],
                    )
                    raise BuildError(
                        f"build failed on attempt {attempt}; "
                        f"no deterministic fix found and no LLM fixer configured.\n"
                        f"Last log tail:\n{_tail(last_log)}"
                    )
                prog.substep("build", f"attempt {attempt}: invoking LLM fixer")
                _apply_llm_fix(llm_fixer, repo_path, last_log, adjustments, apt_packages)
                if len(adjustments) > adjustments_before_attempt:
                    prog.substep(
                        "build",
                        f"LLM fixer applied: "
                        f"{', '.join(a.kind for a in adjustments[adjustments_before_attempt:])}",
                    )
        else:
            # Second failure: invoke LLM
            if llm_fixer is None:
                _persist_attempt_fixers(
                    artifacts_dir,
                    attempt,
                    adjustments[adjustments_before_attempt:],
                )
                raise BuildError(
                    f"build failed after deterministic fixers; LLM fixer not configured.\n"
                    f"Last log tail:\n{_tail(last_log)}"
                )
            prog.substep("build", f"attempt {attempt}: invoking LLM fixer")
            _apply_llm_fix(llm_fixer, repo_path, last_log, adjustments, apt_packages)
            if len(adjustments) > adjustments_before_attempt:
                prog.substep(
                    "build",
                    f"LLM fixer applied: "
                    f"{', '.join(a.kind for a in adjustments[adjustments_before_attempt:])}",
                )

        _persist_attempt_fixers(
            artifacts_dir,
            attempt,
            adjustments[adjustments_before_attempt:],
        )

    if image_tag is None:
        raise BuildError(
            f"build failed after {max_attempts} attempts. "
            f"{len(adjustments)} adjustment(s) applied.\nLast log tail:\n{_tail(last_log)}"
        )

    # Secrets overlay (unchanged from legacy path)
    if secrets_path is not None and secrets_path.exists():
        overlay_tag = f"{base_tag}-secrets"
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "secrets.env").write_bytes(secrets_path.read_bytes())
            (tdp / "Dockerfile").write_text(
                f"FROM {image_tag}\nCOPY secrets.env {secrets_dest}\n"
            )
            proc = docker_invoker(
                [docker_bin, "build", "-t", overlay_tag, str(tdp)]
            )
            if proc.returncode != 0:
                raise BuildError(
                    f"secrets overlay build failed:\n{(proc.stderr or proc.stdout)}"
                )
        return BuildResult(image=overlay_tag, adjustments=tuple(adjustments))

    return BuildResult(image=image_tag, adjustments=tuple(adjustments))


def _persist_attempt_log(
    artifacts_dir: Optional[Path], attempt: int, log: str
) -> None:
    if artifacts_dir is None:
        return
    (artifacts_dir / f"attempt_{attempt}.log").write_text(log)


def _persist_attempt_fixers(
    artifacts_dir: Optional[Path],
    attempt: int,
    adjustments: list[BuildAdjustment],
) -> None:
    if artifacts_dir is None:
        return
    payload = [
        {"phase": a.phase, "kind": a.kind, "description": a.description}
        for a in adjustments
    ]
    (artifacts_dir / f"attempt_{attempt}.fixers.json").write_text(
        json.dumps(payload, indent=2)
    )


def _apply_llm_fix(
    llm_fixer: Callable[[str, Path], "list[dict] | None"],
    repo_path: Path,
    error_log: str,
    adjustments: list[BuildAdjustment],
    apt_packages: list[str],
) -> None:
    """Run the LLM fixer once and apply its returned ops."""
    from plutus_verify.builder.llm_fixer import apply_llm_ops

    ops = llm_fixer(error_log, repo_path) or []
    fix_descriptions, new_apt = apply_llm_ops(ops, repo_path)
    adjustments.extend(fix_descriptions)
    apt_packages.extend(p for p in new_apt if p not in apt_packages)


def _tail(s: str, n: int = 50) -> str:
    lines = s.splitlines()
    return "\n".join(lines[-n:])

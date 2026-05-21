"""Real Docker image builder for the v2 native runtime.

Writes the generated Dockerfile to ``<repo_path>/.plutus/Dockerfile.generated``
and invokes ``docker build`` against the repo as context. Returns the image
tag the orchestrator will pass to the runner.

Kept in its own module so the orchestrator stays Docker-agnostic and tests can
inject fakes without importing real Docker.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Callable, Optional


class BuildError(RuntimeError):
    """`docker build` exited non-zero, or `docker` was not available."""


def build_image(
    dockerfile_text: str,
    repo_path: Path,
    *,
    image_prefix: str = "plutus-v2",
    docker_runner: Optional[Callable[[list[str], Path], subprocess.CompletedProcess]] = None,
) -> str:
    """Build a Docker image from `dockerfile_text` with `repo_path` as the
    build context. Returns the image tag (a content-hash of the Dockerfile).

    The Dockerfile is written to ``<repo_path>/.plutus/Dockerfile.generated``
    so users can inspect it after a run.
    """
    repo_path = repo_path.resolve()
    plutus_dir = repo_path / ".plutus"
    plutus_dir.mkdir(exist_ok=True)
    dockerfile_path = plutus_dir / "Dockerfile.generated"
    dockerfile_path.write_text(dockerfile_text)

    digest = hashlib.sha256(dockerfile_text.encode()).hexdigest()[:12]
    image_tag = f"{image_prefix}:{digest}"

    cmd = [
        "docker", "build",
        "--tag", image_tag,
        "--file", str(dockerfile_path),
        str(repo_path),
    ]
    runner = docker_runner or _default_docker_runner
    proc = runner(cmd, repo_path)
    if proc.returncode != 0:
        raise BuildError(
            f"docker build failed (exit {proc.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stdout (last 2KB): {proc.stdout[-2000:] if proc.stdout else ''}\n"
            f"  stderr (last 2KB): {proc.stderr[-2000:] if proc.stderr else ''}"
        )
    return image_tag


def _default_docker_runner(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run `docker build` and stream output to stdout/stderr in real time
    while also capturing it for the error message."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return proc


def make_image_builder(
    *, image_prefix: str = "plutus-v2"
) -> Callable[[str, Path], str]:
    """Return an `image_builder` callable matching the orchestrator's signature.

    Usage::

        from plutus_verify.spec.runtime.real_image_builder import make_image_builder
        from plutus_verify.spec.runtime import run_v2_pipeline

        result = run_v2_pipeline(
            manifest,
            repo_path=repo,
            image_builder=make_image_builder(),
            runner=DockerRunner(),
            ...,
        )
    """

    def _builder(dockerfile_text: str, repo_path: Path) -> str:
        return build_image(dockerfile_text, repo_path, image_prefix=image_prefix)

    return _builder

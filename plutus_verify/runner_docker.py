"""Real :class:`Runner` implementation backed by the ``docker`` CLI.

Lives in a separate module so importing :mod:`plutus_verify.execute` doesn't
require the ``docker`` Python SDK or a running Docker daemon.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from plutus_verify.compare.rubric import ExecOutcome
from plutus_verify.execute import ExecResult, Runner


@dataclass(frozen=True)
class DockerRunnerConfig:
    memory_limit: str = "8g"
    cpu_limit: str = "4"
    user: Optional[str] = None  # e.g., "1000:1000"
    extra_args: tuple[str, ...] = ()


class DockerRunner(Runner):
    """Spawns ``docker run --rm`` for each step.

    Mounts ``cwd`` to ``/srv/repo`` inside the container (the repo2docker default).
    """

    def __init__(self, config: Optional[DockerRunnerConfig] = None) -> None:
        self._cfg = config or DockerRunnerConfig()

    def run(
        self,
        *,
        image: str,
        command: str,
        cwd: Path,
        network: str,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        env = env or {}
        args = [
            "docker",
            "run",
            "--rm",
            f"--network={network}",
            f"--memory={self._cfg.memory_limit}",
            f"--cpus={self._cfg.cpu_limit}",
            "-v",
            f"{cwd}:/srv/repo",
            "-w",
            "/srv/repo",
        ]
        if self._cfg.user:
            args += ["--user", self._cfg.user]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += list(self._cfg.extra_args)
        # Non-login shell: inherits the container's ENV PATH verbatim so the uv
        # venv at /opt/venv/bin is on PATH. `bash -lc` re-sources /etc/profile on
        # the Debian slim base, which resets PATH and hides the venv (the pip path
        # is unaffected — it installs into the system python, still on PATH).
        args += [image, "bash", "-c", command]
        start = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ExecResult(
                exit_code=-1,
                stdout=(exc.stdout or b"").decode("utf-8", errors="replace") if exc.stdout else "",
                stderr=f"timeout after {timeout_seconds}s",
                duration_seconds=float(timeout_seconds),
                outcome=ExecOutcome.TIMEOUT,
            )
        duration = time.monotonic() - start
        outcome = ExecOutcome.OK if proc.returncode == 0 else ExecOutcome.FAILED
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_seconds=duration,
            outcome=outcome,
        )

    @staticmethod
    def quote(cmd: str) -> str:
        """Convenience for callers building commands."""
        return shlex.quote(cmd)

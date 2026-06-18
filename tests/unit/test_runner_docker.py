"""Unit tests for :class:`DockerRunner` argv construction.

Guards the runner/Dockerfile venv-activation contract. The v2 uv path activates
its environment purely through the image's ``ENV PATH=/opt/venv/bin:$PATH``. A
*login* shell (``bash -lc``) re-sources ``/etc/profile`` on the Debian slim base
and resets ``PATH`` to the system default, dropping ``/opt/venv/bin`` — so steps
must run under a non-login shell that inherits the container's ``ENV`` verbatim.

This is the regression a Dockerfile-string assertion can't catch: the bug lived
in the runner's shell flag, not the generated Dockerfile (0.4.x uv-runner fix).
"""
from pathlib import Path

import plutus_verify.runner_docker as runner_docker
from plutus_verify.runner_docker import DockerRunner


def _capture_argv(monkeypatch):
    captured: dict[str, list[str]] = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _Proc()

    monkeypatch.setattr(runner_docker.subprocess, "run", fake_run)
    return captured


def test_step_runs_under_non_login_shell(monkeypatch, tmp_path: Path):
    captured = _capture_argv(monkeypatch)
    DockerRunner().run(
        image="img",
        command="python -m demo.backtest",
        cwd=tmp_path,
        network="none",
        timeout_seconds=60,
    )
    args = captured["args"]
    # Non-login shell inherits the container's ENV PATH (so /opt/venv/bin wins);
    # `bash -lc` would re-source /etc/profile and reset PATH, hiding the uv venv.
    assert args[-3:] == ["bash", "-c", "python -m demo.backtest"]
    assert "-lc" not in args

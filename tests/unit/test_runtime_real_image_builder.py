"""Tests for the real Docker image builder."""
import subprocess
from pathlib import Path

import pytest

from plutus_verify.spec.runtime.real_image_builder import (
    BuildError,
    build_image,
    make_image_builder,
)


_DOCKERFILE = "FROM python:3.11-slim\nWORKDIR /srv/repo\n"


def test_build_image_writes_dockerfile_and_invokes_docker(tmp_path: Path):
    calls = []

    def fake_runner(cmd, cwd):
        calls.append((cmd, cwd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    tag = build_image(_DOCKERFILE, tmp_path, docker_runner=fake_runner)

    # Tag is deterministic and digest-based
    assert tag.startswith("plutus-v2:")
    assert len(tag.split(":")[1]) == 12

    # Dockerfile got written to .plutus/Dockerfile.generated
    df = tmp_path / ".plutus" / "Dockerfile.generated"
    assert df.exists()
    assert df.read_text() == _DOCKERFILE

    # Exactly one docker invocation, with the expected args
    assert len(calls) == 1
    cmd, cwd = calls[0]
    assert cmd[:2] == ["docker", "build"]
    assert "--tag" in cmd
    assert tag in cmd
    assert "--file" in cmd
    assert str(df) in cmd
    assert str(tmp_path) in cmd
    assert cwd == tmp_path


def test_build_image_raises_build_error_on_nonzero_exit(tmp_path: Path):
    def failing_runner(cmd, cwd):
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="building...", stderr="error: missing layer",
        )

    with pytest.raises(BuildError, match="exit 1"):
        build_image(_DOCKERFILE, tmp_path, docker_runner=failing_runner)


def test_build_image_includes_stderr_tail_in_error(tmp_path: Path):
    def failing_runner(cmd, cwd):
        return subprocess.CompletedProcess(
            args=cmd, returncode=2, stdout="", stderr="specific failure mode XYZ",
        )

    with pytest.raises(BuildError, match="specific failure mode XYZ"):
        build_image(_DOCKERFILE, tmp_path, docker_runner=failing_runner)


def test_image_tag_is_content_addressed(tmp_path: Path):
    def ok_runner(cmd, cwd):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    tag1 = build_image(_DOCKERFILE, tmp_path, docker_runner=ok_runner)
    tag2 = build_image(_DOCKERFILE, tmp_path, docker_runner=ok_runner)
    assert tag1 == tag2

    tag3 = build_image(_DOCKERFILE + "RUN echo hi\n", tmp_path, docker_runner=ok_runner)
    assert tag3 != tag1


def test_make_image_builder_returns_callable(tmp_path: Path, monkeypatch):
    # Patch the default docker runner to avoid invoking real docker
    def fake(cmd, cwd):
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "plutus_verify.spec.runtime.real_image_builder._default_docker_runner",
        fake,
    )

    builder = make_image_builder(image_prefix="custom-pre")
    tag = builder(_DOCKERFILE, tmp_path)
    assert tag.startswith("custom-pre:")

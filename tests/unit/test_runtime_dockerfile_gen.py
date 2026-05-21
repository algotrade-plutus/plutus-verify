"""Tests for the v2 Dockerfile generator."""
import pytest

from plutus_verify.spec.manifest import Env, Secret
from plutus_verify.spec.runtime.dockerfile_gen import (
    UnsupportedEnvError,
    generate_dockerfile,
)


def _minimal_env() -> Env:
    return Env(base="python", python_version="3.11", requirements_file="requirements.txt")


def test_generates_minimal_dockerfile():
    df = generate_dockerfile(_minimal_env(), secrets=())
    assert "FROM python:3.11-slim" in df
    assert "WORKDIR /srv/repo" in df
    assert "COPY requirements.txt ." in df
    assert "pip install --no-cache-dir -r requirements.txt" in df
    assert "COPY . ." in df


def test_includes_os_packages_layer():
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        os_packages=("build-essential", "libpq-dev"),
    )
    df = generate_dockerfile(env, secrets=())
    assert "apt-get update" in df
    assert "build-essential libpq-dev" in df


def test_omits_apt_layer_when_no_os_packages():
    df = generate_dockerfile(_minimal_env(), secrets=())
    assert "apt-get" not in df


def test_omits_requirements_layer_when_unset():
    env = Env(base="python", python_version="3.11", requirements_file=None)
    df = generate_dockerfile(env, secrets=())
    assert "requirements.txt" not in df
    assert "pip install" not in df


def test_gpu_required_raises_unsupported():
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        gpu_required=True,
    )
    with pytest.raises(UnsupportedEnvError, match="GPU.*Plan 2.5"):
        generate_dockerfile(env, secrets=())


def test_base_python_cuda_raises_unsupported():
    env = Env(base="python-cuda", python_version="3.11", requirements_file="requirements.txt")
    with pytest.raises(UnsupportedEnvError, match="python-cuda"):
        generate_dockerfile(env, secrets=())


def test_deterministic_output():
    """Same input → byte-identical Dockerfile, so image hash is stable."""
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        os_packages=("libpq-dev", "build-essential"),
    )
    df1 = generate_dockerfile(env, secrets=())
    df2 = generate_dockerfile(env, secrets=())
    assert df1 == df2
    # os_packages sorted to keep determinism even if input order varies
    env_reordered = Env(
        base="python",
        python_version="3.11",
        requirements_file="requirements.txt",
        os_packages=("build-essential", "libpq-dev"),
    )
    df3 = generate_dockerfile(env_reordered, secrets=())
    assert df1 == df3

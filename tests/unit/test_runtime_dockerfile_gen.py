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


def test_dockerfile_emits_sdk_install_lines_when_basename_provided():
    """When sdk_wheel_basename is set, COPY+RUN install lines are emitted
    after requirements install and before the final COPY . . / CMD."""
    basename = "plutus_verify-0.2.0-py3-none-any.whl"
    df = generate_dockerfile(
        _minimal_env(), secrets=(), sdk_wheel_basename=basename
    )
    copy_line = f"COPY .plutus/build/{basename} /tmp/{basename}"
    run_line = f"RUN pip install --no-cache-dir /tmp/{basename}"
    assert copy_line in df
    assert run_line in df

    lines = df.splitlines()
    # The SDK COPY must appear AFTER pip install -r requirements.txt
    req_install_idx = next(
        i
        for i, line in enumerate(lines)
        if line == "RUN pip install --no-cache-dir -r requirements.txt"
    )
    sdk_copy_idx = lines.index(copy_line)
    sdk_run_idx = lines.index(run_line)
    final_copy_idx = lines.index("COPY . .")
    cmd_idx = next(i for i, line in enumerate(lines) if line.startswith("CMD "))

    assert req_install_idx < sdk_copy_idx
    assert sdk_copy_idx < sdk_run_idx
    assert sdk_run_idx < final_copy_idx
    assert final_copy_idx < cmd_idx


def test_dockerfile_omits_sdk_install_lines_when_basename_none():
    """Default (no kwarg) preserves backward-compat: no .plutus/build/ ref."""
    df = generate_dockerfile(_minimal_env(), secrets=())
    assert ".plutus/build/" not in df


def test_dockerfile_sdk_lines_with_no_requirements_file():
    """Env without requirements_file still gets SDK lines, positioned after
    WORKDIR/os_packages and before COPY . . / CMD."""
    env = Env(
        base="python",
        python_version="3.11",
        requirements_file=None,
        os_packages=("build-essential",),
    )
    basename = "plutus_verify-0.2.0-py3-none-any.whl"
    df = generate_dockerfile(env, secrets=(), sdk_wheel_basename=basename)

    copy_line = f"COPY .plutus/build/{basename} /tmp/{basename}"
    run_line = f"RUN pip install --no-cache-dir /tmp/{basename}"
    assert copy_line in df
    assert run_line in df

    lines = df.splitlines()
    workdir_idx = lines.index("WORKDIR /srv/repo")
    sdk_copy_idx = lines.index(copy_line)
    sdk_run_idx = lines.index(run_line)
    final_copy_idx = lines.index("COPY . .")
    cmd_idx = next(i for i, line in enumerate(lines) if line.startswith("CMD "))

    assert workdir_idx < sdk_copy_idx
    assert sdk_copy_idx < sdk_run_idx
    assert sdk_run_idx < final_copy_idx
    assert final_copy_idx < cmd_idx


def test_pyproject_toml_emits_pip_install_dot():
    """pyproject.toml is a PEP-518 project spec, not a requirements file —
    must use `pip install .`, not `pip install -r pyproject.toml`."""
    env = Env(base="python", python_version="3.11", requirements_file="pyproject.toml")
    df = generate_dockerfile(env, secrets=())
    assert "COPY pyproject.toml ." in df
    assert "RUN pip install --no-cache-dir ." in df
    # Crucially: NOT the `-r` form, which would crash inside the container.
    assert "pip install --no-cache-dir -r pyproject.toml" not in df


def test_requirements_txt_still_uses_dash_r():
    """Regression guard: the legacy path is unchanged."""
    env = Env(base="python", python_version="3.11", requirements_file="requirements.txt")
    df = generate_dockerfile(env, secrets=())
    assert "RUN pip install --no-cache-dir -r requirements.txt" in df
    assert "RUN pip install --no-cache-dir ." not in df


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

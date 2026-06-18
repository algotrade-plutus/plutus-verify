"""Tests for the uv/lockfile reproducible-env support and the non-reproducible
soft-fail (Stage 1: warn-only)."""
from types import SimpleNamespace

import pytest

from plutus_verify.scaffold.check_report import render_check_report
from plutus_verify.spec.loader import ManifestLoadError, load_manifest_from_yaml_text
from plutus_verify.spec.manifest import DataSourceTiers, Env, Manifest, Repo, Step
from plutus_verify.spec.runtime.dockerfile_gen import _UV_VERSION, generate_dockerfile


def _manifest_yaml(env_block: str) -> str:
    return f"""\
schema_version: "2.0"
repo: {{name: D, primary_language: python}}
env:
{env_block}
secrets: []
data_sources: {{processed: [], raw: []}}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "python -m demo.backtest"
expected: []
nine_step_coverage: {{}}
"""


_UV_ENV = """\
  base: python
  python_version: "3.11"
  manager: uv
  lockfile: uv.lock
"""

_PIP_ENV = """\
  base: python
  python_version: "3.11"
  requirements_file: requirements.txt
"""


# ---- schema + loader + validator ----

def test_uv_env_loads_with_manager_and_lockfile():
    m = load_manifest_from_yaml_text(_manifest_yaml(_UV_ENV))
    assert m.env.manager == "uv"
    assert m.env.lockfile == "uv.lock"


def test_manager_defaults_to_pip_when_omitted():
    m = load_manifest_from_yaml_text(_manifest_yaml(_PIP_ENV))
    assert m.env.manager == "pip"
    assert m.env.lockfile is None


def test_uv_without_lockfile_rejected():
    env = "  base: python\n  python_version: \"3.11\"\n  manager: uv\n"
    with pytest.raises(ManifestLoadError, match="uv.*requires.*lockfile"):
        load_manifest_from_yaml_text(_manifest_yaml(env))


def test_unknown_manager_rejected():
    env = "  base: python\n  python_version: \"3.11\"\n  manager: poetry\n  lockfile: poetry.lock\n"
    with pytest.raises(ManifestLoadError, match="schema violation"):
        load_manifest_from_yaml_text(_manifest_yaml(env))


# ---- dockerfile generation ----

def test_uv_dockerfile_restores_lockfile_outside_repo():
    m = load_manifest_from_yaml_text(_manifest_yaml(_UV_ENV))
    df = generate_dockerfile(m.env, sdk_wheel_basename="plutus_verify-9.9.9-py3-none-any.whl")
    assert f"RUN pip install --no-cache-dir uv=={_UV_VERSION}" in df
    assert "ENV UV_PROJECT_ENVIRONMENT=/opt/venv" in df
    assert "COPY pyproject.toml uv.lock ./" in df
    assert "RUN uv sync --frozen --no-install-project" in df
    assert 'ENV PATH="/opt/venv/bin:$PATH"' in df
    # SDK installed into the uv venv (uv venvs have no pip)
    assert "uv pip install --python /opt/venv/bin/python" in df
    # the deprecated pip install -r path must NOT appear
    assert "pip install --no-cache-dir -r" not in df


def test_pip_dockerfile_unchanged():
    m = load_manifest_from_yaml_text(_manifest_yaml(_PIP_ENV))
    df = generate_dockerfile(m.env)
    assert "COPY requirements.txt ." in df
    assert "RUN pip install --no-cache-dir -r requirements.txt" in df
    assert "uv sync" not in df


# ---- env reproducibility classification + check report ----

def _runtime(env_reproducible: bool, notes=None):
    return SimpleNamespace(
        image="img",
        data_tier_used="raw",
        notes=notes or [],
        env_reproducible=env_reproducible,
        step_results={},
        metric_results={},
        artifact_results={},
    )


def _bare_manifest(env: Env) -> Manifest:
    return Manifest(
        schema_version="2.0",
        repo=Repo(name="D", primary_language="python"),
        env=env,
        secrets=(),
        data_sources=DataSourceTiers(),
        steps=(Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="x"),),
        expected=(),
    )


def test_report_marks_locked_env_reproducible():
    m = _bare_manifest(Env(base="python", python_version="3.11", manager="uv", lockfile="uv.lock"))
    out = "\n".join(render_check_report(m, _runtime(True)))
    assert "env: reproducible (locked)" in out


def test_report_marks_pip_env_not_reproducible():
    m = _bare_manifest(Env(base="python", python_version="3.11"))
    out = "\n".join(render_check_report(m, _runtime(False)))
    assert "env: NOT reproducible" in out


def test_exit_code_unaffected_by_non_reproducible_env_stage1():
    """Stage 1 is warn-only: a non-reproducible env does not change the exit code
    on its own (no failing steps/metrics here)."""
    from plutus_verify.scaffold.check import _exit_code

    m = _bare_manifest(Env(base="python", python_version="3.11"))
    runtime = SimpleNamespace(
        step_results={}, metric_results={}, artifact_results={}, env_reproducible=False
    )
    assert _exit_code(m, runtime) == 0

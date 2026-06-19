"""Secret injection is scoped to declared keys — the host environment never leaks
into the 'reproducible' container.

Regression guard for the 0.4.2 bug: `plutus check --secrets-from-env` handed the
orchestrator the entire `os.environ`, and the orchestrator forwarded it verbatim as
docker `-e KEY=VALUE` to every step. Among ~50 host vars that included `PATH`, which
overrode the image's `ENV PATH=/opt/venv/bin:$PATH` and hid the uv venv → every step
failed with ModuleNotFoundError, even for a manifest with `secrets: []`.

The contract (scaffold/manifest_template_todo.py) is: propagate ONLY declared secret
keys, scoped to the steps in each secret's `used_by`. This mirrors the v1 path's
`{k: secrets[k] for k in alt.needs_secrets if k in secrets}` (execute.py).
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.loader import ManifestLoadError, load_manifest_from_yaml_text
from plutus_verify.spec.manifest import Secret
from plutus_verify.spec.runtime import orchestrator as orch_mod
from plutus_verify.spec.runtime.orchestrator import _resolve_step_secrets, run_v2_pipeline


@pytest.fixture(autouse=True)
def _fake_sdk_wheel(monkeypatch):
    def fake(build_ctx: Path) -> Path:
        build_ctx = Path(build_ctx)
        build_ctx.mkdir(parents=True, exist_ok=True)
        wheel = build_ctx / "plutus_verify-0.0.0-py3-none-any.whl"
        if not wheel.exists():
            wheel.write_bytes(b"fake-wheel")
        return wheel

    monkeypatch.setattr(orch_mod, "ensure_plutus_wheel", fake)


def _yaml(secrets_block: str) -> str:
    return f"""\
schema_version: "2.0"
repo: {{name: T, primary_language: python}}
env: {{base: python, python_version: "3.11", requirements_file: requirements.txt}}
{secrets_block}
data_sources: {{processed: [], raw: []}}
steps:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    command: "echo data"
    outputs: ["data/raw/x"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo backtest"
    inputs: [data/raw]
    outputs: ["out/metrics.json"]
expected: []
nine_step_coverage: {{}}
"""


_NO_SECRETS = _yaml("secrets: []")
_WITH_SECRET = _yaml(
    "secrets:\n"
    "  - key: DB_PASSWORD\n"
    "    purpose: db creds\n"
    "    used_by: [in_sample]"
)


def _stage_repo(tmp_path: Path) -> None:
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "x").write_text("ok")
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / "metrics.json").write_text("{}")


def _env_by_command(runner: MagicMock) -> dict[str, dict]:
    return {c.kwargs["command"]: c.kwargs["env"] for c in runner.run.call_args_list}


def _run(tmp_path: Path, yaml: str, pool: dict) -> MagicMock:
    _stage_repo(tmp_path)
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )
    run_v2_pipeline(
        load_manifest_from_yaml_text(yaml),
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets=pool,
    )
    return runner


# ---- the reported bug: host env must not leak ----

def test_no_declared_secrets_injects_nothing_even_from_full_host_env(tmp_path):
    runner = _run(
        tmp_path,
        _NO_SECRETS,
        {"PATH": "/Users/dan/.antigravity/bin:/usr/bin", "HOME": "/Users/dan", "NVM_DIR": "x"},
    )
    for cmd, env in _env_by_command(runner).items():
        assert env == {}, f"host env leaked into step {cmd!r}: {env}"


def test_only_declared_secret_injected_and_scoped_to_used_by(tmp_path):
    runner = _run(
        tmp_path,
        _WITH_SECRET,
        {"DB_PASSWORD": "s3cr3t", "PATH": "/host/bin", "HOME": "/Users/dan"},
    )
    calls = _env_by_command(runner)
    assert calls["echo backtest"] == {"DB_PASSWORD": "s3cr3t"}  # in_sample is in used_by
    assert calls["echo data"] == {}  # data_preparation is not in used_by
    for env in calls.values():
        assert "PATH" not in env and "HOME" not in env


# ---- the pure resolver ----

def test_resolve_filters_to_declared_keys_scoped_by_used_by():
    declared = (Secret(key="DB_PASSWORD", purpose="", used_by=("in_sample",)),)
    pool = {"DB_PASSWORD": "x", "PATH": "/host", "HOME": "/h"}
    assert _resolve_step_secrets(declared, pool, "in_sample") == {"DB_PASSWORD": "x"}
    assert _resolve_step_secrets(declared, pool, "data_preparation") == {}


def test_resolve_empty_with_no_declarations():
    assert _resolve_step_secrets((), {"PATH": "/host"}, "in_sample") == {}


def test_resolve_skips_declared_key_absent_from_pool():
    declared = (Secret(key="API_KEY", purpose="", used_by=("in_sample",)),)
    assert _resolve_step_secrets(declared, {}, "in_sample") == {}


# ---- reserved-key guard: a secret named PATH/HOME/... must not re-clobber the venv ----

def test_resolve_skips_reserved_keys_even_if_declared():
    """Defense-in-depth: even if a manifest declares a secret literally named PATH,
    the resolver refuses to inject it — injecting -e PATH=<host> would override the
    image's ENV PATH and hide the uv venv, re-introducing the very bug being fixed."""
    declared = (Secret(key="PATH", purpose="", used_by=("in_sample",)),)
    assert _resolve_step_secrets(declared, {"PATH": "/host/bin"}, "in_sample") == {}


def test_validator_rejects_reserved_secret_key():
    """Author-facing: a reserved key fails at check-time with a clear message rather
    than as a buried container failure."""
    yaml = _yaml(
        "secrets:\n"
        "  - key: PATH\n"
        "    purpose: nope\n"
        "    used_by: [in_sample]"
    )
    with pytest.raises(ManifestLoadError, match="reserved"):
        load_manifest_from_yaml_text(yaml)

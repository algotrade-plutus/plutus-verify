"""End-to-end: the orchestrator no longer exposes host .env / cache to step containers.

Closure of the Group09-BuyHighSellLow v0.2.9 feedback (skill-feedback.md
issue 2). Uses a fake Runner that records what the "container" would see,
so the test runs without Docker.
"""
from pathlib import Path

from plutus_verify.spec.manifest import Step
from plutus_verify.spec.runtime.orchestrator import _run_step


def test_host_env_and_cache_are_invisible_to_step_via_staging(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # Maintainer's host has the v0.2.9 leak channels:
    (repo / ".env").write_text("DB_PASSWORD=should-never-reach-container\n")
    (repo / ".dockerignore").write_text(".env\ndata/cache/\n")
    (repo / "data" / "cache").mkdir(parents=True)
    (repo / "data" / "cache" / "stale.parquet").write_bytes(b"STALE")
    (repo / "script.py").write_text("# pretend bridge step\n")

    observed: dict[str, object] = {}

    class CheckingRunner:
        def run(self, *, image, command, cwd, network, timeout_seconds, env):
            seen = Path(cwd)
            observed["env_visible"] = (seen / ".env").exists()
            observed["cache_visible"] = (seen / "data" / "cache" / "stale.parquet").exists()
            observed["script_visible"] = (seen / "script.py").exists()
            run_dir = seen / ".plutus" / "run" / "data_collection"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "meta.json").write_text('{"exit_code": 0}\n')
            class R:
                exit_code = 0
                duration_seconds = 0.1
                stdout = ""
                stderr = ""
            return R()

    step = Step(
        id="data_collection",
        nine_step=None,
        required=True,
        command="python script.py",
        network="bridge",
    )
    _run_step(
        step=step,
        image="plutus-v2:fake",
        repo_path=repo,
        runner=CheckingRunner(),
        secrets={"DB_PASSWORD": "from-shell-env-real"},
        satisfied=frozenset(),
    )

    assert observed["env_visible"] is False, (
        "v0.2.9 mount-bypass regression: host .env reached the bridge step's container"
    )
    assert observed["cache_visible"] is False, (
        "cache short-circuit reproducible: stale data/cache/ reached the bridge step's container"
    )
    assert observed["script_visible"] is True, (
        "load-bearing script.py missing from staging"
    )

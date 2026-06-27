"""Unit tests for per-step staging (v0.2.10)."""
from pathlib import Path

from plutus_verify.spec.manifest import Step
from plutus_verify.spec.runtime.staging import (
    extract_outputs,
    populate_staging,
    stage_data_cache,
    stage_prior_results,
)


def _step(step_id: str = "s1", **overrides) -> Step:
    base = dict(
        id=step_id,
        nine_step=None,
        required=True,
        command="echo hi",
    )
    base.update(overrides)
    return Step(**base)


def test_populate_staging_copies_everything_when_no_dockerignore(tmp_path: Path):
    """Sanity: with no .dockerignore in cwd, every file ends up in staging."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "script.py").write_text("print('hi')")
    (cwd / "data").mkdir()
    (cwd / "data" / "input.csv").write_text("a,b\n1,2\n")

    staging = tmp_path / "staging"
    staging.mkdir()
    populate_staging(cwd, staging, _step())

    assert (staging / "script.py").read_text() == "print('hi')"
    assert (staging / "data" / "input.csv").read_text() == "a,b\n1,2\n"


def test_populate_staging_respects_dockerignore(tmp_path: Path):
    """`.dockerignore` exclusions must filter the copy. This is the
    load-bearing guarantee: host `.env` and `data/cache/` never reach
    the container even though the mount used to expose them."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".env").write_text("DB_PASSWORD=leaked\n")
    (cwd / "data").mkdir()
    (cwd / "data" / "cache").mkdir()
    (cwd / "data" / "cache" / "stale.parquet").write_bytes(b"STALE")
    (cwd / "script.py").write_text("print('hi')")
    (cwd / "data" / "raw.csv").write_text("a,b\n")
    (cwd / ".dockerignore").write_text(
        ".env\n"
        "data/cache/\n"
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    populate_staging(cwd, staging, _step())

    assert not (staging / ".env").exists(), "host .env must not reach staging"
    assert not (staging / "data" / "cache").exists(), "stale cache must not reach staging"
    assert (staging / "script.py").exists()
    assert (staging / "data" / "raw.csv").exists()


def test_populate_staging_honors_dockerignore_negate(tmp_path: Path):
    """Docker's `!pattern` re-includes a previously-excluded path. The
    framework's own baseline uses this for `.plutus/build/plutus_verify-*.whl`."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / ".plutus" / "build").mkdir(parents=True)
    (cwd / ".plutus" / "build" / "plutus_verify-0.2.10-py3-none-any.whl").write_bytes(b"WHL")
    (cwd / ".plutus" / "build" / "stale.log").write_text("junk")
    (cwd / ".dockerignore").write_text(
        ".plutus/build/\n"
        "!.plutus/build/plutus_verify-*.whl\n"
    )

    staging = tmp_path / "staging"
    staging.mkdir()
    populate_staging(cwd, staging, _step())

    assert (staging / ".plutus" / "build" / "plutus_verify-0.2.10-py3-none-any.whl").exists()
    assert not (staging / ".plutus" / "build" / "stale.log").exists()


def test_populate_staging_restricts_to_step_inputs_when_declared(tmp_path: Path):
    """Non-empty step.inputs means only those paths are copied — even
    things .dockerignore would allow."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "data").mkdir()
    (cwd / "data" / "raw.csv").write_text("a\n")
    (cwd / "data" / "extra.csv").write_text("b\n")
    (cwd / "config.yaml").write_text("k: v\n")

    step = _step(inputs=("data/raw.csv", "config.yaml"))
    staging = tmp_path / "staging"
    staging.mkdir()
    populate_staging(cwd, staging, step)

    assert (staging / "data" / "raw.csv").exists()
    assert (staging / "config.yaml").exists()
    assert not (staging / "data" / "extra.csv").exists()


def test_extract_outputs_always_returns_plutus_run_dir(tmp_path: Path):
    """`.plutus/run/<step>/` is framework bookkeeping; always copied back."""
    staging = tmp_path / "staging"
    cwd = tmp_path / "cwd"
    staging.mkdir()
    cwd.mkdir()

    run_dir = staging / ".plutus" / "run" / "s1"
    run_dir.mkdir(parents=True)
    (run_dir / "stdout").write_text("hello\n")
    (run_dir / "meta.json").write_text('{"exit": 0}\n')

    extract_outputs(staging, cwd, _step("s1"))

    assert (cwd / ".plutus" / "run" / "s1" / "stdout").read_text() == "hello\n"
    assert (cwd / ".plutus" / "run" / "s1" / "meta.json").read_text() == '{"exit": 0}\n'


def test_extract_outputs_harvests_declared_outputs_to_results_buffer(tmp_path: Path):
    """L2: declared outputs go to .plutus/results/<step>/<path>, NOT the working
    tree root — so `check` never mutates the author's result/ files."""
    staging = tmp_path / "staging"
    cwd = tmp_path / "cwd"
    staging.mkdir()
    cwd.mkdir()

    (staging / "result").mkdir()
    (staging / "result" / "report.json").write_text('{"sharpe": 0.95}\n')
    (staging / "parameter").mkdir()
    (staging / "parameter" / "optimized.json").write_text('{"x": 1}\n')

    step = _step("s1", outputs=("result/", "parameter/optimized.json"))
    extract_outputs(staging, cwd, step)

    results = cwd / ".plutus" / "results" / "s1"
    assert (results / "result" / "report.json").read_text() == '{"sharpe": 0.95}\n'
    assert (results / "parameter" / "optimized.json").read_text() == '{"x": 1}\n'
    # The working tree root is NOT touched (read-only check).
    assert not (cwd / "result").exists()
    assert not (cwd / "parameter").exists()


def test_extract_outputs_drops_undeclared_writes(tmp_path: Path):
    """Files the script wrote outside declared outputs are silently dropped."""
    staging = tmp_path / "staging"
    cwd = tmp_path / "cwd"
    staging.mkdir()
    cwd.mkdir()
    (staging / "wat.txt").write_text("undeclared\n")
    (staging / "result").mkdir()
    (staging / "result" / "expected.json").write_text("declared\n")

    step = _step("s1", outputs=("result/",))
    extract_outputs(staging, cwd, step)

    results = cwd / ".plutus" / "results" / "s1"
    assert (results / "result" / "expected.json").exists()
    assert not (results / "wat.txt").exists()
    assert not (cwd / "wat.txt").exists()


def test_stage_prior_results_injects_earlier_outputs_remapped(tmp_path: Path):
    """The inter-step bus: an earlier step's harvested output at
    .plutus/results/<step>/<path> must appear in a later step's staging at the
    declared <path> (not under the .plutus/results/<step>/ prefix)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    prior = repo / ".plutus" / "results" / "data_preparation" / "data" / "processed"
    prior.mkdir(parents=True)
    (prior / "clean.parquet").write_bytes(b"CLEAN")

    staging = tmp_path / "staging"
    staging.mkdir()
    stage_prior_results(repo, staging, _step("in_sample"))

    assert (staging / "data" / "processed" / "clean.parquet").read_bytes() == b"CLEAN"
    # The .plutus/results/<step>/ prefix must NOT be reproduced in staging.
    assert not (staging / ".plutus" / "results").exists()


def test_stage_data_cache_overlays_downloaded_data_remapped(tmp_path: Path):
    """Downloaded data cached at .plutus/cache/<path> must reach a step's staging
    at the declared <path>, so steps see fetched inputs without the working tree
    ever being written (Bug 3)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    cached = repo / ".plutus" / "cache" / "data" / "raw"
    cached.mkdir(parents=True)
    (cached / "x.parquet").write_bytes(b"DATA")

    staging = tmp_path / "staging"
    staging.mkdir()
    stage_data_cache(repo, staging, _step("data_preparation"))

    assert (staging / "data" / "raw" / "x.parquet").read_bytes() == b"DATA"
    assert not (staging / ".plutus" / "cache").exists()


def test_stage_prior_results_respects_step_inputs_filter(tmp_path: Path):
    """When a step declares inputs, only prior outputs matching that positive
    filter are injected — an unrelated earlier output must not leak in (same
    hermeticity guarantee populate_staging gives for the committed tree)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    results = repo / ".plutus" / "results"
    (results / "prep" / "data" / "processed").mkdir(parents=True)
    (results / "prep" / "data" / "processed" / "clean.parquet").write_bytes(b"WANT")
    (results / "other" / "scratch").mkdir(parents=True)
    (results / "other" / "scratch" / "junk.bin").write_bytes(b"LEAK")

    staging = tmp_path / "staging"
    staging.mkdir()
    stage_prior_results(repo, staging, _step("in_sample", inputs=("data/processed",)))

    assert (staging / "data" / "processed" / "clean.parquet").exists()
    assert not (staging / "scratch" / "junk.bin").exists(), "unrelated prior output leaked"


def test_orchestrator_runs_step_against_staging_not_cwd(tmp_path: Path):
    """The runner's `cwd=` argument now points at a staging dir, and that
    staging dir was populated with the .dockerignore filter applied."""
    from plutus_verify.spec.runtime.orchestrator import _run_step

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("LEAK_ME=1\n")
    (repo / "script.py").write_text("print('hi')\n")
    (repo / ".dockerignore").write_text(".env\n")

    step = _step(command="python script.py")

    # Capture facts INSIDE the runner callback — staging is cleaned up
    # before _run_step returns, so the test can't inspect it directly.
    observed: dict[str, object] = {}

    class FakeRunner:
        def run(self, *, image, command, cwd, network, timeout_seconds, env):
            seen = Path(cwd)
            observed["cwd"] = seen
            observed["is_repo_path"] = (seen == repo)
            observed["has_env"] = (seen / ".env").exists()
            observed["has_script"] = (seen / "script.py").exists()
            run_dir = seen / ".plutus" / "run" / "s1"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "stdout").write_text("hi\n")
            (run_dir / "meta.json").write_text('{"exit_code": 0}\n')
            class R:
                exit_code = 0
                duration_seconds = 0.1
                stdout = "hi\n"
                stderr = ""
            return R()

    _run_step(
        step=step,
        image="plutus-v2:fake",
        repo_path=repo,
        runner=FakeRunner(),
        secrets={},
        satisfied=frozenset(),
    )

    assert observed["is_repo_path"] is False, "runner saw repo_path; staging not wired"
    assert observed["has_env"] is False, "host .env leaked into staging"
    assert observed["has_script"] is True, "load-bearing script.py missing from staging"
    # Bookkeeping was extracted back to repo after the step finished
    assert (repo / ".plutus" / "run" / "s1" / "stdout").read_text() == "hi\n"


def test_run_step_persists_stdout_stderr_for_diagnostics(tmp_path: Path):
    """A failing step must leave its captured stdout/stderr on disk under
    .plutus/run/<step>/ so the failure is diagnosable without re-running the
    container by hand (real DockerRunner returns them only in the ExecResult)."""
    from plutus_verify.spec.runtime.orchestrator import _run_step

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "script.py").write_text("raise SystemExit(1)\n")
    step = _step("s1", command="python script.py")

    class FailingRunner:
        def run(self, *, image, command, cwd, network, timeout_seconds, env):
            class R:
                exit_code = 1
                duration_seconds = 0.2
                stdout = "loading data...\n"
                stderr = "Traceback (most recent call last):\nValueError: boom\n"
            return R()

    sr = _run_step(
        step=step,
        image="img",
        repo_path=repo,
        runner=FailingRunner(),
        secrets={},
        satisfied=frozenset(),
    )

    assert sr.exit_code == 1
    run_dir = repo / ".plutus" / "run" / "s1"
    assert (run_dir / "stderr").read_text() == "Traceback (most recent call last):\nValueError: boom\n"
    assert (run_dir / "stdout").read_text() == "loading data...\n"

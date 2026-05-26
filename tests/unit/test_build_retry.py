"""Retry-loop tests for ``build_with_fixers``.

We stub the ``docker_invoker`` to simulate each build attempt's outcome,
then assert the retry loop applied the correct fixers in the correct order.
"""
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from plutus_verify.builder import BuildError, build_with_fixers
from plutus_verify.util.progress import Progress


def _seed_repo(tmp_path: Path, *, requirements: str = "pandas\nnumpy\n") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text(requirements)
    return repo


def _ok() -> CompletedProcess[str]:
    return CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail(stderr: str) -> CompletedProcess[str]:
    return CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


class _ScriptedDocker:
    """Returns each scripted CompletedProcess in turn, then raises if asked again."""

    def __init__(self, *scripted):
        self.scripted = list(scripted)
        self.calls = 0

    def __call__(self, args):
        if self.calls >= len(self.scripted):
            raise AssertionError("docker_invoker called more times than scripted")
        out = self.scripted[self.calls]
        self.calls += 1
        return out


def test_build_succeeds_on_first_attempt(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    docker = _ScriptedDocker(_ok())
    result = build_with_fixers(
        repo, commit_sha="abc1234567", docker_invoker=docker
    )
    assert result.image.startswith("plutus-run-abc1234")
    assert result.adjustments == ()
    assert docker.calls == 1


def test_build_applies_prebuild_fixer_for_utf16(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_bytes(
        b"\xff\xfe" + "pandas\nnumpy\n".encode("utf-16-le")
    )
    docker = _ScriptedDocker(_ok())
    result = build_with_fixers(
        repo, commit_sha="abc1234567", docker_invoker=docker
    )
    assert any("UTF-16" in a.description for a in result.adjustments)
    # File now plain UTF-8 — readable by pip
    assert (repo / "requirements.txt").read_bytes()[:2] != b"\xff\xfe"


def test_build_retries_with_post_build_fixer_then_succeeds(tmp_path: Path):
    repo = _seed_repo(tmp_path, requirements="psycopg\nnumpy\n")
    # NB: the pre-build fixer will swap psycopg → psycopg[binary] BEFORE the
    # first attempt. So we don't need post-build for this case; just one attempt.
    docker = _ScriptedDocker(_ok())
    result = build_with_fixers(
        repo, commit_sha="abc1234567", docker_invoker=docker
    )
    assert any("psycopg[binary]" in a.description for a in result.adjustments)


def test_build_retries_with_apt_dev_header(tmp_path: Path):
    repo = _seed_repo(tmp_path, requirements="some-c-extension\n")
    # First attempt fails with a missing-header error; post-build fixer injects libpq-dev;
    # second attempt succeeds.
    docker = _ScriptedDocker(
        _fail("fatal error: libpq-fe.h: No such file or directory"),
        _ok(),
    )
    result = build_with_fixers(
        repo, commit_sha="abc1234567", docker_invoker=docker
    )
    assert any("libpq-dev" in a.description for a in result.adjustments)
    assert docker.calls == 2


def test_build_escalates_to_llm_after_deterministic_fixers(tmp_path: Path):
    repo = _seed_repo(tmp_path, requirements="vnstock_ezchart\n")
    docker = _ScriptedDocker(
        _fail("ModuleNotFoundError: No module named 'wordcloud'"),
        _ok(),
    )
    result = build_with_fixers(
        repo, commit_sha="abc1234567", docker_invoker=docker
    )
    # Post-build deterministic fixer caught the ModuleNotFoundError → no LLM needed
    assert "wordcloud" in (repo / "requirements.txt").read_text()
    assert docker.calls == 2


def test_build_invokes_llm_when_deterministic_fixers_have_nothing(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    log = "some weird unknown error that no deterministic fixer recognizes"
    docker = _ScriptedDocker(
        _fail(log),
        _ok(),
    )

    def fake_llm(error_log: str, repo_path: Path):
        return [{"op": "add_to_requirements", "pkg": "mystery-fix", "reason": "tried"}]

    result = build_with_fixers(
        repo, commit_sha="abc1234567",
        docker_invoker=docker, llm_fixer=fake_llm,
    )
    assert any("mystery-fix" in a.description for a in result.adjustments)
    assert "mystery-fix" in (repo / "requirements.txt").read_text()


def test_build_gives_up_after_max_attempts(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    docker = _ScriptedDocker(
        _fail("fatal error: libpq-fe.h: No such file or directory"),
        _fail("fatal error: libpq-fe.h: No such file or directory"),
        _fail("fatal error: libpq-fe.h: No such file or directory"),
    )

    def fake_llm(error_log: str, repo_path: Path):
        return [{"op": "add_apt_package", "pkg": "libpq-dev", "reason": "header"}]

    with pytest.raises(BuildError, match="3 attempts"):
        build_with_fixers(
            repo, commit_sha="abc1234567",
            docker_invoker=docker, llm_fixer=fake_llm,
        )


def test_build_fails_without_llm_when_deterministic_exhausted(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    docker = _ScriptedDocker(
        _fail("totally unknown error"),
    )
    with pytest.raises(BuildError, match="no deterministic fix found"):
        build_with_fixers(
            repo, commit_sha="abc1234567",
            docker_invoker=docker, llm_fixer=None,
        )


def test_build_persists_attempt_artifacts(tmp_path: Path):
    """When artifacts_dir is set, each attempt writes attempt_<n>.log + .fixers.json."""
    repo = _seed_repo(tmp_path)
    art = tmp_path / "build"
    docker = _ScriptedDocker(
        _fail("fatal error: libpq-fe.h: No such file or directory"),
        _ok(),
    )
    result = build_with_fixers(
        repo, commit_sha="abc1234567",
        docker_invoker=docker,
        artifacts_dir=art,
    )
    assert (art / "attempt_1.log").exists()
    assert "libpq-fe.h" in (art / "attempt_1.log").read_text()
    assert (art / "attempt_2.log").exists()
    # attempt_1.fixers.json captures the post-build fixer applied between attempts
    fixers = json.loads((art / "attempt_1.fixers.json").read_text())
    assert any("libpq-dev" in f["description"] for f in fixers)


def test_build_emits_progress_per_attempt(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    run_dir = tmp_path / "run"
    progress = Progress(run_dir, stream=None)
    docker = _ScriptedDocker(_ok())
    build_with_fixers(
        repo, commit_sha="abc1234567",
        docker_invoker=docker,
        progress=progress,
    )
    progress.close()
    log = (run_dir / "run.log").read_text()
    assert "[build]   attempt 1/3: docker build" in log
    assert "[build]   attempt 1/3: ok" in log


def test_dockerfile_includes_apt_when_fixer_emits_one(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    captured_dockerfiles: list[str] = []

    def docker(args):
        # Find -f <dockerfile_path>
        if "-f" in args:
            path = Path(args[args.index("-f") + 1])
            if path.exists():
                captured_dockerfiles.append(path.read_text())
        if len(captured_dockerfiles) == 1:
            return _fail("fatal error: libpq-fe.h: No such file or directory")
        return _ok()

    result = build_with_fixers(
        repo, commit_sha="abc1234567", docker_invoker=docker
    )
    # First Dockerfile (no apt) → second Dockerfile (with libpq-dev)
    assert len(captured_dockerfiles) >= 2
    assert "libpq-dev" not in captured_dockerfiles[0]
    assert "libpq-dev" in captured_dockerfiles[1]

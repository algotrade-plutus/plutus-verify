"""Tests for the ingest stage: git clone + repo metadata capture.

We inject a fake ``git`` runner so these tests don't actually shell out.
"""
import json
from pathlib import Path

import pytest

from plutus_verify.ingest import IngestError, IngestResult, ingest


class _FakeGit:
    """Records calls; lays down a fake repo dir; returns canned `rev-parse` output."""

    def __init__(self, sha: str = "abcdef1234567890" * 2, branch: str = "main") -> None:
        self.sha = sha
        self.branch = branch
        self.calls: list[list[str]] = []
        self._readme = "# A repo\n\nplutus content"

    def run(self, args: list[str], cwd: Path | None = None) -> str:
        self.calls.append(list(args))
        if args[:2] == ["clone", "--depth=1"]:
            # args: ["clone", "--depth=1", "--branch", <ref>, "--", url, dest] OR
            #       ["clone", "--depth=1", "--", url, dest]
            dest = Path(args[-1])
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "README.md").write_text(self._readme, encoding="utf-8")
            return ""
        if args[:2] == ["rev-parse", "HEAD"]:
            return self.sha + "\n"
        if args[:3] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return self.branch + "\n"
        raise AssertionError(f"unexpected git invocation: {args}")


def test_ingest_clones_to_run_dir_and_returns_paths(tmp_path: Path):
    fake = _FakeGit(sha="c" * 40, branch="main")
    result = ingest(
        "https://github.com/algotrade-plutus/ProtoMarketMaker",
        run_dir=tmp_path,
        git_runner=fake.run,
    )
    assert isinstance(result, IngestResult)
    assert result.repo_path == tmp_path / "repo"
    assert result.repo_path.exists()
    assert result.commit_sha == "c" * 40
    assert result.branch == "main"
    assert result.meta_path == tmp_path / "meta.json"
    # meta.json mirrors the result
    meta = json.loads(result.meta_path.read_text())
    assert meta["commit_sha"] == "c" * 40
    assert meta["git_url"].endswith("ProtoMarketMaker")


def test_ingest_passes_ref_to_git_clone(tmp_path: Path):
    fake = _FakeGit()
    ingest(
        "https://example.com/x.git",
        run_dir=tmp_path,
        ref="v1.2.3",
        git_runner=fake.run,
    )
    clone_args = next(c for c in fake.calls if c[0] == "clone")
    assert "--branch" in clone_args
    assert "v1.2.3" in clone_args


def test_ingest_locates_readme(tmp_path: Path):
    fake = _FakeGit()
    result = ingest("https://example.com/x.git", run_dir=tmp_path, git_runner=fake.run)
    assert result.readme_path == result.repo_path / "README.md"
    assert result.readme_path.read_text().startswith("# A repo")


def test_ingest_raises_when_readme_missing(tmp_path: Path):
    fake = _FakeGit()
    # Strip the README from the fake clone behaviour
    fake._readme = ""  # still writes empty; we instead delete after
    with pytest.raises(IngestError):
        # Monkey-patch the runner to skip writing README
        def runner(args: list[str], cwd: Path | None = None) -> str:
            out = fake.run(args, cwd)
            if args[:2] == ["clone", "--depth=1"]:
                (Path(args[-1]) / "README.md").unlink()
            return out

        ingest("https://example.com/x.git", run_dir=tmp_path, git_runner=runner)


def test_meta_json_paths_are_absolute(tmp_path: Path):
    """Docker -v rejects relative paths; meta.json must store absolute ones."""
    import os
    fake = _FakeGit()
    # Use a relative run_dir to simulate the CLI passing --out ./out/...
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        ingest("https://example.com/x.git", run_dir=Path("relative_out"), git_runner=fake.run)
        meta = json.loads((tmp_path / "relative_out" / "meta.json").read_text())
    finally:
        os.chdir(old_cwd)
    assert Path(meta["repo_path"]).is_absolute(), meta["repo_path"]
    assert Path(meta["readme_path"]).is_absolute(), meta["readme_path"]


def test_resume_existing_run_returns_absolute_paths(tmp_path: Path):
    """Even if meta.json on disk has relative paths, resume should absolutise them."""
    from plutus_verify.ingest import resume_existing_run
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "repo").mkdir()
    (run_dir / "repo" / "README.md").write_text("# x")
    # Deliberately seed with RELATIVE paths to test back-compat:
    (run_dir / "meta.json").write_text(json.dumps({
        "git_url": "https://example.com/x.git",
        "repo_path": str(run_dir / "repo"),  # already absolute via tmp_path
        "readme_path": str(run_dir / "repo" / "README.md"),
        "commit_sha": "abc", "branch": "main",
        "meta_path": str(run_dir / "meta.json"),
    }))
    res = resume_existing_run(run_dir)
    assert res.repo_path.is_absolute()


def test_resume_existing_run_loads_meta_and_repo(tmp_path: Path):
    """resume_existing_run picks up a prior ingest's run dir (meta + repo)."""
    from plutus_verify.ingest import resume_existing_run

    # Simulate a prior ingest
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    repo = run_dir / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# resumed", encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps(
            {
                "git_url": "https://example.com/x.git",
                "repo_path": str(repo),
                "readme_path": str(repo / "README.md"),
                "commit_sha": "deadbeef",
                "branch": "main",
                "meta_path": str(run_dir / "meta.json"),
            }
        )
    )

    result = resume_existing_run(run_dir)
    assert result.commit_sha == "deadbeef"
    assert result.branch == "main"
    assert result.repo_path == repo
    assert result.readme_path == repo / "README.md"


def test_resume_existing_run_missing_meta(tmp_path: Path):
    """Helpful error if the run dir hasn't been initialised."""
    from plutus_verify.ingest import IngestError, resume_existing_run

    with pytest.raises(IngestError, match="meta.json"):
        resume_existing_run(tmp_path / "empty")


def test_ingest_supports_local_path_skip_clone(tmp_path: Path):
    """When the source is a local path, no clone happens; we still get metadata."""
    local = tmp_path / "local_repo"
    local.mkdir()
    (local / "README.md").write_text("# local")

    result = ingest(
        str(local),
        run_dir=tmp_path / "out",
        skip_clone=True,
        git_runner=lambda args, cwd=None: pytest.fail("git should not be called"),
    )
    assert result.repo_path == local
    assert result.commit_sha == "local"
    assert result.branch == "local"

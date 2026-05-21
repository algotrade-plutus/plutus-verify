"""Tests for the tee'd Progress emitter."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from plutus_verify.util.progress import NullProgress, Progress


def test_stage_writes_bracketed_line_to_stream(tmp_path: Path) -> None:
    buf = io.StringIO()
    p = Progress(tmp_path, stream=buf)
    p.stage("ingest", "cloning foo @ main")
    p.close()
    assert "[ingest] cloning foo @ main" in buf.getvalue()


def test_substep_is_indented(tmp_path: Path) -> None:
    buf = io.StringIO()
    p = Progress(tmp_path, stream=buf)
    p.substep("extract", "call 1/4 repo_metadata: ok (1.2s)")
    p.close()
    # Two-space indent after the bracketed prefix.
    assert "[extract]   call 1/4" in buf.getvalue()


def test_error_prefixed_with_ERROR(tmp_path: Path) -> None:
    buf = io.StringIO()
    p = Progress(tmp_path, stream=buf)
    p.error("build", "docker build failed (exit 1)")
    p.close()
    assert "[build] ERROR: docker build failed (exit 1)" in buf.getvalue()


def test_events_appended_to_run_log(tmp_path: Path) -> None:
    buf = io.StringIO()
    p = Progress(tmp_path, stream=buf)
    p.stage("ingest", "go")
    p.substep("ingest", "ok")
    p.error("build", "boom")
    p.close()

    log = (tmp_path / "run.log").read_text()
    assert "[ingest] go" in log
    assert "[ingest]   ok" in log
    assert "[build] ERROR: boom" in log


def test_run_log_appends_on_reopen(tmp_path: Path) -> None:
    """Reopening the same run_dir should append, not truncate."""
    p1 = Progress(tmp_path, stream=None)
    p1.stage("ingest", "first")
    p1.close()
    p2 = Progress(tmp_path, stream=None)
    p2.stage("extract", "second")
    p2.close()
    log = (tmp_path / "run.log").read_text()
    assert "[ingest] first" in log
    assert "[extract] second" in log


def test_no_run_dir_skips_disk_output(tmp_path: Path) -> None:
    """run_dir=None must not crash and must not write anything to disk."""
    buf = io.StringIO()
    p = Progress(None, stream=buf)
    p.stage("compare", "no disk here")
    p.close()
    assert "[compare] no disk here" in buf.getvalue()
    # No files should have been created under tmp_path
    assert not (tmp_path / "run.log").exists()


def test_null_progress_is_silent(tmp_path: Path) -> None:
    p = NullProgress()
    # Should not raise; should not write anywhere observable.
    p.stage("ingest", "x")
    p.substep("ingest", "y")
    p.error("ingest", "z")
    p.close()
    assert not (tmp_path / "run.log").exists()


def test_close_is_idempotent(tmp_path: Path) -> None:
    p = Progress(tmp_path, stream=None)
    p.stage("ingest", "x")
    p.close()
    p.close()  # must not raise


def test_context_manager_closes_log(tmp_path: Path) -> None:
    with Progress(tmp_path, stream=None) as p:
        p.stage("ingest", "x")
    # File is closed; reading should yield the written content.
    log = (tmp_path / "run.log").read_text()
    assert "[ingest] x" in log


def test_lines_are_flushed_eagerly(tmp_path: Path) -> None:
    """Live-tail requires immediate flush after each emit."""
    p = Progress(tmp_path, stream=None)
    p.stage("ingest", "tail-me")
    # Read while the emitter is still open — should already be on disk.
    log = (tmp_path / "run.log").read_text()
    assert "[ingest] tail-me" in log
    p.close()

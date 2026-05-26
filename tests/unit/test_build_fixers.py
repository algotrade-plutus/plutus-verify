"""Tests for the hardcoded build fixer library.

Each fixer is a (detector, fix) pair. Pre-build fixers operate on the repo on
disk; post-build fixers parse a Docker build error log.
"""
from pathlib import Path

from plutus_verify.builder.fixers import (
    run_post_build_fixers,
    run_pre_build_fixers,
)


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


# ---------- Pre-build fixers ----------


def test_prebuild_rewrites_utf16_requirements(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    # Simulate UTF-16-LE BOM-encoded requirements.txt
    raw = "\n".join(["pandas", "numpy"]) + "\n"
    (repo / "requirements.txt").write_bytes(b"\xff\xfe" + raw.encode("utf-16-le"))

    adjustments = run_pre_build_fixers(repo)
    assert any("UTF-16" in a.description for a in adjustments)
    # File is now plain UTF-8 (decodable without BOM)
    text = (repo / "requirements.txt").read_text(encoding="utf-8")
    assert "pandas" in text and "numpy" in text
    # No BOM byte
    assert (repo / "requirements.txt").read_bytes()[:2] != b"\xff\xfe"


def test_prebuild_swaps_psycopg_to_binary(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("psycopg\nnumpy\n")
    adjustments = run_pre_build_fixers(repo)
    assert any("psycopg[binary]" in a.description for a in adjustments)
    assert "psycopg[binary]" in (repo / "requirements.txt").read_text()


def test_prebuild_swaps_psycopg2_to_binary(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("psycopg2\nnumpy\n")
    run_pre_build_fixers(repo)
    assert "psycopg2-binary" in (repo / "requirements.txt").read_text()


def test_prebuild_normalises_crlf(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_bytes(b"pandas\r\nnumpy\r\n")
    run_pre_build_fixers(repo)
    text = (repo / "requirements.txt").read_bytes()
    assert b"\r\n" not in text


def test_prebuild_is_idempotent(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("pandas\nnumpy\n")
    first = run_pre_build_fixers(repo)
    second = run_pre_build_fixers(repo)
    assert first == ()  # nothing to fix
    assert second == ()


def test_prebuild_no_requirements_file_is_a_noop(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    # No requirements.txt
    adjustments = run_pre_build_fixers(repo)
    assert adjustments == ()


# ---------- Post-build fixers ----------


def test_postbuild_detects_unsatisfiable_pkg_and_suggests_binary(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("psycopg\nnumpy\n")
    # Simulated pip error
    log = "ERROR: Could not find a version that satisfies the requirement psycopg"
    adjustments, apt = run_post_build_fixers(repo, log)
    # Should swap psycopg -> psycopg[binary] (post-build sees this too)
    assert any("psycopg[binary]" in a.description for a in adjustments)
    assert "psycopg[binary]" in (repo / "requirements.txt").read_text()


def test_postbuild_detects_missing_header_and_emits_apt(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("psycopg\n")
    log = "fatal error: libpq-fe.h: No such file or directory"
    adjustments, apt = run_post_build_fixers(repo, log)
    assert "libpq-dev" in apt
    assert any("libpq-dev" in a.description for a in adjustments)


def test_postbuild_detects_missing_python_dev_header(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("some-c-extension\n")
    log = "fatal error: Python.h: No such file or directory"
    adjustments, apt = run_post_build_fixers(repo, log)
    assert "python3-dev" in apt


def test_postbuild_detects_module_not_found_and_adds_to_requirements(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("vnstock_ezchart\n")
    log = "ModuleNotFoundError: No module named 'wordcloud'"
    adjustments, apt = run_post_build_fixers(repo, log)
    assert any("wordcloud" in a.description for a in adjustments)
    assert "wordcloud" in (repo / "requirements.txt").read_text()


def test_postbuild_returns_empty_when_log_unrecognized(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("pandas\n")
    log = "some unrelated build chatter\n# 12 0.123 doing stuff"
    adjustments, apt = run_post_build_fixers(repo, log)
    assert adjustments == ()
    assert apt == []

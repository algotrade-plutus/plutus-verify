"""Tests for the constrained-op LLM build fixer.

The LLM never runs shell commands. It returns a JSON list of typed ops drawn
from a closed enum. The deterministic Python code parses, validates, and
applies the ops. Invalid ops (wrong enum, suspicious values) are rejected.
"""
import json
from pathlib import Path

import pytest

from plutus_verify.build.llm_fixer import (
    apply_llm_ops,
    parse_llm_ops,
    suggest_build_fixes,
)


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("pandas\nnumpy\n")
    return repo


# ---------- Parsing / validation ----------


def test_parse_accepts_valid_add_to_requirements():
    raw = json.dumps([{"op": "add_to_requirements", "pkg": "wordcloud", "reason": "transitive"}])
    ops = parse_llm_ops(raw)
    assert ops == [{"op": "add_to_requirements", "pkg": "wordcloud", "reason": "transitive"}]


def test_parse_accepts_valid_pin_version():
    raw = json.dumps(
        [{"op": "pin_version", "pkg": "numpy", "version": "1.26.4", "reason": "compat"}]
    )
    ops = parse_llm_ops(raw)
    assert ops[0]["op"] == "pin_version"


def test_parse_accepts_valid_add_apt_package():
    raw = json.dumps([{"op": "add_apt_package", "pkg": "libpq-dev", "reason": "header"}])
    ops = parse_llm_ops(raw)
    assert ops[0]["op"] == "add_apt_package"


def test_parse_rejects_unknown_op():
    raw = json.dumps([{"op": "delete_everything", "path": "/", "reason": "evil"}])
    ops = parse_llm_ops(raw)
    assert ops == []  # filtered


def test_parse_rejects_op_without_reason():
    raw = json.dumps([{"op": "add_to_requirements", "pkg": "x"}])
    ops = parse_llm_ops(raw)
    assert ops == []


def test_parse_rejects_suspicious_pkg_name():
    """No shell metachars, no path traversal, no obvious injection."""
    bad = [
        "x; rm -rf /",
        "../../etc/passwd",
        "x && y",
        "x`whoami`",
        "$(echo)",
        " ",
    ]
    for pkg in bad:
        raw = json.dumps([{"op": "add_to_requirements", "pkg": pkg, "reason": "bad"}])
        assert parse_llm_ops(raw) == [], f"should reject pkg={pkg!r}"


def test_parse_tolerates_malformed_json():
    assert parse_llm_ops("not-json") == []
    assert parse_llm_ops("[invalid json}") == []
    assert parse_llm_ops("") == []


def test_parse_strips_code_fences():
    raw = "```json\n" + json.dumps([{"op": "add_to_requirements", "pkg": "x", "reason": "y"}]) + "\n```"
    ops = parse_llm_ops(raw)
    assert ops and ops[0]["pkg"] == "x"


def test_parse_handles_dict_with_ops_key():
    """Some models wrap ops in {ops: [...]}."""
    raw = json.dumps({"ops": [{"op": "add_to_requirements", "pkg": "x", "reason": "y"}]})
    ops = parse_llm_ops(raw)
    assert ops and ops[0]["pkg"] == "x"


# ---------- Apply ----------


def test_apply_add_to_requirements(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    adjustments, apt = apply_llm_ops(
        [{"op": "add_to_requirements", "pkg": "wordcloud", "reason": "transitive"}],
        repo,
    )
    assert "wordcloud" in (repo / "requirements.txt").read_text()
    assert any("wordcloud" in a.description for a in adjustments)
    assert apt == []


def test_apply_pin_version(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    apply_llm_ops(
        [{"op": "pin_version", "pkg": "numpy", "version": "1.26.4", "reason": "compat"}],
        repo,
    )
    text = (repo / "requirements.txt").read_text()
    assert "numpy==1.26.4" in text


def test_apply_replace_in_requirements(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    (repo / "requirements.txt").write_text("psycopg\nnumpy\n")
    apply_llm_ops(
        [{"op": "replace_in_requirements", "old": "psycopg", "new": "psycopg[binary]", "reason": "libpq"}],
        repo,
    )
    text = (repo / "requirements.txt").read_text()
    assert "psycopg[binary]" in text
    assert "psycopg\n" not in text


def test_apply_add_apt_package(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    adjustments, apt = apply_llm_ops(
        [{"op": "add_apt_package", "pkg": "libpq-dev", "reason": "header"}],
        repo,
    )
    assert "libpq-dev" in apt
    assert any("libpq-dev" in a.description for a in adjustments)


def test_apply_skips_give_up_op(tmp_path: Path):
    repo = _seed_repo(tmp_path)
    adjustments, apt = apply_llm_ops(
        [{"op": "give_up", "reason": "I don't know"}],
        repo,
    )
    # No-op, but recorded so the report shows the LLM bailed out
    assert apt == []
    assert any("give up" in a.description.lower() or "gave up" in a.description.lower() for a in adjustments)


# ---------- End-to-end (with stubbed LLM) ----------


def test_suggest_build_fixes_with_stub_llm(tmp_path: Path):
    repo = _seed_repo(tmp_path)

    class _StubLLM:
        def complete_json(self, system, user, *, temperature=0.0, idle_timeout_seconds=None):
            return json.dumps(
                [{"op": "add_to_requirements", "pkg": "wordcloud", "reason": "transitive"}]
            )

    ops = suggest_build_fixes(
        error_log="ModuleNotFoundError: No module named 'wordcloud'",
        repo_path=repo,
        llm_client=_StubLLM(),
    )
    assert ops and ops[0]["pkg"] == "wordcloud"

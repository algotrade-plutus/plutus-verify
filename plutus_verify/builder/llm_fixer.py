"""Constrained-op LLM build fixer.

The LLM receives the build error log + repo metadata and returns a JSON list
of typed operations from a closed enum:

  * ``add_to_requirements``  — append ``pkg`` to requirements.txt
  * ``pin_version``          — pin ``pkg`` to ``version``
  * ``replace_in_requirements`` — replace ``old`` with ``new`` in requirements.txt
  * ``add_apt_package``      — ask the Dockerfile generator to apt-get install ``pkg``
  * ``give_up``              — record that the LLM couldn't suggest a fix

Anything outside this enum is rejected. Suspicious values (shell metacharacters,
path traversal, whitespace-only) are also rejected so the LLM can't smuggle in
an injection.

The Python side is the driver: it parses, validates, and applies the ops.
The LLM never runs code or touches the filesystem directly.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from plutus_verify.builder.runner import BuildAdjustment
from plutus_verify.util.llm_parsing import strip_markdown_fences


# Allowed PyPI package name characters (PEP 503 normalised + extras + version specifier).
_PYPI_PKG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.\-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9_,\-]+\])?$")
_PYPI_VERSION_RE = re.compile(r"^[A-Za-z0-9_.+\-!*]+$")
# Allowed apt package names (Debian conventions: lowercase alphanumeric + . + - + +)
_APT_PKG_RE = re.compile(r"^[a-z0-9][a-z0-9.\-+]*$")

_ALLOWED_OPS = {"add_to_requirements", "pin_version", "replace_in_requirements",
                "add_apt_package", "give_up"}


def _is_valid_pypi(name: str) -> bool:
    return bool(_PYPI_PKG_RE.match(name)) and len(name) <= 80


def _is_valid_version(v: str) -> bool:
    return bool(_PYPI_VERSION_RE.match(v)) and len(v) <= 40


def _is_valid_apt(name: str) -> bool:
    return bool(_APT_PKG_RE.match(name)) and len(name) <= 80


def parse_llm_ops(raw: str) -> list[dict[str, Any]]:
    """Parse an LLM response into a list of validated ops. Returns ``[]`` on any failure."""
    raw = strip_markdown_fences(raw)
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    # Allow {ops: [...]} wrapping
    if isinstance(obj, dict):
        obj = obj.get("ops", []) or obj.get("operations", []) or []
    if not isinstance(obj, list):
        return []

    valid: list[dict[str, Any]] = []
    for entry in obj:
        if not isinstance(entry, dict):
            continue
        op = entry.get("op")
        reason = entry.get("reason")
        if op not in _ALLOWED_OPS:
            continue
        if not isinstance(reason, str) or not reason.strip():
            continue
        out = {"op": op, "reason": reason.strip()}

        if op == "give_up":
            valid.append(out)
            continue

        if op == "add_to_requirements":
            pkg = entry.get("pkg")
            if not isinstance(pkg, str) or not _is_valid_pypi(pkg):
                continue
            out["pkg"] = pkg
            valid.append(out)
            continue

        if op == "pin_version":
            pkg = entry.get("pkg")
            version = entry.get("version")
            if not (isinstance(pkg, str) and _is_valid_pypi(pkg)):
                continue
            if not (isinstance(version, str) and _is_valid_version(version)):
                continue
            out["pkg"] = pkg
            out["version"] = version
            valid.append(out)
            continue

        if op == "replace_in_requirements":
            old = entry.get("old")
            new = entry.get("new")
            if not (isinstance(old, str) and _is_valid_pypi(old)):
                continue
            if not (isinstance(new, str) and _is_valid_pypi(new)):
                continue
            out["old"] = old
            out["new"] = new
            valid.append(out)
            continue

        if op == "add_apt_package":
            pkg = entry.get("pkg")
            if not isinstance(pkg, str) or not _is_valid_apt(pkg):
                continue
            out["pkg"] = pkg
            valid.append(out)
            continue

    return valid


# -------- Apply ops to the repo --------


def _bare_name(line: str) -> str:
    """Extract the bare lowercased package name from a requirements.txt line."""
    bare = line.strip().split("[")[0]
    for sep in ("==", ">=", "<=", "~=", ">", "<", "!="):
        if sep in bare:
            bare = bare.split(sep)[0]
            break
    return bare.strip().lower()


def apply_llm_ops(
    ops: list[dict[str, Any]], repo: Path
) -> tuple[list[BuildAdjustment], list[str]]:
    """Apply the validated ops; return (adjustments, apt_packages_to_install).

    Reads requirements.txt once into memory, applies all ops, and writes it
    back once at the end (or never, if no op touched it).
    """
    adjustments: list[BuildAdjustment] = []
    apt: list[str] = []

    req_path = repo / "requirements.txt"
    lines: list[str]
    if req_path.exists():
        lines = req_path.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        lines = []
    existing = {n for n in (_bare_name(ln) for ln in lines) if n}
    dirty = False

    for op in ops:
        kind = op["op"]
        reason = op.get("reason", "")

        if kind == "give_up":
            adjustments.append(
                BuildAdjustment(
                    phase="llm",
                    kind="give_up",
                    description=f"LLM gave up on auto-fixing: {reason}",
                )
            )
            continue

        if kind == "add_to_requirements":
            pkg = op["pkg"]
            root = pkg.split("[")[0].lower()
            if root in existing:
                continue
            lines.append(pkg)
            existing.add(root)
            dirty = True
            adjustments.append(
                BuildAdjustment(
                    phase="llm",
                    kind="missing_dep",
                    description=f"LLM: added `{pkg}` to requirements.txt — {reason}",
                )
            )
            continue

        if kind == "pin_version":
            pkg = op["pkg"]
            version = op["version"]
            pinned = f"{pkg}=={version}"
            replaced = False
            for i, ln in enumerate(lines):
                if _bare_name(ln) == pkg.lower():
                    lines[i] = pinned
                    replaced = True
                    break
            if not replaced:
                lines.append(pinned)
                existing.add(pkg.lower())
            dirty = True
            adjustments.append(
                BuildAdjustment(
                    phase="llm",
                    kind="pin_version",
                    description=f"LLM: pinned `{pkg}=={version}` — {reason}",
                )
            )
            continue

        if kind == "replace_in_requirements":
            old = op["old"]
            new = op["new"]
            changed = False
            for i, ln in enumerate(lines):
                if _bare_name(ln) == old.lower():
                    lines[i] = new
                    changed = True
            if changed:
                dirty = True
                adjustments.append(
                    BuildAdjustment(
                        phase="llm",
                        kind="incomplete_dep",
                        description=f"LLM: replaced `{old}` with `{new}` — {reason}",
                    )
                )
            continue

        if kind == "add_apt_package":
            pkg = op["pkg"]
            if pkg not in apt:
                apt.append(pkg)
                adjustments.append(
                    BuildAdjustment(
                        phase="llm",
                        kind="apt_dev_header",
                        description=f"LLM: apt-get install `{pkg}` — {reason}",
                    )
                )
            continue

    if dirty:
        req_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return adjustments, apt


# -------- LLM call --------


_SYSTEM_PROMPT = """A Docker build of a Python repo failed. Suggest minimal fixes.

Return JSON ONLY: an array of operation objects. Allowed operations:

  {"op": "add_to_requirements", "pkg": "<pypi-name>", "reason": "<short>"}
  {"op": "pin_version", "pkg": "<pypi-name>", "version": "<ver>", "reason": "<short>"}
  {"op": "replace_in_requirements", "old": "<pypi-name>", "new": "<pypi-name>", "reason": "<short>"}
  {"op": "add_apt_package", "pkg": "<apt-name>", "reason": "<short>"}
  {"op": "give_up", "reason": "<why>"}

Keep changes minimal. Use give_up if you don't know."""


def suggest_build_fixes(
    error_log: str,
    repo_path: Path,
    llm_client,
    *,
    idle_timeout_seconds: float = 120.0,
) -> list[dict[str, Any]]:
    """Run one LLM call against the error log + repo state; return validated ops."""
    p = repo_path / "requirements.txt"
    reqs = p.read_text(encoding="utf-8", errors="replace") if p.exists() else "(none)"
    tail = "\n".join(error_log.splitlines()[-40:])
    user = (
        f"requirements.txt:\n{reqs}\n\n"
        f"build error log (tail):\n{tail}\n\n"
        "Return the JSON array of ops."
    )
    try:
        try:
            raw = llm_client.complete_json(
                _SYSTEM_PROMPT, user, temperature=0.0, idle_timeout_seconds=idle_timeout_seconds
            )
        except TypeError:
            raw = llm_client.complete_json(_SYSTEM_PROMPT, user, temperature=0.0)
    except Exception:
        return []
    return parse_llm_ops(raw)

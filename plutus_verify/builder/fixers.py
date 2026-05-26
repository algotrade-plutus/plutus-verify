"""Hardcoded build-fixer library.

Each fixer is a (detector, fixer) pair operating either on the on-disk repo
(pre-build) or on a captured build error log (post-build). Detectors are
strict so we don't apply a fix unnecessarily; fixers are idempotent.

Pre-build catches things we can see *before* running Docker:
  - UTF-16 BOM ``requirements.txt`` (decode + rewrite as UTF-8 LF)
  - CRLF line endings in ``requirements.txt`` (normalise to LF)
  - ``psycopg`` (v3) / ``psycopg2`` declared without their binary extras
    (swap to ``psycopg[binary]`` / ``psycopg2-binary``)

Post-build catches recurring failure signatures from a real ``docker build``:
  - "Could not find a version that satisfies the requirement <pkg>" — try the
    binary variant (`-binary` suffix) when the pkg is psycopg / psycopg2
  - "fatal error: <X>.h: No such file or directory" — return the apt-get
    package that ships that header
  - "ModuleNotFoundError: No module named '<X>'" — add X to requirements
"""
from __future__ import annotations

import re
from pathlib import Path

from plutus_verify.builder.runner import BuildAdjustment


# Map from missing-header → apt package that ships it.
_HEADER_TO_APT = {
    "libpq-fe.h": "libpq-dev",
    "Python.h": "python3-dev",
    "ffi.h": "libffi-dev",
    "openssl/ssl.h": "libssl-dev",
    "lapack.h": "liblapack-dev",
    "blas.h": "libblas-dev",
    "sasl.h": "libsasl2-dev",
    "ldap.h": "libldap2-dev",
    "krb5.h": "libkrb5-dev",
    "stdio.h": "build-essential",  # implies general toolchain missing
}


def _read_requirements_bytes(repo: Path) -> "bytes | None":
    p = repo / "requirements.txt"
    if not p.exists():
        return None
    return p.read_bytes()


def _write_requirements_text(repo: Path, text: str) -> None:
    (repo / "requirements.txt").write_text(text, encoding="utf-8")


# -------- Pre-build fixers --------


def _fix_utf16_bom(repo: Path) -> "BuildAdjustment | None":
    raw = _read_requirements_bytes(repo)
    if raw is None or len(raw) < 2:
        return None
    bom = raw[:2]
    if bom == b"\xff\xfe":
        text = raw[2:].decode("utf-16-le", errors="replace")
    elif bom == b"\xfe\xff":
        text = raw[2:].decode("utf-16-be", errors="replace")
    else:
        return None
    # Normalise line endings + write back as UTF-8
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    _write_requirements_text(repo, text)
    return BuildAdjustment(
        phase="pre_build",
        kind="encoding",
        description="rewrote requirements.txt from UTF-16 BOM to UTF-8",
    )


def _fix_crlf_in_requirements(repo: Path) -> "BuildAdjustment | None":
    raw = _read_requirements_bytes(repo)
    if raw is None:
        return None
    if b"\r\n" not in raw:
        return None
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    _write_requirements_text(repo, text)
    return BuildAdjustment(
        phase="pre_build",
        kind="encoding",
        description="normalised CRLF line endings in requirements.txt to LF",
    )


_PSYCOPG_LINE_RE = re.compile(r"^\s*psycopg\s*(?:[<>=!~].*)?$", re.MULTILINE)
_PSYCOPG2_LINE_RE = re.compile(r"^\s*psycopg2\s*(?:[<>=!~].*)?$", re.MULTILINE)


def _fix_psycopg_binary(repo: Path) -> "BuildAdjustment | None":
    p = repo / "requirements.txt"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    changed = False
    if _PSYCOPG_LINE_RE.search(text) and "psycopg[binary]" not in text:
        text = _PSYCOPG_LINE_RE.sub("psycopg[binary]", text)
        changed = True
    if changed:
        p.write_text(text, encoding="utf-8")
        return BuildAdjustment(
            phase="pre_build",
            kind="incomplete_dep",
            description="replaced `psycopg` with `psycopg[binary]` (slim image lacks libpq)",
        )
    return None


def _fix_psycopg2_binary(repo: Path) -> "BuildAdjustment | None":
    p = repo / "requirements.txt"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    if not _PSYCOPG2_LINE_RE.search(text) or "psycopg2-binary" in text:
        return None
    text = _PSYCOPG2_LINE_RE.sub("psycopg2-binary", text)
    p.write_text(text, encoding="utf-8")
    return BuildAdjustment(
        phase="pre_build",
        kind="incomplete_dep",
        description="replaced `psycopg2` with `psycopg2-binary` (slim image lacks libpq)",
    )


_PRE_BUILD_FIXERS = (
    _fix_utf16_bom,
    _fix_crlf_in_requirements,
    _fix_psycopg_binary,
    _fix_psycopg2_binary,
)


def run_pre_build_fixers(repo: Path) -> tuple[BuildAdjustment, ...]:
    """Run all pre-build fixers in declared order; return adjustments applied."""
    applied: list[BuildAdjustment] = []
    for fn in _PRE_BUILD_FIXERS:
        adj = fn(repo)
        if adj is not None:
            applied.append(adj)
    return tuple(applied)


# -------- Post-build fixers --------


_RE_UNSAT = re.compile(
    r"Could not find a version that satisfies the requirement (\S+)"
)
_RE_MISSING_HEADER = re.compile(
    r"fatal error: ([A-Za-z0-9_/.+-]+\.h): No such file or directory"
)
_RE_MISSING_MODULE = re.compile(
    r"ModuleNotFoundError: No module named ['\"]([A-Za-z0-9_.\-]+)['\"]"
)


_PKG_BINARY_EQUIVALENT = {
    "psycopg": "psycopg[binary]",
    "psycopg2": "psycopg2-binary",
}


def _append_to_requirements(repo: Path, line: str) -> bool:
    p = repo / "requirements.txt"
    text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    pinned_root = line.split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip()
    if any(
        ln.strip().split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip() == pinned_root
        for ln in text.splitlines()
    ):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += line + "\n"
    p.write_text(text, encoding="utf-8")
    return True


def run_post_build_fixers(
    repo: Path, error_log: str
) -> tuple[tuple[BuildAdjustment, ...], list[str]]:
    """Inspect ``error_log`` and apply matching deterministic fixers.

    Returns ``(adjustments, apt_packages_to_install)``. apt_packages should be
    threaded into the Dockerfile template on the next attempt.
    """
    adjustments: list[BuildAdjustment] = []
    apt: list[str] = []

    # 1. Unsatisfiable package -> binary variant
    for pkg in _RE_UNSAT.findall(error_log):
        bare = pkg.split("[")[0]
        if bare in _PKG_BINARY_EQUIVALENT:
            equiv = _PKG_BINARY_EQUIVALENT[bare]
            # Rewrite the requirement
            p = repo / "requirements.txt"
            if p.exists():
                text = p.read_text(encoding="utf-8", errors="replace")
                pattern = re.compile(rf"^\s*{re.escape(bare)}(\s.*)?$", re.MULTILINE)
                new_text, n = pattern.subn(equiv, text, count=1)
                if n > 0 and new_text != text:
                    p.write_text(new_text, encoding="utf-8")
                    adjustments.append(
                        BuildAdjustment(
                            phase="post_build",
                            kind="incomplete_dep",
                            description=(
                                f"replaced `{bare}` with `{equiv}` after pip couldn't "
                                "satisfy the bare package"
                            ),
                        )
                    )

    # 2. Missing C header -> apt package
    for header in _RE_MISSING_HEADER.findall(error_log):
        pkg = _HEADER_TO_APT.get(header)
        if pkg and pkg not in apt:
            apt.append(pkg)
            adjustments.append(
                BuildAdjustment(
                    phase="post_build",
                    kind="apt_dev_header",
                    description=(
                        f"added apt package `{pkg}` to provide missing header "
                        f"`{header}`"
                    ),
                )
            )

    # 3. ModuleNotFoundError -> add as requirement
    for missing in _RE_MISSING_MODULE.findall(error_log):
        # Strip submodule path (foo.bar -> foo)
        root = missing.split(".")[0]
        if _append_to_requirements(repo, root):
            adjustments.append(
                BuildAdjustment(
                    phase="post_build",
                    kind="missing_dep",
                    description=(
                        f"added `{root}` to requirements.txt (transitive dep gap)"
                    ),
                )
            )

    return tuple(adjustments), apt

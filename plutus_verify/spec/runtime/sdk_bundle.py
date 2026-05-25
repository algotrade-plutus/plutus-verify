"""Locate the plutus-verify source and build a wheel for the Docker image.

The Docker pipeline needs to install `plutus-verify` inside the image so the
runtime helpers (results loading, comparisons, etc.) are available to the
generated entrypoint. This module finds the SDK's source on the local
filesystem and produces a wheel that the Dockerfile generator can ``COPY``
into the build context.

Public API:
    ``ensure_plutus_wheel(build_context_dir)`` returns the absolute path to a
    wheel matching the currently-installed plutus-verify version. Idempotent:
    a fresh wheel is reused; stale older-version wheels are cleaned up.

Resolution order (first success wins):

1. **Vendored wheel** -- a wheel shipped inside the installed package at
   ``plutus_verify/_bundled/plutus_verify-X.Y.Z-py3-none-any.whl``. Populated
   by ``scripts/release-build.sh`` before each release; absent in editable
   dev installs. Production path; no on-demand build.
2. **PEP 610 ``direct_url.json``** -- editable wheel-format installs.
3. **Egg-info-adjacent source tree** -- legacy editable installs.

(2) and (3) build a wheel on demand via ``python -m build``. (1) just
copies the prebuilt wheel into the build context.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


class SdkBundleError(RuntimeError):
    """Failed to locate or build a plutus-verify wheel."""


_PACKAGE = "plutus-verify"
_WHEEL_PREFIX = "plutus_verify"


def _vendored_wheel() -> Optional[Path]:
    """Return path to the bundled wheel shipped inside the installed package.

    Returns ``None`` if no wheel ships inside ``plutus_verify/_bundled/``
    (the dev/editable case).
    """
    try:
        from importlib.resources import files

        bundled = files("plutus_verify._bundled")
        for entry in bundled.iterdir():
            if entry.name.endswith(".whl") and entry.is_file():
                # Convert Traversable to Path via str. For filesystem-backed
                # resources (the only case we ship in) this is a real path.
                return Path(str(entry))
    except (ImportError, FileNotFoundError, ModuleNotFoundError, OSError):
        return None
    return None


def ensure_plutus_wheel(build_context_dir: Path) -> Path:
    """Build (or reuse) a plutus_verify wheel inside ``build_context_dir``.

    Returns the absolute path to the staged wheel (``.whl`` file).

    Strategy (in order -- first one to succeed wins):
        1. Vendored wheel: ``plutus_verify/_bundled/plutus_verify-*.whl``
           shipped inside the installed package. Production path; no build.
        2. PEP 610 ``direct_url.json`` (editable wheel-format install).
        3. Egg-info-adjacent source tree (legacy editable install).

    For (1), the wheel is staged into ``build_context_dir`` via
    ``shutil.copy2``; no ``python -m build`` invocation. For (2) and (3),
    fall back to the existing build-from-source code path.

    Raises:
        SdkBundleError: source not locatable, build failed, or the target
            path exists as a file rather than a directory.
    """
    build_context_dir = Path(build_context_dir)

    if build_context_dir.exists() and not build_context_dir.is_dir():
        raise SdkBundleError(
            f"build context path is not a directory: {build_context_dir}"
        )

    try:
        build_context_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SdkBundleError(
            f"could not create build context dir {build_context_dir}: {exc}"
        ) from exc

    build_context_dir = build_context_dir.resolve()

    try:
        dist = distribution(_PACKAGE)
    except PackageNotFoundError as exc:
        raise SdkBundleError(
            f"{_PACKAGE} is not installed in the current environment; "
            "cannot bundle SDK for Docker image"
        ) from exc

    current_version = dist.version
    expected_wheel = (
        build_context_dir
        / f"{_WHEEL_PREFIX}-{current_version}-py3-none-any.whl"
    )
    if expected_wheel.exists():
        return expected_wheel

    # Clean up stale wheels from a previous version.
    for stale in build_context_dir.glob(f"{_WHEEL_PREFIX}-*-py3-none-any.whl"):
        try:
            stale.unlink()
        except OSError:
            pass

    # Strategy 1: vendored wheel inside the installed package.
    vendored = _vendored_wheel()
    if vendored is not None and vendored.exists():
        shutil.copy2(vendored, expected_wheel)
        return expected_wheel

    # Strategies 2 + 3: locate source on disk and build a wheel.
    source_dir = _locate_source(dist)
    tmp_wheel = _build_wheel_from_source(source_dir)

    shutil.copy2(tmp_wheel, expected_wheel)
    return expected_wheel


def _locate_source(dist) -> Path:
    """Return the source directory of an editable plutus-verify install.

    Tries PEP 610 ``direct_url.json`` first; falls back to the parent of an
    ``*.egg-info`` directory when ``direct_url.json`` is unavailable.
    """
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text:
        try:
            data = json.loads(direct_url_text)
        except json.JSONDecodeError as exc:
            raise SdkBundleError(
                f"could not parse direct_url.json for {_PACKAGE}: {exc}"
            ) from exc
        url = data.get("url", "")
        dir_info = data.get("dir_info", {}) or {}
        if url.startswith("file://") and dir_info.get("editable"):
            source_dir = Path(urlparse(url).path)
            if (source_dir / "pyproject.toml").is_file():
                return source_dir
            raise SdkBundleError(
                f"{_PACKAGE} direct_url points at {source_dir} but no "
                "pyproject.toml found there"
            )
        raise SdkBundleError(
            f"{_PACKAGE} is installed non-editably; SDK bundling requires an "
            "editable install or a PyPI release (not yet supported here)"
        )

    # Fallback for editable installs that didn't produce direct_url.json
    # (e.g. setuptools' default .egg-info layout): locate the source via the
    # imported package's __file__, then walk up to the directory containing
    # pyproject.toml. Public API; no private attributes.
    import plutus_verify

    mod_dir = Path(plutus_verify.__file__).resolve().parent
    candidate = mod_dir.parent
    if (candidate / "pyproject.toml").is_file():
        return candidate

    raise SdkBundleError(
        f"could not locate {_PACKAGE} source on disk: no PEP 610 "
        "direct_url.json and no pyproject.toml next to plutus_verify package"
    )


def _build_wheel_from_source(source_dir: Path) -> Path:
    """Run ``python -m build --wheel`` and return the resulting wheel path.

    The wheel is left inside a temp directory whose lifetime is bounded by
    the caller — the caller is expected to ``shutil.copy2`` it elsewhere
    immediately. We return the path inside the temp dir; the temp dir is
    deliberately *not* cleaned here because doing so would invalidate the
    returned path. Callers should copy the file and let the OS reclaim the
    temp dir later (or wrap this in their own context).
    """
    tmp = Path(tempfile.mkdtemp(prefix="plutus-sdk-wheel-"))
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp)],
        cwd=str(source_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SdkBundleError(
            f"`python -m build --wheel` failed in {source_dir} "
            f"(exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    wheels = list(tmp.glob(f"{_WHEEL_PREFIX}-*-py3-none-any.whl"))
    if not wheels:
        raise SdkBundleError(
            f"build succeeded but no wheel was produced in {tmp}"
        )
    return wheels[0]

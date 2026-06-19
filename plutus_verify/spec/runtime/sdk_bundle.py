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
4. **Re-pack the installed files** -- last resort for a plain (non-self-bundling,
   non-editable) wheel install: re-zip the recorded package tree + ``.dist-info``
   into a fresh wheel. No source, no PyPI.

(2) and (3) build a wheel on demand via ``python -m build``. (1) just copies the
prebuilt wheel into the build context. (4) re-zips the installed files in place.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


class SdkBundleError(RuntimeError):
    """Failed to locate or build a plutus-verify wheel."""


_PACKAGE = "plutus-verify"
_WHEEL_PREFIX = "plutus_verify"

# Shown when the SDK can't be staged into the image because the install is a
# plain (non-self-bundling) wheel and isn't editable. Names the three working
# resolution strategies in priority order so the message is actionable — a
# *release* wheel installed non-editably works fine (it self-bundles), which the
# old "editable install or a PyPI release" wording wrongly implied it didn't.
_NON_SELF_BUNDLING_HINT = (
    f"To stage the SDK into the image, install {_PACKAGE} as either:\n"
    f"  - a RELEASE wheel (self-bundling), e.g. `uv pip install <release-wheel>` "
    f"or `uv tool install <release-wheel>` (built by scripts/release-build.sh); or\n"
    f"  - an editable checkout: `pip install -e .` / `uv pip install -e .`.\n"
    f"The verifier resolves the SDK in order: vendored plutus_verify/_bundled/ "
    f"wheel (RELEASE wheel only) -> editable source build -> re-pack of the "
    f"installed files. A plain `uv build` / `python -m build` wheel normally works "
    f"via re-pack; this error means even that failed (e.g. the install has no "
    f"RECORD manifest)."
)


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

    # Strategies 2 + 3: locate an editable source on disk and build a fresh wheel.
    try:
        source_dir = _locate_source(dist)
    except SdkBundleError:
        # Strategy 4 (last resort): no vendored wheel and no source — re-pack the
        # installed package files into a wheel. Makes a plain (non-self-bundling)
        # wheel install work with no PyPI and no source checkout. Re-raises the
        # actionable source error if even re-packing can't run.
        tmp_wheel = _repack_installed_wheel(dist)
    else:
        tmp_wheel = _build_wheel_from_source(source_dir)

    shutil.copy2(tmp_wheel, expected_wheel)
    return expected_wheel


def _repack_installed_wheel(dist) -> Path:
    """Reconstruct a wheel from the files of an already-installed plutus-verify.

    Strategy 4 — the last resort when there is no vendored wheel (plain, not a
    release wheel) and no source tree on disk (non-editable). Re-zips the recorded
    package tree and its ``.dist-info`` into a fresh ``.whl`` so the image still
    gets a valid, installable SDK. No network, no PyPI, no ``python -m build``.

    The re-packed wheel needs no populated ``_bundled/`` — it's only staged into
    the image and ``pip install``ed there; the image doesn't bundle further.

    Installer-generated entries (console scripts that escape site-packages, e.g.
    ``../../bin/plutus``) and byte-compiled ``.pyc`` / ``__pycache__`` are skipped:
    a wheel ships neither.
    """
    files = getattr(dist, "files", None)
    if not files:
        raise SdkBundleError(
            f"cannot re-pack the installed {_PACKAGE}: no file manifest (RECORD) "
            f"is available for the install.\n\n{_NON_SELF_BUNDLING_HINT}"
        )

    dist_info = f"{_WHEEL_PREFIX}-{dist.version}.dist-info"
    tmp = Path(tempfile.mkdtemp(prefix="plutus-sdk-repack-"))
    wheel_path = tmp / f"{_WHEEL_PREFIX}-{dist.version}-py3-none-any.whl"

    written = 0
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in files:
            posix = entry.as_posix()
            top = posix.split("/", 1)[0]
            # Only the package tree and its dist-info belong in a wheel.
            if top not in (_WHEEL_PREFIX, dist_info):
                continue
            if posix.endswith(".pyc") or "__pycache__" in posix:
                continue
            src = Path(dist.locate_file(entry))
            if not src.is_file():
                continue
            zf.write(src, posix)
            written += 1

    if written == 0:
        raise SdkBundleError(
            f"cannot re-pack the installed {_PACKAGE}: no package files found on "
            f"disk.\n\n{_NON_SELF_BUNDLING_HINT}"
        )
    return wheel_path


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
        raise SdkBundleError(_NON_SELF_BUNDLING_HINT)

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
        f"could not locate a {_PACKAGE} SDK to bundle (no PEP 610 "
        f"direct_url.json and no pyproject.toml next to the plutus_verify "
        f"package).\n\n{_NON_SELF_BUNDLING_HINT}"
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

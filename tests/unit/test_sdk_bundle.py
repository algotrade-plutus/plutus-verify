"""Tests for SDK wheel bundling helper (Plan 7 Task 2)."""
from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import pytest

from plutus_verify.spec.runtime.sdk_bundle import (
    SdkBundleError,
    ensure_plutus_wheel,
)


def _current_version() -> str:
    return distribution("plutus-verify").version


def test_ensure_plutus_wheel_builds_wheel_in_target_dir(tmp_path):
    """Happy path: builds a wheel matching the current plutus-verify version."""
    wheel = ensure_plutus_wheel(tmp_path)

    assert wheel.exists(), f"wheel does not exist: {wheel}"
    assert wheel.is_file()
    assert tmp_path.resolve() in wheel.resolve().parents, (
        f"wheel {wheel} is not inside {tmp_path}"
    )
    version = _current_version()
    assert wheel.name == f"plutus_verify-{version}-py3-none-any.whl"


def test_ensure_plutus_wheel_is_idempotent(tmp_path):
    """A second call with a fresh wheel reuses it (no rebuild)."""
    first = ensure_plutus_wheel(tmp_path)
    first_mtime = first.stat().st_mtime

    second = ensure_plutus_wheel(tmp_path)
    second_mtime = second.stat().st_mtime

    assert first == second
    assert first_mtime == second_mtime, (
        "second call should not have rebuilt the wheel"
    )


def test_ensure_plutus_wheel_cleans_stale_versions(tmp_path):
    """A wheel with a different version is removed during ensure."""
    stale = tmp_path / "plutus_verify-0.0.1-py3-none-any.whl"
    stale.write_bytes(b"stale")

    wheel = ensure_plutus_wheel(tmp_path)

    assert not stale.exists(), "stale wheel was not cleaned up"
    assert wheel.exists()
    assert wheel.name == f"plutus_verify-{_current_version()}-py3-none-any.whl"


def test_ensure_plutus_wheel_creates_target_dir(tmp_path):
    """If target dir does not exist, it gets created."""
    nested = tmp_path / "nested" / "build"
    assert not nested.exists()

    wheel = ensure_plutus_wheel(nested)

    assert nested.is_dir()
    assert wheel.parent.resolve() == nested.resolve()


def test_ensure_plutus_wheel_raises_when_package_not_installed(
    tmp_path, monkeypatch
):
    """If plutus-verify is not findable, raise SdkBundleError."""

    def _raise(_name):
        raise PackageNotFoundError("plutus-verify")

    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle.distribution", _raise
    )

    with pytest.raises(SdkBundleError, match="plutus-verify"):
        ensure_plutus_wheel(tmp_path)


def test_ensure_plutus_wheel_raises_on_build_failure(tmp_path, monkeypatch):
    """If `python -m build` fails, raise SdkBundleError with stderr."""

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="some stdout",
            stderr="BUILD FAILED: bad zen detected",
        )

    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle.subprocess.run", _fake_run
    )

    with pytest.raises(SdkBundleError, match="BUILD FAILED: bad zen detected"):
        ensure_plutus_wheel(tmp_path)


def test_ensure_plutus_wheel_target_is_a_file_raises(tmp_path):
    """If target path exists as a file (not a directory), raise SdkBundleError."""
    target = tmp_path / "build"
    target.write_text("i am a file, not a dir")

    with pytest.raises(SdkBundleError):
        ensure_plutus_wheel(target)


def test_vendored_wheel_is_used_when_present(tmp_path, monkeypatch):
    """When a vendored wheel ships in the installed package, use it directly
    -- no `python -m build` invocation.
    """
    version = _current_version()
    fake_wheel = tmp_path / f"plutus_verify-{version}-py3-none-any.whl"
    fake_wheel.write_bytes(b"PRETEND-WHEEL-BYTES")

    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle._vendored_wheel",
        lambda: fake_wheel,
    )

    # If anything tries to shell out to `python -m build`, fail loudly.
    def _explode(*_args, **_kwargs):
        raise AssertionError(
            "subprocess.run must not be called when a vendored wheel is present"
        )

    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle.subprocess.run", _explode
    )

    build_dir = tmp_path / "build"
    wheel = ensure_plutus_wheel(build_dir)

    assert wheel.exists()
    assert wheel.name == f"plutus_verify-{version}-py3-none-any.whl"
    assert wheel.parent.resolve() == build_dir.resolve()
    assert wheel.read_bytes() == b"PRETEND-WHEEL-BYTES", (
        "staged wheel content should match the vendored wheel byte-for-byte"
    )


def test_vendored_wheel_path_falls_back_when_absent(tmp_path, monkeypatch):
    """When no vendored wheel ships (dev/editable install), the existing
    source-build path runs and produces a real wheel.
    """
    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle._vendored_wheel",
        lambda: None,
    )

    wheel = ensure_plutus_wheel(tmp_path)

    assert wheel.exists()
    assert wheel.name == f"plutus_verify-{_current_version()}-py3-none-any.whl"


def test_noneditable_plain_wheel_error_is_actionable():
    """A plain (non-self-bundling) wheel installed non-editably must produce an
    error that names the working fix — the RELEASE wheel — not the misleading
    "editable install or a PyPI release (not yet supported)" phrasing that
    confused the 9-step dogfood. See handoff Request 1, ask 2."""
    import json as _json

    from plutus_verify.spec.runtime.sdk_bundle import _locate_source

    class _FakeDist:
        def read_text(self, name):
            if name == "direct_url.json":
                # url is a file:// wheel, dir_info NOT editable → the non-editable branch
                return _json.dumps(
                    {
                        "url": "file:///tmp/plutus_verify-9.9-py3-none-any.whl",
                        "dir_info": {},
                    }
                )
            return None

    with pytest.raises(SdkBundleError) as exc:
        _locate_source(_FakeDist())
    msg = str(exc.value)
    assert "release wheel" in msg.lower(), f"error should name the release wheel: {msg}"
    assert "uv pip install" in msg, f"error should give an install command: {msg}"
    assert "not yet supported" not in msg, "the misleading phrasing should be gone"


def test_repack_installed_wheel_reconstructs_valid_wheel(tmp_path):
    """Strategy 4: reconstruct a wheel from the installed package files when there
    is no source and no vendored wheel (a plain non-editable wheel install). The
    result must contain the package tree + dist-info and EXCLUDE installer-generated
    scripts and .pyc. See handoff Request 1, ask 3."""
    import zipfile
    from importlib.metadata import PackagePath

    from plutus_verify.spec.runtime.sdk_bundle import _repack_installed_wheel

    base = tmp_path / "site-packages"
    (base / "plutus_verify").mkdir(parents=True)
    (base / "plutus_verify" / "__init__.py").write_text("__version__='9.9.9'\n")
    (base / "plutus_verify" / "core.py").write_text("x = 1\n")
    (base / "plutus_verify" / "__pycache__").mkdir()
    (base / "plutus_verify" / "__pycache__" / "core.cpython-311.pyc").write_bytes(b"PYC")
    di = base / "plutus_verify-9.9.9.dist-info"
    di.mkdir()
    (di / "METADATA").write_text("Name: plutus-verify\nVersion: 9.9.9\n")
    (di / "WHEEL").write_text("Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
    (di / "RECORD").write_text("plutus_verify/__init__.py,,\n")
    (base.parent / "bin").mkdir(exist_ok=True)
    (base.parent / "bin" / "plutus").write_text("#!/bin/sh\n")  # installer script

    class _FakeDist:
        version = "9.9.9"

        @property
        def files(self):
            return [
                PackagePath("plutus_verify/__init__.py"),
                PackagePath("plutus_verify/core.py"),
                PackagePath("plutus_verify/__pycache__/core.cpython-311.pyc"),
                PackagePath("plutus_verify-9.9.9.dist-info/METADATA"),
                PackagePath("plutus_verify-9.9.9.dist-info/WHEEL"),
                PackagePath("plutus_verify-9.9.9.dist-info/RECORD"),
                PackagePath("../../bin/plutus"),  # installer script, escapes site-packages
            ]

        def locate_file(self, p):
            return base / str(p)

    wheel = _repack_installed_wheel(_FakeDist())

    assert wheel.name == "plutus_verify-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
    assert "plutus_verify/__init__.py" in names
    assert "plutus_verify/core.py" in names
    assert "plutus_verify-9.9.9.dist-info/METADATA" in names
    assert "plutus_verify-9.9.9.dist-info/WHEEL" in names
    # excluded: installer script + bytecode
    assert not any("bin/plutus" in n for n in names), names
    assert not any(n.endswith(".pyc") for n in names), names


def test_ensure_plutus_wheel_strategy4_repacks_when_no_source(tmp_path, monkeypatch):
    """Wiring: when there's no vendored wheel AND no source on disk, ensure_plutus_wheel
    falls back to re-packing the installed wheel rather than raising."""
    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle._vendored_wheel", lambda: None
    )

    def _no_source(_dist):
        from plutus_verify.spec.runtime.sdk_bundle import SdkBundleError as _E
        raise _E("no editable source")

    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle._locate_source", _no_source
    )
    version = _current_version()
    repacked = tmp_path / f"plutus_verify-{version}-py3-none-any.whl"
    repacked.write_bytes(b"REPACKED-WHEEL")
    monkeypatch.setattr(
        "plutus_verify.spec.runtime.sdk_bundle._repack_installed_wheel",
        lambda dist: repacked,
    )

    build = tmp_path / "build"
    wheel = ensure_plutus_wheel(build)

    assert wheel.exists()
    assert wheel.name == f"plutus_verify-{version}-py3-none-any.whl"
    assert wheel.read_bytes() == b"REPACKED-WHEEL"
    assert wheel.parent.resolve() == build.resolve()


def test_vendored_wheel_helper_returns_none_in_dev_install():
    """In this editable dev install, _bundled/ is empty so the helper
    returns ``None`` (the wheel-existence branch in `ensure_plutus_wheel`
    is exercised in `test_vendored_wheel_is_used_when_present`).
    """
    from plutus_verify.spec.runtime.sdk_bundle import _vendored_wheel

    assert _vendored_wheel() is None

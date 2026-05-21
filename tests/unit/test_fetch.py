"""Tests for plutus_verify.fetch: opt-in download of manual_download alternatives.

The fetcher dispatches on URL host. We mock the underlying download tool (gdown,
wget, curl) and assert: the right tool is invoked with the right args, the
expected layout is checked post-download, and FetchResult reports correctly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from plutus_verify.extract.plan import StepAlternative
from plutus_verify.fetch import FetchResult, FetchSkipped, fetch_manual_download


def _alt(url: str, expected_layout: tuple[str, ...] = ("data/is/", "data/os/")) -> StepAlternative:
    return StepAlternative(
        label="Drive",
        kind="manual_download",
        url=url,
        expected_layout=expected_layout,
    )


# ---------- Source-type dispatch ----------


def test_dispatches_to_gdown_for_google_drive_folder(tmp_path: Path):
    """Folder download: gdown is given <repo>/data (common parent of layout)."""
    calls: list[tuple[str, Path]] = []

    def fake_gdown_folder(url: str, output: str, **kw) -> None:
        calls.append((url, Path(output)))
        # gdown extracts the Drive folder's contents INTO `output`.
        # The Drive root has `is/` and `os/` (no wrapping data/).
        (Path(output) / "is").mkdir(parents=True)
        (Path(output) / "os").mkdir(parents=True)
        (Path(output) / "is" / "x.csv").write_text("data")

    alt = _alt("https://drive.google.com/drive/folders/abc123")
    result = fetch_manual_download(
        alt, repo_path=tmp_path, gdown_folder=fake_gdown_folder
    )
    assert isinstance(result, FetchResult)
    assert result.ok, result.message
    assert calls and calls[0][0] == alt.url
    # Target should be <repo>/data (common parent of "data/is/" + "data/os/")
    assert calls[0][1] == tmp_path / "data"


def test_dispatches_to_gdown_for_google_drive_file(tmp_path: Path):
    calls: list[tuple[str, Path]] = []

    def fake_gdown_file(url: str, output: str, **kw) -> None:
        calls.append((url, Path(output)))
        # Simulate gdown placing a CSV inside the target dir so the layout check
        # passes after download. Target for layout=('data/is/',) is <repo>/data.
        (Path(output) / "is").mkdir(parents=True)
        (Path(output) / "is" / "downloaded.csv").write_text("data")

    alt = StepAlternative(
        label="x",
        kind="manual_download",
        url="https://drive.google.com/file/d/abc/view",
        expected_layout=("data/is/",),
    )
    result = fetch_manual_download(
        alt, repo_path=tmp_path, gdown_file=fake_gdown_file
    )
    assert result.ok, result.message
    assert calls and "drive.google.com" in calls[0][0]


def test_download_target_is_common_parent_of_expected_layout(tmp_path: Path):
    """For layout = ['data/is/', 'data/os/'], target = <repo>/data."""
    calls: list[tuple[str, Path]] = []

    def fake(url: str, output: str, **kw) -> None:
        calls.append((url, Path(output)))
        # Pretend Drive has the contents nested correctly
        (Path(output) / "is").mkdir(parents=True)
        (Path(output) / "os").mkdir(parents=True)

    alt = _alt(
        "https://drive.google.com/drive/folders/abc",
        expected_layout=("data/is/", "data/os/"),
    )
    fetch_manual_download(alt, repo_path=tmp_path, gdown_folder=fake)
    assert calls[0][1] == tmp_path / "data"


def test_download_target_is_repo_root_when_no_common_parent(tmp_path: Path):
    """For layout = ['is/', 'os/'], no common parent → download into repo root."""
    calls: list[tuple[str, Path]] = []

    def fake(url: str, output: str, **kw) -> None:
        calls.append((url, Path(output)))
        (Path(output) / "is").mkdir()
        (Path(output) / "os").mkdir()

    alt = _alt(
        "https://drive.google.com/drive/folders/abc",
        expected_layout=("is/", "os/"),
    )
    fetch_manual_download(alt, repo_path=tmp_path, gdown_folder=fake)
    assert calls[0][1] == tmp_path


def test_returns_skipped_for_unknown_url_host(tmp_path: Path):
    alt = _alt("https://example.com/some-data.zip")
    result = fetch_manual_download(alt, repo_path=tmp_path)
    assert isinstance(result, FetchSkipped)
    assert "unknown" in result.reason.lower() or "unsupported" in result.reason.lower()


# ---------- expected_layout verification ----------


def test_fetch_reports_failure_when_expected_layout_still_missing(tmp_path: Path):
    """If the downloader runs but doesn't produce expected files, fetch fails."""

    def lying_gdown(url: str, output: str, **kw) -> None:
        # Pretend success but don't create anything
        pass

    alt = _alt("https://drive.google.com/drive/folders/abc")
    result = fetch_manual_download(
        alt, repo_path=tmp_path, gdown_folder=lying_gdown
    )
    assert not result.ok
    assert "expected_layout" in result.message.lower() or "missing" in result.message.lower()


def test_fetch_short_circuits_if_layout_already_present(tmp_path: Path):
    """If the expected layout is already on disk, no download attempted."""
    (tmp_path / "data" / "is").mkdir(parents=True)
    (tmp_path / "data" / "os").mkdir(parents=True)
    (tmp_path / "data" / "is" / "x.csv").write_text("data")

    called = False

    def should_not_fire(*a, **kw):
        nonlocal called
        called = True

    alt = _alt("https://drive.google.com/drive/folders/abc")
    result = fetch_manual_download(
        alt, repo_path=tmp_path, gdown_folder=should_not_fire
    )
    assert result.ok
    assert not called
    assert "already" in result.message.lower() or "present" in result.message.lower()


# ---------- Downloader error handling ----------


def test_fetch_reports_failure_when_downloader_raises(tmp_path: Path):
    def boom(*a, **kw):
        raise RuntimeError("403 forbidden")

    alt = _alt("https://drive.google.com/drive/folders/abc")
    result = fetch_manual_download(
        alt, repo_path=tmp_path, gdown_folder=boom
    )
    assert not result.ok
    assert "403" in result.message or "forbidden" in result.message.lower()


# ---------- No URL means no fetch ----------


def test_fetch_skipped_when_alternative_has_no_url(tmp_path: Path):
    alt = StepAlternative(label="x", kind="manual_download", url=None)
    result = fetch_manual_download(alt, repo_path=tmp_path)
    assert isinstance(result, FetchSkipped)
    assert "url" in result.reason.lower()

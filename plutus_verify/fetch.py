"""Opt-in manual-download fetcher.

When the user passes ``--auto-fetch``, the pipeline calls
:func:`fetch_manual_download` for each step whose ``manual_download``
alternative's ``expected_layout`` files aren't present on disk.

The fetcher dispatches by URL host. Today: Google Drive (folders and files).
Add new sources by extending :func:`_pick_downloader`. The LLM is intentionally
not in the loop — the URL → tool mapping is deterministic.

All downloads are explicit (gated on the CLI flag) and reported as findings,
so reviewers see exactly what was fetched from where.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Callable, Optional

from plutus_verify.extract.plan import StepAlternative

__all__ = ["FetchResult", "FetchSkipped", "fetch_manual_download"]


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a fetch attempt that actually invoked a downloader."""

    ok: bool
    message: str


@dataclass(frozen=True)
class FetchSkipped:
    """Returned when we declined to fetch (unsupported URL, no URL, etc.)."""

    reason: str


_GDOWN_FOLDER_RE = re.compile(r"drive\.google\.com/(?:drive/)?folders/")
_GDOWN_FILE_RE = re.compile(r"drive\.google\.com/file/d/")


def _default_gdown_folder(url: str, output: str, **kwargs) -> None:
    import gdown  # local import to keep test stubs cheap

    gdown.download_folder(url, output=output, quiet=False, **kwargs)


def _default_gdown_file(url: str, output: str, **kwargs) -> None:
    import gdown

    gdown.download(url, output=output, quiet=False, fuzzy=True, **kwargs)


def _layout_entry_present(repo_path: Path, entry: str) -> bool:
    """Check one expected_layout entry, supporting glob patterns.

    Plain paths use ``.exists()``. Patterns with ``*`` or ``?`` are expanded
    via ``Path.glob`` and considered present iff at least one file matches.
    """
    if any(ch in entry for ch in "*?["):
        # Glob — strip trailing slash since glob doesn't match a bare dir.
        pattern = entry.rstrip("/")
        return any(True for _ in repo_path.glob(pattern))
    return (repo_path / entry).exists()


def _layout_present(repo_path: Path, expected_layout: tuple[str, ...]) -> bool:
    if not expected_layout:
        return False
    return all(_layout_entry_present(repo_path, p) for p in expected_layout)


def _common_parent_dir(expected_layout: tuple[str, ...]) -> str:
    """Compute the longest common parent directory of ``expected_layout``.

    The downloader extracts its content into this subdirectory relative to the
    repo root. Examples::

        ('data/is/', 'data/os/')   -> 'data'   # Plutus pattern
        ('data/raw.csv',)          -> 'data'
        ('is/', 'os/')             -> ''       # no common parent
        ('result/',)               -> 'result' # single-dir target

    Rationale: Plutus repos commonly publish their Google Drive folder with the
    inner data dirs (e.g. ``is/`` + ``os/``) at the root of the shared folder,
    and expect them placed under ``<repo>/data/``. Downloading directly into
    the common parent puts them in the right place.
    """
    if not expected_layout:
        return ""
    parts_list: list[tuple[str, ...]] = []
    for entry in expected_layout:
        stripped = entry.rstrip("/")
        pp = PurePath(stripped)
        # If the entry was a dir (trailing slash) keep all parts; if it was a
        # file path, use the parent's parts.
        parts_list.append(pp.parts if entry.endswith("/") else pp.parent.parts)
    common: list[str] = []
    for tup in zip(*parts_list):
        if all(x == tup[0] for x in tup):
            common.append(tup[0])
        else:
            break
    return "/".join(common)


def _layout_missing_message(repo_path: Path, expected_layout: tuple[str, ...]) -> str:
    missing = [p for p in expected_layout if not (repo_path / p).exists()]
    return f"expected_layout still missing after download: {missing}"


def fetch_manual_download(
    alt: StepAlternative,
    *,
    repo_path: Path,
    gdown_folder: Callable[..., None] = _default_gdown_folder,
    gdown_file: Callable[..., None] = _default_gdown_file,
) -> "FetchResult | FetchSkipped":
    """Attempt to fetch the data for a ``manual_download`` alternative.

    Returns ``FetchResult`` if a downloader was invoked (success or failure),
    or ``FetchSkipped`` if we declined (unknown source, no URL, etc.).
    """
    url = alt.url
    if not url:
        return FetchSkipped(reason="alternative has no URL")

    # If the layout is already on disk, do nothing — but report success so the
    # caller can move on to using this alternative.
    if _layout_present(repo_path, alt.expected_layout):
        return FetchResult(ok=True, message="expected_layout already present, no download needed")

    # Download into the common parent of expected_layout so the extracted
    # structure lands where the repo's scripts expect it.
    subdir = _common_parent_dir(alt.expected_layout)
    target_dir = repo_path / subdir if subdir else repo_path
    target_dir.mkdir(parents=True, exist_ok=True)
    target = str(target_dir)

    if _GDOWN_FOLDER_RE.search(url):
        try:
            gdown_folder(url, output=target)
        except Exception as exc:  # surface the downloader's error verbatim
            return FetchResult(ok=False, message=f"gdown folder download failed: {exc}")
    elif _GDOWN_FILE_RE.search(url):
        try:
            gdown_file(url, output=target)
        except Exception as exc:
            return FetchResult(ok=False, message=f"gdown file download failed: {exc}")
    else:
        return FetchSkipped(reason=f"unsupported URL host (no known downloader): {url}")

    if not _layout_present(repo_path, alt.expected_layout):
        return FetchResult(ok=False, message=_layout_missing_message(repo_path, alt.expected_layout))
    return FetchResult(ok=True, message=f"fetched from {url}")

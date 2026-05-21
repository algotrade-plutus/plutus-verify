"""Tiered data acquisition: processed > raw > run the code.

Resolver is downloader-agnostic — the caller injects a downloader callable
that returns True/False per attempted source. The default downloader (built
below) reuses fetch.py for Google Drive and urllib for plain HTTP / github
release tarballs. S3 is not implemented in Plan 2.
"""
from __future__ import annotations

import logging
import shutil
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

from plutus_verify.spec.manifest import DataSource, Manifest

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataTierResult:
    satisfied: frozenset[str]
    tier_used: Literal["processed", "raw", "code"]
    notes: tuple[str, ...] = ()


Downloader = Callable[[DataSource, Path], bool]


def resolve_data_tiers(
    manifest: Manifest,
    *,
    repo_path: Path,
    downloader: Downloader,
    force_tier: Optional[Literal["processed", "raw", "code"]] = None,
) -> DataTierResult:
    notes: list[str] = []
    if force_tier == "code":
        return DataTierResult(
            satisfied=frozenset(), tier_used="code", notes=("forced --data-tier=code",)
        )

    satisfied: set[str] = set()
    tier_used: Literal["processed", "raw", "code"] = "code"

    if force_tier in (None, "processed"):
        for ds in manifest.data_sources.processed:
            if _layout_present(repo_path, ds.expected_layout):
                notes.append(f"processed/{ds.kind}: layout already present")
                satisfied.update(ds.satisfies)
                tier_used = "processed"
                continue
            try:
                ok = downloader(ds, repo_path)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"processed/{ds.kind} failed: {exc}")
                continue
            if ok and _layout_present(repo_path, ds.expected_layout):
                notes.append(f"processed/{ds.kind}: downloaded")
                satisfied.update(ds.satisfies)
                tier_used = "processed"

    if force_tier in (None, "raw"):
        for ds in manifest.data_sources.raw:
            if set(ds.satisfies).issubset(satisfied):
                continue
            if _layout_present(repo_path, ds.expected_layout):
                notes.append(f"raw/{ds.kind}: layout already present")
                satisfied.update(ds.satisfies)
                if tier_used == "code":
                    tier_used = "raw"
                continue
            try:
                ok = downloader(ds, repo_path)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"raw/{ds.kind} failed: {exc}")
                continue
            if ok and _layout_present(repo_path, ds.expected_layout):
                notes.append(f"raw/{ds.kind}: downloaded")
                satisfied.update(ds.satisfies)
                if tier_used == "code":
                    tier_used = "raw"

    return DataTierResult(satisfied=frozenset(satisfied), tier_used=tier_used, notes=tuple(notes))


def _layout_present(repo_path: Path, expected_layout: tuple[str, ...]) -> bool:
    if not expected_layout:
        return False
    for entry in expected_layout:
        if any(ch in entry for ch in "*?["):
            if not any(True for _ in repo_path.glob(entry.rstrip("/"))):
                return False
        else:
            if not (repo_path / entry).exists():
                return False
    return True


def default_downloader(source: DataSource, target_dir: Path) -> bool:
    """Built-in downloader. Dispatches by ``source.kind``.

    Honors ``source.expected_layout``'s common parent: downloads land in
    ``<target_dir>/<common_parent>`` so a Google Drive folder whose contents
    are ``is/...`` + ``os/...`` end up under ``<target_dir>/data/`` when the
    expected_layout is ``["data/is/*", "data/os/*"]``.
    """
    common = _common_parent_dir(source.expected_layout)
    download_into = target_dir / common if common else target_dir
    kind = source.kind
    if kind == "google_drive":
        return _download_google_drive(source.url, download_into)
    if kind in ("github_release", "http"):
        return _download_url_archive(source.url, download_into)
    if kind == "s3":
        _log.warning("s3 downloader is not implemented in Plan 2; skipping %s", source.url)
        return False
    _log.warning("unknown data-source kind %r; skipping %s", kind, source.url)
    return False


def _common_parent_dir(expected_layout: tuple[str, ...]) -> str:
    """Longest common parent directory of all entries in ``expected_layout``.

    Examples:
        ('data/is/', 'data/os/')      -> 'data'
        ('data/raw/*.parquet',)       -> 'data/raw'
        ('out/m.json', 'out/c.png')   -> 'out'
        ()                            -> ''
    """
    from pathlib import PurePath

    if not expected_layout:
        return ""
    parts_list: list[tuple[str, ...]] = []
    for entry in expected_layout:
        stripped = entry.rstrip("/")
        # If entry is a glob, take everything before the first wildcard segment
        if any(ch in stripped for ch in "*?["):
            segs = stripped.split("/")
            for i, seg in enumerate(segs):
                if any(ch in seg for ch in "*?["):
                    segs = segs[:i]
                    break
            parts_list.append(tuple(segs))
            continue
        pp = PurePath(stripped)
        parts_list.append(pp.parts if entry.endswith("/") else pp.parent.parts)
    common: list[str] = []
    for tup in zip(*parts_list):
        if all(x == tup[0] for x in tup):
            common.append(tup[0])
        else:
            break
    return "/".join(common)


def _download_google_drive(url: str, target_dir: Path) -> bool:
    try:
        from plutus_verify.fetch import _default_gdown_file, _default_gdown_folder
    except ImportError:
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        if "/folders/" in url:
            _default_gdown_folder(url, output=str(target_dir))
        else:
            _default_gdown_file(url, output=str(target_dir))
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("gdown failed for %s: %s", url, exc)
        return False


def _download_url_archive(url: str, target_dir: Path) -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_path = target_dir / Path(url).name
    try:
        with urllib.request.urlopen(url) as resp, archive_path.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception as exc:  # noqa: BLE001
        _log.warning("download failed for %s: %s", url, exc)
        return False
    suffix = "".join(archive_path.suffixes).lower()
    try:
        if suffix.endswith(".tar.gz") or suffix.endswith(".tgz"):
            with tarfile.open(archive_path, "r:gz") as tf:
                tf.extractall(target_dir)
        elif suffix.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(target_dir)
        else:
            return True  # raw file download — no extraction
    except Exception as exc:  # noqa: BLE001
        _log.warning("archive extraction failed for %s: %s", archive_path, exc)
        return False
    return True

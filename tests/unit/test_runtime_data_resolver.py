"""Tests for the v2 data-tier resolver."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.spec.manifest import DataSource, DataSourceTiers, Manifest
from plutus_verify.spec.runtime.data_resolver import (
    DataTierResolution,
    DataTierResult,
    resolve_data_tiers,
)


def _manifest_with_sources(processed=(), raw=()) -> Manifest:
    from plutus_verify.spec.manifest import Env, Repo, Step
    return Manifest(
        schema_version="2.0",
        repo=Repo(name="T", primary_language="python"),
        env=Env(base="python", python_version="3.11", requirements_file="r.txt"),
        secrets=(),
        data_sources=DataSourceTiers(processed=tuple(processed), raw=tuple(raw)),
        steps=(
            Step(id="data_collection", nine_step="step_2_data_collection", required=True, command="echo c"),
            Step(id="data_processing", nine_step="step_3_data_processing", required=True, command="echo p"),
            Step(id="in_sample", nine_step="step_4_in_sample", required=True, command="echo b"),
        ),
        expected=(),
    )


def test_no_data_sources_marks_nothing_satisfied(tmp_path):
    m = _manifest_with_sources()
    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=lambda *a, **kw: False)
    assert res.satisfied == frozenset()
    assert res.tier_used == "code"


def test_processed_satisfies_multiple_steps(tmp_path):
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    m = _manifest_with_sources(processed=(ds,))

    def fake_dl(source, target_dir):
        (target_dir / "data" / "processed").mkdir(parents=True, exist_ok=True)
        (target_dir / "data" / "processed" / "x").write_text("ok")
        return True

    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=fake_dl)
    assert res.satisfied == frozenset({"data_collection", "data_processing"})
    assert res.tier_used == "processed"


def test_raw_satisfies_one_step_when_processed_unavailable(tmp_path):
    raw_ds = DataSource(
        kind="github_release",
        url="https://github.com/x/y/raw.tar.gz",
        expected_layout=("data/raw/x",),
        satisfies=("data_collection",),
    )
    m = _manifest_with_sources(raw=(raw_ds,))

    def fake_dl(source, target_dir):
        (target_dir / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (target_dir / "data" / "raw" / "x").write_text("ok")
        return True

    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=fake_dl)
    assert res.satisfied == frozenset({"data_collection"})
    assert res.tier_used == "raw"


def test_processed_falls_through_to_raw_on_failure(tmp_path):
    proc = DataSource(
        kind="s3",  # unsupported
        url="s3://x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    raw = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/raw/x",),
        satisfies=("data_collection",),
    )
    m = _manifest_with_sources(processed=(proc,), raw=(raw,))

    def fake_dl(source, target_dir):
        if source.kind == "s3":
            return False
        (target_dir / "data" / "raw").mkdir(parents=True, exist_ok=True)
        (target_dir / "data" / "raw" / "x").write_text("ok")
        return True

    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=fake_dl)
    assert res.satisfied == frozenset({"data_collection"})
    assert res.tier_used == "raw"


def test_layout_already_present_counts_as_satisfied(tmp_path):
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "processed" / "x").write_text("ok")
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    m = _manifest_with_sources(processed=(ds,))

    downloader = MagicMock(return_value=False)
    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=downloader)
    assert res.satisfied == frozenset({"data_collection", "data_processing"})
    downloader.assert_not_called()


def test_force_tier_code_skips_all_downloads(tmp_path):
    ds = DataSource(
        kind="google_drive",
        url="https://drive.google.com/x",
        expected_layout=("data/processed/x",),
        satisfies=("data_collection", "data_processing"),
    )
    m = _manifest_with_sources(processed=(ds,))
    downloader = MagicMock(return_value=True)
    res = resolve_data_tiers(m, repo_path=tmp_path, downloader=downloader, force_tier="code")
    assert res.satisfied == frozenset()
    assert res.tier_used == "code"
    downloader.assert_not_called()

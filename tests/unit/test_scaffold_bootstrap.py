"""Tests for `plutus_verify.scaffold.bootstrap`.

Covers Task 1 (filesystem detection helpers) and Task 2 (scaffold_bootstrap
core), which together emit ``.plutus/manifest.yaml.draft`` +
``.plutus/manifest_TODO.md`` from results.json files.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from plutus_verify.scaffold.bootstrap import (
    BootstrapError,
    _artifact_compare_kind,
    _detect_python_version,
    _detect_repo_name,
    _detect_requirements_file,
    _to_display_name,
    scaffold_bootstrap,
)
from plutus_verify.sdk import step as pv_step


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Create an empty repo skeleton (so pv.step writes under tmp_path)."""
    (tmp_path / ".plutus").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_results(
    repo: Path,
    step_id: str,
    metrics: list[tuple[str, float, str]] | None = None,
    artifacts: list[tuple[str, str, str]] | None = None,
) -> None:
    metrics = metrics or []
    artifacts = artifacts or []
    with pv_step(step_id, repo_path=repo) as r:
        for name, value, unit in metrics:
            r.metric(name, value, unit=unit)
        for name, path, kind in artifacts:
            r.artifact(name, path, kind=kind)


def _load_yaml(text: str):
    return YAML(typ="rt").load(io.StringIO(text))


# ---------------------------------------------------------------------------
# Helper unit tests (Task 1)
# ---------------------------------------------------------------------------


def test_detect_python_version_prefers_python_version_file(tmp_path: Path) -> None:
    (tmp_path / ".python-version").write_text("3.12\n")
    assert _detect_python_version(tmp_path) == "3.12"


def test_detect_python_version_strips_patch(tmp_path: Path) -> None:
    (tmp_path / ".python-version").write_text("3.11.5\n")
    assert _detect_python_version(tmp_path) == "3.11"


def test_detect_python_version_uses_pyproject_requires_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "foo"\nrequires-python = ">=3.11"\n'
    )
    assert _detect_python_version(tmp_path) == "3.11"


def test_detect_python_version_pyproject_range_first_match(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.11,<3.13"\n'
    )
    assert _detect_python_version(tmp_path) == "3.11"


def test_detect_python_version_pyproject_tilde(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = "~=3.10"\n'
    )
    assert _detect_python_version(tmp_path) == "3.10"


def test_detect_python_version_fallback(tmp_path: Path) -> None:
    assert _detect_python_version(tmp_path) == "3.11"


def test_detect_python_version_python_version_wins_over_pyproject(
    tmp_path: Path,
) -> None:
    (tmp_path / ".python-version").write_text("3.12\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.9"\n'
    )
    assert _detect_python_version(tmp_path) == "3.12"


def test_detect_requirements_file_present(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("numpy\n")
    assert _detect_requirements_file(tmp_path) == "requirements.txt"


def test_detect_requirements_file_absent(tmp_path: Path) -> None:
    assert _detect_requirements_file(tmp_path) is None


def test_detect_repo_name_simple_dir(tmp_path: Path) -> None:
    repo = tmp_path / "my_strategy"
    repo.mkdir()
    assert _detect_repo_name(repo) == "my_strategy"


def test_detect_repo_name_dot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # `.` resolves to tmp_path → tmp_path.name
    assert _detect_repo_name(Path(".")) == tmp_path.name


def test_detect_repo_name_trailing_slash(tmp_path: Path) -> None:
    repo = tmp_path / "alpha"
    repo.mkdir()
    # Path normalizes trailing slashes
    assert _detect_repo_name(Path(str(repo) + "/")) == "alpha"


def test_to_display_name_snake_case() -> None:
    assert _to_display_name("sharpe_ratio") == "Sharpe Ratio"


def test_to_display_name_single_token() -> None:
    assert _to_display_name("hpr") == "Hpr"


def test_to_display_name_three_tokens() -> None:
    assert _to_display_name("annual_return_pct") == "Annual Return Pct"


def test_artifact_compare_kind_chart() -> None:
    assert _artifact_compare_kind("chart") == "visual_similarity"


def test_artifact_compare_kind_image() -> None:
    assert _artifact_compare_kind("image") == "visual_similarity"


def test_artifact_compare_kind_json() -> None:
    assert _artifact_compare_kind("json") == "json_numeric_tolerance"


def test_artifact_compare_kind_csv() -> None:
    assert _artifact_compare_kind("csv") == "byte_exact"


def test_artifact_compare_kind_other() -> None:
    assert _artifact_compare_kind("other") == "byte_exact"


def test_artifact_compare_kind_unknown() -> None:
    assert _artifact_compare_kind("unknown") == "byte_exact"


# ---------------------------------------------------------------------------
# Core tests (Task 2)
# ---------------------------------------------------------------------------


def test_happy_path_single_step(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo,
        "in_sample",
        metrics=[
            ("sharpe_ratio", 0.95, "ratio"),
            ("maximum_drawdown", -0.20, "fraction"),
        ],
        artifacts=[("equity_curve", "result/backtest/hpr.svg", "chart")],
    )

    result = scaffold_bootstrap(repo)

    assert result.draft_path == repo / ".plutus" / "manifest.yaml.draft"
    assert result.todo_path == repo / ".plutus" / "manifest_TODO.md"
    assert result.draft_path.exists()
    assert result.todo_path.exists()
    assert result.steps_with_metrics == 1
    assert result.metrics_total == 2

    data = _load_yaml(result.draft_path.read_text())
    assert data["schema_version"] == "2.0"
    assert data["env"]["python_version"] == "3.11"  # default fallback
    assert data["env"]["requirements_file"] is None

    expected = data["expected"]
    assert len(expected) == 1
    assert expected[0]["step_id"] == "in_sample"
    metric_names = [m["name"] for m in expected[0]["metrics"]]
    assert metric_names == ["sharpe_ratio", "maximum_drawdown"]
    assert expected[0]["metrics"][0]["value"] == 0.95
    assert expected[0]["metrics"][1]["value"] == -0.20
    assert expected[0]["metrics"][0]["tolerance"]["kind"] == "relative"
    assert expected[0]["metrics"][0]["tolerance"]["value"] == 0.05

    refs = expected[0]["artifacts"]
    assert len(refs) == 1
    assert refs[0]["path"] == "result/backtest/hpr.svg"
    assert refs[0]["compare"] == "visual_similarity"


def test_happy_path_multi_step(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample",
        metrics=[("sharpe_ratio", 1.1, "ratio")],
    )
    _write_results(
        repo, "out_of_sample",
        metrics=[("sharpe_ratio", 0.8, "ratio")],
    )

    result = scaffold_bootstrap(repo)
    data = _load_yaml(result.draft_path.read_text())

    step_ids = [s["id"] for s in data["steps"]]
    assert "in_sample" in step_ids
    assert "out_of_sample" in step_ids

    expected_step_ids = [e["step_id"] for e in data["expected"]]
    assert "in_sample" in expected_step_ids
    assert "out_of_sample" in expected_step_ids

    assert result.steps_with_metrics == 2
    assert result.metrics_total == 2


def test_refuses_on_existing_manifest_yaml(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )
    (repo / ".plutus" / "manifest.yaml").write_text("schema_version: '2.0'\n")

    with pytest.raises(BootstrapError) as exc_info:
        scaffold_bootstrap(repo)
    assert "manifest.yaml already exists" in str(exc_info.value)


def test_refuses_on_existing_draft_without_force(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )
    (repo / ".plutus" / "manifest.yaml.draft").write_text("# existing draft\n")

    with pytest.raises(BootstrapError) as exc_info:
        scaffold_bootstrap(repo)
    assert "force" in str(exc_info.value)


def test_refuses_on_existing_todo_without_force(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )
    (repo / ".plutus" / "manifest_TODO.md").write_text("# existing TODO\n")

    with pytest.raises(BootstrapError) as exc_info:
        scaffold_bootstrap(repo)
    assert "manifest_TODO.md" in str(exc_info.value)


def test_force_overwrites_both_files(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )
    draft_path = repo / ".plutus" / "manifest.yaml.draft"
    todo_path = repo / ".plutus" / "manifest_TODO.md"
    draft_path.write_text("# stale draft\n")
    todo_path.write_text("# stale TODO\n")

    result = scaffold_bootstrap(repo, force=True)

    assert "stale draft" not in draft_path.read_text()
    assert "stale TODO" not in todo_path.read_text()
    assert "schema_version" in draft_path.read_text()
    assert result.steps_with_metrics == 1


def test_no_results_json_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    # no pv.step invocations → .plutus/run/ either absent or empty
    with pytest.raises(BootstrapError) as exc_info:
        scaffold_bootstrap(repo)
    assert "pv.step" in str(exc_info.value)


def test_draft_is_valid_yaml(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo,
        "in_sample",
        metrics=[("sharpe_ratio", 1.1, "ratio")],
        artifacts=[("eq", "result/eq.png", "chart")],
    )

    result = scaffold_bootstrap(repo)
    text = result.draft_path.read_text()
    # No parse error → success. Also returns a dict-like object.
    parsed = _load_yaml(text)
    assert parsed is not None
    assert "schema_version" in parsed


def test_draft_contains_todo_sentinels(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )

    result = scaffold_bootstrap(repo)
    text = result.draft_path.read_text()

    assert "TODO_command_for_in_sample" in text
    assert "TODO_nine_step" in text
    assert "TODO_secrets" in text
    assert "TODO_os_packages" in text
    assert "TODO_data_sources" in text
    assert "TODO_inputs_for_in_sample" in text
    assert "TODO_depends_on_for_in_sample" in text
    assert "TODO_nine_step_coverage" in text


def test_display_name_auto_derived(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )

    result = scaffold_bootstrap(repo)
    text = result.draft_path.read_text()
    # auto-derived display name appears in proximity to the metric
    assert "display_name: Sharpe Ratio" in text


def test_python_version_file_honored(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / ".python-version").write_text("3.12\n")
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )

    result = scaffold_bootstrap(repo)
    data = _load_yaml(result.draft_path.read_text())
    assert data["env"]["python_version"] == "3.12"


def test_requirements_txt_honored(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "requirements.txt").write_text("numpy>=1.20\n")
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )

    result = scaffold_bootstrap(repo)
    data = _load_yaml(result.draft_path.read_text())
    assert data["env"]["requirements_file"] == "requirements.txt"


def test_artifacts_compare_kind(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo,
        "in_sample",
        metrics=[("sharpe_ratio", 1.0, "ratio")],
        artifacts=[
            ("eq_chart", "out/eq.png", "chart"),
            ("metrics_json", "out/metrics.json", "json"),
            ("trades_csv", "out/trades.csv", "csv"),
        ],
    )

    result = scaffold_bootstrap(repo)
    data = _load_yaml(result.draft_path.read_text())
    refs = data["expected"][0]["artifacts"]
    by_path = {r["path"]: r["compare"] for r in refs}
    assert by_path["out/eq.png"] == "visual_similarity"
    assert by_path["out/metrics.json"] == "json_numeric_tolerance"
    assert by_path["out/trades.csv"] == "byte_exact"


def test_steps_outputs_autofilled_from_artifacts(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo,
        "in_sample",
        metrics=[("sharpe_ratio", 1.0, "ratio")],
        artifacts=[("eq", "out/eq.png", "chart")],
    )

    result = scaffold_bootstrap(repo)
    data = _load_yaml(result.draft_path.read_text())
    in_sample_step = next(s for s in data["steps"] if s["id"] == "in_sample")
    assert "out/eq.png" in list(in_sample_step["outputs"])


def test_todo_placeholder_written(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_results(
        repo, "in_sample", metrics=[("sharpe_ratio", 1.0, "ratio")]
    )

    result = scaffold_bootstrap(repo)
    assert result.todo_path.exists()
    text = result.todo_path.read_text()
    # Task 3 will replace this; for now just confirm a placeholder is written
    assert "Plutus manifest TODO" in text or "TODO" in text

"""Tests for the native v2 orchestrator."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plutus_verify.sdk import step as pv_step
from plutus_verify.spec.loader import load_manifest_from_yaml_text
from plutus_verify.spec.runtime import orchestrator as orch_mod
from plutus_verify.spec.runtime.orchestrator import V2RuntimeResult, run_v2_pipeline
from plutus_verify.spec.runtime.sdk_bundle import SdkBundleError


@pytest.fixture(autouse=True)
def _fake_sdk_wheel(monkeypatch, tmp_path):
    """Default fake for `ensure_plutus_wheel`: writes a marker wheel file and
    returns its path. Keeps tests fast (no real `python -m build`) and
    deterministic regardless of whether plutus-verify is installed editable.

    Tests that want to exercise the SdkBundleError path can override by
    monkeypatching `orch_mod.ensure_plutus_wheel` themselves.
    """
    def fake(build_ctx: Path) -> Path:
        build_ctx = Path(build_ctx)
        build_ctx.mkdir(parents=True, exist_ok=True)
        wheel = build_ctx / "plutus_verify-0.2.0-py3-none-any.whl"
        if not wheel.exists():
            wheel.write_bytes(b"fake-wheel")
        return wheel

    monkeypatch.setattr(orch_mod, "ensure_plutus_wheel", fake)


_YAML = """\
schema_version: "2.0"
repo: {name: T, primary_language: python}
env: {base: python, python_version: "3.11", requirements_file: requirements.txt}
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    command: "echo data"
    outputs: ["data/raw/x"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo backtest"
    inputs: [data/raw]
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    metrics:
      - name: sharpe
        value: 0.85
        tolerance: {kind: relative, value: 0.05}
    artifacts: []
nine_step_coverage: {}
"""


def _stage_repo(tmp_path: Path):
    """Pre-create files the steps' inputs/outputs check expects."""
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "x").write_text("ok")
    (tmp_path / "out").mkdir(parents=True)
    (tmp_path / "out" / "metrics.json").write_text('{"sharpe": 0.86}')


def test_runtime_runs_all_steps_and_compares_metrics(tmp_path):
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)
    image_builder = MagicMock(return_value="built-image-tag")
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1,
    )

    # Pre-write the results.json that the (fake) script would have produced.
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe", 0.86, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert isinstance(result, V2RuntimeResult)
    assert result.image == "built-image-tag"
    image_builder.assert_called_once()
    assert runner.run.call_count == 2  # data_preparation + in_sample
    hr = result.metric_results["in_sample"]["sharpe"]
    assert hr.ok is True
    assert hr.actual == 0.86
    assert hr.expected == 0.85


def test_runtime_skips_steps_satisfied_by_data_source(tmp_path):
    _stage_repo(tmp_path)
    yaml = _YAML.replace(
        "data_sources: {processed: [], raw: []}",
        """data_sources:
  processed: []
  raw:
    - kind: github_release
      url: https://example.com/raw.tar.gz
      expected_layout: ["data/raw/x"]
      satisfies: [data_preparation]""",
    )
    manifest = load_manifest_from_yaml_text(yaml)
    image_builder = MagicMock(return_value="img")
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
        downloader=lambda *a, **kw: True,  # pretend download succeeds
    )

    # data_preparation skipped → only in_sample ran
    assert runner.run.call_count == 1
    assert result.data_tier_used == "raw"


def test_runtime_propagates_step_failure(tmp_path):
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)
    runner = MagicMock()
    # data_preparation fails — in_sample should still be attempted? Per design,
    # downstream steps that declare it as depends_on skip. With no depends_on,
    # in_sample runs anyway. The orchestrator records the failure but does not
    # raise — it surfaces in `result.step_results`.
    runner.run.side_effect = [
        MagicMock(exit_code=1, stdout="", stderr="boom", duration_seconds=0.1),
        MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1),
    ]

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert result.step_results["data_preparation"].exit_code == 1
    assert result.step_results["in_sample"].exit_code == 0


def test_runtime_preflight_failure_marks_step_skipped(tmp_path):
    """If input is missing AND not satisfied by a data source, step should
    surface a clear preflight error in step_results."""
    # in_sample needs data/raw but we don't pre-stage it
    manifest = load_manifest_from_yaml_text(_YAML)
    runner = MagicMock()
    runner.run.return_value = MagicMock(exit_code=0, stdout="", stderr="", duration_seconds=0.1)

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=runner,
        vision_client=None,
        secrets={},
    )

    # data_preparation has no inputs, runs OK; outputs missing → preflight failure post-run
    dc = result.step_results["data_preparation"]
    assert dc.preflight_error is not None
    assert "missing output" in dc.preflight_error


# --- Plan 6 / Task 4: metric comparison reads results.json by metric name ---


def _make_manifest_with_metrics(metrics_yaml: str) -> str:
    """Build a manifest YAML string with the given metrics block."""
    return f"""\
schema_version: "2.0"
repo: {{name: T, primary_language: python}}
env: {{base: python, python_version: "3.11", requirements_file: requirements.txt}}
secrets: []
data_sources: {{processed: [], raw: []}}
steps:
  - id: data_preparation
    nine_step: step_2_data_preparation
    required: true
    command: "echo data"
    outputs: ["data/raw/x"]
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "echo backtest"
    inputs: [data/raw]
    outputs: ["out/metrics.json"]
expected:
  - step_id: in_sample
    metrics:
{metrics_yaml}
    artifacts: []
nine_step_coverage: {{}}
"""


def _runner_ok():
    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )
    return runner


def test_metric_passes_when_results_json_value_matches_within_tolerance(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.95, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is True
    assert hr.actual == 0.95
    assert hr.expected == 0.95


def test_metric_fails_when_results_json_value_outside_tolerance(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.80, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is False
    assert hr.actual == 0.80
    assert hr.expected == 0.95
    assert "0.95" in hr.detail  # tolerance detail mentions the expected value


def test_missing_results_json_fails_every_metric(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
        "      - name: sortino_ratio\n"
        "        value: 1.10\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)
    # NOTE: no SDK call — results.json is absent

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hrs = result.metric_results["in_sample"]
    assert set(hrs.keys()) == {"sharpe_ratio", "sortino_ratio"}
    for name, hr in hrs.items():
        assert hr.ok is False
        assert hr.actual is None
        assert "results.json missing" in hr.detail


def test_metric_not_produced_fails_only_that_metric(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: sharpe_ratio\n"
        "        value: 0.95\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
        "      - name: sortino_ratio\n"
        "        value: 1.10\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    # Write only sharpe_ratio — sortino_ratio is absent.
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 0.95, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hrs = result.metric_results["in_sample"]
    assert hrs["sharpe_ratio"].ok is True
    assert hrs["sharpe_ratio"].actual == 0.95

    assert hrs["sortino_ratio"].ok is False
    assert hrs["sortino_ratio"].actual is None
    assert "not produced" in hrs["sortino_ratio"].detail
    assert "sortino_ratio" in hrs["sortino_ratio"].detail


def test_relative_tolerance_pass_within_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: sharpe_ratio\n"
        "        value: 1.0\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 1.04, unit="ratio")  # 4% off → within 5%

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is True


def test_relative_tolerance_fail_outside_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: sharpe_ratio\n"
        "        value: 1.0\n"
        "        tolerance: {kind: relative, value: 0.05}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe_ratio", 1.10, unit="ratio")  # 10% off → outside 5%

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["sharpe_ratio"]
    assert hr.ok is False
    assert hr.actual == 1.10


def test_absolute_tolerance_pass_within_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: max_drawdown\n"
        "        value: -0.20\n"
        "        tolerance: {kind: absolute, value: 0.02}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("max_drawdown", -0.21, unit="fraction")  # |diff|=0.01 ≤ 0.02

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["max_drawdown"]
    assert hr.ok is True
    assert hr.actual == -0.21


def test_absolute_tolerance_fail_outside_bounds(tmp_path):
    _stage_repo(tmp_path)
    yaml = _make_manifest_with_metrics(
        "      - name: max_drawdown\n"
        "        value: -0.20\n"
        "        tolerance: {kind: absolute, value: 0.02}\n"
    )
    manifest = load_manifest_from_yaml_text(yaml)

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("max_drawdown", -0.25, unit="fraction")  # |diff|=0.05 > 0.02

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=MagicMock(return_value="img"),
        runner=_runner_ok(),
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["max_drawdown"]
    assert hr.ok is False
    assert hr.actual == -0.25


# --- Plan 7 / Task 3: SDK wheel staging in orchestrator ---


def test_run_v2_pipeline_stages_sdk_wheel_and_passes_basename_to_dockerfile_gen(
    tmp_path, monkeypatch
):
    """The orchestrator stages the wheel via ensure_plutus_wheel and the
    resulting basename appears in the dockerfile_text passed to image_builder."""
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)

    marker_basename = "plutus_verify-9.9.9-py3-none-any.whl"

    def fake_ensure(build_ctx: Path) -> Path:
        build_ctx = Path(build_ctx)
        build_ctx.mkdir(parents=True, exist_ok=True)
        wheel = build_ctx / marker_basename
        wheel.write_bytes(b"marker")
        return wheel

    monkeypatch.setattr(orch_mod, "ensure_plutus_wheel", fake_ensure)

    captured = {}

    def fake_builder(dockerfile_text: str, repo_path: Path) -> str:
        captured["dockerfile"] = dockerfile_text
        captured["repo_path"] = repo_path
        return "img"

    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )

    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe", 0.86, unit="ratio")

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=fake_builder,
        runner=runner,
        vision_client=None,
        secrets={},
    )

    df = captured["dockerfile"]
    assert f"COPY .plutus/build/{marker_basename} /tmp/{marker_basename}" in df
    assert f"RUN pip install --no-cache-dir /tmp/{marker_basename}" in df

    # The wheel file was actually staged on disk inside the repo build ctx
    staged = tmp_path / ".plutus" / "build" / marker_basename
    assert staged.is_file()

    # Notes reflect the success path
    assert any(
        "SDK wheel staged" in note and marker_basename in note
        for note in result.notes
    )


def test_run_v2_pipeline_raises_sdk_bundle_error_when_metrics_required(
    tmp_path, monkeypatch
):
    """When the manifest declares expected.metrics (scripts will need the SDK),
    a bundling failure is FATAL — the pipeline refuses to build a degraded
    image that would crash on `import plutus_verify` inside the container."""
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)

    def boom(build_ctx: Path) -> Path:
        raise SdkBundleError("test reason")

    monkeypatch.setattr(orch_mod, "ensure_plutus_wheel", boom)

    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )

    with pytest.raises(SdkBundleError) as exc_info:
        run_v2_pipeline(
            manifest,
            repo_path=tmp_path,
            image_builder=MagicMock(return_value="img"),
            runner=runner,
            vision_client=None,
            secrets={},
        )

    msg = str(exc_info.value)
    assert "Refusing to build a degraded image" in msg
    assert "test reason" in msg
    assert exc_info.value.__cause__ is not None


def test_run_v2_pipeline_handles_sdk_bundle_error_gracefully_when_no_metrics(
    tmp_path, monkeypatch
):
    """If the manifest has NO expected.metrics, the scripts don't need the SDK
    (they're hand-rolling JSON or just producing artifacts). Bundling failure
    degrades gracefully: dockerfile has no .plutus/build/ reference, notes
    surface the reason."""
    _stage_repo(tmp_path)
    # Manifest variant with empty expected.metrics for both steps.
    yaml_no_metrics = _YAML.replace(
        "    metrics:\n      - name: sharpe\n        value: 0.85\n        tolerance: {kind: relative, value: 0.05}\n",
        "    metrics: []\n",
    )
    manifest = load_manifest_from_yaml_text(yaml_no_metrics)

    def boom(build_ctx: Path) -> Path:
        raise SdkBundleError("test reason")

    monkeypatch.setattr(orch_mod, "ensure_plutus_wheel", boom)

    captured = {}

    def fake_builder(dockerfile_text: str, repo_path: Path) -> str:
        captured["dockerfile"] = dockerfile_text
        return "img"

    runner = MagicMock()
    runner.run.return_value = MagicMock(
        exit_code=0, stdout="", stderr="", duration_seconds=0.1
    )

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=fake_builder,
        runner=runner,
        vision_client=None,
        secrets={},
    )

    assert isinstance(result, V2RuntimeResult)
    df = captured["dockerfile"]
    assert ".plutus/build/" not in df

    matched = [
        note
        for note in result.notes
        if "SDK wheel not staged" in note and "test reason" in note
    ]
    assert matched, f"Expected SDK error note, got: {result.notes}"


def test_compare_metrics_skips_when_step_failed(tmp_path):
    """If a step exits non-zero, declared metrics are reported as
    not-evaluated rather than blindly comparing against any stale results.json
    on disk. Prevents the stale-results false-positive class of bug."""
    _stage_repo(tmp_path)
    manifest = load_manifest_from_yaml_text(_YAML)

    # Stale results.json that happens to match the manifest exactly.
    with pv_step("in_sample", repo_path=tmp_path) as r:
        r.metric("sharpe", 0.85, unit="ratio")

    image_builder = MagicMock(return_value="img")
    runner = MagicMock()
    # in_sample step exits non-zero (script crashed).
    def fake_run(**kwargs):
        if "backtest" in kwargs.get("command", ""):
            return MagicMock(exit_code=1, stdout="", stderr="boom",
                             duration_seconds=0.1)
        return MagicMock(exit_code=0, stdout="", stderr="",
                         duration_seconds=0.1)
    runner.run.side_effect = fake_run

    result = run_v2_pipeline(
        manifest,
        repo_path=tmp_path,
        image_builder=image_builder,
        runner=runner,
        vision_client=None,
        secrets={},
    )

    hr = result.metric_results["in_sample"]["sharpe"]
    assert hr.ok is False
    assert hr.actual is None
    assert "step 'in_sample' failed" in hr.detail
    assert "step exited 1" in hr.detail

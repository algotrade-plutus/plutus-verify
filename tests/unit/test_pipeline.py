"""End-to-end test of the pipeline orchestrator with stubbed adapters."""
import json
from pathlib import Path

import pytest

from plutus_verify.compare.rubric import ExecOutcome, StepVerdict
from plutus_verify.config import Config
from plutus_verify.execute import ExecResult
from plutus_verify.pipeline import PipelineInputs, run_pipeline
from tests.unit.test_plan_schema import _minimal_valid_plan


_GOLD_README = "# Demo\n\nReport sharpe 0.95"


def _build_gold_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "README.md").write_text(_GOLD_README)
    (repo_dir / "backtesting.py").write_text(
        "print('| Sharpe Ratio | 0.9498 |')\n"
    )


class _FakeGitRunner:
    def __init__(self, repo_seed):
        self._seed = repo_seed

    def __call__(self, args, cwd=None):
        if args[:2] == ["clone", "--depth=1"]:
            dest = Path(args[-1])
            self._seed(dest)
            return ""
        if args[:2] == ["rev-parse", "HEAD"]:
            return "abc1234567890\n"
        if args[:3] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return "main\n"
        raise AssertionError(f"unexpected git args: {args}")


class _StubLLMClient:
    """Test stub for the decomposed extractor (Iteration 4).

    Tests pass a full ExtractedPlan as JSON; this stub inspects each call's
    user prompt and returns the matching per-call element so we can keep
    existing test fixtures (full-plan-shaped) without rewriting them.
    """

    def __init__(self, response_json: str):
        self.response_json = response_json
        try:
            data = json.loads(response_json)
        except (json.JSONDecodeError, TypeError):
            data = None
        self._plan = data if isinstance(data, dict) and "expected_results" in data else None

    def complete_json(self, system, user, *, temperature=0.0):
        if self._plan is None:
            return self.response_json  # legacy: return raw string for non-plan stubs
        if "repo-metadata template" in user:
            return json.dumps(self._plan.get("repo", {}))
        if "7 PLUTUS standard steps" in user:
            return json.dumps(
                {
                    k: {
                        "present": v.get("present"),
                        "section_heading": v.get("section_heading"),
                    }
                    for k, v in self._plan.get("nine_step_mapping", {}).items()
                }
            )
        if "PLUTUS step marked present below" in user:
            return json.dumps(
                [
                    {k: v for k, v in s.items() if k != "depends_on"}
                    for s in self._plan.get("steps", [])
                ]
            )
        if "step ID below that reports results" in user:
            return json.dumps(self._plan.get("expected_results", []))
        return self.response_json


class _StubBuilder:
    def __init__(self, image: str = "stub-image:latest"):
        self.image = image
        self.calls = []

    def build(self, *, repo_path: Path, commit_sha: str):
        self.calls.append(repo_path)
        return self.image


class _StubRunner:
    def __init__(self, output_factory):
        self._factory = output_factory
        self.calls = []

    def run(self, *, image, command, cwd, network, timeout_seconds, env=None):
        self.calls.append(command)
        return self._factory(command, cwd)


class _StubVision:
    def judge_chart(self, *, chart_name, produced_png, reference_png):
        return json.dumps(
            {
                "shape_match": {"verdict": "match", "reason": ""},
                "scale_match": {"verdict": "match", "reason": ""},
                "structure_match": {"verdict": "match", "reason": ""},
                "overall": {"verdict": "match", "confidence": 0.9},
            }
        )


def test_pipeline_runs_end_to_end_and_reports_reproduced(tmp_path: Path):
    out_dir = tmp_path / "out"

    git = _FakeGitRunner(_build_gold_repo)
    llm = _StubLLMClient(json.dumps(_minimal_valid_plan()))
    builder = _StubBuilder()

    def runner_factory(command, cwd):
        # The plan asks for `python backtesting.py` and expects Sharpe 0.9516
        return ExecResult(
            exit_code=0,
            stdout="| Sharpe Ratio | 0.9498 |\n",
            stderr="",
            duration_seconds=1.0,
            outcome=ExecOutcome.OK,
        )

    runner = _StubRunner(runner_factory)
    vision = _StubVision()

    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/repo.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,  # plan has no charts anyway
        ),
        git_runner=git,
        llm_client=llm,
        builder=builder,
        runner=runner,
        vision=vision,
    )

    assert result.overall.verdict == StepVerdict.REPRODUCED
    assert result.overall.exit_code == 0
    assert (out_dir / "report.json").exists()
    assert (out_dir / "report.md").exists()
    assert (out_dir / "plan.json").exists()
    payload = json.loads((out_dir / "report.json").read_text())
    assert payload["verdict"] == "reproduced"


def test_pipeline_detects_metric_drift_and_reports_partial(tmp_path: Path):
    """Tamper test: actual Sharpe wildly off -> partial verdict."""
    out_dir = tmp_path / "out"
    git = _FakeGitRunner(_build_gold_repo)
    llm = _StubLLMClient(json.dumps(_minimal_valid_plan()))
    builder = _StubBuilder()

    def runner_factory(command, cwd):
        return ExecResult(
            exit_code=0,
            stdout="| Sharpe Ratio | 9.9999 |\n",  # out of tolerance
            stderr="",
            duration_seconds=1.0,
            outcome=ExecOutcome.OK,
        )

    runner = _StubRunner(runner_factory)

    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/repo.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
        ),
        git_runner=git,
        llm_client=llm,
        builder=builder,
        runner=runner,
        vision=_StubVision(),
    )
    assert result.overall.verdict == StepVerdict.PARTIAL
    assert result.overall.exit_code == 1


def test_pipeline_extract_only_skips_build_and_execute(tmp_path: Path):
    out_dir = tmp_path / "out"
    git = _FakeGitRunner(_build_gold_repo)
    llm = _StubLLMClient(json.dumps(_minimal_valid_plan()))
    builder = _StubBuilder()
    runner = _StubRunner(lambda cmd, cwd: pytest.fail("runner must not be called"))

    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/repo.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
            extract_only=True,
        ),
        git_runner=git,
        llm_client=llm,
        builder=builder,
        runner=runner,
        vision=_StubVision(),
    )
    assert result.overall is None
    assert (out_dir / "plan.json").exists()
    assert not builder.calls


def test_pipeline_use_plan_skips_extract(tmp_path: Path):
    """When a plan is supplied, extract is skipped (LLM never called)."""
    out_dir = tmp_path / "out"
    git = _FakeGitRunner(_build_gold_repo)

    class _BoomLLM:
        def complete_json(self, *a, **k):
            pytest.fail("LLM must not be called when plan is pre-loaded")

    builder = _StubBuilder()

    def runner_factory(command, cwd):
        return ExecResult(
            exit_code=0,
            stdout="| Sharpe Ratio | 0.9498 |\n",
            stderr="",
            duration_seconds=1.0,
            outcome=ExecOutcome.OK,
        )

    from plutus_verify.extract.plan import parse_plan
    plan = parse_plan(_minimal_valid_plan())

    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/repo.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
            pre_loaded_plan=plan,
        ),
        git_runner=git,
        llm_client=_BoomLLM(),
        builder=builder,
        runner=_StubRunner(runner_factory),
        vision=_StubVision(),
    )
    assert result.overall.verdict == StepVerdict.REPRODUCED


def test_pipeline_pre_built_image_skips_build(tmp_path: Path):
    """When an image tag is supplied, build is skipped (builder never called)."""
    out_dir = tmp_path / "out"
    git = _FakeGitRunner(_build_gold_repo)
    llm = _StubLLMClient(json.dumps(_minimal_valid_plan()))

    class _BoomBuilder:
        def build(self, *, repo_path, commit_sha):
            pytest.fail("builder must not be called when image is pre-built")

    runner_calls: list[str] = []

    def runner_factory(command, cwd):
        runner_calls.append(command)
        return ExecResult(
            exit_code=0,
            stdout="| Sharpe Ratio | 0.9498 |\n",
            stderr="",
            duration_seconds=1.0,
            outcome=ExecOutcome.OK,
        )

    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/repo.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
            pre_built_image="my-prebuilt-image:tag",
        ),
        git_runner=git,
        llm_client=llm,
        builder=_BoomBuilder(),
        runner=_StubRunner(runner_factory),
        vision=_StubVision(),
    )
    assert result.overall.verdict == StepVerdict.REPRODUCED


def test_pipeline_builds_verification_trail_and_persists_artifacts(tmp_path: Path):
    """End-to-end: pipeline emits a per-stage trail, persists run.log + per-step files."""
    out_dir = tmp_path / "out"

    git = _FakeGitRunner(_build_gold_repo)
    llm = _StubLLMClient(json.dumps(_minimal_valid_plan()))
    builder = _StubBuilder()

    def runner_factory(command, cwd):
        return ExecResult(
            exit_code=0,
            stdout="| Sharpe Ratio | 0.9498 |\n",
            stderr="some warning\n",
            duration_seconds=1.5,
            outcome=ExecOutcome.OK,
        )

    from plutus_verify.util.progress import Progress
    progress = Progress(out_dir, stream=None)
    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/repo.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
            progress=progress,
        ),
        git_runner=git,
        llm_client=llm,
        builder=builder,
        runner=_StubRunner(runner_factory),
        vision=_StubVision(),
    )
    progress.close()

    # Trail covers each stage at least once
    stages = [t.stage for t in result.verification_trail]
    for required in ("ingest", "extract", "build", "fetch", "execute", "compare", "report"):
        assert required in stages, f"missing trail stage: {required}"

    # run.log was created and contains stage banners
    log = (out_dir / "run.log").read_text()
    assert "[ingest]" in log
    assert "[extract]" in log
    assert "[build]" in log
    assert "[execute]" in log
    assert "[compare]" in log
    assert "[report]" in log

    # Per-step artifacts persisted
    assert (out_dir / "execute" / "in_sample_backtest.stdout").read_text() == (
        "| Sharpe Ratio | 0.9498 |\n"
    )
    assert (out_dir / "execute" / "in_sample_backtest.stderr").read_text() == "some warning\n"
    meta = json.loads((out_dir / "execute" / "in_sample_backtest.meta.json").read_text())
    assert meta["outcome"] == "ok"

    # report.json has the verification_trail field
    payload = json.loads((out_dir / "report.json").read_text())
    assert "verification_trail" in payload
    trail_stages = [t["stage"] for t in payload["verification_trail"]]
    assert "execute" in trail_stages
    # report.md contains the Verification Trail section
    md = (out_dir / "report.md").read_text()
    assert "## Verification Trail" in md


def test_pipeline_resume_existing_run_dir_skips_ingest_and_extract(tmp_path: Path):
    """When out_dir already has meta.json + plan.json, ingest+extract are both skipped."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    repo = tmp_path / "existing_repo"
    repo.mkdir()
    (repo / "README.md").write_text("# resumed")
    # Seed meta.json + plan.json
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "git_url": "https://example.com/x.git",
                "repo_path": str(repo),
                "readme_path": str(repo / "README.md"),
                "commit_sha": "resumed",
                "branch": "main",
                "meta_path": str(out_dir / "meta.json"),
            }
        )
    )
    (out_dir / "plan.json").write_text(json.dumps(_minimal_valid_plan()))

    class _BoomGit:
        def __call__(self, *a, **k):
            pytest.fail("git must not be invoked when resuming")

    class _BoomLLM:
        def complete_json(self, *a, **k):
            pytest.fail("LLM must not be invoked when resuming with plan.json on disk")

    def runner_factory(command, cwd):
        return ExecResult(
            exit_code=0,
            stdout="| Sharpe Ratio | 0.9498 |\n",
            stderr="",
            duration_seconds=1.0,
            outcome=ExecOutcome.OK,
        )

    result = run_pipeline(
        PipelineInputs(
            source="https://example.com/x.git",
            out_dir=out_dir,
            secrets_path=None,
            config=Config(),
            charts_enabled=False,
            resume_existing=True,
        ),
        git_runner=_BoomGit(),
        llm_client=_BoomLLM(),
        builder=_StubBuilder(),
        runner=_StubRunner(runner_factory),
        vision=_StubVision(),
    )
    assert result.overall.verdict == StepVerdict.REPRODUCED

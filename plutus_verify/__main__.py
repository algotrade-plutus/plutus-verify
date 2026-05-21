"""CLI entrypoint for ``plutus-verify``.

The CLI is a thin wrapper around :func:`plutus_verify.pipeline.run_pipeline`.
It chooses real adapters (OpenAI-compatible LLM client, repo2docker builder,
Docker runner, Gemma vision client) and injects them.
"""
from __future__ import annotations

import datetime as dt
import sys
import traceback
from pathlib import Path
from typing import Optional

import click

from plutus_verify.build import build_with_fixers, BuildResult
from plutus_verify.build.llm_fixer import suggest_build_fixes
from plutus_verify.compare.llm_match import OpenAIMetricMatchClient
from plutus_verify.compare.vision_client import OpenAIVisionClient
from plutus_verify.config import load_config
from plutus_verify.extract.client import OpenAICompatClient
from plutus_verify.pipeline import PipelineInputs, run_pipeline
from plutus_verify.runner_docker import DockerRunner, DockerRunnerConfig
from plutus_verify.util.progress import Progress


class _RealBuilder:
    def __init__(
        self,
        image_prefix: str,
        secrets_path: Optional[Path],
        llm_for_fixes: Optional[object] = None,
    ):
        self._prefix = image_prefix
        self._secrets = secrets_path
        self._llm = llm_for_fixes

    def build(
        self,
        *,
        repo_path: Path,
        commit_sha: str,
        progress: Optional[Progress] = None,
        artifacts_dir: Optional[Path] = None,
    ) -> BuildResult:
        llm_fixer = None
        if self._llm is not None:
            def llm_fixer(error_log: str, rp: Path):
                return suggest_build_fixes(error_log, rp, self._llm)
        return build_with_fixers(
            repo_path,
            commit_sha=commit_sha,
            image_prefix=self._prefix,
            secrets_path=self._secrets,
            llm_fixer=llm_fixer,
            progress=progress,
            artifacts_dir=artifacts_dir,
        )


def _default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@click.command(context_settings={"show_default": True})
@click.argument("source", required=False)
@click.option("--ref", default=None, help="git ref (branch or sha) to check out")
@click.option(
    "--secrets",
    "secrets_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help=".env-style file injected into the runtime image",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
)
@click.option(
    "--out",
    "out_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("./out"),
)
@click.option(
    "--resume-from",
    type=click.Choice(["extract", "build", "execute", "compare", "report"]),
    default=None,
)
@click.option(
    "--prefer-data-path",
    type=click.Choice(["google_drive", "db_loader", "auto"]),
    default="auto",
)
@click.option("--llm-endpoint", default=None, help="override the configured LLM endpoint")
@click.option("--no-charts", is_flag=True, help="skip the vision-based chart judgement")
@click.option("--dry-run", is_flag=True, help="ingest+extract+build only (no execute/compare)")
@click.option("--extract-only", is_flag=True, help="ingest+extract only; write plan.json and stop")
@click.option("--skip-clone", is_flag=True, help="treat SOURCE as a local repo path")
@click.option(
    "--auto-fetch",
    is_flag=True,
    help="Auto-download data for steps with a manual_download alternative (e.g., Google Drive). Each fetch is logged as a finding.",
)
@click.option(
    "--use-plan",
    "use_plan_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=None,
    help="Load this plan.json instead of running extract (implies resume).",
)
@click.option(
    "--skip-build",
    "skip_build_image",
    default=None,
    metavar="IMAGE_TAG",
    help="Skip the build stage and use this pre-existing docker image tag.",
)
@click.option("--batch", "batch_file", type=click.Path(path_type=Path, dir_okay=False), default=None)
def main(
    source: Optional[str],
    ref: Optional[str],
    secrets_path: Optional[Path],
    config_path: Optional[Path],
    out_root: Path,
    resume_from: Optional[str],
    prefer_data_path: str,
    llm_endpoint: Optional[str],
    no_charts: bool,
    dry_run: bool,
    extract_only: bool,
    skip_clone: bool,
    auto_fetch: bool,
    use_plan_path: Optional[Path],
    skip_build_image: Optional[str],
    batch_file: Optional[Path],
) -> None:
    """Verify reproducibility of a PLUTUS-standard repo.

    SOURCE is a git URL (or a local path with --skip-clone). With --batch, SOURCE
    is omitted and the file should contain one source per line.
    """
    cfg = load_config(config_path)
    if llm_endpoint:
        cfg.llm.endpoint = llm_endpoint
    if no_charts:
        cfg.charts.enabled = False

    if batch_file:
        sources = [
            ln.strip()
            for ln in batch_file.read_text().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        worst_exit = 0
        for src in sources:
            run_id = _default_run_id() + "-" + Path(src).name
            code = _run_one(
                src,
                run_dir=out_root / run_id,
                cfg=cfg,
                ref=ref,
                secrets_path=secrets_path,
                resume_from=resume_from,
                prefer_data_path=prefer_data_path,
                dry_run=dry_run,
                extract_only=extract_only,
                skip_clone=skip_clone,
                auto_fetch=auto_fetch,
            )
            worst_exit = max(worst_exit, code)
        sys.exit(worst_exit)

    if not source:
        click.echo("error: SOURCE required (or use --batch)", err=True)
        sys.exit(2)

    # --out semantics: if it's an existing run dir (has meta.json), use it as-is.
    # Otherwise treat it as the parent root and timestamp under it.
    if (out_root / "meta.json").exists():
        run_dir = out_root
        resume_existing = True
    else:
        run_dir = out_root / _default_run_id()
        resume_existing = False

    sys.exit(
        _run_one(
            source,
            run_dir=run_dir,
            cfg=cfg,
            ref=ref,
            secrets_path=secrets_path,
            resume_from=resume_from,
            prefer_data_path=prefer_data_path,
            dry_run=dry_run,
            extract_only=extract_only,
            skip_clone=skip_clone,
            auto_fetch=auto_fetch,
            use_plan_path=use_plan_path,
            skip_build_image=skip_build_image,
            resume_existing=resume_existing,
        )
    )


def _run_one(
    source: str,
    *,
    run_dir: Path,
    cfg,
    ref: Optional[str],
    secrets_path: Optional[Path],
    resume_from: Optional[str],
    prefer_data_path: str,
    dry_run: bool,
    extract_only: bool,
    skip_clone: bool,
    auto_fetch: bool = False,
    use_plan_path: Optional[Path] = None,
    skip_build_image: Optional[str] = None,
    resume_existing: bool = False,
) -> int:
    run_dir.mkdir(parents=True, exist_ok=True)
    progress = Progress(run_dir)
    progress.stage("setup", f"run dir: {run_dir}")
    llm = OpenAICompatClient(
        endpoint=cfg.llm.endpoint,
        model=cfg.llm.model,
        idle_timeout_seconds=cfg.llm.timeout_seconds,
        num_ctx=cfg.llm.num_ctx,
        think=cfg.llm.think,
    )
    if cfg.llm.prewarm:
        try:
            progress.stage("setup", f"prewarming {cfg.llm.model}...")
            llm.prewarm()
        except Exception as exc:  # non-fatal
            progress.error("setup", f"prewarm failed (continuing): {exc}")
    vision = OpenAIVisionClient(
        endpoint=cfg.llm.endpoint,
        model=cfg.llm.vision_model,
        timeout_seconds=cfg.llm.timeout_seconds,
    )
    builder = _RealBuilder(
        image_prefix=cfg.repo2docker.image_prefix,
        secrets_path=secrets_path,
        llm_for_fixes=llm if cfg.compare.llm_fallback else None,
    )
    runner = DockerRunner(
        DockerRunnerConfig(
            memory_limit=cfg.execute.memory_limit,
            cpu_limit=cfg.execute.cpu_limit,
        )
    )
    match_client = None
    if cfg.compare.llm_fallback:
        match_client = OpenAIMetricMatchClient(
            endpoint=cfg.llm.endpoint,
            model=cfg.llm.model,
            idle_timeout_seconds=cfg.llm.timeout_seconds,
            num_ctx=cfg.llm.num_ctx,
        )

    pre_loaded_plan = None
    if use_plan_path:
        import json as _json
        from plutus_verify.extract.plan import parse_plan as _parse_plan
        pre_loaded_plan = _parse_plan(_json.loads(Path(use_plan_path).read_text()))

    inputs = PipelineInputs(
        source=source,
        out_dir=run_dir,
        secrets_path=secrets_path,
        config=cfg,
        ref=ref,
        skip_clone=skip_clone,
        auto_fetch=auto_fetch,
        charts_enabled=cfg.charts.enabled and not extract_only and not dry_run,
        prefer_data_path=None if prefer_data_path == "auto" else prefer_data_path,
        extract_only=extract_only or dry_run,  # treat dry_run same as extract_only here
        resume_from=resume_from,
        pre_loaded_plan=pre_loaded_plan,
        pre_built_image=skip_build_image,
        resume_existing=resume_existing or (use_plan_path is not None and skip_clone),
        progress=progress,
    )
    try:
        result = run_pipeline(
            inputs,
            llm_client=llm,
            builder=builder,
            runner=runner,
            vision=vision,
            match_client=match_client,
        )
    except Exception as exc:  # surface any pipeline-time failure to the user
        progress.error("pipeline", f"{type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stderr)
        progress.close()
        return 2

    progress.close()

    if result.overall is None:
        # Final verdict line goes to stdout so wrappers (CI, batch mode) can grep it.
        click.echo(f"plan.json written to {result.out_dir / 'plan.json'}")
        click.echo(f"trail: {result.out_dir}/run.log")
        return 0

    click.echo(f"verdict: {result.overall.verdict.value} (exit {result.overall.exit_code})")
    click.echo(f"reports: {result.out_dir}/report.md  {result.out_dir}/report.json")
    click.echo(f"trail: {result.out_dir}/run.log")
    return result.overall.exit_code


if __name__ == "__main__":
    main()

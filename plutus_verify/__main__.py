"""CLI entrypoint for ``plutus-verify`` / ``plutus``.

Provides a Click group with subcommands:
  - verify   : original single-command verifier (PLUTUS-standard repo)
  - init     : scaffold .plutus/manifest.yaml + .github/workflows/plutus.yml
  - check    : run the native v2 pipeline locally against a working copy
  - snapshot : capture step outputs into .plutus/expected/

The legacy ``plutus-verify <git_url>`` form is preserved via the backward-compat
``main()`` entrypoint which injects 'verify' when the first arg isn't a known
subcommand.
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


# ---------------------------------------------------------------------------
# Top-level CLI group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx: click.Context) -> None:
    """plutus: reproducibility tooling for PLUTUS-standard repos."""
    if ctx.invoked_subcommand is None:
        click.echo(cli.get_help(ctx))


# ---------------------------------------------------------------------------
# verify subcommand (original single-command behaviour)
# ---------------------------------------------------------------------------

@cli.command("verify", context_settings={"show_default": True})
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
def verify_cmd(
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


# ---------------------------------------------------------------------------
# init subcommand
# ---------------------------------------------------------------------------

@cli.command("init")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option("--force", is_flag=True, help="overwrite existing manifest/workflow")
def init_cmd(repo_path: Path, force: bool) -> None:
    """Scaffold .plutus/manifest.yaml and .github/workflows/plutus.yml."""
    from plutus_verify.scaffold.init import scaffold_init

    res = scaffold_init(Path(repo_path), force=force)
    click.echo(f"created manifest: {res.created_manifest}")
    click.echo(f"created workflow: {res.created_workflow}")
    click.echo(f"created example script: {res.created_example_script}")
    click.echo("  - see .plutus/example_script.py for how to instrument your scripts")


# ---------------------------------------------------------------------------
# check subcommand
# ---------------------------------------------------------------------------

@cli.command("check")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option("--secrets-from-env", is_flag=True, help="use environment variables as secrets")
@click.option(
    "--data-tier",
    type=click.Choice(["processed", "raw", "code", "auto"]),
    default="auto",
)
def check_cmd(repo_path: Path, secrets_from_env: bool, data_tier: str) -> None:
    """Run the v2 pipeline locally against a working copy."""
    import os

    from plutus_verify.scaffold.check import scaffold_check
    from plutus_verify.spec.loader import ManifestLoadError
    from plutus_verify.spec.runtime import BuildError, make_image_builder

    try:
        from plutus_verify.runner_docker import DockerRunner

        secrets = dict(os.environ) if secrets_from_env else {}
        click.echo(f"building image from .plutus/Dockerfile.generated...")
        res = scaffold_check(
            Path(repo_path),
            image_builder=make_image_builder(),
            runner=DockerRunner(),
            vision_client=None,
            secrets=secrets,
            force_data_tier=None if data_tier == "auto" else data_tier,
        )
    except ManifestLoadError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(2)
        return
    except BuildError as exc:
        click.echo(f"docker build failed:\n{exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(2)
        return

    click.echo(f"image: {res.runtime_result.image}")
    click.echo(f"data tier: {res.runtime_result.data_tier_used}")
    for sid, sr in res.runtime_result.step_results.items():
        status = "ok" if sr.exit_code == 0 and sr.preflight_error is None else "FAIL"
        skip = f" (skipped: {sr.skipped_reason})" if sr.skipped_reason else ""
        pf = f" [preflight: {sr.preflight_error}]" if sr.preflight_error else ""
        click.echo(f"  {status} {sid}: exit={sr.exit_code}{skip}{pf}")
    for step_id, hrs in res.runtime_result.metric_results.items():
        for name, h in hrs.items():
            marker = "ok" if h.ok else "FAIL"
            click.echo(f"  {marker} {step_id}.{name}: actual={h.actual} expected={h.expected} {h.detail}")
    ctx = click.get_current_context()
    ctx.exit(res.exit_code)


# ---------------------------------------------------------------------------
# snapshot subcommand
# ---------------------------------------------------------------------------

@cli.command("snapshot")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option("--no-run", is_flag=True, help="don't run check first; snapshot existing outputs")
@click.option(
    "--no-reference-outputs",
    is_flag=True,
    default=False,
    help="Don't copy step output files into .plutus/expected/.",
)
@click.option(
    "--no-metrics",
    is_flag=True,
    default=False,
    help="Don't write expected.metrics[].value into manifest.yaml.",
)
def snapshot_cmd(
    repo_path: Path,
    no_run: bool,
    no_reference_outputs: bool,
    no_metrics: bool,
) -> None:
    """Capture step outputs into .plutus/expected/ and fill metric values."""
    from plutus_verify.scaffold.snapshot import scaffold_snapshot

    if not no_run:
        click.echo(
            "error: running check before snapshot requires --no-run for now (real builder not wired)",
            err=True,
        )
        ctx = click.get_current_context()
        ctx.exit(3)
        return

    res = scaffold_snapshot(
        Path(repo_path),
        run_check_first=False,
        update_reference_outputs=not no_reference_outputs,
        update_metric_values=not no_metrics,
    )
    click.echo(f"  files copied: {res.files_copied}")
    click.echo(f"  metrics updated: {res.metrics_updated}")
    for n in res.notes:
        click.echo(f"  {n}")


# ---------------------------------------------------------------------------
# transfer subcommand
# ---------------------------------------------------------------------------

@cli.command("transfer")
@click.argument("repo_path", type=click.Path(path_type=Path, file_okay=False), default=".")
@click.option(
    "--llm-endpoint",
    default=None,
    help="OpenAI-compatible endpoint (default: config or http://localhost:11434/v1)",
)
@click.option(
    "--llm-model",
    default=None,
    help="model name (default: from config or gemma4:26b)",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="YAML config overriding LLM defaults (timeouts, num_ctx, etc.)",
)
@click.option("--no-prewarm", is_flag=True, help="skip the LLM prewarm step")
@click.option("--force", is_flag=True, help="overwrite an existing instrument_TODO.md")
def transfer_cmd(
    repo_path: Path,
    llm_endpoint: Optional[str],
    llm_model: Optional[str],
    config_path: Optional[Path],
    no_prewarm: bool,
    force: bool,
) -> None:
    """Convert a legacy README-based repo into a v2 draft manifest."""
    from plutus_verify.scaffold.transfer import TransferError, scaffold_transfer

    cfg = load_config(config_path)
    if llm_endpoint:
        cfg.llm.endpoint = llm_endpoint
    if llm_model:
        cfg.llm.model = llm_model

    click.echo(f"endpoint: {cfg.llm.endpoint}")
    click.echo(f"model: {cfg.llm.model}")

    llm = OpenAICompatClient(
        endpoint=cfg.llm.endpoint,
        model=cfg.llm.model,
        idle_timeout_seconds=cfg.llm.timeout_seconds,
        num_ctx=cfg.llm.num_ctx,
        think=cfg.llm.think,
    )

    if cfg.llm.prewarm and not no_prewarm:
        click.echo(f"prewarming {cfg.llm.model} (first load can take 30-120s for big models)...")
        try:
            llm.prewarm()
            click.echo("prewarm: ok")
        except Exception as exc:
            click.echo(f"prewarm failed (continuing anyway): {exc}", err=True)

    def _on_attempt(label: str, raw: str, err: Optional[Exception]) -> None:
        if err is None:
            click.echo(f"  {label}: ok ({len(raw)} chars)")
        else:
            click.echo(f"  {label}: {type(err).__name__}: {err}", err=True)

    click.echo("extracting v1 plan from README via 4 LLM calls...")
    try:
        res = scaffold_transfer(
            Path(repo_path),
            llm_client=llm,
            on_attempt=_on_attempt,
            first_attempt_idle_seconds=float(
                getattr(cfg.llm, "first_attempt_timeout_seconds", 180)
            ),
            retry_idle_seconds=float(cfg.llm.timeout_seconds),
            max_retries=cfg.llm.max_retries,
            force=force,
        )
    except TransferError as exc:
        click.echo(f"error: {exc}", err=True)
        ctx = click.get_current_context()
        ctx.exit(2)
        return
    click.echo(f"\nwrote draft: {res.draft_path}")
    click.echo(f"wrote instrument_TODO.md: {res.instrument_todo_path}")
    click.echo(res.plan_summary)
    click.echo(
        "Next: instrument each step's script per .plutus/instrument_TODO.md, "
        "review the draft's TODO markers, then "
        "`mv .plutus/manifest.yaml.draft .plutus/manifest.yaml` and run `plutus check`."
    )


# ---------------------------------------------------------------------------
# Backward-compatible entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    """Backward-compatible bare entrypoint: ``plutus-verify <git_url>`` → ``plutus verify <git_url>``."""
    args = sys.argv[1:]
    # If first arg looks like a known subcommand, pass through; else inject 'verify'
    known = {"init", "check", "snapshot", "transfer", "verify", "--help", "-h", "--version"}
    if args and args[0] not in known and not args[0].startswith("-"):
        args = ["verify"] + args
    cli(args=args, prog_name="plutus-verify", standalone_mode=True)


if __name__ == "__main__":
    main()

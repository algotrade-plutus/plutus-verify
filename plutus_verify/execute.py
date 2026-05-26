"""Execute stage: run each step of the plan in topological order.

The ``Runner`` interface is what touches Docker. Tests inject a fake runner;
production uses :class:`DockerRunner` (see :mod:`plutus_verify.runner_docker`).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from plutus_verify.compare.rubric import ExecOutcome
from plutus_verify.extract.plan import ExtractedPlan, Step, StepAlternative
from plutus_verify.util.json_io import save_json
from plutus_verify.util.progress import NullProgress, Progress


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    outcome: ExecOutcome
    alternative_used: Optional[str] = None


class Runner(Protocol):
    """A single-shot command runner inside a sandbox (Docker, venv, etc.)."""

    def run(
        self,
        *,
        image: str,
        command: str,
        cwd: Path,
        network: str,
        timeout_seconds: int,
        env: dict[str, str] | None = None,
    ) -> ExecResult: ...


_SKIPPED = ExecResult(
    exit_code=-1,
    stdout="",
    stderr="skipped due to upstream failure or unavailable alternative",
    duration_seconds=0.0,
    outcome=ExecOutcome.SKIPPED,
)


def _topo_sort(steps: tuple[Step, ...]) -> list[Step]:
    by_id = {s.id: s for s in steps}
    ordered: list[Step] = []
    seen: set[str] = set()

    def visit(sid: str) -> None:
        if sid in seen:
            return
        s = by_id[sid]
        for dep in s.depends_on:
            if dep in by_id:
                visit(dep)
        seen.add(sid)
        ordered.append(s)

    for s in steps:
        visit(s.id)
    return ordered


def _choose_alternative(
    step: Step,
    *,
    available_secrets: dict[str, str],
    prefer_data_path: Optional[str],
    manual_download_resolver: Optional[Callable[[StepAlternative], bool]],
) -> tuple[Optional[StepAlternative], Optional[str]]:
    """Pick the first viable alternative; return (alt, skip_reason_if_none)."""
    if step.alternatives is None:
        return None, None
    alts = list(step.alternatives)
    if prefer_data_path is not None:
        # stable-sort: preferred label first
        alts.sort(key=lambda a: 0 if a.label == prefer_data_path else 1)
    for alt in alts:
        if alt.kind == "manual_download":
            if manual_download_resolver and manual_download_resolver(alt):
                return alt, None
        elif alt.kind == "command":
            missing = [k for k in alt.needs_secrets if k not in available_secrets]
            if not missing:
                return alt, None
    return None, "no viable alternative (manual download absent and required secrets missing)"


def run_plan(
    plan: ExtractedPlan,
    *,
    image: str,
    repo_path: Path,
    runner: Runner,
    available_secrets: Optional[dict[str, str]] = None,
    prefer_data_path: Optional[str] = None,
    manual_download_resolver: Optional[Callable[[StepAlternative], bool]] = None,
    progress: Optional[Progress] = None,
    artifacts_dir: Optional[Path] = None,
) -> dict[str, ExecResult]:
    """Execute every step of the plan in topological order.

    Returns a mapping ``step_id -> ExecResult``. Failed dependencies cascade to
    SKIPPED for downstream steps.

    If ``progress`` is given, emit a substep event per step (``running`` /
    ``ok`` / ``failed`` / ``skipped``). If ``artifacts_dir`` is given,
    persist ``<step_id>.stdout``, ``<step_id>.stderr`` and
    ``<step_id>.meta.json`` under it for each step that actually ran.
    """
    secrets = available_secrets or {}
    prog = progress or NullProgress()
    if artifacts_dir is not None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, ExecResult] = {}
    for step in _topo_sort(plan.steps):
        # cascade skip if any dependency failed/skipped
        bad_dep = next(
            (
                d
                for d in step.depends_on
                if d in outputs
                and outputs[d].outcome in (ExecOutcome.FAILED, ExecOutcome.TIMEOUT, ExecOutcome.SKIPPED)
            ),
            None,
        )
        if bad_dep is not None:
            outputs[step.id] = _SKIPPED
            prog.substep("execute", f"{step.id}: skipped (dependency {bad_dep} failed)")
            continue

        # `artifact_check` mode: don't run anything; compare.metrics will
        # verify the produced files exist in the repo.
        if step.verification_mode == "artifact_check":
            outputs[step.id] = ExecResult(
                exit_code=0,
                stdout="",
                stderr="",
                duration_seconds=0.0,
                outcome=ExecOutcome.OK,
                alternative_used="artifact_check",
            )
            prog.substep("execute", f"{step.id}: skipped (artifact_check)")
            continue

        # An empty alternatives tuple means "no alternatives — run the main
        # command directly". The decomposed extractor's prompt yields [] for
        # most non-data steps, so the `is not None` distinction (legacy from
        # iter 1) would misroute these into the alt-picker. Use truthiness.
        if step.alternatives:
            alt, skip_reason = _choose_alternative(
                step,
                available_secrets=secrets,
                prefer_data_path=prefer_data_path,
                manual_download_resolver=manual_download_resolver,
            )
            if alt is None:
                if step.required:
                    outputs[step.id] = ExecResult(
                        exit_code=-1,
                        stdout="",
                        stderr=skip_reason or "no viable alternative",
                        duration_seconds=0.0,
                        outcome=ExecOutcome.FAILED,
                    )
                    prog.substep("execute", f"{step.id}: failed ({skip_reason or 'no viable alternative'})")
                else:
                    outputs[step.id] = _SKIPPED
                    prog.substep("execute", f"{step.id}: skipped ({skip_reason or 'no viable alternative'})")
                continue
            if alt.kind == "manual_download":
                # Data assumed already present at expected_layout paths.
                outputs[step.id] = ExecResult(
                    exit_code=0,
                    stdout=f"manual_download:{alt.label}",
                    stderr="",
                    duration_seconds=0.0,
                    outcome=ExecOutcome.OK,
                    alternative_used=alt.label,
                )
                prog.substep("execute", f"{step.id}: ok (manual_download:{alt.label})")
                continue
            # alt.kind == "command"
            env = {k: secrets[k] for k in alt.needs_secrets if k in secrets}
            prog.substep(
                "execute",
                f"{step.id}: running (alt={alt.label}, timeout {alt.timeout_seconds}s)",
            )
            result = runner.run(
                image=image,
                command=alt.command or "",
                cwd=repo_path,
                network=alt.network,
                timeout_seconds=alt.timeout_seconds,
                env=env,
            )
            res = ExecResult(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_seconds=result.duration_seconds,
                outcome=result.outcome,
                alternative_used=alt.label,
            )
            outputs[step.id] = res
            _persist_step_artifacts(
                artifacts_dir,
                step.id,
                res,
                command=alt.command or "",
                network=alt.network,
            )
            _emit_step_completion(prog, step.id, res, artifacts_dir)
            continue

        # ordinary single-command step
        if not step.command:
            outputs[step.id] = _SKIPPED
            prog.substep("execute", f"{step.id}: skipped (no command)")
            continue
        prog.substep(
            "execute",
            f"{step.id}: running (timeout {step.timeout_seconds}s)",
        )
        result = runner.run(
            image=image,
            command=step.command,
            cwd=repo_path,
            network=step.network,
            timeout_seconds=step.timeout_seconds,
            env=None,
        )
        outputs[step.id] = result
        _persist_step_artifacts(
            artifacts_dir,
            step.id,
            result,
            command=step.command,
            network=step.network,
        )
        _emit_step_completion(prog, step.id, result, artifacts_dir)
    return outputs


def _persist_step_artifacts(
    artifacts_dir: Optional[Path],
    step_id: str,
    result: ExecResult,
    *,
    command: str,
    network: str,
) -> None:
    """Write <step_id>.{stdout,stderr,meta.json} under artifacts_dir."""
    if artifacts_dir is None:
        return
    (artifacts_dir / f"{step_id}.stdout").write_text(result.stdout or "")
    (artifacts_dir / f"{step_id}.stderr").write_text(result.stderr or "")
    meta = {
        "step_id": step_id,
        "command": command,
        "network": network,
        "alternative_used": result.alternative_used,
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "outcome": result.outcome.value,
    }
    save_json(meta, artifacts_dir / f"{step_id}.meta.json")


def _emit_step_completion(
    prog: Progress,
    step_id: str,
    result: ExecResult,
    artifacts_dir: Optional[Path],
) -> None:
    artifact_hint = (
        f" — {artifacts_dir.name}/{step_id}.{{stdout,stderr,meta.json}}"
        if artifacts_dir is not None
        else ""
    )
    status_word = {
        ExecOutcome.OK: "ok",
        ExecOutcome.FAILED: "failed",
        ExecOutcome.TIMEOUT: "timeout",
        ExecOutcome.SKIPPED: "skipped",
    }.get(result.outcome, result.outcome.value)
    prog.substep(
        "execute",
        f"{step_id}: {status_word} "
        f"(exit {result.exit_code}, {result.duration_seconds:.1f}s)"
        f"{artifact_hint}",
    )

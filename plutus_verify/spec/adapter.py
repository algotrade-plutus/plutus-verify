"""Bridge: v2 Manifest → v1 ExtractedPlan.

This adapter is intentionally lossy: it bridges v2 → v1 so the legacy
build/execute/compare code can run against v2-authored repos. Plan 2 added a
native v2 runtime so v2 repos no longer execute through the v1 path; the
adapter is still called to produce an auditable `plan.json` for the v2 path.
Full retirement is deferred until the legacy LLM-extract pathway is removed.

Documented losses (each emits an extraction_notes entry on the returned plan):
  - env.os_packages, env.gpu_required (Plan 2 generates the Dockerfile natively)
  - steps[*].inputs (Plan 2 adds input pre-flight)
  - artifacts of compare != visual_similarity (Plan 2 adds full comparator)
  - data_sources.processed entries that span multiple steps (Plan 2 has tier resolver)
  - steps[*].nine_step == None becomes step_4_in_sample placeholder
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from plutus_verify.spec.manifest import (
    Manifest,
    NINE_STEP_KEYS,
)

if TYPE_CHECKING:
    from plutus_verify.extract.plan import ExtractedPlan


_FREE_FORM_PLACEHOLDER = "step_4_in_sample"


def to_extracted_plan(m: Manifest) -> "ExtractedPlan":
    """Convert v2 Manifest to v1 ExtractedPlan.

    Returns an ExtractedPlan with intentional lossy translation documented
    in extraction_notes.
    """
    # Import here to avoid httpx dependency at module load time
    from plutus_verify.extract.plan import (
        EnvSetup,
        ExpectedChart,
        ExpectedMetric,
        ExpectedResult,
        ExtractedPlan,
        Locate as PlanLocate,
        NineStepEntry,
        Repo as PlanRepo,
        SecretRequirement,
        Step as PlanStep,
        StepAlternative,
        Tolerance as PlanTolerance,
    )

    notes: list[str] = []

    # Helper: index raw data sources by step
    raw_by_step: dict[str, tuple] = {}
    for ds in m.data_sources.raw:
        for step_id in ds.satisfies:
            raw_by_step.setdefault(step_id, []).append(ds)
    raw_by_step = {k: tuple(v) for k, v in raw_by_step.items()}

    # Process env setup
    if m.env.os_packages:
        notes.append(
            f"v2 env.os_packages {list(m.env.os_packages)} ignored by the legacy "
            "pipeline; Plan 2 generates the Dockerfile natively."
        )
    if m.env.gpu_required:
        notes.append("v2 env.gpu_required=true ignored by the legacy pipeline.")

    env_setup = EnvSetup(
        kind="requirements_txt",
        path=m.env.requirements_file,
        python_version=m.env.python_version,
        extra_setup_commands=(),
    )

    # Process secrets
    secrets_required = tuple(
        SecretRequirement(
            key=s.key,
            purpose=s.purpose,
            step_ids=tuple(u for u in s.used_by if not u.startswith("data_sources.")),
        )
        for s in m.secrets
    )

    # Build repo
    repo = PlanRepo(
        name=m.repo.name,
        primary_language=m.repo.primary_language,
        env_setup=env_setup,
        secrets_required=secrets_required,
    )

    # Process data sources
    for ds in m.data_sources.processed:
        if len(ds.satisfies) > 1:
            notes.append(
                f"v2 data_sources.processed entry (kind={ds.kind}, url={ds.url}) "
                f"satisfies multiple steps {list(ds.satisfies)}; not natively "
                "honored by the legacy pipeline. Plan 2 implements the tier resolver."
            )

    # Process steps
    def _build_step(s):
        if s.nine_step is None:
            notes.append(
                f"v2 free-form step '{s.id}' (label={s.label!r}) mapped to "
                f"placeholder nine_step={_FREE_FORM_PLACEHOLDER}."
            )
            nine_step = _FREE_FORM_PLACEHOLDER
        else:
            nine_step = s.nine_step

        if s.inputs:
            notes.append(
                f"v2 step '{s.id}' inputs {list(s.inputs)} not enforced in adapter; "
                "Plan 2 adds input pre-flight."
            )

        raw_sources = raw_by_step.get(s.id, ())
        alternatives = (
            tuple(
                StepAlternative(
                    label=ds.label or f"{ds.kind} download",
                    kind="manual_download",
                    url=ds.url,
                    expected_layout=ds.expected_layout,
                    needs_secrets=ds.secrets_required,
                    network="bridge",
                    timeout_seconds=1800,
                    produces=ds.expected_layout,
                )
                for ds in raw_sources
            )
            if raw_sources
            else None
        )

        return PlanStep(
            id=s.id,
            nine_step=nine_step,
            required=s.required,
            depends_on=s.depends_on,
            command=s.command,
            config_files=(),
            network=s.network,
            timeout_seconds=s.timeout_seconds,
            produces=s.outputs,
            alternatives=alternatives,
            verification_mode=s.verification_mode,
        )

    steps = tuple(_build_step(s) for s in m.steps)

    # Process expected results
    def _build_expected(er):
        def _synthetic_locate(h_name: str) -> "PlanLocate":
            # v2 metrics no longer carry a locator; the SDK writes a canonical
            # results.json (Task 1) and the v2 runtime reads it natively (Task 2 + 4).
            # The v1 ExpectedMetric still requires a locate field, so we synthesize
            # one that points at the SDK's results.json. This locator is never
            # exercised by the v2 path; it exists only so the audit-trail
            # ExtractedPlan stays constructible.
            return PlanLocate(
                kind="json_file",
                path=f".plutus/run/{er.step_id}/results.json",
                jsonpath=f"$.metrics[?(@.name=='{h_name}')].value",
            )

        metrics = tuple(
            ExpectedMetric(
                name=h.name,
                value=h.value,
                locate=_synthetic_locate(h.name),
                tolerance=PlanTolerance(kind=h.tolerance.kind, value=h.tolerance.value),
            )
            for h in er.metrics
        )

        chart_refs = []
        for r in er.artifacts:
            if r.compare == "visual_similarity":
                chart_refs.append(
                    ExpectedChart(
                        name=r.path,
                        produced_path=r.path,
                        reference_image=None,
                    )
                )
            else:
                notes.append(
                    f"v2 artifacts path={r.path} compare={r.compare} "
                    "not supported by legacy pipeline; Plan 2 adds the full comparator."
                )

        return ExpectedResult(step_id=er.step_id, metrics=tuple(metrics), charts=tuple(chart_refs))

    expected_results = tuple(_build_expected(er) for er in m.expected)

    # Build nine_step mapping
    mapping = {k: NineStepEntry(present=False, section_heading=None, confidence=1.0) for k in NINE_STEP_KEYS}
    for k, v in m.nine_step_coverage.items():
        mapping[k] = NineStepEntry(present=v.present, section_heading=v.section, confidence=1.0)

    return ExtractedPlan(
        schema_version="1.0",
        repo=repo,
        nine_step_mapping=mapping,
        steps=steps,
        expected_results=expected_results,
        extraction_notes=tuple(notes),
    )

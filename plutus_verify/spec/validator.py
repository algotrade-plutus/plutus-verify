"""Cross-field invariants for the v2 manifest.

JSON-Schema validates structure; this module enforces relationships:
  - env.manager 'uv' requires a lockfile
  - the data_preparation step must declare a command
  - sub_processes is only allowed on the data_preparation step
  - step ids unique
  - every depends_on references an existing step
  - every expected.step_id references an existing step
  - every data_source.satisfies references an existing step
  - every secret.used_by references an existing step
"""
from __future__ import annotations

from plutus_verify.spec.manifest import Manifest


class ManifestInvariantError(ValueError):
    """Raised when a structurally-valid manifest violates a cross-field rule."""


_DATA_STEP_IDS = ("data_preparation",)


def check_invariants(m: Manifest) -> None:
    if m.env.manager == "uv" and not m.env.lockfile:
        raise ManifestInvariantError(
            "env.manager 'uv' requires env.lockfile to point at a committed "
            "lockfile (e.g. uv.lock) for the verifier to restore"
        )

    step_ids = [s.id for s in m.steps]
    if len(set(step_ids)) != len(step_ids):
        dupes = sorted({sid for sid in step_ids if step_ids.count(sid) > 1})
        raise ManifestInvariantError(f"duplicate step id(s): {dupes}")

    step_id_set = set(step_ids)

    for s in m.steps:
        if s.id in _DATA_STEP_IDS and not s.command:
            raise ManifestInvariantError(
                f"step '{s.id}' requires a non-empty command (data steps must "
                "have runnable code even when data_sources provides downloads)"
            )
        if s.sub_processes is not None and s.nine_step != "step_2_data_preparation":
            raise ManifestInvariantError(
                f"step '{s.id}' declares sub_processes, which is only allowed on "
                "the data_preparation step (nine_step: step_2_data_preparation)"
            )
        for dep in s.depends_on:
            if dep not in step_id_set:
                raise ManifestInvariantError(
                    f"step '{s.id}' depends_on unknown step '{dep}'"
                )

    for er in m.expected:
        if er.step_id not in step_id_set:
            raise ManifestInvariantError(
                f"expected refers to unknown step_id '{er.step_id}'"
            )

    for tier_name, sources in (("processed", m.data_sources.processed), ("raw", m.data_sources.raw)):
        for ds in sources:
            for step_id in ds.satisfies:
                if step_id not in step_id_set:
                    raise ManifestInvariantError(
                        f"data_sources.{tier_name} entry (url={ds.url}) "
                        f"satisfies unknown step '{step_id}'"
                    )

    for sec in m.secrets:
        for step_id in sec.used_by:
            # Allow data-source qualifiers like "data_sources.processed.s3"
            if step_id.startswith("data_sources."):
                continue
            if step_id not in step_id_set:
                raise ManifestInvariantError(
                    f"secret {sec.key} used_by unknown step '{step_id}'"
                )

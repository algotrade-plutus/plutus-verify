"""Deterministic stitcher: assemble per-call elements into an ``ExtractedPlan``.

Inputs are the parsed elements from the decomposed extractor (one dict / list
per LLM call). Output is a single dict that passes :func:`parse_plan`.

The stitcher owns:
- Filling in ``confidence`` for nine_step_mapping (the LLM doesn't pick it).
- Deriving ``depends_on`` for every step from the standard Plutus pattern
  (every executable step depends on the data_collection step, if present).
- Cross-linking ``secrets_required[].step_ids`` by scanning each step's
  ``alternatives[].needs_secrets``.
- Wrapping bare-list element inputs into the canonical fields.
- Adding ``extraction_notes: []`` (no LLM input needed).

By construction, the output is structurally complete; ``parse_plan`` then
performs the schema check.
"""
from __future__ import annotations

from typing import Any

from plutus_verify.extract.plan import (
    NINE_STEP_KEYS,
    ExtractedPlan,
    parse_plan,
)

__all__ = ["assemble_plan_dict", "stitch"]


# Standard Plutus dependency pattern: every executable step depends on the
# data_collection step (if present). Data collection itself depends on nothing.
_DATA_COLLECTION_KEY = "step_2_data_collection"


def assemble_plan_dict(
    repo: dict[str, Any],
    nine_step: dict[str, Any],
    steps: list[dict[str, Any]],
    results: list[dict[str, Any]],
    additional_steps: list[dict[str, Any]] | None = None,
    extraction_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble per-call elements into a canonical plan dict.

    The returned dict is structurally complete and ready for ``parse_plan``.
    Any LLM-emitted ``depends_on`` on individual steps is discarded — the
    stitcher derives this field deterministically.
    """
    all_steps = list(steps) + list(additional_steps or [])
    data_collection_id = _find_step_id_by_nine_step(all_steps, _DATA_COLLECTION_KEY)

    enriched_steps = [
        _enrich_step(s, data_collection_id=data_collection_id) for s in all_steps
    ]

    enriched_repo = _enrich_repo(repo, steps=enriched_steps)
    enriched_mapping = _enrich_nine_step_mapping(nine_step)

    return {
        "schema_version": "1.0",
        "repo": enriched_repo,
        "nine_step_mapping": enriched_mapping,
        "steps": enriched_steps,
        "expected_results": list(results),
        "extraction_notes": list(extraction_notes or []),
    }


def stitch(
    repo: dict[str, Any],
    nine_step: dict[str, Any],
    steps: list[dict[str, Any]],
    results: list[dict[str, Any]],
    additional_steps: list[dict[str, Any]] | None = None,
    extraction_notes: list[str] | None = None,
) -> ExtractedPlan:
    """Assemble + validate. Raises ``PlanValidationError`` on schema violation."""
    data = assemble_plan_dict(
        repo=repo,
        nine_step=nine_step,
        steps=steps,
        results=results,
        additional_steps=additional_steps,
        extraction_notes=extraction_notes,
    )
    return parse_plan(data)


# ---------- Internals ----------


def _find_step_id_by_nine_step(
    steps: list[dict[str, Any]], nine_step_key: str
) -> str | None:
    for s in steps:
        if s.get("nine_step") == nine_step_key:
            sid = s.get("id")
            if isinstance(sid, str) and sid:
                return sid
    return None


def _enrich_step(
    step: dict[str, Any], *, data_collection_id: str | None
) -> dict[str, Any]:
    """Return a copy of ``step`` with derived ``depends_on`` set.

    Drops any LLM-supplied ``depends_on`` value — we own this field.
    Also fills in ``alternatives[].expected_layout`` for ``manual_download``
    alternatives that don't have it: copy the step's ``produces`` so the
    executor's manual-download resolver can check whether the data is on disk.
    """
    out = dict(step)
    out.pop("depends_on", None)  # never trust LLM-supplied deps

    nine = out.get("nine_step")
    if nine == _DATA_COLLECTION_KEY or not data_collection_id:
        out["depends_on"] = []
    elif out.get("id") == data_collection_id:
        out["depends_on"] = []
    else:
        out["depends_on"] = [data_collection_id]

    produces = list(out.get("produces") or [])
    alts = out.get("alternatives")
    if isinstance(alts, list) and produces:
        new_alts: list[dict[str, Any]] = []
        for alt in alts:
            if not isinstance(alt, dict):
                continue
            alt = dict(alt)
            if alt.get("kind") == "manual_download" and not alt.get("expected_layout"):
                alt["expected_layout"] = list(produces)
            new_alts.append(alt)
        out["alternatives"] = new_alts

    return out


def _enrich_nine_step_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Ensure all 7 keys exist; supply confidence (1.0 if present, else 0.0)."""
    out: dict[str, Any] = {}
    for key in NINE_STEP_KEYS:
        entry = mapping.get(key) or {}
        present = bool(entry.get("present", False))
        heading = entry.get("section_heading")
        if heading is not None and not isinstance(heading, str):
            heading = None
        out[key] = {
            "present": present,
            "section_heading": heading,
            # Stitcher owns confidence — LLM self-reported confidence isn't trustworthy.
            "confidence": 1.0 if present else 0.0,
        }
    return out


def _enrich_repo(
    repo: dict[str, Any], *, steps: list[dict[str, Any]]
) -> dict[str, Any]:
    """Normalise ``repo`` and cross-link ``secrets_required[].step_ids``."""
    out = dict(repo)

    # Ensure env_setup has the expected shape.
    env = out.get("env_setup") or {}
    out["env_setup"] = {
        "kind": env.get("kind", "none"),
        "path": env.get("path"),
        "python_version": env.get("python_version"),
        "extra_setup_commands": list(env.get("extra_setup_commands") or []),
    }

    # Normalise secrets_required: accept bare strings or dicts, ensure {key, purpose, step_ids}.
    secrets_in = out.get("secrets_required") or []
    parsed: list[tuple[str, str]] = []
    for s in secrets_in:
        if isinstance(s, str):
            parsed.append((s, ""))
        elif isinstance(s, dict):
            key_val = s.get("key") or s.get("name")
            if isinstance(key_val, str) and key_val:
                parsed.append((key_val, s.get("purpose") or ""))
    cross_links = _build_secret_to_step_index(steps, [k for k, _ in parsed])
    out["secrets_required"] = [
        {
            "key": key,
            "purpose": purpose,
            "step_ids": sorted(cross_links.get(key, set())),
        }
        for key, purpose in parsed
    ]

    # Required strings; fill safe defaults if missing.
    out["name"] = out.get("name") or ""
    out["primary_language"] = out.get("primary_language") or "python"
    return out


def _build_secret_to_step_index(
    steps: list[dict[str, Any]], secret_keys: list[str]
) -> dict[str, set[str]]:
    """Map each secret key to the step ids that use it.

    Plutus convention: the only step that needs secrets is data_collection
    (DB credentials, API keys to fetch market data). Link every declared
    secret to whichever step has nine_step="step_2_data_collection" unless
    an alternative's needs_secrets list explicitly says otherwise.
    """
    out: dict[str, set[str]] = {}

    # First: use any explicit needs_secrets the LLM put on alternatives.
    for s in steps:
        sid = s.get("id")
        if not isinstance(sid, str):
            continue
        alts = s.get("alternatives") or []
        for alt in alts:
            if not isinstance(alt, dict):
                continue
            for key in alt.get("needs_secrets") or []:
                if isinstance(key, str) and key:
                    out.setdefault(key, set()).add(sid)

    # Fallback: any declared secret with no explicit owner links to data_collection.
    data_collection_id = _find_step_id_by_nine_step(steps, _DATA_COLLECTION_KEY)
    if data_collection_id:
        for key in secret_keys:
            out.setdefault(key, set()).add(data_collection_id)

    return out

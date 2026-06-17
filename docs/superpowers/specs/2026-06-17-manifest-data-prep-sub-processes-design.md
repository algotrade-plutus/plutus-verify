# Design: `sub_processes` documentation block on the data_preparation step

**Date:** 2026-06-17
**Status:** approved (design), pending implementation
**Scope:** additive manifest schema feature. Does **not** change the v2025 9-step
process or the 7 `NINE_STEP_KEYS`.

## Context / problem

In v2025, the old v2023 steps *data collection* and *data processing* were merged
into a single canonical step, `step_2_data_preparation`. The merge lost the ability
to describe those two activities separately. In the golden/happy path (a repo just
downloads prepared data files), there is genuinely nothing to run — but when a repo
*does* collect and/or process data, the manifest currently has no structured place
to document **what** those sub-activities are and **how** they're performed.

This feature adds an **optional, documentation-only** block to the data_preparation
step that records its two sub-processes. It is purely for clarity and manifest
completeness; the verifier never executes it.

## Decisions (locked with user)

1. **Shape:** a *fixed pair* — exactly two named slots, `collection` and
   `processing` (not a free-form list).
2. **Placement:** an optional `sub_processes` field on the step, **enforced** to the
   data_preparation step only (validator invariant); illegal elsewhere.
3. **Surfacing:** rendered in `plutus check` output under the Step 2 section.
4. **Execution:** never executed by the verifier — documentation only. The step's
   own `command` (or a satisfying `data_source`) is what actually runs.

## Schema (`plutus_verify/spec/schema.py`)

Add one optional property to the step definition:

```yaml
sub_processes:                 # optional; only on the data_preparation step
  collection:                  # optional slot
    description: "..."         # REQUIRED when the slot is present
    command: "..."            # optional
    inputs: ["..."]           # optional
    outputs: ["..."]          # optional
  processing:                  # optional slot, same shape
    description: "..."
    command: "..."
    inputs: ["..."]
    outputs: ["..."]
```

- `sub_processes` object: `additionalProperties: false`; only `collection` and
  `processing` keys allowed; both individually optional (so a repo may document just
  one). Absent entirely in the download-only happy path.
- Each slot: `additionalProperties: false`; `required: ["description"]`;
  `command` is `string | null`; `inputs`/`outputs` are arrays of strings (mirroring
  the Step fields).

## Dataclasses (`plutus_verify/spec/manifest.py`)

- New frozen `SubProcess(description: str, command: str | None, inputs: tuple[str, ...], outputs: tuple[str, ...])`.
- New frozen `SubProcesses(collection: SubProcess | None, processing: SubProcess | None)`.
- New `Step` field: `sub_processes: SubProcesses | None = None`.
- Wire construction through the existing dict→dataclass builder used by the loader.

## Validator (`plutus_verify/spec/validator.py`)

New cross-field invariant in `check_invariants`:

> For every step, if `step.sub_processes is not None` and
> `step.nine_step != "step_2_data_preparation"`, raise `ManifestInvariantError`
> ("sub_processes is only allowed on the data_preparation step
> (nine_step: step_2_data_preparation)").

## Check report (`plutus_verify/scaffold/check_report.py`)

When rendering the **Step 2: Data Preparation** section, if the step carries
`sub_processes`, print each present slot as an indented line, e.g.:

```
Step 2: Data Preparation
  ok data_preparation: exit=0
    • collection: pull VN30F1M ticks from the DB
    • processing: resample ticks to 1-minute bars
```

(Command shown after the description only if present, e.g. `— python -m x.collect`.)

## Docs & templates

- Show the optional block (commented) in the `db-backed-loader.yaml` and
  `drive-backed.yaml` skill templates and the `init` skeleton
  (`scaffold/templates.py`), plus `scaffold/manifest_template_todo.py`.
- Document it in `docs/feature/v2-manifest.md` (step options + an example).
- The `processed-csv-shipped.yaml` template stays **without** the block — it models
  the download-only happy path where there is nothing to document.

## Testing

- Schema: accepts `sub_processes` on the data_preparation step; rejects unknown slot
  keys and unknown fields within a slot; `description` required when a slot is
  present.
- Validator: rejects `sub_processes` on a non-data_preparation step.
- Loader: builds the `SubProcesses`/`SubProcess` dataclasses correctly; a manifest
  with no block (happy path) still loads with `step.sub_processes is None`.
- Check report: a data_preparation step with `sub_processes` renders the
  collection/processing lines under Step 2.

## Out of scope

- No change to `NINE_STEP_KEYS`, the 9-step process, or the legacy LLM-extraction
  island.
- The verifier does not execute sub-process `command`s, nor preflight their
  `inputs`/`outputs`. They are descriptive only.
- No back-compat concern: the field is new and optional; existing manifests are
  unaffected.

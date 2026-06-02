---
subject: extraction
date: 2026-06-01
version: 1.0
status: current
---

# LLM Extraction Subsystem — Architecture & Design

## Overview

The extraction subsystem turns a repo's `README.md` into a validated
`ExtractedPlan` — the structured contract the otherwise-deterministic v1 pipeline
consumes. It is the **v1 / legacy path**: it only runs for repos that do *not*
ship a `.plutus/manifest.yaml`. For v2 repos the manifest is the plan and this
whole subsystem is bypassed (see [v2-spec-and-execution](v2-spec-and-execution.md)).

It exists to bridge a hard gap: real research repos describe their results in
prose and markdown tables, not in a machine schema. The subsystem's job is to
extract that description reliably enough that downstream stages can execute and
compare against it — while keeping the LLM strictly a *structured-output
extractor*, never an agent. The stable boundary is the versioned `ExtractedPlan`
schema; the model can be swapped without touching downstream code.

## Architecture

```
README.md
   │ extract_plan()
   ▼
decompose ── 4 sequential form-filling LLM calls ──► DecomposeResult
 (repo, nine_step, steps, results)                         │
   │  templates.py (prompts) + llm_parsing (fence-strip)   │
   ▼                                                        ▼
stitch ── assemble + derive untrusted fields ──────► ExtractedPlan (plan.py)
   │                                                        │
   ▼  parse_plan: JSON-Schema + referential invariants     │
   ▼                                                        ▼
validate_plan (validator.py) ── Phase 1 deterministic ──► plan.json
                               (Phase 2 LLM pass disabled)
```

### Components

#### Public entry — `plutus_verify/extract/__init__.py`
- `extract_plan(readme_text, client, ...)` (`:39`) — thin: calls `decompose`
  then `stitch`, mapping errors to `ExtractError`. Validation is a separate
  stage the pipeline invokes afterward.

#### Decompose — `plutus_verify/extract/decompose.py`
- **Purpose:** four sequential form-filling calls instead of one free-form call —
  `repo`, `nine_step`, `steps` (fed the present nine-step keys), `results` (fed
  the step ids). A fifth "extras" call for non-Plutus steps is stubbed
  (`additional_steps` always `[]`).
- **Key interfaces:** `decompose` (`:314`), `_run_call` per-call retry loop
  (`:260`), per-call parsers (`:65`/`:83`/`:138`/`:173`), `_normalize_step`
  (`:103`) which repairs common LLM slips before schema check.

#### Templates — `plutus_verify/extract/templates.py`
- One shared `SYSTEM_FILL` prompt ("JSON only, fixed field names, enum values
  verbatim, null when unknown"); per-call user templates embedding the README;
  `RETRY_SUFFIX` that appends the parser's error so the model self-corrects.

#### Stitch — `plutus_verify/extract/stitch.py`
- Assembles the call outputs into a plan dict and **owns the untrustworthy
  fields**: it sets `confidence` itself (1.0 if present else 0.0), discards the
  LLM's `depends_on` and re-derives it from the standard Plutus pattern (every
  executable step depends on data collection), and cross-links secrets to steps.

#### Plan schema — `plutus_verify/extract/plan.py`
- The `ExtractedPlan` dataclass tree + `PLAN_SCHEMA` (Draft 2020-12,
  `schema_version "1.0"`). `parse_plan` (`:330`) validates against the schema and
  enforces referential invariants (every `depends_on` and `expected.step_id`
  references a real step).

#### LLM client — `plutus_verify/extract/client.py`
- `OpenAICompatClient` (`:51`) targets Ollama's **native `/api/chat`** (not the
  `/v1` compat path, which silently ignores `options.num_ctx`). Always streaming,
  fresh `httpx.Client` per call, content-idle timeout, captures `message.content`
  (Gemma's `thinking` resets the idle timer but is discarded). `prewarm` (`:140`)
  forces the runner to load with the chosen `num_ctx`.

#### Validator — `plutus_verify/extract/validator.py`
- `validate_plan` (`:335`): Phase 1 (deterministic, always) drops impossible
  stdout-table metrics on `artifact_check` steps and warns on missing json-file
  paths; Phase 2 (optional LLM corrections pass) is **disabled in production**
  because it hallucinated no-op corrections.

## Design Principles

- **LLM as structured-output extractor, never an agent.**
- **Localized, cheap retries.** Small form-filling calls (200B–2KB each) with
  per-call retry budgets and self-correcting error suffixes.
- **The stitcher owns derived truth.** Anything the LLM can't be trusted with
  (confidence, dependency edges) is computed deterministically.
- **Schema is the contract.** Validation + persistence to `plan.json` let
  reviewers hand-edit and resume.

## Design Decisions

### Decompose-then-stitch (replaced single free-form extraction)
- **Context:** a single free-form extraction produced fragile, schema-violating
  JSON.
- **Decision:** split into four small form-filling calls assembled
  deterministically by `stitch`.
- **Rationale:** each blob is tiny so retries are cheap; errors localize to one
  call; small prompts work with a single idle timeout.
- **Trade-offs:** 4× the calls (each with its own retry budget) and sequential
  data passing between calls.

### Native `/api/chat` over the OpenAI-compat path
- **Decision:** call Ollama's native endpoint.
- **Rationale:** only it honors `options.num_ctx`; the compat path silently
  ignores it, pinning Ollama's large default and blowing memory.

### Phase 2 (LLM correction pass) kept but disabled
- **Context:** the second LLM pass hallucinated no-op corrections.
- **Decision:** `pipeline.py` calls `validate_plan(..., llm_client=None)`;
  Phase 1 (deterministic) is the only pass that runs. Phase 2 stays as dormant
  safety-net code.

## Data Model

`ExtractedPlan` (`plan.py:317`): `schema_version`, `repo`, `nine_step_mapping`,
`steps`, `expected_results`, `extraction_notes`. Notable nested types:

- `Step` (`:262`): `id`, `nine_step`, `required`, `depends_on`, `command`,
  `network` (default `none`), `timeout_seconds`, `produces`, `alternatives`,
  `verification_mode` (`execute`/`artifact_check`).
- `StepAlternative` (`:249`): `manual_download` (with `url`/`expected_layout`) or
  `command`, each with its own `needs_secrets`/`network`.
- `ExpectedMetric` (`:293`): `name`, `value` (float or string for categorical
  params), `locate` (`stdout_table`/`json_file`/`file_regex`), `tolerance`
  (`relative`/`absolute`/`exact`).
- `ExpectedChart` (`:303`): `name`, `produced_path`, optional `reference_image`.

The "nine-step" mapping uses `NINE_STEP_KEYS` from `constants.py` — which, despite
the name, holds **7** keys (`step_1_hypothesis` … `step_7_paper_trading`).

## Error Handling & Edge Cases

- Parser `ValueError` → retry with the error suffix → `DecomposeError` →
  `ExtractError`. Schema/invariant failure → `PlanValidationError` →
  `ExtractError`.
- Network errors (timeouts, connection errors, optional `openai` API errors)
  retry with the same prompt.
- The validator treats LLM failures as fix-notes, not errors —
  `ValidatorError` is reserved for unrecoverable state.

## Performance Considerations

- Four calls × small prompts is the cost; the client streams and uses a
  content-idle timeout (not a wall-clock one) so a slow-but-progressing model
  isn't killed.
- `prewarm` amortizes Ollama cold start and forces the intended `num_ctx`.

## Future Considerations

- **This whole subsystem is the v1 legacy path.** v2 repos bypass it; deletion
  of `extract/plan.py` and the LLM branch is deferred (it's still used by
  `plutus transfer`).
- **The "extras" call is stubbed** — no escape hatch yet for non-Plutus ML steps
  in extraction.
- **Client quirks are bug-compat workarounds:** `iter_bytes` not `iter_lines`
  (httpx 0.28 buffering); a 10s stderr heartbeat instead of per-token echo
  (which stalls the stream); no constrained JSON mode (it deadlocks Gemma on
  long prompts).
- **Doc drift:** the design plan references an older `extract/prompt.py` layout;
  the shipped code uses `templates.py` + `decompose.py` + `stitch.py`.

## Features Covered

- [repo-verification](../feature/repo-verification.md) — the v1 path that consumes the extracted plan.
- [legacy-migration](../feature/legacy-migration.md) — `transfer` reuses this extractor to seed a v2 draft.

## Source Materials

- Plan: `docs/plan/2026-05-15-plutus-verify-design.md`
- Code: `plutus_verify/extract/{__init__,client,decompose,plan,stitch,templates,validator}.py`,
  `plutus_verify/util/llm_parsing.py`, `plutus_verify/constants.py`
</content>

# plutus-verify MVP — Simplify Pass (A + B + C)

## Context

The project reached MVP on the `refactor` branch (10 plans landed, 59 Python files, ~10.6K LOC). A `/simplify` diagnostic ran three review agents (reuse, quality, efficiency) across the whole `plutus_verify/` package. The codebase is in solid shape — no architectural rot — but a small cluster of cross-cutting issues should be tightened before merging to `main`:

- A handful of helpers got re-implemented 2–3× across modules (~175 LOC of duplication).
- `pipeline.run_pipeline` has grown to 951 lines as a god-function.
- Stage outcomes and step keys are stringly-typed even though the allowed values are documented.
- A few real wall-clock wins exist in the LLM/compare hot paths.

This plan executes all eleven high/medium findings in three sequential passes (A → B → C). Each pass leaves the tree green; later passes assume earlier passes landed. Findings #12–#17 from the diagnostic are explicitly deferred (see "Out of scope" at the end).

## Approach

Three passes, each committed independently so they can be reviewed / reverted in isolation.

### Pass A — Consolidation (low-risk, mostly mechanical)

Goal: extract duplicated helpers; no behavior change. ~150 LOC saved.

**A1. Single source of truth for `_strip_fences`**
- Create `plutus_verify/util/llm_parsing.py` with `strip_markdown_fences(text: str) -> str` (regex form — the imperative form in `build/llm_fixer.py` is incidental drift, not intentional).
- Replace inline `_FENCE_RE` / `_strip_fences` in:
  - [extract/decompose.py:42-49](../../plutus_verify/extract/decompose.py#L42-L49)
  - [compare/llm_match.py:60-67](../../plutus_verify/compare/llm_match.py#L60-L67)
  - [build/llm_fixer.py:51-59](../../plutus_verify/builder/llm_fixer.py#L51-L59)
- Add a small test verifying fenced / unfenced / nested-backtick inputs all round-trip correctly.

**A2. Single source of truth for `NINE_STEP_KEYS`**
- Create `plutus_verify/constants.py` (or reuse `spec/manifest.py` as canonical) with `NINE_STEP_KEYS: tuple[str, ...]`.
- Remove the duplicate at [extract/plan.py:17-25](../../plutus_verify/extract/plan.py#L17-L25); import from canonical site. Drop the "future cleanup" comment that lives in both files.
- Confirm `plutus transfer` still imports cleanly — that's the dependency the duplication comment cites.

**A3. JSON I/O helpers**
- Add `plutus_verify/util/json_io.py` with `load_json(path: Path) -> Any` and `save_json(obj: Any, path: Path, *, indent: int = 2) -> None`.
- Replace `json.loads(path.read_text())` / `path.write_text(json.dumps(..., indent=2))` patterns in:
  - [ingest.py:51](../../plutus_verify/ingest.py#L51), [ingest.py:115](../../plutus_verify/ingest.py#L115)
  - [execute.py:275](../../plutus_verify/execute.py#L275)
  - [pipeline.py:218,236,242,248,315,321](../../plutus_verify/pipeline.py#L218)
  - [compare/metrics.py:289](../../plutus_verify/compare/metrics.py#L289)

**A4. Shared subprocess / Docker injector pattern**
- Add `plutus_verify/util/subprocess.py` with a `SubprocessRunner` protocol + `default_runner` that wraps `subprocess.run` with consistent capture/text/timeout defaults.
- Replace the bespoke injectors at:
  - [build/runner.py:100-105](../../plutus_verify/builder/runner.py#L100-L105) (`_DockerInvoker`, `_default_docker`)
  - [spec/runtime/real_image_builder.py:62-72](../../plutus_verify/spec/runtime/real_image_builder.py#L62-L72) (`_default_docker_runner`)
  - [ingest.py:10-36](../../plutus_verify/ingest.py#L10-L36) (`GitRunner`, `_default_git_runner`)
- Keep call-site signatures the same; only the type alias + default move.

### Pass B — Pipeline & types (real refactor)

Goal: readability + type safety. Behavior unchanged.

**B1. `StageOutcome` literal type + helper**
- Define `StageOutcome = Literal["ok", "skipped", "failed", "partial"]` in `plutus_verify/report/__init__.py` (next to `TrailEntry` — that's where the type belongs).
- Add `TrailOutcome.from_counts(ok: int, skipped: int, failed: int) -> StageOutcome` to replace the unreadable ternary at [pipeline.py:454](../../plutus_verify/pipeline.py#L454).
- Update `TrailEntry.outcome: str` → `outcome: StageOutcome`.
- Replace raw `"ok"` / `"skipped"` / `"failed"` / `"partial"` string literals throughout [pipeline.py](../../plutus_verify/pipeline.py) (currently scattered between lines 172 and 462).

**B2. Decompose `pipeline.run_pipeline` (951 lines) into per-stage functions**
- Each stage gets its own private function in [pipeline.py](../../plutus_verify/pipeline.py):
  ```
  _run_ingest(...)  -> tuple[IngestResult, TrailEntry]
  _run_extract(...) -> tuple[ExtractedPlan, TrailEntry, list[Finding]]
  _run_build(...)   -> tuple[BuildResult, TrailEntry]
  _run_fetch(...)   -> tuple[None, TrailEntry, list[Finding]]
  _run_execute(...) -> tuple[dict[str, ExecResult], TrailEntry]
  _run_compare(...) -> tuple[list[StepReport], TrailEntry]
  _run_report(...)  -> tuple[OverallReport, TrailEntry]
  ```
- `run_pipeline` becomes a thin sequencer: build inputs, call each stage, collect `TrailEntry`s, handle the `--resume-from` short-circuits.
- Target post-refactor size: `run_pipeline` ≤ 120 lines; total file ≤ 800 lines.
- Do NOT introduce a new abstraction (registry / list of callables) — straight-line sequencing keeps the resume logic readable.

**B3. `CallConfig` dataclass for the extract retry loop**
- Bundle the stable params of [`_run_call` at extract/decompose.py:247-299](../../plutus_verify/extract/decompose.py#L247-L299) (`client`, `temperature`, `idle_timeout_seconds`, `max_retries`, `on_attempt`) into a frozen dataclass.
- New signature: `_run_call(config: CallConfig, *, call_index: int, label: str, user_prompt: str, parser: _CallParser) -> Any`.
- Update the 4 call sites in `decompose()` ([decompose.py:328-383](../../plutus_verify/extract/decompose.py#L328-L383)).

**B4. Typed `DecomposeResult` return value**
- Replace the documented-by-docstring `dict[str, Any]` return from `decompose()` ([decompose.py:386-392](../../plutus_verify/extract/decompose.py#L386-L392)) with `@dataclass DecomposeResult(repo: dict, nine_step: dict, steps: list, results: list, additional_steps: list)`.
- Update `stitch()` to accept the typed value. Remove the `.get(k, {}).get("present")` chain at [decompose.py:353](../../plutus_verify/extract/decompose.py#L353) and equivalents in `stitch.py`.

### Pass C — Hot-path efficiency (measurable wins, careful verification needed)

Goal: real wall-clock + cost wins. Each item must be verified with a before/after timing on a representative repo before merging.

**C1. Avoid passing full README to each of the 4 extract LLM calls**
- Currently [extract/decompose.py:328-383](../../plutus_verify/extract/decompose.py#L328-L383) embeds the full README in the user prompt of every call. With a 50KB README that's ~200KB of duplicate tokens per extraction.
- Option A (smallest diff): hoist `present_step_keys` / `step_ids` computation out of the call prompts; pass only the relevant slice to Calls 2–4. The README is genuinely needed by Call 1 only.
- Option B (bigger but better): if the LLM endpoint supports it, set up prompt-cache markers around the README so subsequent calls pay only the cache-read price. Out of scope if Gemma vLLM doesn't expose cache control — Option A only in that case.
- **Verify**: time the `extract` stage on a known repo before/after; aim for ≥30% wall-clock reduction.

**C2. Read `requirements.txt` once in the LLM-fixer ops loop**
- [build/llm_fixer.py:137-264](../../plutus_verify/builder/llm_fixer.py#L137-L264): `apply_llm_ops()` re-reads requirements.txt from disk per op (line 142, 156, 208, 241). With 3 ops that's 4 reads + 3 writes.
- Refactor `apply_llm_ops()` to: read once → mutate in-memory → write once at the end. Ops become pure functions on the parsed lines.
- **Verify**: build-fixer tests still pass; smoke-test a real fix loop.

**C3. Batch chart-vision calls**
- [compare/charts.py:51-123](../../plutus_verify/compare/charts.py#L51-L123) calls `vision.judge_chart()` once per chart in a for-loop. N charts → N round-trips.
- Add a `vision.judge_charts(pairs: list[ChartPair]) -> list[ChartVerdict]` method on `VisionClient`; have the default OpenAI-compat implementation send a single multi-image call. Fall back to per-chart if the endpoint rejects the batched form.
- **Verify**: chart-comparison tests still pass; time `compare` stage end-to-end on a multi-chart repo.

**C4. Hoist plan.json read out of the resume branches**
- [pipeline.py:241-252](../../plutus_verify/pipeline.py#L241-L252): `parse_plan(json.loads(plan_path.read_text()))` appears in all 3 branches of the resume-from-extract conditional.
- Hoist the read+parse once before the branch.
- Trivial; bundle with B2 if convenient since `_run_extract` will own this.

## Critical files to modify

- New: `plutus_verify/util/llm_parsing.py`, `plutus_verify/util/json_io.py`, `plutus_verify/util/subprocess.py`, `plutus_verify/constants.py`
- Major edits: [pipeline.py](../../plutus_verify/pipeline.py), [extract/decompose.py](../../plutus_verify/extract/decompose.py), [report/__init__.py](../../plutus_verify/report/__init__.py)
- Minor edits: [extract/plan.py](../../plutus_verify/extract/plan.py), [extract/stitch.py](../../plutus_verify/extract/stitch.py), [build/runner.py](../../plutus_verify/builder/runner.py), [build/llm_fixer.py](../../plutus_verify/builder/llm_fixer.py), [compare/llm_match.py](../../plutus_verify/compare/llm_match.py), [compare/metrics.py](../../plutus_verify/compare/metrics.py), [compare/charts.py](../../plutus_verify/compare/charts.py), [ingest.py](../../plutus_verify/ingest.py), [execute.py](../../plutus_verify/execute.py), [spec/runtime/real_image_builder.py](../../plutus_verify/spec/runtime/real_image_builder.py), [spec/manifest.py](../../plutus_verify/spec/manifest.py)

## Existing code to reuse / build on

- `plutus_verify/util/progress.py` already exists — establishes the `util/` package convention. New util modules slot in alongside it.
- `plutus_verify/spec/runtime/sdk_bundle.py` already centralizes one cross-stage concern (SDK wheel bundling) — model the new `util/subprocess.py` similarly: protocol + default + ≤ 200 LOC.
- `TrailEntry` in [report/__init__.py](../../plutus_verify/report/__init__.py) already exists — that's the natural home for `StageOutcome`; do not create a separate types module.
- `_NETWORK_ERROR_TYPES` in [extract/decompose.py](../../plutus_verify/extract/decompose.py) shows how network errors are already categorized — `CallConfig`'s retry semantics should preserve this exact split.

## Verification

After each pass:

1. **Unit tests**: `pytest tests/` — must pass clean. (~21 test files across `tests/`.)
2. **Import check**: `python -c "import plutus_verify"` to catch import-level breaks introduced by the constants / util moves.
3. **Smoke test the CLI**: `plutus-verify --help` and `plutus-verify ./tests/fixtures/<some-repo> --dry-run` (or equivalent) — confirms the pipeline wiring still composes.

After Pass C specifically:

4. **Before/after timing** on a representative repo (e.g. a real ProtoMarketMaker run): record `extract` and `compare` stage wall-clock. Pass C is only merged if at least C1 shows a measurable improvement.

After all three passes:

5. **LOC budget check**: confirm net LOC reduction is ≥100 lines (target was 175 from duplication elimination, minus ~75 LOC of new util-module overhead).
6. **`plutus transfer` still works** — the duplicate `NINE_STEP_KEYS` exists specifically because of this consumer. Run any existing `plutus transfer` smoke test before declaring A2 done.
7. **Commit per pass**: `simplify: pass A — consolidation`, `simplify: pass B — pipeline + types`, `simplify: pass C — hot-path efficiency`. Three reviewable commits, not one mega-diff.

## Explicitly out of scope

Diagnostic findings #12–#17 are deferred:
- Broad `except Exception` narrowing — risk/reward unclear without a specific bug to chase.
- TOCTOU `if path.exists()` → try/except — purely defensive; no observed bug.
- Dead Call-5 stub removal — keep the scaffolding; it's documented and ~5 LOC.
- Stdout/stderr streaming to disk — production concern, not MVP-blocker.
- Deeply nested JSON-Schema literal in [extract/plan.py:33-300+](../../plutus_verify/extract/plan.py#L33) — works; refactor pressure is high but not urgent.
- Regex re-compilation in `_locate_file_regex` ([compare/metrics.py:321](../../plutus_verify/compare/metrics.py#L321)) — verified per-metric, not in a tight loop. Not worth fixing.

# Simplify pass (post-MVP)

A `/simplify` diagnostic run after the v2 MVP reached "shipped" status.
Three review agents (reuse, quality, efficiency) scanned the whole
`plutus_verify/` package (~10.6 KLOC, 59 files); the resulting plan
[`docs/plan/2026-05-25-plutus-verify-mvp-simplify-pass.md`](../plan/2026-05-25-plutus-verify-mvp-simplify-pass.md)
prescribed eleven high/medium items in three sequential passes. This
report records what landed, what was skipped, and the one
gitignore-and-rename surprise that surfaced mid-execution.

## TL;DR

Three commits on `refactor`:

| Pass | Commit | Theme |
|---|---|---|
| **A** | `ed24aa3` | Consolidate duplicated helpers |
| **B** | `2cfeefe` | Pipeline & types |
| **C** | `26d9162` | Hot-path efficiency + `plutus_verify/build` → `builder` rename |

**Test posture**: 485 → 493 (8 new tests for the shared
`strip_markdown_fences` helper). All 493 green at the end of every
pass — no skips, no xfails introduced.

**Aggregate diff** (across all three commits, code + tests):
**24 files changed · +1412 / −324**. Most of the insertions are the
five `plutus_verify/builder/` source files, which were previously
silently excluded from version control by a too-loose `.gitignore` rule
(the surprise — covered in its own section below).

## Pass A — Consolidation (commit `ed24aa3`)

Goal: extract duplicated helpers. No behavior change. **15 files, +277 / −71.**

| Item | Status | What landed |
|---|---|---|
| **A1** | done | New `plutus_verify/util/llm_parsing.py::strip_markdown_fences` replaces three near-duplicate `_strip_fences` implementations in [`extract/decompose.py`](../../plutus_verify/extract/decompose.py), [`compare/llm_match.py`](../../plutus_verify/compare/llm_match.py), and (post-rename) [`builder/llm_fixer.py`](../../plutus_verify/builder/llm_fixer.py). Two were byte-identical regex copies; the third was an imperative variant with subtly different edge cases. 8 new unit tests in [`tests/unit/test_util_llm_parsing.py`](../../tests/unit/test_util_llm_parsing.py). |
| **A2** | done | New `plutus_verify/constants.py` is the single source of truth for `NINE_STEP_KEYS`. [`extract/plan.py`](../../plutus_verify/extract/plan.py) and [`spec/manifest.py`](../../plutus_verify/spec/manifest.py) re-export from it, so existing call sites (including `plutus transfer`'s legacy dependency on `extract.plan`) keep working unchanged. The "future cleanup" comment that lived in both files is gone. |
| **A3** | done | New `plutus_verify/util/json_io.py::load_json` / `save_json` replaces the scattered `json.loads(p.read_text())` / `p.write_text(json.dumps(..., indent=2))` boilerplate across [`ingest.py`](../../plutus_verify/ingest.py), [`execute.py`](../../plutus_verify/execute.py), [`pipeline.py`](../../plutus_verify/pipeline.py), [`spec/runtime/refcompare.py`](../../plutus_verify/spec/runtime/refcompare.py), [`compare/metrics.py`](../../plutus_verify/compare/metrics.py), and [`report/__init__.py`](../../plutus_verify/report/__init__.py). Callers with special flags (`sort_keys`, `allow_nan`) stayed on raw `json`. |
| **A4** | **skipped** | Plan called for a shared `SubprocessRunner` protocol. Inspecting the three existing injectors revealed semantically different signatures: `ingest.GitRunner` returns `str` (stdout) with `check=True`; `build/runner._DockerInvoker` returns `CompletedProcess` with no defaults; `spec/runtime/real_image_builder._default_docker_runner` returns `CompletedProcess` with `timeout=1800`. Forcing them through one protocol would add indirection without saving meaningful LOC. The diagnostic agent overstated the duplication. |

## Pass B — Pipeline & types (commit `2cfeefe`)

Goal: readability + type safety. Behavior unchanged. **3 files, +335 / −250.**

| Item | Status | What landed |
|---|---|---|
| **B1** | done | `StageOutcome = Literal["ok", "skipped", "failed", "partial"]` in [`report/__init__.py`](../../plutus_verify/report/__init__.py), next to `TrailEntry` where it belongs. `TrailEntry.outcome` is now typed `StageOutcome`. New `outcome_from_counts(ok=, failed=)` helper replaces the unreadable `"failed" if n_fail else ("ok" if n_ok else "skipped")` ternary at the old `pipeline.py:454`. The compare/execute outcome expressions kept their custom `"partial"` semantics — those aren't derivable from counts alone. |
| **B2** | done (scoped) | `run_pipeline` trimmed from **538 → 363 lines** by extracting the three heaviest blocks: `_run_extract_via_llm` (LLM-driven extract branch + the `_save_attempt` closure), `_run_compare_stage` (per-step metric + chart comparison), and `_build_findings` + `_BUILD_KIND_MAP` (findings assembly). The plan's seven-function decomposition target was over-eager — fully decomposing every stage would have forced 8+ parameters per helper, which the plan itself flagged as a B3 smell. The remaining stages are short enough to read linearly under the `# ---------- stage ----------` markers. |
| **B3** | done | `CallConfig` frozen dataclass in [`extract/decompose.py`](../../plutus_verify/extract/decompose.py) bundles the stable per-extraction settings (`client`, `temperature`, `idle_timeout_seconds`, `max_retries`, `on_attempt`). `_run_call`'s 4 call sites in `decompose()` now pass only what varies (`call_index`, `label`, `user_prompt`, `parser`). |
| **B4** | done | `DecomposeResult` TypedDict types the dict that `decompose()` returns. Chosen over a fresh `@dataclass` because keys match `stitch()`'s kwargs — `stitch(**result)` keeps working, and dict-style access in [`tests/unit/test_extract_decompose.py`](../../tests/unit/test_extract_decompose.py) is unaffected. Pure type-system signal, zero call-site churn. |

## Pass C — Efficiency + the rename (commit `26d9162`)

Goal: real wall-clock / cost wins. Items requiring real-LLM timing
validation are off-limits in this pass. **11 files, +956 / −10.**

| Item | Status | What landed |
|---|---|---|
| **C1** | **skipped** | Plan proposed slimming the README from 3 of the 4 extract calls. Inspecting [`extract/templates.py`](../../plutus_verify/extract/templates.py) showed each call genuinely needs the full README: Call 2 identifies which 9-step entries are present, Call 3 enforces "COMMAND PROVENANCE: command MUST come from an explicit shell command shown in a code block in the README", Call 4 captures every metric the README's tables list. No slice is safe to strip. Prompt-caching (Option B) would require touching the LLM client and is its own refactor. |
| **C2** | done | [`builder/llm_fixer.py::apply_llm_ops`](../../plutus_verify/builder/llm_fixer.py) refactored to read `requirements.txt` once into memory, mutate the line list across all ops, and write back once. Replaces the per-op read/write loop (4 reads + 3 writes for 3 ops) with O(1) I/O. Introduces a small `_bare_name()` helper that consolidates the PEP-440 package-name extraction inlined in two op handlers. 26 fixer tests still pass. |
| **C3** | **skipped** | Plan called for batching N vision calls into one multi-image LLM call. Realistic risk: multi-image attention is uneven on Gemma's vision model, and the plan itself flagged this as needing before/after timing on a representative repo — which can't be done offline. The current per-chart codepath is correct and well-tested; sequential, not pathological. |
| **C4** | **skipped** | Plan claimed `parse_plan(load_json(plan_path))` appears in "all 3 branches" of the resume-from-extract conditional. Verified: the two call sites at [pipeline.py:244 and :250](../../plutus_verify/pipeline.py#L244) live in **mutually-exclusive elif arms** — only one runs per invocation. Hoisting would force an unconditional read in the fresh-clone case (the `else:` LLM-extract branch doesn't need it). The diagnostic agent miscounted. |

## The surprise: `plutus_verify/build/` was gitignored

Mid-Pass-C, after the C2 refactor of `apply_llm_ops`, the working tree
showed it as clean and `git diff HEAD` returned nothing — but the file
clearly had the new content via `grep`. Investigation:

```
$ git check-ignore -v plutus_verify/build/llm_fixer.py
.gitignore:9:build/	plutus_verify/build/llm_fixer.py
```

The `.gitignore` rule `build/` (no leading slash) matches a directory
named `build` at **any depth**. Its legitimate target is the
setuptools/distutils artifact directory at `./build/` (built by
`scripts/release-build.sh`). It was silently excluding
`plutus_verify/build/` and its 5 source files (`__init__.py`,
`dockerfile.py`, `fixers.py`, `llm_fixer.py`, `runner.py`) since they
were first written. **Anyone cloning the repo fresh would have been
missing the entire build stage of the pipeline** — even though it's
load-bearing for `plutus-verify` end-to-end.

The Pass A commit message claimed `build/llm_fixer.py` was updated as
part of A1. In reality, that file's edits never made it into a commit
because the file wasn't tracked.

After consulting on the resolution, the chosen path was **rename to
remove the collision**:

- `plutus_verify/build/` → `plutus_verify/builder/`
- Updated imports in [`plutus_verify/__main__.py`](../../plutus_verify/__main__.py), [`plutus_verify/spec/runtime/dockerfile_gen.py`](../../plutus_verify/spec/runtime/dockerfile_gen.py), all four internal `builder/*.py` cross-imports, and the three test files (`test_build_llm_fixer.py`, `test_build_fixers.py`, `test_build_retry.py`).
- `pyproject.toml` package discovery is wildcard (`plutus_verify*`), so the rename is picked up automatically.
- `.gitignore` was left alone — the rename removes the collision permanently. The rule `build/` now matches only the legitimate top-level artifact dir.
- The A1 strip-fences consolidation and the C2 read-once refactor of `apply_llm_ops` both landed cleanly as part of the Pass C commit, since the renamed `builder/` is properly tracked.

Test filenames (`test_build_*.py`) were kept — they describe the *stage*
of the pipeline, not the *package directory*. Renaming them would
muddy git history for no semantic gain.

## What didn't land vs. the original plan

Four items were skipped after on-the-ground inspection contradicted the
diagnostic agents' confidence:

- **A4** (shared SubprocessRunner) — three injectors with genuinely different return types; no clean abstraction.
- **C1** (slim README) — all four LLM templates substantively need the full README; no safe slice exists.
- **C3** (batch chart vision) — behavior-affecting prompt refactor; requires real-LLM validation.
- **C4** (hoist plan.json read) — call sites are mutually exclusive elif arms, not redundant.

Each was committed-message-documented with its rationale rather than
silently dropped. This is the simplify skill's "if a finding is a false
positive, note it and move on" guidance — and a reminder that
diagnostic agents are good at flagging surface patterns but can
overstate without verifying against actual code paths.

The remaining six low-impact items (#12–#17 in the original diagnostic
— `except Exception` narrowing, TOCTOU `if path.exists()`, dead Call-5
stub, stdout streaming, deeply-nested plan-schema literal,
`_locate_file_regex` per-metric recompile) were already explicitly
deferred in the plan's "Out of scope" section.

## Branch state at end of pass

- `refactor` branch, three new commits since `75cd6ee` (the prior `Reorganized docs` commit)
- 493 tests passing, 0 xfailed, 0 skipped
- `run_pipeline`: 538 → 363 lines
- `plutus_verify/pipeline.py`: 951 → 1016 lines (orchestrator slimmed; extracted helpers added their own signatures + docstrings — net slight grow)
- Net code reduction is offset by **+874 lines of newly-tracked `plutus_verify/builder/` source code** that was previously gitignored
- New modules: `plutus_verify/constants.py`, `plutus_verify/util/json_io.py`, `plutus_verify/util/llm_parsing.py`
- Directory rename: `plutus_verify/build/` → `plutus_verify/builder/`

## Suggested follow-ups (none in scope of this pass)

- **Verify the build stage end-to-end against a real Docker build** now that the source files are tracked. The unit tests covered the logic, but a fresh-clone-then-`plutus-verify` smoke test confirms the rename didn't break any indirect import path.
- **Consider Anthropic prompt caching for the 4 extract LLM calls** if/when the project moves off Gemma vLLM. The full README is sent four times per extraction — with cache control, calls 2–4 would only pay the cache-read price.
- **Open a tracked issue for the C3 vision batching idea** with a clear before/after timing requirement and a "guard with a feature flag" rollout plan.
- **Replace the legacy `plutus transfer` consumer of `extract.plan.NINE_STEP_KEYS`** so the re-export shim in `extract/plan.py` can be dropped (the constants.py canonical source already exists).

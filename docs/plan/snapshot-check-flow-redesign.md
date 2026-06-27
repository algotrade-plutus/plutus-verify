---
title: Snapshot/Check flow — read-only verify + in-container snapshot
feature: snapshot-check-flow
status: implemented (L1 + L2 landed; both decisions resolved)
date: 2026-06-27
updated: 2026-06-28
origin: 9-step dogfood handoff → verify-session deliberation
---

# Snapshot / Check Flow — Redesign Plan

> **What this is.** A design record + proposal for the `plutus snapshot` / `plutus check`
> data flow. It started as a 9-step dogfood brief (2 limitations + 1 design question) and
> became a full deliberation. This doc captures the verified mechanics, the reasoning, the
> agreed direction, and the (now-resolved) decisions. Implementation is **complete** —
> see §12 for the as-built summary.

## TL;DR — what we concluded

1. **Keep `.plutus/expected/`** as the frozen groundtruth. The single-folder idea
   ("committed `result/` is the groundtruth") was explored and **rejected** — see §6.
2. The real defects are two narrow command-semantics bugs, not the folder split:
   - **L1** — `snapshot` can't run the container (`--no-run` forced) → baselines are
     captured from the **laptop**, but `check` verifies in the **container**. Env mismatch.
   - **L2** — `check` **overwrites** `result/` with the container's output → verification
     mutates the working tree; `check` is not read-only.
3. Fixing L1 + L2 collapses the mental model to **two verbs** over **three stores**:
   - **`snapshot` = bless** (runs in the container; writes groundtruth: metric *numbers* →
     manifest, artifact *files* → `.plutus/expected/`; also drops a human-facing `result/`).
   - **`check` = verify** (read-only; regenerate into `.plutus/results/`, diff against groundtruth).
   - The three stores: **`.plutus/expected/`** = committed, snapshot-only groundtruth (the
     database); **`.plutus/results/`** = ephemeral per-run harvest buffer, written by *both* verbs,
     **gitignored**; **`result/`** = committed, snapshot-only human-facing view (the UI).
4. **Both decisions are now resolved** (see §10): (1) inter-step output propagation =
   thread harvested outputs forward via `.plutus/results/` (option a); (2) `snapshot` **does**
   write a human-facing `result/`. Both fall out of naming the harvest buffer `.plutus/results/`.

---

## 1. Origin / context

Dogfooded on **unmodified plutus-verify 0.4.3** while building a 9-step strategy repo: a
per-fill **transaction log** as a `byte_exact` CSV artifact (in_sample + out_of_sample) plus
committed chart SVGs shown in the README. It **works today** — `plutus check` exits 0 twice,
trade logs verify `byte_exact`, no framework changes needed. The notes below are two friction
points and one design question that surfaced. All code refs are against
`plutus-automation-scoring` as currently checked out (0.4.3).

---

## 2. Current flow (verified, as-is)

1. `populate_staging(cwd → temp staging)` filtered by `.dockerignore` + `step.inputs` — the
   run does **not** bind-mount cwd (`spec/runtime/staging.py:29`; header cites the
   Group09-BuyHighSellLow runtime-mount leak that motivated per-step staging in 0.2.10).
2. Build image, `runner.run(cwd=staging)` — the step writes its outputs +
   `.plutus/run/<step>/results.json` **inside staging** (`orchestrator.py:256-266`).
3. `extract_outputs(staging, repo_path, step)` copies back to the **working tree**: always
   `.plutus/run/<step>/`, plus **every file matching `step.outputs`** → overwrites
   `result/...` (`spec/runtime/staging.py:56-86`).
4. Compare (`orchestrator.py:400-401`):
   ```python
   expected_path = expected_root / er.step_id / r.path   # .plutus/expected/...  ← groundtruth
   produced_path = repo_path / r.path                     # result/...  (just overwritten in step 3)
   ```
   `byte_exact` / `json_numeric` missing reference = **FAIL**; `visual_similarity` missing =
   **SKIP** (`spec/runtime/artifact_compare.py`).

### 2.1 There are two verification channels (key clarification)

A frequent point of confusion: the groundtruth lives in **two different stores**, by type.

| Channel | Produced by | Groundtruth store (committed) | Compared in `check` |
|---|---|---|---|
| **Metrics (numbers)** | the SDK block `pv.step(...).metric(...)` → `.plutus/run/<step>/results.json` | **`manifest.yaml`** (`expected.metrics[].value` + tolerance) | results.json value within tolerance of the manifest value |
| **Artifacts (files)** | your code writes a file (e.g. `result/trades.csv`); declared in `expected.artifacts[]` with a compare mode | **`.plutus/expected/<step>/<path>`** (frozen file copy) | produced file vs the `.plutus/expected/` file (byte_exact / json_numeric / visual) |

So `result/` is **not** a special framework dir — it's just wherever the author's declared
outputs happen to live. `.plutus/expected/` is **not** authored by hand — `snapshot` *copies*
the produced files into it. After `snapshot` + commit, the **same bytes exist twice**:
`result/trades.csv` (human-facing, README-linked) and
`.plutus/expected/in_sample/trades.csv` (frozen baseline). That duplication is the smell that
kicked off the design question. (Git content-addresses identical blobs, so the cost is
working-tree clutter + conceptual confusion, not repo bloat.)

---

## 3. Limitation 1 — `snapshot` baselines from the **laptop**, not the container

**Mechanics.** The `snapshot` CLI hard-blocks the in-container path:
```python
# __main__.py:481
if not no_run:
    echo("error: running check before snapshot requires --no-run for now (real builder not wired)")
    exit(3)
res = scaffold_snapshot(repo_path, run_check_first=False, ...)
```
`scaffold_snapshot` **already supports** `run_check_first=True` (it takes `image_builder` /
`runner`, `scaffold/snapshot.py:30-58`, and even **defaults** it to `True`) — the CLI just
never wires them and forces `--no-run`. So the only reachable path copies **host-disk** outputs
into `.plutus/expected/` (`scaffold/snapshot.py:63-102`, `src = repo_path / output`).

**Impact.** A `byte_exact` baseline = whatever the author's **laptop** produced, while `check`
runs in the **container** and does a literal byte compare. It passes only if
`laptop bytes == container bytes`. Safe for artifacts that are pure functions of committed
inputs + pinned formatting (e.g. a CSV under `uv sync --frozen`), fragile for everything else —
and the author must *reason* about the equivalence rather than the tool guaranteeing it.

**Fix (L1).** Wire `run_check_first=True` into the `snapshot` CLI (construct
`make_image_builder()` + `DockerRunner()` exactly as the `check` command does at
`__main__.py:409-421`) so baselines are captured from the same container `check` reproduces.

**Unlocks.**
- `byte_exact` **charts** (promote from `visual_similarity` SKIP → exact) — SVG/PNG bytes
  depend on the matplotlib/freetype/zlib build.
- `byte_exact` **binary artifacts**: cleaned `*.parquet`, `model.pkl`, `*.npy` (layout depends
  on the lib build → a local baseline ~never matches the container).
- Correct baseline regeneration from **any machine / CI** (Windows/ARM/teammate who skipped the
  locked env).
- Non-Python steps (R, compiled binaries) where the local toolchain ≠ container.

---

## 4. Limitation 2 — `check` overwrites the working tree with the container's outputs

**Mechanics.** `extract_outputs` copies every `step.outputs` match from staging back over the
author's `result/...` files (`spec/runtime/staging.py:72-86`). So a *verification* action
mutates the working tree.

**Impact.** Any declared output that isn't byte-identical between the local commit and the
container render shows up as a git modification after **every** `check`: a rasterized/timestamped
README chart churns on each run, real diffs are harder to spot, and `check` is not read-only.
(Worked around in the dogfood by making charts pure-vector + deterministic so the bytes match.)

**Fix (L2).** Write produced artifact files to a **per-step buffer** (`.plutus/results/<step>/`)
instead of overwriting `result/`, and point `produced_path` at that buffer. `check` becomes
read-only w.r.t. the working tree. (Only the declared `step.outputs` *files* move; the metrics
channel's `.plutus/run/<step>/results.json` is unaffected — see §7.2.)

**Caveat (the load-bearing subtlety).** The current writeback is **also the inter-step data
bus**: each step runs in a fresh staging copy populated from the working tree, so today step N's
output is copied back to cwd precisely so step N+1's staging picks it up
(`orchestrator.py` `_run_step` → `populate_staging(repo_path, …)`). So L2 cannot *blanket*
remove the writeback — it must decide how a later step gets an earlier step's output (see §10,
Decision 1).

**Unlocks.**
- Commit **any** README chart (rasterized, timestamped, hand-annotated) without git noise.
- `check` is **read-only** — safe in CI / pre-commit / while editing; no spurious diffs.
- Diff "produced this run" vs "committed reference" side-by-side for drift debugging (today the
  produced file overwrites the reference, so you lose the "before").

---

## 5. The design question — why is `.plutus/expected/` separate from `result/`?

Initial read: the standard golden-file split — the reference must be **frozen and separate**
because `check` regenerates the live output; comparing the just-written file to itself would be
vacuous. The two are also **entangled with L2**: because `check` overwrites `result/`, `result/`
*can't* be the frozen reference → hence a separate `.plutus/expected/`. That entanglement
suggested a **single-folder** model might be viable once L2 is fixed (committed `result/` *is*
the groundtruth, compared against the sandbox). §6 is where we worked out whether that holds.

---

## 6. Deliberation — single-folder vs two-folder (and why we keep `.plutus/expected/`)

### 6.1 The single-folder idea
If `check` no longer overwrites `result/` (L2), then `result/` could stay frozen and *be* the
reference: committed `result/` = groundtruth, produced output → sandbox, compare the two. No
`.plutus/expected/`, no duplication.

### 6.2 Why it fails — the invariant
> **The groundtruth must be written *only* by `snapshot`.**

That's what makes "blessed" an explicit, detectable act. Two failure cases prove `result/`
can't satisfy it, because **ordinary local runs write to `result/`**:

- **Author never snapshots.** If the groundtruth is a snapshot-only store, "never snapshotted"
  = the store is empty → `check` fails with *"no blessed reference."* The **absence is the
  signal** (this is already today's behavior: missing reference = FAIL). With `result/` as the
  groundtruth, a plain run already populated it, so there's no way to tell "blessed" from
  "incidental last-run output" — and a forgotten snapshot can silently pass.
- **Author changes code, forgets to re-snapshot.** With a frozen store, `check` regenerates,
  mismatches the frozen reference, and **fails on purpose** — *"output drifted from what you
  blessed; re-snapshot if intended."* That's the feature, not a bug. With `result/` as the
  groundtruth, a local run already overwrote it to match the new code, so the drift goes
  undetected.

So the two "problems" with single-folder are really **proof that a snapshot-only frozen store
is necessary** — and `.plutus/expected/` is exactly that store.

### 6.3 The actual root cause
Not "two folders." The root is that **today the implementation forces the author to
hand-mediate the two folders**:
1. `snapshot` can't run the container (`--no-run`), so the author must run code first to make
   `result/`, then snapshot copies `result/` → `.plutus/expected/` (L1).
2. `check` overwrites `result/`, so `result/`'s identity is corrupted — sometimes "my output,"
   sometimes "the last check's output" (L2).

That manual shuffling is the confusion — not the existence of a reference folder. Fix the two
command semantics and `.plutus/expected/` becomes **internal plumbing `snapshot` manages**; the
author only ever touches two verbs.

### 6.4 Conclusion
**Keep `.plutus/expected/` as the snapshot-only frozen groundtruth. Drop the single-folder
idea.** The remaining work is L1 + L2 (the §10 decisions are now resolved — see §10). Note the
naming trap this clears up: `.plutus/expected/` is the groundtruth/database, **not**
`.plutus/results/`. The latter is the ephemeral per-run buffer written by every `check`, so it
*cannot* be the snapshot-only groundtruth; it's the "produced this run" scratch area. Duplication
with `result/` is accepted (Decision 2 = yes) and git-deduped regardless.

---

## 7. The proposal

### 7.1 The reframe that drives everything
> **`snapshot` and `check` are the *same pipeline run* with a different final verb.**
> Both: build the image → run every step in a sandbox → harvest each step's produced metrics +
> files. Then `snapshot` **writes** them as groundtruth (bless); `check` **compares** them to
> groundtruth (verify).

Decide `snapshot`'s produce-machinery and you've decided `check`'s too (they're identical up to
the last move). That's why `snapshot` is specced first (§8).

### 7.2 The two-verb model (target end-state)
- **`snapshot` = bless** — runs in the container; harvests each step's output into
  `.plutus/results/`, then writes the groundtruth: metric *numbers* → `manifest.yaml`, artifact
  *files* → `.plutus/expected/`, plus a human-facing copy → `result/`. The **only** way to bless.
- **`check` = verify** — read-only w.r.t. the working tree; regenerate into `.plutus/results/`,
  diff against the frozen groundtruth (numbers in the manifest + files in `.plutus/expected/`).
  Never writes `.plutus/expected/`, `result/`, or any tracked file.

#### The three stores

| Store | Role | Written by | Committed |
|---|---|---|---|
| `.plutus/expected/<step>/…` | groundtruth / database (frozen baseline files) | **`snapshot` only** | yes |
| `manifest.yaml` `expected.metrics[].value` | groundtruth / database (frozen baseline numbers) | **`snapshot` only** | yes |
| `.plutus/results/<step>/…` | per-run harvest buffer + inter-step bus ("produced this run") | `snapshot` **and** `check` | **no — gitignored** |
| `result/…` | human-facing view for the README (the UI) | `snapshot` only | yes |

#### What gets compared

| | Groundtruth (committed, snapshot-only) | Produced by `check` | Compared |
|---|---|---|---|
| **Numbers** | `manifest.yaml` `expected.metrics[].value` | `.plutus/run/<step>/results.json` *(unchanged)* | within tolerance |
| **Files** | `.plutus/expected/<step>/…` | `.plutus/results/<step>/…` | byte_exact / json_numeric / visual |

> **Naming guard.** It is tempting to call `.plutus/results/` "the groundtruth," but it is written
> by *every* `check`, so it can't be the snapshot-only baseline. The database is
> `.plutus/expected/` (+ the manifest numbers); `.plutus/results/` is scratch; `result/` is the UI.

> **Scope guard (the metrics channel is untouched).** Only artifact *files* move to
> `.plutus/results/`. Metric *numbers* keep flowing through `.plutus/run/<step>/results.json` (the
> SDK writes it, `extract_outputs` returns it, `_compare_metrics` and the snapshot metric-bless
> read it) — that path already works and is orthogonal to L1/L2. Both `.plutus/run/` and
> `.plutus/results/` are wiped at the start of every run so a stale prior-run file can never
> produce a false-positive comparison or get blessed.

---

## 8. `plutus snapshot` — detailed proposed behavior

**Pre:** repo with manifest + instrumented code + committed source data; Docker available.

1. **Load & validate** the manifest.
2. **Build the image** from `env` (pinned uv + lockfile) — the *same* builder `check` uses.
   This is what makes the baseline match the verification environment (kills L1's fragility).
3. **Run the pipeline**, steps in dependency order. For each step:
   - a. fresh **sandbox** dir;
   - b. **populate** it = committed tree (filtered by `.dockerignore` + `step.inputs`)
     **＋ earlier steps' `.plutus/results/`** ← *the inter-step bus (Decision 1 = option a)*;
   - c. **run** the step's command in the container;
   - d. the step writes, inside the sandbox: `.plutus/run/<step>/results.json` (metrics, via the
     SDK) + its declared `step.outputs` files;
   - e. **harvest** from the sandbox: `.plutus/run/<step>/` (bookkeeping + results.json) back to
     cwd as today, and each declared `step.outputs` file into the retained per-step buffer
     `.plutus/results/<step>/`. *(Nothing is written to `result/` or `.plutus/expected/` yet.)*
4. **Bless** — gated on *all required steps exited 0* (refuse to bless a failing run, as today
   at `scaffold/snapshot.py:54-58`):
   - **Metrics:** for each `expected` step, read its `.plutus/run/<step>/results.json` → write the
     values into `manifest.yaml` (`expected.metrics[].value`). *(Already implemented; source path
     unchanged.)*
   - **Artifacts:** copy each harvested output from `.plutus/results/<step>/` →
     `.plutus/expected/<step>/<path>`.
   - **Human-facing (Decision 2 = yes):** also copy each harvested output → `result/<path>` for
     the README. `check` never touches these.
5. **Report:** N files blessed, M metric values written, any missing-output warnings.

**After snapshot, committed:** `manifest.yaml` (frozen numbers) + `.plutus/expected/…` (frozen
files) + `result/…` (README view). `.plutus/results/` is gitignored and left as-is.

**Delta from today's `scaffold_snapshot`:** it must harvest produced files from the **sandbox**
into `.plutus/results/` (step 3e) and bless from there, rather than reading `result/` after
`check` clobbered it. The bless logic (step 4) is already implemented; the changes are the source
of the files (`.plutus/results/` not `repo_path / output`), running the real builder, and the
added `result/` write.

---

## 9. `plutus check` — detailed proposed behavior (mirror of §8)

1. Load & validate the manifest.
2. Build the image (same builder).
3. Run the pipeline, steps in dependency order — **identical to §8 steps 3a–3e** (same sandbox,
   same harvest into `.plutus/results/`, same inter-step bus).
4. **Verify** (instead of bless):
   - **Metrics:** compare each `.plutus/run/<step>/results.json` value to `manifest.yaml`
     `expected.metrics[].value` within tolerance *(source path unchanged)*.
   - **Artifacts:** compare each `.plutus/results/<step>/<path>` produced file to
     `.plutus/expected/<step>/<path>` (byte_exact / json_numeric / visual). Missing reference =
     FAIL (byte/json) / SKIP (visual), as today.
   - **Read-only:** never write `result/` or `.plutus/expected/`. Only `.plutus/results/`
     (gitignored) is touched, so the working tree stays clean.
5. Emit the report; exit 0 / 1 / 2 as today.

---

## 10. Resolved decisions

Both decisions are settled by naming the harvest buffer `.plutus/results/` and treating it as an
ephemeral, gitignored per-run store distinct from the `.plutus/expected/` groundtruth.

### Decision 1 — inter-step output propagation → **(a) thread harvested outputs forward**
When `check` (and `snapshot`) can no longer write `result/`, step N+1 reads step N's output from
**`.plutus/results/`**: after step N is harvested, its `.plutus/results/<step>/` files are fed
into step N+1's sandbox alongside the committed inputs. This reproduces the pipeline end-to-end
and works whether or not the intermediate is committed — the only option that survives the
**first** snapshot (when no committed groundtruth for intermediates exists yet).

`snapshot` and `check` use the **same** mechanism (verify the way you blessed). `result/` is
**never** the inter-step channel — that role lives in `.plutus/results/`.

*(Rejected — (b) each step reads committed inputs only:* simpler, but step N+1 would see the
*committed* intermediate, not step N's fresh output, and it breaks the first snapshot for any
not-yet-committed intermediate. Only viable when every intermediate is committed source data.)

### Decision 2 — does `snapshot` also write `result/`? → **yes**
`snapshot` writes human-facing copies into `result/` for the README (from `.plutus/results/`);
`check` never touches them. The cost is a duplicate of the bytes already in `.plutus/expected/`,
but git content-addresses identical blobs so the on-disk/repo cost is ~nil, and README paths stay
conventional (`result/...`) rather than linking inside a dot-dir. `.plutus/results/` is added to
the framework-managed `.dockerignore` baseline (so it never leaks into the next image build) and
should be gitignored by the strategy author (so verification runs never dirty the working tree) —
see §11.

---

## 11. Implementation notes (decisions resolved)

- `__main__.py` (`snapshot_cmd`, ~:457-499): drop the `--no-run` hard block; construct
  `make_image_builder()` + `DockerRunner()` and call `scaffold_snapshot(run_check_first=True, …)`.
  `--no-run` can remain as an explicit opt-out for the local-bytes path. **(L1)**
- `spec/runtime/staging.py` `extract_outputs` (+ `orchestrator.py` `_run_step`): produced
  `step.outputs` *files* go to **`.plutus/results/<step>/`**, not cwd; `.plutus/run/<step>/`
  bookkeeping (incl. results.json) still returns to cwd unchanged. The harvest is keyed by step
  (`.plutus/results/<step>/<path>`), but injecting an earlier step's output into step N+1's staging
  must remap back to the declared **`<path>`** (step code reads `data/x.parquet`, not
  `.plutus/results/stepN/data/x.parquet`). Populate step N+1's staging from committed inputs **＋
  earlier steps' `.plutus/results/`** (Decision 1 = option a). **(L2)**
- `scaffold/check.py` `scaffold_check` (~:34-36): wipe **`.plutus/results/`** at run start too,
  exactly as `.plutus/run/` is wiped now — a stale prior-run artifact must never be compared or
  blessed. **(P2)**
- `spec/runtime/orchestrator.py` `_compare_artifacts` (~:397-410): `produced_path` reads
  **`.plutus/results/<step>/<path>`** instead of `repo_path / r.path`. `_compare_metrics` is
  **unchanged** (still reads `.plutus/run/<step>/results.json`). **(L2)**
- `scaffold/snapshot.py`: harvest artifact files from **`.plutus/results/`** rather than
  `repo_path / output`; metric-bless still reads `.plutus/run/<step>/results.json` (unchanged);
  files → `.plutus/expected/`, then **additionally copy files → `result/`** (Decision 2 = yes).
- `spec/runtime/real_image_builder.py` `_DOCKERIGNORE_BASELINE` (~:58): add `.plutus/results/`
  alongside `.plutus/run/` — it is the same prior-run ephemera, and must not leak into the next
  image build context. **This does *not* break the inter-step bus**: `populate_staging` filters the
  cwd→staging copy through `.dockerignore` (so the regular copy excludes it — no leak), while
  Decision 1's propagation injects the prior step's `.plutus/results/` into the next sandbox
  *explicitly*, on top of the filtered tree.
- `.gitignore` (strategy repo, **author convention** — the framework does not write user
  `.gitignore`s): authors should ignore `.plutus/results/` so verification runs never dirty the
  working tree, same as `.plutus/run/`.
- `spec/runtime/artifact_compare.py`: unchanged (compare modes are agnostic to where the two
  paths come from).
- Tests: a `manager: uv` integration fixture that builds + runs a step end-to-end (the standing
  gap noted across 0.4.1–0.4.3) would also cover the read-only + harvest behavior.

---

## 12. As-built summary (2026-06-28)

Landed in two increments, TDD throughout; full suite green except one unrelated pre-existing
failure (`test_compare_charts`, fails on clean `main`).

**L1 — in-container snapshot wired.**
- `__main__.py` `snapshot_cmd`: dropped the `--no-run` hard block; without `--no-run` it builds
  `make_image_builder()` + `DockerRunner()` and calls `scaffold_snapshot(run_check_first=True)`.
  `--no-run` remains the local-bytes opt-out (`run_check_first=False`).
- `real_image_builder.py`: `.plutus/results/` added to the `.dockerignore` baseline.

**L2 — read-only verify + `.plutus/results/` harvest.**
- `spec/runtime/staging.py`: `extract_outputs` harvests declared outputs to
  `.plutus/results/<step>/` (was: working-tree root); `.plutus/run/<step>/` bookkeeping still
  returns to cwd. New `stage_prior_results(repo, staging, step)` = the inter-step bus (remaps
  `.plutus/results/<step>/<path>` → `staging/<path>`, respects `step.inputs`). New
  `harvest_committed_outputs` mirrors `artifact_check` (shipped) outputs into the buffer for a
  uniform compare.
- `spec/runtime/orchestrator.py` `_run_step`: clears the per-step buffer; injects the bus after
  `populate_staging`; input preflight now runs against the **staging sandbox** (committed inputs +
  injected intermediates); output preflight runs against `.plutus/results/<step>/`.
  `_compare_artifacts`: `produced_path` reads `.plutus/results/<step>/<path>`. `_compare_metrics`
  unchanged (still `.plutus/run/<step>/results.json`).
- `scaffold/check.py`: wipes `.plutus/results/` at run start (alongside `.plutus/run/`).
- `scaffold/snapshot.py`: with `run_check_first=True`, blesses artifacts from `.plutus/results/`
  into both `.plutus/expected/<step>/` (groundtruth) **and** the working tree (`result/`); with
  `--no-run`, blesses from the author's local outputs as before. Metric-bless unchanged.
- `preflight.py`, `artifact_compare.py`: **unchanged** — call sites just pass a different base path.

**Author follow-up (not framework-enforced):** strategy repos should add `.plutus/results/` to
their `.gitignore` (same as `.plutus/run/`).

---

## Appendix — original brief questions + the answers reached

**Q1. Is `.plutus/expected/` separate deliberately, or just because `check` overwrites
`result/`?** Both, and independently load-bearing. The invariant: the reference is a frozen,
committed, **snapshot-only** baseline that `check` never writes, so the comparison is "live
regeneration vs. immutable baseline," never a file against itself. Beyond the overwrite it buys
step-keyed provenance (`.plutus/expected/<step_id>/…` avoids cross-step path collisions),
curation (only declared outputs are blessed), and a clean git signal (the baseline moves only on
`snapshot`).

**Q2. Is the `extract_outputs` writeback intentional, or could it go to a sandbox?** Intentional
— it's the **inter-step data bus** (step N's output reaches step N+1 through cwd today), not just
inspection. It moves to **`.plutus/results/`** (L2) with the bus role preserved (Decision 1 =
option a: step N+1's sandbox is populated from committed inputs + earlier steps' `.plutus/results/`);
a blanket redirect would break multi-step pipelines.

**Q3. Is in-container `snapshot` on the roadmap? What blocks "real builder not wired"?** It's
intended (the function defaults `run_check_first=True`); the CLI just doesn't wire
`image_builder`/`runner`. Small, well-defined work — `check` already constructs them. Coupling:
with L2, in-container snapshot must read produced bytes from **`.plutus/results/`**, not cwd.

**Q4. Would a single-folder model be acceptable?** No — the reference/produced distinction is
intrinsic to golden-file verification, and the groundtruth must be snapshot-only (§6.2). Keep
`.plutus/expected/`; pursue L1 + L2 instead. (A true "single folder" is really a *relocation* of
the split, not its elimination, and `result/` is the wrong survivor because ordinary runs write
to it.)

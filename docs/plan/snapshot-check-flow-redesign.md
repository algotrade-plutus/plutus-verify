---
title: Snapshot/Check flow — read-only verify + in-container snapshot
feature: snapshot-check-flow
status: proposed (design agreed; two decisions open)
date: 2026-06-27
origin: 9-step dogfood handoff → verify-session deliberation
---

# Snapshot / Check Flow — Redesign Plan

> **What this is.** A design record + proposal for the `plutus snapshot` / `plutus check`
> data flow. It started as a 9-step dogfood brief (2 limitations + 1 design question) and
> became a full deliberation. This doc captures the verified mechanics, the reasoning, the
> agreed direction, and the two decisions still open. Implementation has **not** started.

## TL;DR — what we concluded

1. **Keep `.plutus/expected/`** as the frozen groundtruth. The single-folder idea
   ("committed `result/` is the groundtruth") was explored and **rejected** — see §6.
2. The real defects are two narrow command-semantics bugs, not the folder split:
   - **L1** — `snapshot` can't run the container (`--no-run` forced) → baselines are
     captured from the **laptop**, but `check` verifies in the **container**. Env mismatch.
   - **L2** — `check` **overwrites** `result/` with the container's output → verification
     mutates the working tree; `check` is not read-only.
3. Fixing L1 + L2 collapses the mental model to **two verbs**:
   - **`snapshot` = bless** (runs in the container; writes groundtruth: metric *numbers* →
     manifest, artifact *files* → `.plutus/expected/`).
   - **`check` = verify** (read-only; regenerate in a sandbox, diff against groundtruth).
4. **Two decisions remain open** (see §10): (a) inter-step output propagation, and
   (b) whether `snapshot` also writes a human-facing `result/`.

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

**Fix (L2).** Write produced outputs to a **sandbox** (e.g. `.plutus/run/<step>/outputs/`)
instead of overwriting `result/`, and point `produced_path` at the sandbox. `check` becomes
read-only w.r.t. the working tree.

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
idea.** The remaining work is L1 + L2 (+ the §10 decisions). Duplication with `result/` becomes
optional (see Decision 2) — and git-deduped regardless.

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
- **`snapshot` = bless** — runs in the container; writes the groundtruth: metric *numbers* →
  `manifest.yaml`, artifact *files* → `.plutus/expected/`. The **only** way to bless.
- **`check` = verify** — read-only; regenerate in a sandbox, diff against the frozen groundtruth
  (numbers in the manifest + files in `.plutus/expected/`). Never writes the working tree.

| | Groundtruth (committed, snapshot-only) | Produced by `check` | Compared |
|---|---|---|---|
| **Numbers** | `manifest.yaml` `expected.metrics[].value` | `results.json` (ephemeral, in sandbox) | within tolerance |
| **Files** | `.plutus/expected/<step>/…` | sandbox copy | byte_exact / json_numeric / visual |

---

## 8. `plutus snapshot` — detailed proposed behavior

**Pre:** repo with manifest + instrumented code + committed source data; Docker available.

1. **Load & validate** the manifest.
2. **Build the image** from `env` (pinned uv + lockfile) — the *same* builder `check` uses.
   This is what makes the baseline match the verification environment (kills L1's fragility).
3. **Run the pipeline**, steps in dependency order. For each step:
   - a. fresh **sandbox** dir;
   - b. **populate** it = committed tree (filtered by `.dockerignore` + `step.inputs`)
     **＋ [outputs of earlier steps in this run]** ← *the propagation slot — Decision 1*;
   - c. **run** the step's command in the container;
   - d. the step writes, inside the sandbox: `.plutus/run/<step>/results.json` (metrics, via the
     SDK) + its declared `step.outputs` files;
   - e. **harvest** from the sandbox into a retained per-step area (e.g.
     `.plutus/run/<step>/outputs/`): the results.json + each declared output file.
     *(Nothing is written to `result/` here.)*
4. **Bless** — gated on *all required steps exited 0* (refuse to bless a failing run, as today
   at `scaffold/snapshot.py:54-58`):
   - **Metrics:** for each `expected` step, read its harvested results.json → write the values
     into `manifest.yaml` (`expected.metrics[].value`). *(Already implemented.)*
   - **Artifacts:** copy each harvested declared output → `.plutus/expected/<step>/<path>`.
   - *(Optional — Decision 2)* also drop a human-facing copy into `result/` for the README.
5. **Report:** N files blessed, M metric values written, any missing-output warnings.

**After snapshot, committed:** `manifest.yaml` (frozen numbers) + `.plutus/expected/…` (frozen
files) [+ optional `result/…`].

**Delta from today's `scaffold_snapshot`:** it must harvest produced files from the **sandbox**
(step 3e) rather than reading `result/` after `check` clobbered it. The bless logic (step 4) is
already implemented; the change is the source of the files + running the real builder.

---

## 9. `plutus check` — detailed proposed behavior (mirror of §8)

1. Load & validate the manifest.
2. Build the image (same builder).
3. Run the pipeline, steps in dependency order — **identical to §8 steps 3a–3e** (same sandbox,
   same harvest, same propagation slot).
4. **Verify** (instead of bless):
   - **Metrics:** compare each harvested results.json value to `manifest.yaml`
     `expected.metrics[].value` within tolerance.
   - **Artifacts:** compare each harvested produced file to `.plutus/expected/<step>/<path>`
     (byte_exact / json_numeric / visual). Missing reference = FAIL (byte/json) / SKIP (visual),
     as today.
   - **Read-only:** never write `result/` or `.plutus/expected/`.
5. Emit the report; exit 0 / 1 / 2 as today.

---

## 10. Open decisions

### Decision 1 — inter-step output propagation (the §4 caveat, now front-and-center)
When `check` (and `snapshot`) can no longer write `result/`, how does step N+1 read step N's
output? `snapshot` constrains this more than `check`: **on the first bless there is no committed
groundtruth for intermediates yet**, so a derived-but-uncommitted intermediate *must* come from
the earlier step's freshly harvested output.

- **(a) Thread harvested outputs forward** — after step N runs, feed its harvested
  `step.outputs` into step N+1's sandbox (alongside committed inputs). Reproduces the pipeline
  end-to-end; works whether or not the intermediate is committed. More plumbing. **Superset —
  the only option that always works for the first snapshot.**
- **(b) Each step reads committed inputs only** — simpler, but step N+1 sees the *committed*
  intermediate, not step N's fresh output; impossible for a not-yet-committed intermediate
  (breaks the first snapshot). Only viable when every intermediate is committed source data
  (e.g. Tier-1 shipped CSVs).

Whatever is chosen, `snapshot` and `check` must use the **same** mechanism (verify the way you
blessed), and `result/` is **never** the inter-step channel — that role moves into the
sandbox/harvest area.

### Decision 2 — does `snapshot` also write `result/`?
- **No `result/`:** `.plutus/expected/` is the only file store; README links into it. Zero
  duplication; slightly less conventional README paths (linking inside a dot-dir).
- **Yes `result/`:** `snapshot` writes human-facing copies for the README; `check` never touches
  them. Convenience, at the cost of the (git-deduped) duplicate.

---

## 11. Implementation notes (once the decisions land)

- `__main__.py` (`snapshot_cmd`, ~:457-499): drop the `--no-run` hard block; construct
  `make_image_builder()` + `DockerRunner()` and call `scaffold_snapshot(run_check_first=True, …)`.
  `--no-run` can remain as an explicit opt-out for the local-bytes path. **(L1)**
- `spec/runtime/staging.py` `extract_outputs` (+ `orchestrator.py` `_run_step`): produced
  `step.outputs` go to a sandbox/harvest area, not cwd; `.plutus/run/<step>/` bookkeeping still
  returns. Implement Decision 1's propagation here. **(L2)**
- `spec/runtime/orchestrator.py` `_compare_artifacts` (~:397-410): `produced_path` reads the
  harvest area instead of `repo_path / r.path`. **(L2)**
- `scaffold/snapshot.py`: harvest produced files from the sandbox/harvest area rather than
  `repo_path / output`. Bless logic (metrics → manifest, files → `.plutus/expected/`) unchanged.
- `spec/runtime/artifact_compare.py`: unchanged (compare modes are agnostic to where the two
  paths come from).
- Tests: a `manager: uv` integration fixture that builds + runs a step end-to-end (the standing
  gap noted across 0.4.1–0.4.3) would also cover the read-only + harvest behavior.

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
inspection. It can move to a sandbox (L2) but the bus role must be preserved (Decision 1); a
blanket redirect would break multi-step pipelines.

**Q3. Is in-container `snapshot` on the roadmap? What blocks "real builder not wired"?** It's
intended (the function defaults `run_check_first=True`); the CLI just doesn't wire
`image_builder`/`runner`. Small, well-defined work — `check` already constructs them. Coupling:
with L2, in-container snapshot must read produced bytes from the **sandbox/harvest area**, not
cwd.

**Q4. Would a single-folder model be acceptable?** No — the reference/produced distinction is
intrinsic to golden-file verification, and the groundtruth must be snapshot-only (§6.2). Keep
`.plutus/expected/`; pursue L1 + L2 instead. (A true "single folder" is really a *relocation* of
the split, not its elimination, and `result/` is the wrong survivor because ordinary runs write
to it.)

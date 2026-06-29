---
name: plutus-transform
description: Use when restructuring a trading-research repo into the canonical installable Python project — recognises phrases like "transform this into the canonical project", "restructure into a src/ layout", "make this an installable package", "convert flat scripts to a package", "canonicalize this repo", "add console scripts / pyproject / uv". OPTIONAL and separate from the standard chain (standardize → scoring → document): it reshapes code, not the manifest's verification contract. Detects `.plutus/manifest.yaml` — if present, re-wires the env + step commands and re-greens `plutus check` + re-snapshots; if absent, leaves canonical code ready for a later `plutus-standardize`.
---

# plutus-transform

Restructure a flat / script-based trading-research repo into the **canonical installable Python project**: a `src/<pkg>/` package with console-script entry points, a uv-locked environment, package-qualified imports, and a minimal test suite — the shape defined in [`references/canonical-layout.md`](references/canonical-layout.md). Anchored on the package installing + importing cleanly, the console scripts running under `uv run`, and (when the repo is already Plutus-compliant) `plutus check .` staying green after the move.

This skill is **optional and orthogonal** to the standard chain ([`plutus-standardize`](../plutus-standardize/SKILL.md) → [`plutus-scoring`](../plutus-scoring/SKILL.md) → [`plutus-document`](../plutus-document/SKILL.md)). Those make a repo *verifiable*; this one makes the *code* canonical. It does not author a manifest from scratch, instrument scripts with `pv.step`, or score — it reshapes layout and packaging and, if a manifest already exists, keeps it green.

The workflow runs six phases (Pre-flight → Survey → Decide → Restructure → Re-wire manifest → Verify), then Phase 6 (Consolidate knowledge — silent unless this session deviated from the documented workflow), then a hand-off **offer** (never an auto-chain). **Detect & adapt**: Phase 4 (manifest re-wire) and the `plutus check`/`snapshot` half of Phase 5 run **only if `.plutus/manifest.yaml` is present**; on a manifest-less repo the gate is uv + pytest only. Phase 2 is the only interactive phase. `env.install_project` requires `plutus-verify` 0.4.6+ — gate on it in Pre-flight.

## Pre-flight (before Phase 1)

1. Confirm target repo path. Default to CWD; accept an explicit path argument.
2. **Require a git repo with a clean working tree.** Phase 3 is a heavy `git mv` / delete pass; uncommitted work muddies the reviewable diff and risks loss.
   - Not a git repo (`git rev-parse --is-inside-work-tree` fails): `git init` + `git add -A && git commit -m "initial state before canonical transform"`.
   - Dirty tree: stop and ask the maintainer to commit or stash first. Do not proceed over uncommitted changes.
3. Confirm `uv` is on PATH (`uv --version`) and the target is a Python project (has `*.py` and/or a `pyproject.toml`).
4. **Detect `.plutus/manifest.yaml`.** Its presence sets the *adapt* branch — Phase 4 and the plutus half of Phase 5 run only when it exists. If present, probe the SDK version: `python -c "import plutus_verify; print(plutus_verify.__version__)"`. `env.install_project` (used in Phase 4) **requires 0.4.6+**; on an older SDK, surface the constraint and either upgrade the dev install or stop before Phase 4. plutus-verify is **not on PyPI** — install from the GitHub release wheel (see [`plutus-standardize` Pre-flight](../plutus-standardize/SKILL.md) for the `$WHL` snippet); never a PyPI name, never a guessed local path.
5. **Already canonical?** If Phase 1 will find a `src/<pkg>/` layout *and* `[project.scripts]` *and* a committed `uv.lock`, there is nothing to do — report it and stop. Do not churn a repo that is already in canonical shape.

## Phase 1 — Survey

Dispatch parallel `Explore` subagents (single message, multiple `Agent` calls):

- **Layout & import graph**: every top-level `*.py`, every loose top-level package dir (`config/`, `database/`, `metrics/`, `filter/`, …), any existing `src/`. Build the intra-project import graph (who imports whom). Mark each entry script — those with an `if __name__ == "__main__":` block.
- **Classification**: split modules into **entry scripts** (have `__main__`), **library modules** (imported by others), **orphans** (imported by nothing, no `__main__`), and **residue/empty dirs** (no tracked `.py`, often left over from abandoned subsystems).
- **Collisions & landmines**: name collisions (a `foo.py` module shadowed by a `foo/` package, or vice-versa — see GT2); a `.gitignore` that ignores `__init__.py` or `.python-version` (GT1); `requirements.txt` alongside or instead of `pyproject.toml`; whether a committed `uv.lock` exists; presence of `tests/`.
- **Manifest shape** *(only if `.plutus/manifest.yaml` present)*: current `env` block, each step's `command`, and the `inputs`/`outputs`/`expected` paths (which must stay byte-for-byte at repo root after the move).

Synthesize a **Restructure Survey**: current layout, the proposed package name, the entry-script → `main()` → console-script map, the orphan/residue disposition list, the collision list, the dependency/lockfile state, and (if present) the manifest command map. Carry it into Phase 2.

**Exit criteria**: survey present in the conversation; entry/library/orphan/residue classification done; collisions enumerated; manifest command map captured when a manifest exists.

## Phase 2 — Decide

Single `AskUserQuestion` call with the questions from [`references/decision-tree.md`](references/decision-tree.md):

- **T1** — package name: distribution name + import/package name (default derived from the repo/dir name, e.g. `my-strategy` / `my_strategy`).
- **T2** — console-script prefix + entry map: the prefix (e.g. `ms-`, from the package initials) and each entry module → `main()` → script-name binding. Entry modules may be renamed for clarity (`backtesting.py` → `backtest.py`); record the rename.
- **T3** — orphan / residue disposition: per orphan, **delete** or **keep-as-drop-candidate** (moved into the package, flagged, not deleted). Residue/empty dirs are deleted by default.
- **T4** — dependency policy: **upgrade-to-floors** (default — current pins become `>=` floors, `uv lock` resolves latest-compatible) or **preserve pins**. Surface risky majors (numpy/pandas/matplotlib) so the maintainer can veto a specific bump.
- **T5** — Python floor: keep the repo's `requires-python`, or set one explicitly. Default: keep.

Record the answers as a **Decision Block**; quote it back in Phase 6.

**Exit criteria**: T1–T5 on record.

## Phase 3 — Restructure

Sequential, no further user interaction except the boundary asks below. **Use `git mv` for every move** (preserves history — GT5).

1. **Branch isolation** — before any disk writes: `git checkout -b plutus-transform` (fall back to `plutus-transform-<YYYY-MM-DD>` if it exists). Confirm with `git branch --show-current`. All Phase 3–5 edits land here; the maintainer reviews the diff before merging.
2. **Scaffold the package** — create `src/<pkg>/__init__.py` with `"""<one-line description>."""` + `__version__ = "<version>"`, and an empty `__init__.py` for every subpackage (`config/`, `database/`, `metrics/`, …).
3. **Write `pyproject.toml`** from [`references/pyproject-template.toml`](references/pyproject-template.toml): hatchling backend, `[tool.hatch.build.targets.wheel] packages = ["src/<pkg>"]`, deps per T4, `[project.scripts]` per T2, `[dependency-groups] dev = ["pytest>=8", "pylint>=3.3"]`. **`plutus_verify` is never a dependency** (GT6).
4. **Move modules in** — `git mv` each entry script (applying T2 renames) and each library module into `src/<pkg>/` and its subpackages.
5. **Delete residue / dissolve collisions** — `rm -rf` the now-empty residue dirs per T3. Removing an empty shadow package (e.g. `utils/` next to `utils.py`) dissolves the collision (GT2). Orphans kept under T3 move into the package with a `# DROP CANDIDATE: imported by nothing` comment.
6. **Rewrite imports** — every intra-project import becomes absolute and package-qualified: `from config.config import X` → `from <pkg>.config.config import X`; `from backtesting import Backtesting` → `from <pkg>.backtest import Backtesting`. Use the import graph from Phase 1; do not miss transitive ones inside subpackages.
7. **Expose `main()`** — in each entry module, wrap the `if __name__ == "__main__":` body into `def main():` (body unchanged, re-indented), then append a thin guard so both the console script and `python -m <pkg>.<mod>` work (GT8):
   ```python
   if __name__ == "__main__":
       main()
   ```
8. **Drop `requirements.txt`** — `git rm requirements.txt` (uv.lock is the single source of truth — GT9). Leave it only under T4 = preserve-pins *and* the maintainer asks to keep it.
9. **Fix `.gitignore` + pin Python** — remove any `__init__.py` and `.python-version` ignore lines (both must be committed — GT1); keep `__pycache__`, `*.csv`, `.env`, `*venv/`, and the `.plutus/` ephemera lines. Write `.python-version` (the T5 floor).
10. **Add tests** — `tests/__init__.py` (empty) + `tests/test_smoke.py`: assert the package imports + has `__version__`, every entry module imports, and one true unit on a pure helper (see [`references/canonical-layout.md`](references/canonical-layout.md) for the template).

**Boundary asks** (confirm before applying): deleting any source file (orphans under T3 = delete); a `requirements.txt` → uv port that loosens a constraint (T4). Writing `pyproject.toml` / `uv.lock` and the moves themselves are pre-authorized by the Phase 2 decisions.

**Exit criteria**: package scaffolded; all modules under `src/<pkg>/`; residue gone; imports package-qualified; every entry module exposes `main()`; `requirements.txt` removed; `.gitignore` fixed; `tests/` present.

## Phase 4 — Re-wire the manifest

**Runs only if `.plutus/manifest.yaml` is present.** Skip entirely on a manifest-less repo (the hand-off will offer `plutus-standardize`).

1. **`env` block** — set `manager: uv`, `lockfile: uv.lock`, `install_project: true`, `requirements_file: null`. Keep `base: python`; set `python_version` to the T5 floor. `install_project: true` is what makes the container install the repo's own package so its console scripts + `import <pkg>` resolve in step commands (requires 0.4.6+ — gated in Pre-flight).
2. **Step commands** — rewrite each step's `command` to the console script per the T2 map (`python backtesting.py` → `<prefix>-backtest`, etc.). Steps with no command (e.g. `optimization` as `artifact_check`) are unchanged.
3. **Paths unchanged** — leave every `inputs` / `outputs` / `expected` path exactly as-is. `parameter/`, `data/`, `result/` stay at repo root and are cwd-relative (GT3); only commands change.
4. **Validate**:
   ```python
   from plutus_verify.spec.loader import load_manifest
   load_manifest(".plutus/manifest.yaml")   # raises on invalid; errors on install_project if SDK < 0.4.6
   ```

**Exit criteria**: manifest validates; `env` ported to uv + `install_project: true`; commands point at console scripts; paths untouched.

## Phase 5 — Verify (the gate)

1. **Lock + sync** — `uv lock` (resolves per T4; on a conflict, loosen the **one** offending constraint and re-lock — surface it in Phase 6), then `uv sync`.
2. **Install the SDK into the dev venv** *(only if any script does `import plutus_verify`)* — from the GitHub release wheel, **not** PyPI, **not** the repo's `pyproject.toml` (GT6). For a Drive-backed (Tier-2) repo, install the `[runner]` extra so `gdown` is present host-side — into **the venv the `plutus` CLI runs out of**, which for a `uv tool`/pipx install is *not* the project `.venv` (`uv tool install --force "plutus-verify[runner] @ $WHL"`; check with `head -1 $(which plutus)`) (GT10).
3. **Local gate** — always run:
   ```bash
   uv run python -c "import <pkg>; print(<pkg>.__version__)"
   uv run <each cheap console script>     # skip DB-only / long optimizer runs; note which were skipped
   uv run pytest -q
   ```
   Expect imports OK, scripts produce their declared outputs, tests pass. A clean run here confirms collisions are dissolved (the old `ImportError` is dead).
4. **Plutus gate** *(only if manifest present)*:
   ```bash
   plutus check . --secrets-from-env      # confirm exit 0
   plutus snapshot .                       # re-bless baselines under the new env
   git add .plutus/expected .plutus/manifest.yaml result && git commit -m "chore: re-bless baselines after canonical restructure"
   ```
   Re-blessed metric values may shift slightly under T4-upgraded deps — that is **expected**; the new baseline is committed deliberately. On FAIL, match the symptom against [`references/known-gotchas.md`](references/known-gotchas.md); fix layout/manifest-side, never silently widen tolerance.

**Exit criteria**: `uv run` imports + scripts + `pytest` all green; and (manifest present) `plutus check` exits 0 and `plutus snapshot` re-blessed + committed.

## Phase 6 — Consolidate knowledge

**Always runs; silent unless this session required substantive navigation beyond the documented workflow.** Same discipline as `plutus-standardize` Phase 6 — catch divergence worth promoting without filing paperwork on clean runs.

First emit a brief **Restructure summary** (non-interactive): package name, the module-move + rename map, deletions, orphans kept as drop-candidates, the dep policy + any loosened constraint, and the manifest re-wire (or "no manifest — standardize offered next").

Then the divergence check. **Emit a substantive report only if at least one fired**:

- A collision / layout pathology that didn't match GT1–GT10 in [`references/known-gotchas.md`](references/known-gotchas.md) (cost 3+ exchanges to untangle).
- A Phase-2 decision that didn't fit T1–T5 cleanly (improvised option, merged options, new branch).
- A dependency upgrade (T4) that broke the pipeline and needed a non-obvious upper-bound or code fix.
- The `plutus snapshot` re-bless shifted a metric beyond declared tolerance (signal that a dep bump changed results materially, not just jitter).
- The `plutus check` gate took 3+ manifest/layout revisions to reach exit 0.

If **none** fired, emit one line: `Phase 6: no divergence detected — Skill shape worked cleanly for this repo.` Don't write a file.

If **any** fired, write `.plutus/skill-feedback.md` (one section per category: *what happened* / *what the Skill's current shape said* / *draft promotion* — a ready-to-paste GT or T-option). Present the path + a one-paragraph summary; the maintainer decides whether to promote. The Skill does not auto-promote.

**Exit criteria**: summary emitted; then either the one-line "no divergence" or `.plutus/skill-feedback.md` written with the user notified.

## Final step — Hand-off offer (not an auto-chain)

This skill is optional and standalone, so it **offers** the next step rather than auto-invoking it:

- **No manifest** → the repo is now canonical but unverified. Offer `plutus-standardize` (it will set `install_project: true` cleanly against the new package layout, D6).
- **Manifest re-greened** → the run commands changed, so the README's reproduction block is stale. Offer `plutus-document` (refresh the README) and then `plutus-scoring` (re-confirm the rubric score).

State the offer and stop. Do not invoke the next skill without the maintainer's go-ahead.

## Verification before completion

Mechanical checks before declaring done:

- `uv run python -c "import <pkg>"` succeeds; `uv run pytest -q` is green.
- Each declared console script resolves (`uv run python -c "import importlib.metadata as m; print([e.name for e in m.entry_points(group='console_scripts') if e.name.startswith('<prefix>')])"`).
- `requirements.txt` is gone; `uv.lock`, `.python-version`, and every `__init__.py` are tracked (`git ls-files`).
- No name collisions remain (no `foo.py` and `foo/` sharing a name).
- **Manifest present**: `plutus check . --secrets-from-env` exits 0; a second invocation gives the same exit (non-determinism sanity check); `plutus snapshot` re-bless committed.
- Phase 6 produced either the one-line "no divergence" or `.plutus/skill-feedback.md`.

If any check fails, do **not** declare done. Diagnose per `references/known-gotchas.md`.

## Interaction model

- Phase 2 is the only interactive phase. Phases 3–6 run without interruption unless a hard error or a boundary ask appears.
- The "delete source / port deps" boundary requires confirmation: deleting orphan modules (T3 = delete) and loosening a constraint during the uv port (T4). Module moves, the package scaffold, `pyproject.toml`/`uv.lock`, import rewrites, and `main()` extraction are pre-authorized by the Phase 2 decisions.
- All work lands on the `plutus-transform` branch — fully reversible by branch switch. The maintainer reviews the diff before merging to `main`.
- The hand-off is an **offer**, never an auto-chain — this skill is optional and orthogonal to standardize/scoring/document.

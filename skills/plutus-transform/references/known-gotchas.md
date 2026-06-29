# Known gotchas (GT1–GT10)

Failure patterns and landmines specific to canonicalizing a research repo. Phase 1
surfaces them; Phase 3/5 fix them. When a symptom doesn't match anything here, it's a
Phase 6 divergence — draft a GT promotion.

---

## GT1 — `.gitignore` ignores `__init__.py` / `.python-version`

**Symptom**: works locally, breaks in a fresh clone — `ModuleNotFoundError: No module
named '<pkg>.config'`, or the env resolves to the wrong Python. Package markers and the
version pin were never committed.

**Cause**: a `.gitignore` line `__init__.py` (common in repos that scaffold empty
`__init__.py` everywhere) or `.python-version`. The files exist in the working tree but
aren't tracked, so the behavior diverges between local and clone/container.

**Fix**: remove both lines from `.gitignore` (Phase 3 step 9); `git add` every
`__init__.py` and `.python-version`. Verify with `git ls-files | grep __init__`.

---

## GT2 — Name collision: `foo.py` shadowed by `foo/`

**Symptom**: `ImportError: cannot import name '<x>' from 'foo'` even though `foo.py`
clearly defines it. A `foo/` package (often an empty `__init__.py` stub from an abandoned
subsystem) shadows the `foo.py` module on `sys.path`.

**Cause**: both `foo.py` and `foo/` live at the same level; Python resolves the package,
not the module. Classic cases: `utils.py` + `utils/`, `evaluation.py` + `evaluation/`.

**Fix**: deleting the empty shadow dir dissolves the collision. Under the `src/` layout
the module becomes `<pkg>/foo.py` and there is no sibling `foo/`, so the collision can't
recur. This is "delete residue" (T3), not an orphan-module deletion.

---

## GT3 — Moving `parameter/` / `data/` / `result/` into the package

**Symptom**: after the move, `plutus check` FAILs with missing inputs, or scripts write
charts somewhere the manifest doesn't expect.

**Cause**: these dirs are **cwd-relative** and referenced by the manifest's
`inputs`/`outputs`/`expected` paths. The pipeline runs from the repo root (`/work` in the
container). Moving them under `src/<pkg>/` breaks every path.

**Fix**: leave `parameter/`, `data/`, `result/` at repo root. Only *source modules* move
into the package; data/config/output stay put and the manifest paths are unchanged
(Phase 4 step 3). Making them configurable via CLI args is out of scope.

---

## GT4 — `env.install_project` requires plutus-verify 0.4.6+

**Symptom**: `load_manifest` raises a schema error on `env.install_project`, or
`plutus check` ignores it and the console scripts don't exist in-container
(`command not found: <prefix>-backtest`).

**Cause**: the `install_project` field landed in 0.4.6. On an older SDK the field is
unknown (validator error) or unsupported (silently not installed).

**Fix**: gate in Pre-flight — probe `plutus_verify.__version__`; require ≥ 0.4.6 before
Phase 4. If the dev SDK is older, upgrade the dev install from the GitHub release wheel,
or stop before the manifest re-wire.

---

## GT5 — Losing history on the move

**Symptom**: `git log src/<pkg>/backtest.py` shows only one commit; the file's history is
orphaned at the old path.

**Cause**: the module was recreated (Write + delete) instead of moved.

**Fix**: use `git mv` for every relocation (Phase 3 step 4). Git records the rename and
`--follow` traces history across it. Renames + content edits in the same commit can
confuse rename detection — move first (one commit), rewrite imports / extract `main()`
after (a second commit).

---

## GT6 — `plutus_verify` leaking into project dependencies

**Symptom**: `uv lock` tries to resolve `plutus-verify` from PyPI and fails (it's not
published there), or the wheel ships with a hard dependency on the verifier.

**Cause**: scripts `import plutus_verify`, so it's tempting to add it to
`[project.dependencies]`. It must never be there — the verifier **injects** itself into
the container, and a published wheel shouldn't depend on the test harness.

**Fix**: keep `plutus_verify` out of `pyproject.toml` entirely. Install it ad-hoc into the
dev venv only (Phase 5 step 2) from the GitHub release wheel:
`uv pip install "$WHL"`, or run a script with `uv run --with "$WHL" <script>`.

---

## GT7 — Re-bless required after a dependency upgrade

**Symptom**: after T4 = upgrade-to-floors, `plutus check` FAILs metric comparisons — the
numbers shifted slightly under new numpy/pandas/matplotlib.

**Cause**: the committed baseline was blessed under the old deps; latest-compatible
resolution changes floating-point results a little.

**Fix**: this is expected, not a bug. After `plutus check` reaches exit 0 (or to
establish the new baseline), run `plutus snapshot .` to re-bless `.plutus/expected/` +
`result/` under the locked env, then commit deliberately (Phase 5 step 4). If a value
moved *materially* (beyond plausible jitter), that's a Phase 6 divergence — a dep bump
changed strategy results, surface it.

---

## GT8 — Console script with no `main()`

**Symptom**: `uv run <prefix>-backtest` → `ImportError: cannot import name 'main'`, or the
script's logic sits at module top-level and runs on *import* (so `import <pkg>.backtest`
executes the whole backtest).

**Cause**: the entry script kept its `if __name__ == "__main__":` body but `[project.scripts]`
points at `<pkg>.backtest:main`, which doesn't exist; or logic was never guarded.

**Fix**: wrap the `__main__` body in `def main():` and keep a thin guard
`if __name__ == "__main__": main()` (Phase 3 step 7). Both the console script and
`python -m <pkg>.backtest` then work, and importing the module has no side effects.

---

## GT9 — `requirements.txt` left beside `uv.lock`

**Symptom**: contributors `pip install -r requirements.txt` and get a different env than
the verifier (which uses `uv sync --frozen` against `uv.lock`); the two drift.

**Cause**: the uv port added `pyproject.toml` + `uv.lock` but never removed the legacy
`requirements.txt`, leaving two competing sources of truth.

**Fix**: `git rm requirements.txt` (Phase 3 step 8). `uv.lock` is canonical. Keep it only
under T4 = preserve-pins *and* an explicit maintainer request — and if kept, the README
must say it's secondary.

---

## GT10 — Drive-backed (Tier-2) repo needs `gdown` host-side for the gate

**Symptom**: the Phase 5 plutus gate aborts the Drive fetch with
`ModuleNotFoundError: No module named 'gdown'`, then downstream steps FAIL on missing
`data/...csv`.

**Cause**: the Drive fetch runs **host-side, in the same interpreter that runs the
`plutus` CLI** (`data_resolver._download_google_drive` → `fetch._default_gdown_*`), and
`gdown` ships only in plutus-verify's `runner` extra — the base wheel doesn't include it.
(Same root cause as `plutus-standardize` G13.)

**Fix**: install the runner extra into **the venv the `plutus` CLI runs out of** — *not*
necessarily the project `.venv`. Which venv that is depends on how `plutus` was installed
(`head -1 $(which plutus)` shows the interpreter):

- **`uv tool` / pipx install** (global, isolated venv at
  `~/.local/share/uv/tools/plutus-verify/`) — reinstall the *tool* with the extra:
  ```bash
  uv tool install --force "plutus-verify[runner] @ $WHL"   # gdown into the CLI's venv
  ```
  Installing into the project `.venv` here does **nothing** — the fetch never runs there.
- **Invoked from the project `.venv`** (e.g. `uv run plutus`) — only then does
  ```bash
  uv pip install "plutus-verify[runner] @ $WHL"   # or minimally 'gdown>=5.0'
  ```
  satisfy the fetch.

Do this before the gate (Phase 5 step 2). This is dev-env tooling, not a project
dependency (GT6 still holds).

> **Provenance:** the project-`.venv` install was the literal reading of the old GT10
> ("install into the dev venv") and it silently failed on a `uv tool`-installed CLI
> (ProtoSmartBeta, 2026-06-29) — `gdown` landed in the project venv but `plutus check`
> still raised `No module named 'gdown'`. "dev venv" was ambiguous; it means the CLI's venv.

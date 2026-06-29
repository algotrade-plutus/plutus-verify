# Decision tree (Phase 2)

The (up to 5) choices presented in Phase 2's single `AskUserQuestion` call. Each entry:
question, options, recommended default, rationale. Defaults are derived from Phase 1's
Restructure Survey, so a maintainer can usually default through all five.

---

## T1 — Package name

**Header**: `Package name`

**Question**: "What should the package be named (distribution / import name)?"

**Options**:
- **Derive from repo name** *(Recommended; default)* — distribution = kebab-case of the
  repo/dir name, import = snake_case of it (e.g. `MyStrategy` → `my-strategy` /
  `my_strategy`).
- **Custom** — maintainer supplies both names. Use when the repo name is non-descriptive
  or already taken on an internal index.

**Default**: derive from repo name. The import name is the snake_case of the distribution
name — they must agree (hatchling builds `src/<import_name>`).

---

## T2 — Console-script prefix + entry map

**Header**: `Console scripts`

**Question**: "What console-script prefix, and which modules are the entry points?"

**Options**:
- **Initials prefix + detected entries** *(Recommended; default)* — prefix = the
  package initials (`my_strategy` → `ms-`); entries = every module with an
  `if __name__ == "__main__":` block, mapped to a `main()` script. Entry modules are
  renamed to a clean verb noun where the original is awkward (`backtesting.py` →
  `backtest.py`, `optimization.py` → `optimize.py`, `evaluation.py` → `evaluate.py`).
- **Custom prefix / map** — maintainer overrides the prefix or the rename map.

**Default**: initials prefix, detected entries, conventional renames. Typical result:
`ms-load-data`, `ms-backtest`, `ms-optimize`, `ms-evaluate`. Record each
`<script> = "<pkg>.<module>:main"` binding for `pyproject.toml` and the manifest re-wire.

---

## T3 — Orphan / residue disposition

**Header**: `Orphans`

**Question**: "How should orphan modules and empty leftover dirs be handled?"

**Options**:
- **Delete residue, keep orphans as drop-candidates** *(Recommended; default)* — empty
  residue dirs (no tracked `.py`) are `rm -rf`'d; orphan modules (imported by nothing,
  no `__main__`) move into the package with a `# DROP CANDIDATE` comment, not deleted.
- **Delete both** — also `git rm` the orphan modules. Use only when the maintainer
  confirms they are dead.
- **Keep both** — move residue + orphans untouched. Use when unsure; revisit later.

**Default**: delete residue, keep orphans flagged. Deleting an *empty shadow* package
(e.g. `utils/` beside `utils.py`) is part of "delete residue" — it dissolves the
collision (GT2) and is not an orphan-module deletion.

---

## T4 — Dependency policy

**Header**: `Deps`

**Question**: "Keep exact pins, or upgrade to latest-compatible during the restructure?"

**Options**:
- **Upgrade to floors** *(Recommended; default)* — current versions become `>=` floors;
  `uv lock` resolves latest-compatible and pins them in `uv.lock`. The Phase 5 run
  doubles as a regression check.
- **Preserve pins** — keep `==` versions (locked exactly). Behavior-preserving; the diff
  stays purely structural. Choose when the maintainer wants zero dep churn in this PR.

**Default**: upgrade to floors. Surface risky majors (numpy / pandas / matplotlib) in the
question so the maintainer can veto a specific bump — a vetoed dep gets an upper bound
(`numpy>=2.0,<3`) and is re-locked.

---

## T5 — Python floor

**Header**: `Python`

**Question**: "Keep the repo's `requires-python`, or set it explicitly?"

**Options**:
- **Keep repo's floor** *(Recommended; default)* — reuse the existing
  `requires-python`; write it to `.python-version`.
- **Set explicitly** — pin a specific floor (e.g. `>=3.11`). Use when the current floor
  is missing, too loose, or incompatible with a chosen dep.

**Default**: keep the repo's floor. The chosen floor flows into `pyproject.toml`
(`requires-python`), `.python-version`, and the manifest's `env.python_version`.

---

## Output of Phase 2

A Decision Block. Each answer feeds Phase 3/4:
- T1 → package dir `src/<import_name>/`, `pyproject.toml` `name`, `__init__.py` docstring
- T2 → `[project.scripts]` entries, entry-module renames, manifest step `command`s
- T3 → which dirs are `rm -rf`'d, which orphans move flagged vs deleted
- T4 → `pyproject.toml` dep constraints (`>=` floors vs `==`) + any vetoed upper bound
- T5 → `requires-python`, `.python-version`, `env.python_version`

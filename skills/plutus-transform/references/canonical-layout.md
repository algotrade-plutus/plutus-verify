# Canonical layout — the target shape

`plutus-transform` reshapes any flat / script-based research repo into the shape below.
Throughout, `<pkg>` is the import name and `<prefix>` the console-script prefix; the
`my_strategy` / `ms-` names in examples are illustrative placeholders, not a real repo.

---

## The shape

```
<repo>/
├── pyproject.toml              # metadata, deps, [project.scripts], hatchling backend
├── uv.lock                     # committed; reproducibility source of truth
├── .python-version             # the requires-python floor (committed)
├── README.md
├── .gitignore                  # must NOT ignore __init__.py or .python-version
├── src/
│   └── <pkg>/                  # import name: snake_case of the distribution name
│       ├── __init__.py         # """<one-line>.""" + __version__
│       ├── <entry>.py          # one per pipeline stage; each exposes main()
│       ├── ...                 # library modules
│       ├── config/{__init__,config}.py
│       ├── database/{__init__,...}.py
│       └── metrics/{__init__,metric}.py
├── parameter/                  # *.json inputs — STAY at repo root (manifest refs)
├── data/                       # runtime data, gitignored (is/ os/ sample/)
├── result/                     # output artifacts — STAY at repo root (manifest refs)
└── tests/
    ├── __init__.py
    └── test_smoke.py           # import package + entry modules + 1 unit on a pure helper
```

## The rules

1. **`src/` layout.** All pipeline source lives under `src/<pkg>/`. The import name
   `<pkg>` is the snake_case of the distribution name (`my-strategy` →
   `my_strategy`).
2. **Console scripts, not file paths.** Each pipeline stage is invoked through a
   `[project.scripts]` entry (`ms-backtest = "my_strategy.backtest:main"`), not
   `python backtesting.py`. Every entry module exposes `def main()` + a thin
   `if __name__ == "__main__": main()` guard so `python -m <pkg>.<mod>` still works.
3. **uv + committed lockfile.** `pyproject.toml` declares deps; `uv.lock` pins them and
   is committed. `requirements.txt` is removed.
4. **Package-qualified absolute imports.** `from <pkg>.config.config import ...` — never
   bare `from config.config import ...` (which only works from the repo root and
   collides with stdlib/3rd-party names).
5. **Data/config/output stay at repo root.** `parameter/`, `data/`, `result/` are
   cwd-relative and referenced by the manifest; do **not** move them into the package.
6. **Tests exist.** A minimal `tests/` proves the package imports and at least one pure
   helper behaves.
7. **No collisions, no residue.** A `foo.py` module and a `foo/` package cannot coexist;
   empty leftover dirs from abandoned subsystems are deleted.

## Before → after (a typical flat candidate)

```
BEFORE (flat)                          AFTER (canonical)
─────────────                          ─────────────────
backtesting.py                         src/<pkg>/backtest.py
optimization.py                        src/<pkg>/optimize.py
evaluation.py                          src/<pkg>/evaluate.py
data_loader.py                         src/<pkg>/data_loader.py
utils.py                               src/<pkg>/utils.py
config/config.py                       src/<pkg>/config/config.py
database/{data_service,query}.py       src/<pkg>/database/{data_service,query}.py
metrics/metric.py                      src/<pkg>/metrics/metric.py
filter/financial.py                    src/<pkg>/filter/financial.py
requirements.txt                       (removed — uv.lock is canonical)
(no tests/)                            tests/{__init__,test_smoke}.py
(no src/)                              src/<pkg>/__init__.py
```

`parameter/`, `result/`, `data/`, `.plutus/` stay exactly where they are.

## tests/test_smoke.py template

```python
"""Smoke + unit tests for <pkg>."""
from decimal import Decimal

import <pkg>
from <pkg>.<helper_module> import <pure_helper>


def test_package_imports_and_has_version():
    assert isinstance(<pkg>.__version__, str)


def test_entry_modules_import():
    import <pkg>.<entry1>  # noqa: F401
    import <pkg>.<entry2>  # noqa: F401
    # ... one import line per entry module


def test_<pure_helper>_contract():
    # Assert real behavior of a pure helper (no I/O, no DB). Read its signature
    # first and match the assertion to its actual contract.
    result = <pure_helper>(Decimal("1.234"))
    assert isinstance(result, Decimal)
```

Pick a helper with **no side effects** (no DB connection, no file I/O) so the test runs
in CI without secrets. `round_decimal`-style numeric helpers are ideal.

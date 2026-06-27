"""End-to-end (no Docker): a src-layout package repo whose pipeline is invoked
via a console script, verified through env.install_project.

Builds a minimal installable package + manifest in a tmp repo, loads it through
the real load_manifest path (schema + invariants, incl. the pyproject check),
and asserts the generated Dockerfile installs the project so the console script
exists at run time.
"""
from pathlib import Path

from plutus_verify.spec.loader import load_manifest
from plutus_verify.spec.runtime.dockerfile_gen import generate_dockerfile


_MANIFEST = """\
schema_version: "2.0"
repo: {name: ProtoMarketMaker, primary_language: python}
env:
  base: python
  python_version: "3.11"
  manager: uv
  lockfile: uv.lock
  install_project: true
secrets: []
data_sources: {processed: [], raw: []}
steps:
  - id: in_sample
    nine_step: step_4_in_sample
    required: true
    command: "pmm-backtest"          # console script from the installed package
expected: []
nine_step_coverage: {}
"""

_PYPROJECT = """\
[project]
name = "proto-market-maker"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
pmm-backtest = "proto_market_maker.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
"""


def _make_src_layout_repo(root: Path) -> None:
    (root / ".plutus").mkdir(parents=True)
    (root / ".plutus" / "manifest.yaml").write_text(_MANIFEST)
    (root / "pyproject.toml").write_text(_PYPROJECT)
    (root / "uv.lock").write_text("# pinned\n")
    pkg = root / "src" / "proto_market_maker"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "cli.py").write_text("def main():\n    print('backtest ok')\n")


def test_src_layout_install_project_chain(tmp_path: Path):
    repo = tmp_path / "ProtoMarketMaker"
    repo.mkdir()
    _make_src_layout_repo(repo)

    # Full load path: schema + invariants, including the pyproject-at-root check.
    manifest = load_manifest(repo)
    assert manifest.env.install_project is True
    assert manifest.steps[0].command == "pmm-backtest"

    df = generate_dockerfile(manifest.env)
    # Deps cached first (project excluded), project installed after full COPY.
    assert "RUN uv sync --frozen --no-install-project" in df
    install = "RUN uv pip install --python /opt/venv/bin/python --no-cache-dir --no-deps ."
    assert install in df
    assert df.index("COPY . .") < df.index(install)

# Publishing `plutus-verify` to PyPI

Walks through the first PyPI upload (and subsequent releases) and the small
code change to flip the Dockerfile generator from local-wheel staging to a
PyPI install.

Plan 7 made the package PyPI-ready (proper metadata, classifiers, build
artifacts pass `twine check`). It did NOT publish. This runbook is what to
follow when we're ready.

---

## Prerequisites

- PyPI account: <https://pypi.org/account/register/>
- TestPyPI account (separate from PyPI): <https://test.pypi.org/account/register/>
- An API token from each (scoped to the project, not "all projects" — safer):
  - PyPI: <https://pypi.org/manage/account/token/>
  - TestPyPI: <https://test.pypi.org/manage/account/token/>
- `~/.pypirc` configured:
  ```ini
  [distutils]
  index-servers =
    pypi
    testpypi

  [pypi]
  username = __token__
  password = pypi-XXXXXX

  [testpypi]
  repository = https://test.pypi.org/legacy/
  username = __token__
  password = pypi-XXXXXX
  ```
  Set `chmod 600 ~/.pypirc`.
- Dev tools installed in your venv: `pip install build twine`.

---

## Release procedure

### 1. Verify the working tree is clean and on the right branch

```bash
git status                # no uncommitted changes
git log --oneline -5      # confirm HEAD points at the version you want to ship
```

### 2. Bump the version

Edit `pyproject.toml`:
```toml
version = "0.2.0"   # → "0.3.0" or whatever you're publishing
```

Versioning convention (semver-ish):
- **patch** (0.2.0 → 0.2.1): bugfix only, no API change
- **minor** (0.2.0 → 0.3.0): backward-compatible additions
- **major** (0.2.0 → 1.0.0): backward-incompatible changes (avoid until stable)

Commit:
```bash
git add pyproject.toml
git commit -m "chore: bump version to <new-version>"
```

### 3. Tag

```bash
git tag -a v0.3.0 -m "Release v0.3.0"
```

(Don't push the tag yet — push it together with the commit *after* a successful upload, so a failed upload doesn't leave a dangling tag.)

### 4. Clean previous build artifacts

```bash
rm -rf dist/ build/ *.egg-info
```

(Or `python -m build` will reuse stale artifacts.)

### 5. Build

```bash
source .venv/bin/activate
python -m build --wheel --sdist
```

Expected output (last line):
```
Successfully built plutus_verify-<version>.tar.gz and plutus_verify-<version>-py3-none-any.whl
```

### 6. Validate

```bash
twine check dist/*
```

Expected: `PASSED` for both `.whl` and `.tar.gz`. If FAILED, fix `pyproject.toml` (most often `description`, `readme`, or classifier strings) and rebuild.

### 7. Smoke test on TestPyPI

```bash
twine upload --repository testpypi dist/*
```

Then in a **fresh venv** (not your dev venv):
```bash
python -m venv /tmp/plutus-smoke
source /tmp/plutus-smoke/bin/activate
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ plutus-verify==<version>
python -c "import plutus_verify; print(plutus_verify.__version__)"
plutus --help
deactivate
rm -rf /tmp/plutus-smoke
```

The `--extra-index-url` flag is necessary so transitive deps (click, pyyaml, etc.) come from real PyPI; TestPyPI doesn't mirror them reliably.

If the smoke test passes: proceed. If not: yank from TestPyPI (`twine` doesn't have a yank command — use the TestPyPI web UI), fix, rebuild, retry on a bumped patch version.

### 8. Real PyPI upload

```bash
twine upload dist/*
```

Output ends with:
```
View at: https://pypi.org/project/plutus-verify/<version>/
```

### 9. Push the commit and tag

```bash
git push origin <branch>
git push origin v<version>
```

### 10. Flip `dockerfile_gen` to install from PyPI

After the first successful PyPI publish, the runtime no longer needs to build a wheel from the local source — it can `pip install plutus-verify==<version>` directly. This is a ~5-line code change.

In `plutus_verify/spec/runtime/dockerfile_gen.py`, the SDK install section currently emits:
```
COPY .plutus/build/plutus_verify-<v>-py3-none-any.whl /tmp/...
RUN pip install --no-cache-dir /tmp/...
```

Switch to a version-pinned install:
```
RUN pip install --no-cache-dir plutus-verify==<published-version>
```

And in `plutus_verify/spec/runtime/orchestrator.py`, remove or guard the call to `ensure_plutus_wheel` (no longer needed for the PyPI path).

The `sdk_bundle` module + tests stay around — they're still useful for dev installs against unreleased branches (e.g., `pip install -e .` in the dev tree, no PyPI release yet). The dockerfile_gen can branch: if `plutus-verify` is installed *from a wheel* (PyPI), use the version-pinned install; if from an *editable install* (dev tree), stage the wheel via sdk_bundle.

Detection logic (sketch):
```python
def _dockerfile_sdk_section(version: str, is_editable: bool, basename: str | None) -> list[str]:
    if is_editable and basename is not None:
        return [
            f"COPY .plutus/build/{basename} /tmp/{basename}",
            f"RUN pip install --no-cache-dir /tmp/{basename}",
        ]
    return [
        f"RUN pip install --no-cache-dir plutus-verify=={version}",
    ]
```

Decide which path to take by inspecting the distribution's metadata (presence of `direct_url.json` with `editable: true`).

### 11. Verify a downstream install

In ProtoMarketMaker (or whichever target repo), update `requirements.txt` to include:
```
plutus-verify>=<version>
```

(Or, if going through the auto-include path: do nothing — the verifier injects it.)

Run `plutus check` end-to-end. Confirm the image installs the package from PyPI and the SDK works in-container.

---

## Rolling back

PyPI does not allow re-uploading the same version. If you need to fix a broken release:

1. Yank the broken version via the PyPI web UI: <https://pypi.org/project/plutus-verify/> → Manage → Yank.
   - Yanked versions remain installable by exact version pin (so existing pinned consumers keep working) but won't be picked by `pip install plutus-verify` without a version.
2. Bump the patch version (e.g., 0.3.0 broken → 0.3.1).
3. Re-run the procedure from step 4.

**Never** force-push a tag or rewrite version history.

---

## Common failure modes

- **`twine check` complains about long_description**: README.md is shorter than PyPI expects, or its first line is not a heading. Add content to README.
- **`twine upload` 403 Forbidden**: API token wrong or scoped to the wrong project. Regenerate.
- **`pip install` from TestPyPI fails resolving deps**: missing `--extra-index-url https://pypi.org/simple/`. TestPyPI doesn't have most third-party packages.
- **PyPI says "version already exists"**: you can't overwrite. Bump and re-upload.
- **`docker build` fails inside `plutus check` after the dockerfile_gen flip**: the published version on PyPI may not exist yet, or your image's pip is too old. Pin to a known-good version.

---

## Future enhancements (not part of this runbook)

- **CI release pipeline**: a GitHub Action that runs on a tag push, builds, runs `twine check`, uploads to PyPI. Removes manual steps 4–8.
- **Trusted Publishers**: PyPI supports OIDC-based publishing without long-lived tokens — preferred once CI is in place.
- **Version derived from git**: tools like `hatch-vcs` derive version from the most recent tag. Reduces drift between `pyproject.toml` and tags.

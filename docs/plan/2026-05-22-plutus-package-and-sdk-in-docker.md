# Plutus v2 Spec — Package plutus-verify + Auto-inject SDK in Docker (Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Ship `plutus-verify` as a properly-packaged Python distribution. The verifier's Dockerfile generator auto-injects the SDK into every generated image so author scripts can `import plutus_verify as pv` without manually editing `requirements.txt`. Use a local wheel today; ready the package for a future PyPI publish.

**Architecture:** Three pieces — (1) PyPI-ready `pyproject.toml` metadata, (2) a small `sdk_bundle` runtime helper that locates or builds a wheel of plutus-verify and stages it in the Docker build context, (3) `dockerfile_gen` emits `COPY` + `pip install` lines for the staged wheel. Switch to `pip install plutus-verify==<version>` once on PyPI.

**Tech Stack:** No new deps in the package itself. Dev-time uses `build` (PyPA's wheel builder).

---

## Why this plan exists

Plan 6 stood up the SDK and the file contract. Task 7 verified the contract by hand-rolling JSON in ProtoMarketMaker's scripts because the generated Docker image doesn't include `plutus_verify`. The DONE doc names this as a deferred limitation:

> SDK install path inside the generated Docker image — today author scripts must either hand-roll the results.json write or pip install plutus_verify via requirements.txt.

For authors to use the ergonomic SDK (`with pv.step(...) as r: r.metric(...)`), the SDK has to be importable inside the container. The verifier knows its scripts will use the SDK, so it should ensure the SDK is there. Author requirements.txt stays clean.

A second prerequisite for downstream adoption: `plutus-verify` must be a real, installable package — proper metadata, README, license, classifiers. This plan brings the project to publish-ready (without publishing yet) and uses a built wheel locally in the meantime.

---

## Architectural decisions (recorded)

1. **Local wheel today, PyPI tomorrow.** User chose "Local wheel for now, but prepare properly for the PyPI publish." So this plan hardens metadata for PyPI, builds a wheel locally, and the dockerfile_gen consumes the local wheel. A separate future change flips dockerfile_gen to `pip install plutus-verify==<version>` once we publish.
2. **Verifier owns SDK installation, not authors.** User chose "Auto-include via dockerfile_gen." Author's `requirements.txt` stays untouched. The dockerfile_gen unconditionally adds the SDK-install lines. If an author overrides, that's still possible (their requirements.txt runs after the SDK install).
3. **Wheel is built on demand.** The runtime helper builds a wheel from the current `plutus-verify` source at image-build time. No checked-in wheel binary, no stale `dist/` artifacts in the repo. Build is fast (~2s).
4. **Source location detection via `importlib.metadata`.** The helper finds plutus-verify's source by inspecting its installed distribution. For editable/source installs (the dev case), it builds from the source tree. For wheel installs (the future PyPI case), the helper would short-circuit to `pip install plutus-verify==<version>` — but that path is out of scope for this plan.
5. **Wheel staged in Docker build context.** The Dockerfile generator writes the wheel into a known location inside the build context (the repo's `.plutus/build/` subdir — already inside the verifier namespace) and emits `COPY` + `RUN pip install`. The path is `.plutus/build/plutus_verify-<version>-py3-none-any.whl`.
6. **`.plutus/build/` is verifier-managed, gitignored.** The build context is ephemeral — gets recreated on every image build. Authors don't see it, don't manage it.

---

## File Structure

**Modified:**

- `pyproject.toml` — full metadata hardening (description, README pointer, license, urls, classifiers, keywords, version bump to 0.2.0)
- `plutus_verify/spec/runtime/dockerfile_gen.py` — emit `COPY` + `RUN pip install` for the SDK wheel
- `plutus_verify/spec/runtime/real_image_builder.py` — call into the new sdk_bundle helper to stage the wheel before invoking `docker build`
- `plutus_verify/spec/runtime/__init__.py` — re-export `ensure_plutus_wheel`, `SdkBundleError` if useful
- `.gitignore` — add `.plutus/build/` (verifier-managed build context)

**New:**

- `plutus_verify/spec/runtime/sdk_bundle.py` — `ensure_plutus_wheel(build_context_dir) -> Path` + `SdkBundleError`
- `docs/runbook/publishing-to-pypi.md` — checklist for future publish

**Tests:**

- `tests/unit/test_sdk_bundle.py` — wheel build, error paths, idempotency
- `tests/unit/test_runtime_dockerfile_gen.py` — extend with new assertions about the SDK install lines
- `tests/unit/test_runtime_real_image_builder.py` — extend to confirm the helper is called

**README:**

- `README.md` — add a brief "Installation" section that points at the wheel build (or PyPI when ready)

---

## Task 1: Harden `pyproject.toml` for PyPI

**Files:**
- Modify: `pyproject.toml`
- Add: `README.md` "Installation" section (if not already present in a usable form)

Goal: the project metadata is sufficient for `python -m build` to produce a wheel and sdist that pass `twine check` and would be acceptable to upload to PyPI.

Sub-steps:
- [ ] **Step 1 — audit existing `pyproject.toml`** and produce a diff. Current minimal version exists; add: `description` (one line), `readme = "README.md"`, `license = {text = "TBD-or-MIT-etc"}`, `authors = [{name = "...", email = "..."}]`, `urls = {"Source" = ...}`, `classifiers = [...]`, `keywords = [...]`. Bump `version` from `0.1.0` to `0.2.0` to mark the v2-spec inversion.
- [ ] **Step 2 — verify `python -m build` succeeds locally**. Install `build` if needed: `pip install build`. Run `python -m build --wheel --sdist`. Should produce `dist/plutus_verify-0.2.0-py3-none-any.whl` and `dist/plutus_verify-0.2.0.tar.gz`.
- [ ] **Step 3 — verify `twine check dist/*`** succeeds. Install `twine` if needed. Should report "Passed" for both artifacts.
- [ ] **Step 4 — commit**.

Commit message:
```
chore(pkg): harden pyproject.toml for PyPI; bump version to 0.2.0

Adds description, README pointer, license, authors, urls, classifiers,
and keywords. python -m build produces a passing wheel + sdist; twine
check is clean. Not publishing yet — local wheel only — but this puts
us one command away when we are.
```

---

## Task 2: `sdk_bundle.py` — locate-or-build wheel

**Files:**
- Create: `plutus_verify/spec/runtime/sdk_bundle.py`
- Test: `tests/unit/test_sdk_bundle.py`

Public API:

```python
class SdkBundleError(RuntimeError):
    """Failed to locate or build a plutus-verify wheel."""


def ensure_plutus_wheel(build_context_dir: Path) -> Path:
    """Place a `plutus_verify-*.whl` inside `build_context_dir` and return its path.

    Strategy:
    1. Locate the plutus-verify source via `importlib.metadata.distribution("plutus-verify")`.
       If it's an editable install (a `direct_url.json` file exists or `dist.locate_file` resolves
       to a source tree), grab the source root.
    2. Build a wheel from that source via `python -m build --wheel --outdir <tmp>`.
    3. Copy the resulting wheel into `build_context_dir`.
    4. Return the absolute path of the placed wheel.

    Raises SdkBundleError if any step fails.
    """
```

TDD sub-steps:
- [ ] **Step 1 — failing test for happy path**: `ensure_plutus_wheel(tmp_path)` returns a path that exists, ends with `.whl`, and is inside `tmp_path`.
- [ ] **Step 2 — failing test for idempotency**: calling twice returns paths to (likely the same) wheel; second call doesn't rebuild if a fresh wheel already exists in the directory.
- [ ] **Step 3 — failing test for missing source**: monkeypatch `importlib.metadata.distribution` to raise → SdkBundleError, message mentions the package.
- [ ] **Step 4 — implementation**:
  - Use `importlib.metadata.distribution("plutus-verify")` to find the distribution
  - For editable installs, parse `direct_url.json` (PEP 610) to get the source root, OR fall back to `dist._path.parent` (works for setuptools editable installs)
  - Use `subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", tmp])` to build
  - Copy `glob("plutus_verify-*-py3-none-any.whl")[0]` into `build_context_dir`
- [ ] **Step 5 — run tests**: `source .venv/bin/activate && pytest tests/unit/test_sdk_bundle.py -v`
- [ ] **Step 6 — commit**.

Commit message:
```
feat(spec/runtime): sdk_bundle locates+builds plutus-verify wheel

Adds ensure_plutus_wheel(build_context_dir) — uses importlib.metadata
to find the installed plutus-verify source, runs `python -m build`
to produce a wheel, copies it into the build context. Returns the
wheel path for dockerfile_gen to COPY+RUN against. Idempotent.
```

---

## Task 3: Wire `dockerfile_gen` to emit the SDK-install lines

**Files:**
- Modify: `plutus_verify/spec/runtime/dockerfile_gen.py`
- Modify: `plutus_verify/spec/runtime/real_image_builder.py`
- Test: `tests/unit/test_runtime_dockerfile_gen.py` (extend), `tests/unit/test_runtime_real_image_builder.py` (extend)

Sub-steps:
- [ ] **Step 1 — failing test in dockerfile_gen**: with a fake wheel path argument, the emitted Dockerfile contains `COPY .plutus/build/plutus_verify-<v>-py3-none-any.whl /tmp/` and `RUN pip install /tmp/plutus_verify-<v>-py3-none-any.whl`. The COPY uses the wheel's basename relative to the repo's `.plutus/build/`.
- [ ] **Step 2 — extend `generate_dockerfile(env, secrets, *, sdk_wheel_basename=None)`** signature. When `sdk_wheel_basename` is provided, emit two new lines after the requirements.txt install: `COPY .plutus/build/<basename> /tmp/<basename>` and `RUN pip install /tmp/<basename>`. When `None`, no SDK lines emitted (keeps current tests passing and is the "if you really don't want it" escape hatch — but real_image_builder always passes a value).
- [ ] **Step 3 — failing test in real_image_builder**: when `build_image(...)` is called, `ensure_plutus_wheel` is invoked with `repo_path / ".plutus" / "build"` and the resulting wheel basename is threaded into `generate_dockerfile`. Mock subprocess + ensure_plutus_wheel; assert the dockerfile_gen call.
- [ ] **Step 4 — update `real_image_builder.build_image`** to:
  - Compute build context dir `repo_path / ".plutus" / "build"`; `mkdir(parents=True, exist_ok=True)`
  - Call `wheel_path = ensure_plutus_wheel(build_context_dir)`
  - Pass `sdk_wheel_basename=wheel_path.name` to `generate_dockerfile`
- [ ] **Step 5 — `.gitignore` updates**: append `.plutus/build/` (the verifier-managed build artifacts dir).
- [ ] **Step 6 — run tests**: `source .venv/bin/activate && pytest tests/unit/test_runtime_dockerfile_gen.py tests/unit/test_runtime_real_image_builder.py tests/unit/test_sdk_bundle.py -v`
- [ ] **Step 7 — commit**.

Commit message:
```
feat(spec/runtime): dockerfile_gen auto-injects plutus-verify wheel

Generated Dockerfile now COPYs and pip-installs a wheel of plutus-verify
into every image. real_image_builder builds the wheel via sdk_bundle.
Author scripts can `import plutus_verify as pv` without touching their
own requirements.txt.
```

---

## Task 4: Integration verification with ProtoMarketMaker

**Files:**
- Modify: `out/transfer-test/ProtoMarketMaker/backtesting.py` — replace Task 7's hand-rolled `_plutus_emit_results` with a real `with pv.step(...) as r: ...` block
- Modify: `out/transfer-test/ProtoMarketMaker/evaluation.py` — same
- Run: `plutus check out/transfer-test/ProtoMarketMaker`

Sub-steps:
- [ ] **Step 1 — replace the helper-call blocks in `backtesting.py`** with real SDK usage:

  ```python
  import plutus_verify as pv

  with pv.step("in_sample_backtest") as r:
      r.metric("sharpe_ratio",     float(sharpe),               unit="ratio")
      r.metric("sortino_ratio",    float(sortino),              unit="ratio")
      r.metric("maximum_drawdown", float(mdd),                  unit="ratio")
      r.metric("hpr",              float(bt.metric.hpr()),      unit="ratio")
      r.metric("monthly_return",   float(returns['monthly_return']), unit="ratio")
      r.metric("annual_return",    float(returns['annual_return']),  unit="ratio")
      r.artifact("equity_curve",   "result/backtest/hpr.svg",       kind="chart")
      r.artifact("drawdown_chart", "result/backtest/drawdown.svg",  kind="chart")
      r.artifact("inventory",      "result/backtest/inventory.svg", kind="chart")
      r.metadata(seed=2025)
  ```

  Remove the `_plutus_emit_results` helper definition and call. Keep the `print()` lines (they're useful for human-readable container logs).

- [ ] **Step 2 — same for `evaluation.py`** with `step_id="out_of_sample_backtest"` and `result/optimization/...` artifact paths.
- [ ] **Step 3 — run `plutus check`**:
  ```bash
  cd /Users/dan/algotrade-research/plutus-automation-scoring
  source .venv/bin/activate
  python -m plutus_verify check out/transfer-test/ProtoMarketMaker 2>&1 | tee out/transfer-test/check7.log
  ```
  Expected: same 6/6 in-sample + 3/6 OOS pass pattern as Task 7. The only change is the producer (real SDK in container vs hand-rolled json.dump); the file contract and verifier behavior are identical.

- [ ] **Step 4 — confirm the wheel was installed inside the container** by inspecting the generated Dockerfile and (if needed) running `docker run --rm <image> pip show plutus-verify`.

- [ ] **Step 5 — commit** (out/ is gitignored per Plan 5's pattern; this verifies the work, no in-tree files change here beyond what Tasks 1–3 committed).

Verification result feeds into the wrap-up doc.

---

## Task 5: PyPI publish runbook

**Files:**
- Create: `docs/runbook/publishing-to-pypi.md`

Content outline:
- Prerequisites (PyPI account, `~/.pypirc`, `twine` installed)
- Steps:
  1. Update `version` in `pyproject.toml`
  2. `python -m build --wheel --sdist`
  3. `twine check dist/*`
  4. `twine upload --repository testpypi dist/*` (smoke test on TestPyPI first)
  5. Test install from TestPyPI in a clean venv
  6. `twine upload dist/*` (real PyPI)
  7. Flip `dockerfile_gen` to emit `RUN pip install plutus-verify==<version>` (small code change, ~5 lines)
- Rollback: yanking a release on PyPI

Sub-steps:
- [ ] **Step 1 — write the runbook**
- [ ] **Step 2 — commit**

Commit message:
```
docs: PyPI publish runbook for plutus-verify

Walks through TestPyPI smoke → real PyPI upload → dockerfile_gen
switch from local-wheel to pip-install-from-PyPI.
```

---

## Verification (how we'll know it works)

**Unit:** ~10 new tests across `test_sdk_bundle.py`, extensions in `test_runtime_dockerfile_gen.py` and `test_runtime_real_image_builder.py`. Full suite stays green.

**Integration:** end-to-end run against ProtoMarketMaker with real `import plutus_verify as pv` calls. Pass pattern matches Task 7 (6/6 in-sample, 3/6 OOS). The diff vs Task 7: ProtoMarketMaker's scripts no longer hand-roll JSON — they use the SDK directly.

**Regression:** all 393 existing unit tests pass. Net test count likely ≈403.

---

## Out of scope

- Actual PyPI publish (runbook only — when ready, follow it)
- GPU support (`env.base=python-cuda`) — orthogonal
- `plutus snapshot --metrics` — that's Plan 8 (snapshot-then-commit workflow), tracked separately
- Removing the legacy v1 `extract/plan.py` and v1 compare path — still deferred
- Non-Python SDKs (R, Julia, shell) — the file contract supports them; ergonomic libraries are future work

---

## Connection to Plan 8

Plan 8 will extend `plutus snapshot` to write `expected.metrics[].value` from each step's results.json. The author workflow becomes:

1. `plutus init` — scaffold manifest skeleton + example_script.py + CI workflow
2. Instrument scripts with `pv.step(...)` blocks (Plan 7 makes this work in Docker)
3. Run `plutus snapshot` — fills manifest's metric values from a fresh run
4. Review diff, `git commit` — the commit IS the verification claim
5. CI runs `plutus check` — verifies committed values match fresh runs

Plan 7 is the prerequisite (SDK has to be reachable for step 2). Plan 8 is the toil-killer (step 3).

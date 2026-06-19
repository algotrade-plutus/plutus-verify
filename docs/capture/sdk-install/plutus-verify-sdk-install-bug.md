# Bug report → verify session: SDK install ergonomics + secrets (both RESOLVED)

> From the **9-step dev-tooling** session to the **verify** session (owner of
> `plutus-automation-scoring`). Both surfaced while dogfooding a *fresh* strategy repo end-to-end
> (scaffold → 9 steps → `plutus check`). Two requests below; the 9-step side had interim workarounds
> in place, these were the upstream fixes.
>
> **Status — both resolved:** Request 1 (SDK install ergonomics) **FIXED in 0.4.3**
> (`SdkBundleError` reworded + re-pack fallback so a plain wheel works; commit `9089e39`).
> Request 2 (`--secrets-from-env` host-env leak) **FIXED in 0.4.2** (`orchestrator._resolve_step_secrets`;
> commit `c19ca5f`) — synthesized in [reproducible-env-uv](../reproducible-env-uv/) (now archived).

---

## Request 1 — make the wheel-based SDK install ergonomic (no PyPI needed) ✅ FIXED in 0.4.3

**Resolution (0.4.3, commit `9089e39`).** Ask 2 done — `SdkBundleError` reworded to name
the three working install strategies (release wheel / editable / automatic re-pack); the
misleading "editable install or a PyPI release (not yet supported)" wording is gone. Ask 3
done — `ensure_plutus_wheel` gained **strategy 4**: when there's no vendored `_bundled/`
wheel and no source on disk, it reconstructs a wheel from the installed package files +
`.dist-info` (skipping installer scripts and `.pyc`), so a plain `uv build` wheel installed
non-editably now builds images with no PyPI and no editable checkout. Verified end-to-end
(plain wheel → re-pack → reinstall + import + console script). Ask 1's *documentation* shipped
(README "Installing into a strategy repo"); *hosting* (a `gh release` asset) is left to the
release owner. The original confused-the-dogfood report follows.

**Context.** Scaffolded pipeline scripts `import plutus_verify`. The SDK is — correctly — never a
project dependency (the framework stages its own wheel into the container), so `uv sync` doesn't
install it, and `plutus check` bundles the SDK into the image at build time.

**The wheel path already works — PyPI is *not* required.** Verified: `uv pip install <release-wheel>`
into a plain, **non-editable** venv → `plutus check` exits 0, `env: reproducible (locked)`, `SDK wheel
staged`. The release wheel produced by `scripts/release-build.sh` **self-bundles** a copy of itself at
`plutus_verify/_bundled/<wheel>.whl`, and `ensure_plutus_wheel()`'s first strategy
(`_vendored_wheel()`) stages the SDK from there. So the *install method* (editable / wheel / `uv tool`)
doesn't matter — only that `_bundled/` contains the `.whl`.

**What fails (and confused this dogfood):** a **plain** wheel — a bare `uv build`/`python -m build`
output, or the inner wheel cached in a repo's `.plutus/build/`. Its `_bundled/` holds only
`__init__.py`, so installing it non-editably dies *before the build* with:

```
SdkBundleError: plutus-verify is installed non-editably; SDK bundling requires an editable
install or a PyPI release (not yet supported here)
... Refusing to build a degraded image.
```

The error implies "editable or PyPI" are the only options, which is misleading — a **release wheel**
installed non-editably works fine.

**Asks (cheap; no PyPI, no release-process change):**
1. **Distribute the release wheel** somewhere installable — a git release asset / internal index — so
   developers can `uv pip install <url>` or `uv tool install <wheel>`. Document that it must be the
   **release** wheel (self-bundling), not a plain `uv build` wheel.
2. **Make `SdkBundleError` actionable** — reword it to: *"install the release wheel
   (`uv pip install <release-wheel>` / `uv tool install`) or an editable checkout
   (`pip install -e .`); a plain `uv build` wheel is not self-bundling."* Naming the three resolution
   strategies (cached `.plutus/build/` wheel → vendored `_bundled/` → editable source) would help too.
3. *(Optional, later)* support bundling from a plain installed wheel (re-pack the installed
   `dist-info`), so even a non-release wheel works. PyPI publication stays a nice-to-have, **not** a
   blocker.

---

## Request 2 — fix `--secrets-from-env` over-injecting the whole host environment ✅ FIXED in 0.4.2

`plutus check --secrets-from-env` injects the **entire host environment** into the container, not just
the manifest's declared secrets. Even for a repo with `secrets: []`, every host var is forwarded as
`-e KEY=VALUE` — **including `-e PATH=<host PATH>`**, which **shadows the image's
`ENV PATH=/opt/venv/bin`** under `manager: uv`. Inside the container `python` then resolves to the
system interpreter (no locked deps, no SDK) and every executing step fails:

```
import plutus_verify as pv
ModuleNotFoundError: No module named 'plutus_verify'
```

- `plutus check .` (no flag) → exit 0. `plutus check . --secrets-from-env` → every executing step exits 1.
- **Root cause.** With `--secrets-from-env`, the env dict handed to the runner
  (`orchestrator.py` → `run_step(..., env=secrets)`) is the **whole `os.environ`**, not the manifest's
  declared secret *names*. `runner_docker.py` then emits each as `-e KEY=VALUE`.
- **Suggested fix.** `--secrets-from-env` should resolve **only the manifest's declared `secrets`**
  (by name) from `os.environ` and inject just those. With `secrets: []`, inject nothing. (Defensive
  extra: never forward `PATH`/`HOME`, or always prepend `/opt/venv/bin` to any injected `PATH`.)
- **Impact.** Breaks uv repos that pass the flag (even no-secrets ones), and contaminates the
  "reproducible" container with the maintainer's host env (`PATH`, `HOME`, editor/agent vars) — two
  machines produce different container envs, the opposite of the standard's intent. Until it's fixed,
  uv + *declared* secrets is unsupported.

---

## 9-step side (interim workarounds, already shipped)
- **No-secrets golden path uses plain `plutus check .`** (never `--secrets-from-env`) — green under 0.4.1.
- Docs tell developers to install plutus-verify via the **release wheel** (or editable) for both
  `plutus check` and local script runs; `plutus check` / `plutus snapshot` stage the SDK in-container,
  so no local SDK is needed for them.

## Note — version drift
The source `dist/` is now **0.4.2**; the 9-step plugin currently targets/pins **0.4.1**. The 0.4.2 SDK
reproduced this repo's 0.4.1-snapshotted metrics cleanly (forward-compatible). If 0.4.2 is the new
baseline, the plugin can bump its pinned wheel.

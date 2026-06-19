# Bug reports → verify session: uv-locked env step execution

> Handoff from the **9-step dev-tooling** session to the **verify** session.
> Found while migrating the 9-step plugin's example repo to the uv standard.
> Two distinct runtime bugs blocked uv-env steps from running. **#1 is FIXED in 0.4.1.**
> **#2 is FIXED in 0.4.2** (affects `--secrets-from-env`).

---

## Bug #1 — login shell drops the venv PATH ✅ FIXED in 0.4.1

**Was:** `runner_docker.py` ran steps with `bash -lc` (login shell); Debian `/etc/profile` reset PATH and
dropped the `/opt/venv/bin` the uv Dockerfile sets → `ModuleNotFoundError`.
**Fix shipped:** commit `b56968f` changed `bash -lc` → `bash -c`. Confirmed present in 0.4.1. Thanks!

---

## Bug #2 — `--secrets-from-env` injects the ENTIRE host environment (incl. PATH) ✅ FIXED in 0.4.2

**Fix shipped:** `orchestrator._resolve_step_secrets` now injects only the manifest's declared
secret keys, scoped per `used_by`; with `secrets: []` nothing is injected. A reserved-key denylist
(PATH/HOME/LD_LIBRARY_PATH/…) is rejected by the validator at check-time and dropped by the
resolver. uv + declared-secrets repos are now supported — the 9-step plugin can re-enable
`--secrets-from-env` for repos that declare secrets. See capture `2026-06-19-bug-fix` (Bug #2).

After the #1 fix, uv-env steps **still fail** when `plutus check` is run with `--secrets-from-env`, even
for a manifest that declares **no secrets** (`secrets: []`).

### Symptom
```
File "/srv/repo/src/<pkg>/backtesting.py", line 12, in <module>
    import plutus_verify as pv
ModuleNotFoundError: No module named 'plutus_verify'
```
`plutus check .` (no flag) → **exit 0, env: reproducible (locked)**, all metrics pass.
`plutus check . --secrets-from-env` → every executing step exits 1.

### Root cause
With `--secrets-from-env`, the env dict handed to the runner (`orchestrator.py` `run_step(..., env=secrets)`)
is the **entire `os.environ`**, not just the manifest's declared secret names. The runner emits each as
`-e KEY=VALUE` (`runner_docker.py`), so the container receives, among ~50 host vars:

```
-e PATH=/Users/dan/.antigravity/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:...   # the macOS HOST PATH
-e HOME=/Users/dan  -e SHELL=/bin/zsh  -e VSCODE_*  -e CLAUDE_*  -e NVM_*  ...
```

Docker `-e PATH=<host>` **overrides the image's `ENV PATH="/opt/venv/bin:$PATH"`**, so inside the
container `python` resolves on the host PATH (whose only entry that exists in the container is
`/usr/local/bin`) → the **system** python, which has neither the locked deps nor the SDK → import fails.
(The pip path tolerated this because it installs into that same system python; uv puts everything in
`/opt/venv`, which the injected PATH hides.)

### Proof (captured by instrumenting the runner during a real `plutus check . --secrets-from-env`)
The docker args for the `in_sample` step contained the full host environment, including
`-e PATH=/Users/dan/.../opt/homebrew/bin:/usr/local/bin:...` (no `/opt/venv/bin`), and the step exited 1
with the traceback above. The same step with `plutus check .` (no flag → no `-e` injection) exits 0.

### Impact
- **Reproducibility + security smell:** the "reproducible" container is contaminated by the maintainer's
  host environment (PATH, HOME, editor/agent vars, …). Two maintainers on different machines get
  different container envs — the opposite of the standard's intent.
- **Breaks uv repos** that pass `--secrets-from-env`, even with no declared secrets.

### Suggested fix
`--secrets-from-env` should resolve **only the manifest's declared `secrets`** (by name) from `os.environ`
and inject just those — never the whole environment. With `secrets: []`, inject nothing. (Defensively,
the runner could also refuse to inject `PATH`/`HOME` or always prepend `/opt/venv/bin` to any injected
`PATH`, but the real fix is to stop forwarding all of `os.environ`.)

### 9-step-side handling (no verifier change required for the default path)
The 9-step plugin's golden path is Tier-1 (committed CSV, **no secrets**), so it now runs `plutus check .`
(without `--secrets-from-env`) — correct usage for a no-secrets repo, and green under 0.4.1. The plugin
will only add `--secrets-from-env` for repos that actually declare secrets; until #2 is fixed, uv +
declared-secrets is unsupported (documented as a known limitation).

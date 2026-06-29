# Known gotchas

Failure patterns the Skill detects during Phases 3 and 4. Each entry is **Symptom → Diagnosis → Fix**. When `plutus check` FAILs or a smoke-run crashes, match the symptom against this list before improvising.

> Source: [docs/others/zbounce-v1-to-v2-upgrade.md](../../../docs/others/zbounce-v1-to-v2-upgrade.md) §5.

---

## G1 — Module-level DB connection forces network/secret routing

**Symptom.** `plutus check` reports `FAIL <step>: exit=1` with no stderr surfaced. Pre-0.2.6, no further diagnostic on screen.

**Diagnosis.** A module imported transitively by the step (commonly `database/data_service.py` or `db.py`) calls `psycopg2.connect(...)` / `sqlalchemy.create_engine(...)` at **import time**, e.g.

```python
# database/data_service.py
data_service = DataService()   # ← runs psycopg2.connect on import
```

Any script that imports the data layer — even backtest scripts that read only from CSVs at runtime — opens a connection the instant Python loads it. With `network: none` and no DB env vars forwarded, DNS resolution fails:

```
psycopg2.OperationalError: could not translate host name "<host>"
to address: Temporary failure in name resolution
```

**Reproduce manually** when the report swallows the trace:

```bash
docker images | grep plutus-v2          # find current image
docker run --rm --network=none \
  -v "$PWD:/srv/repo" -w /srv/repo \
  plutus-v2:<hash> bash -c "python <step-script>.py 2>&1; echo EXIT=\$?"
```

> Use `bash -c` (non-login), exactly as the runner does — a login shell (`-lc`)
> re-sources `/etc/profile` and drops the uv venv's `/opt/venv/bin` from `PATH`,
> so a `manager: uv` repo would fail the manual repro while `plutus check` passes.

**Fix (manifest-only, no source change).**
1. Affected step: `network: none` → `network: bridge`
2. All DB secrets: extend `used_by:` to include the step that imports the data layer.

**Proper fix (defer to maintainer, never silently apply).** Remove the module-level instantiation; have callers construct locally. Surface this in Phase 4.5's "architectural smells" section.

---

## G2 — Internally-conflicting dependency file

**Symptom.** At `uv lock` time, resolution fails and names the offending constraint:
```
error: No solution found when resolving dependencies:
  ... numpy>=2.4 is incompatible with numba<0.60 (needs numpy<2.3)
```
Deprecated-fallback case (a pip/requirements.txt env not yet ported to uv):
```
ERROR: Cannot install -r requirements.txt ... conflicting dependencies.
```

**Diagnosis.** The repo's pins are mutually incompatible (e.g. `numpy==2.4.2` pinned alongside `pandas_ta` whose `numba` transitive needs `numpy<2.3`). The canonical source resolved by `uv lock` is `pyproject.toml`'s `[project.dependencies]`; a `requirements.txt` is a deprecated fallback to be ported. The root cause is the same wherever the pins live, but the fix centers on `pyproject.toml` + `uv.lock`.

**Fix.** `uv lock` surfaces the conflict explicitly and names the offending constraint. Loosen the ONE offending constraint in `pyproject.toml` (e.g. relax `numpy`) and re-run `uv lock` — no silent strip-all. Routed through D5 in [`decision-tree.md`](decision-tree.md) (the "port to uv" default), **always asked in Phase 2**. The regenerated `uv.lock` lands as a commit on the `plutus-verify-v2` branch so the change is reviewable and reversible.

If `uv lock` *still* cannot resolve after loosening the offending constraint (rare — usually a transitive needs an OS package, or a genuinely impossible version graph), surface the failure to the maintainer for direction. Don't silently keep retrying.

---

## G3 — `.env` placeholders crash shell sourcing

**Symptom.**
```
$ set -a; source .env; set +a
.env:8: parse error near '\n'
```

**Diagnosis.** `.env` (or `.env.example` the user copied) ships unquoted angle-bracket placeholders like `MARKET_REDIS_HOST=<redis_host>`. Angle brackets are shell I/O redirection metacharacters.

**Fix.** Don't `source .env`. Export only the needed keys:

```bash
eval "$(grep -E '^(KEY1|KEY2|KEY3)=' .env | sed 's/^/export /')"
plutus check . --secrets-from-env
```

`--secrets-from-env` makes the host environment the *candidate pool*, but only the keys declared in `manifest.secrets[]` are forwarded into a container — each injected only into the steps named in that secret's `used_by`. With `secrets: []`, nothing is injected (host `PATH`/`HOME`/editor vars never reach the container). Fixed in 0.4.2; before that the whole `os.environ` was forwarded to every step, and the injected host `PATH` shadowed the image's `/opt/venv/bin`, breaking uv repos with `ModuleNotFoundError`.

---

## G4 — `visual_similarity` artifacts silently failed (pre-0.2.6)

**Symptom.** Every metric shows `ok`; `plutus check` exits 1. No surfaced reason on screen.

**Diagnosis (0.2.5).** `compare_artifact` had a strict gate: missing `.plutus/expected/` → `ok=False`, which `_exit_code` gated on. Artifact results weren't rendered in the report.

**Fix (0.2.5+, the correct way).** Populate `.plutus/expected/<step>/<chart_path>` from README-referenced charts during Phase 3 step 5b (manifest authoring). This captures the v1-committed bytes as the verification baseline before any new execution overwrites the files. See **G7** for the gotcha of doing this via `plutus snapshot` at the wrong time.

**Fix (0.2.6+).** Missing snapshot is now a non-blocking SKIP for `visual_similarity`. The Phase 3 step 5b baseline copy is still essential — without it, the maintainer gets a green `plutus check` but every `visual_similarity` check is a non-verifying SKIP. The Skill's job is real verification, so the copy stays required.

**Fix (0.2.7+).** With the baseline copy in place, `visual_similarity` falls back to byte comparison when no LLM is configured: byte-identical → real `ok byte_identical`; byte-different → `WARN byte_identical` (non-blocking). See [`v0.2.7.md`](v0.2.7.md).

---

## G5 — Container stderr/stdout swallowed (pre-0.2.6)

**Symptom.** Step FAILs `exit=1`, report shows no diagnostic.

**Diagnosis.** `DockerRunner.run` captured stdout/stderr but the report renderer didn't surface them per-step pre-0.2.6.

**Fix.** Manual repro:
```bash
docker run --rm \
  --network=<bridge|none from manifest> \
  -v "$PWD:/srv/repo" -w /srv/repo \
  plutus-v2:<hash> bash -c "<step command> 2>&1; echo EXIT=\$?"
```
0.2.6 added per-step artifact rendering. Step stderr surfacing is still a separate deferred item — manual repro remains the diagnostic path.

---

## G6 — SDK rejects `Decimal` metric values

**Symptom.**
```
ValueError: metric value must be a number; got Decimal
```

**Diagnosis.** Metric helpers return `Decimal` (common in repos that use `Decimal` for monetary precision: `bt.metric.sharpe_ratio`, `bt.metric.hpr`, etc.). The SDK's `r.metric(name, value)` accepts only `int|float`.

**Fix.** Cast at the call site:
```python
r.metric("sharpe_ratio", float(bt.metric.sharpe_ratio(...) * Decimal(np.sqrt(250))))
```

Wrap every `r.metric()` value in `float(...)` when the helper returns `Decimal`. Same for `r.artifact()` paths (always `str`) and `r.metadata()` values (must be JSON-serializable — cast `Decimal` → `float`).

---

## G7 — Chart baseline captured after smoke-run is tautological

**Symptom.** `plutus check` exits 0 with `--visual-check` configured. Every `visual_similarity` line is `ok`. But a deliberate change to the script that visibly alters a chart still produces `ok` — the LLM judges them similar because they really are: it's comparing the new run against itself.

**Diagnosis.** Older versions of this Skill ran `plutus snapshot --no-run --no-metrics .` in Phase 4 step 2, *after* the Phase 4 step 1 smoke-run. The smoke-run on the host overwrites the v1-committed chart files (`result/backtest/*.svg`). Snapshot then captures the smoke-run's output as the baseline. `plutus check` runs the script again (in Docker), overwriting the file once more, then compares the new output to the snapshot — which is the *previous* output of the *same* script. Tautological.

**Fix.** Capture the baseline **before** any host execution. The current Skill shape does this in Phase 3 step 5b: while authoring the manifest, copy each README-referenced chart from `<repo>/<path>` directly into `.plutus/expected/<step_id>/<path>`. This uses the v1-committed bytes — the actual reference the README claims. Then the smoke-run can overwrite the live `result/` files harmlessly; `.plutus/expected/` is already preserved.

**Detection.** After the Skill completes, eyeball the bytes of one chart:

```bash
diff -q .plutus/expected/<step_id>/<chart_path> \
        <(git show HEAD:<chart_path>)
```

Empty output (no difference) means baseline matches the v1 commit — correct. Any diff means the baseline was contaminated by a smoke-run or other execution.

**Reproducibility implication.** A divergence test (modify a plot title; re-run) should produce `FAIL visual_similarity` with `--visual-check` configured, or `WARN byte_identical` on 0.2.7+ without an LLM. If both return `ok`, you're hitting G7.

---

## G11 — Runtime volume mount bypasses `.dockerignore` (v0.2.9 only)

> **Status:** Closed on `plutus_verify >= 0.2.10` — each step runs in a
> filtered staging copy, not against the maintainer's cwd. The recipe
> below remains useful only for diagnosing whether you're on a
> pre-0.2.10 framework.

**Symptom.** `data_preparation` (or any Tier 3 bridge step) exits 0 quickly. With `--secrets-from-env` and no `DB_*` env vars in the host shell (`env | grep '^DB_'` returns nothing), the step still passes. On the second `plutus check` run, the host's cached parquet's mtime is unchanged — the DB was never queried.

**Diagnosis.** 0.2.9's `.dockerignore` correctly excludes `.env`, `data/cache/`, etc. from the **image build context**. But `runner_docker.py` runs each step with `-v {cwd}:/srv/repo`, which is an **unfiltered Docker volume mount**. The mount overlays the host's full working directory onto the container — `.dockerignore` is a build-context concept and doesn't apply at runtime.

Result: even on 0.2.9, the container sees the host's `.env` (read by `config/secrets.py`'s pydantic-settings) and the host's `data/cache/*.parquet` (`run_data_loader fetch` is cache-first and short-circuits).

Verify by mtime:

```bash
# Pre-run mtime
stat -f '%Sm' data/cache/<symbol>/1min/<month>.parquet

plutus check . --secrets-from-env

# Post-run mtime — unchanged = short-circuited via mount
stat -f '%Sm' data/cache/<symbol>/1min/<month>.parquet
```

Confirm `.env` is reachable via the mount:

```bash
docker run --rm -v "$PWD:/srv/repo" plutus-v2:<tag> ls -la /srv/repo/.env
# If this lists the file, the mount is exposing it (image layer is still clean)
```

**Fix (until the volume mount is reworked in a future release).**

```bash
rm -rf data/cache/      # or whichever ephemera dirs the loader checks
plutus check . --secrets-from-env
```

If the bridge step now fails (no creds in shell, no `.env` readable via mount), wire `--secrets-from-env` properly: re-key `.env` to use the prefix the code expects (e.g. `DB_*` for `pydantic env_prefix="DB_"`), and either `eval "$(grep -E '^DB_' .env | sed 's/^/export /')"` or export the keys directly in the shell. Then re-run.

**Scoring implication.** Report this in Phase 4.5 as a verification-correctness caveat. The step's `ok` is real-but-conditional: it depends on the maintainer having cleared host caches and exported secrets explicitly. Compliance scoring on Tier 3 repos should not over-credit "Reproducible" until the mount-layer fix lands.

---

## G12 — All execution steps FAIL exit=2 after declaring `step.inputs` (v0.2.10+)

**Symptom.** `plutus check` reports `FAIL <step>: exit=2` for every step whose `command:` runs a Python script. Optimization steps (`artifact_check` mode) and chart artifact comparison may still pass — the failure is specifically in script execution.

**Diagnosis.** v0.2.10 introduced per-step staging ([`plutus_verify/spec/runtime/staging.py`](../../../plutus_verify/spec/runtime/staging.py)). When `step.inputs` is declared non-empty, it's a **complete-coverage allowlist**: only paths matching the patterns get copied to staging. If you listed just the "data inputs" (e.g. `[reports/IS/result.json]`) without also listing the script binary and source-tree dirs, the script itself isn't in staging — `python <script>` exits 2 with "No such file or directory."

Confirmed via container stdout:

```
python: can't open file '/srv/repo/scripts/plutus_emit_in_sample.py': [Errno 2] No such file or directory
```

**Fix.** Either set `inputs: []` (lets `.dockerignore`-only filter handle the default copy — same as v0.2.9 behavior) OR expand `inputs` to cover every file the script needs.

- For Tier 3 `data_preparation`, typical minimum: `[src/, config/, pyproject.toml, .env.example]`.
- For wrapper scripts: `[scripts/<wrapper>.py, reports/<run>/]`.

**Detection.** Manual repro (bypasses staging by mounting cwd directly — only works as a diagnostic, not a production substitute):

```bash
docker run --rm --network=none \
  -v "$PWD:/srv/repo" -w /srv/repo \
  <image> bash -c "<step.command> 2>&1; echo EXIT=\$?"
```

If this succeeds (because the host's full tree is mounted), then the step works in principle — the failure is staging-filter scope, not a real bug. Compare what the manual repro had access to vs what `step.inputs` declared.

**Recommended default.** Start every new manifest with `inputs: []` per step. Tighten step-by-step only after confirming the manifest works at the looser default. See the updated Phase 3 step 6.5 guidance in [`v0.2.10.md`](v0.2.10.md).

---

## G13 — `google_drive` data source fails host-side with `ModuleNotFoundError: gdown` (0.5.0+)

**Symptom.** `plutus check` prints `gdown failed for <url>: No module named 'gdown'`, skips the Drive fetch, falls back to the `data_preparation` command (which then crashes if it needs DB secrets), and every downstream backtest step FAILs `FileNotFoundError` on its input CSV (e.g. `data/is/pe_dps.csv`).

**Diagnosis.** The Drive fetch runs in the **host** `.venv`, not in-container. `gdown` ships only in plutus-verify's `runner` extra (`runner = ["docker>=7.0", "jupyter-repo2docker>=2024.3", "build>=1.0", "gdown>=5.0"]`), but the base release wheel does not include it. So any **D1 = Drive-backed (Tier-2)** repo hits a missing-`gdown` error host-side even on 0.5.0+. (`references/v0.5.0.md`'s "works out of the box" note holds only when the SDK is installed *with* the `runner` extra.)

**Fix.** Install the `runner` extra (or `gdown` directly) into the smoke `.venv` during pre-flight step 2 / Phase 3 step 2:

```bash
uv pip install "plutus-verify[runner] @ $WHL"   # $WHL = the GitHub release wheel URL
# or, minimally:
uv pip install 'gdown>=5.0'
```

Re-run `plutus check`. Do this for **every Tier-2 repo** — it's an env/tooling step, not a manifest fix.

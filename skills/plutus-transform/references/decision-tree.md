# Decision tree (Phase 2)

The (up to 5) mutually-exclusive choices presented in Phase 2's single `AskUserQuestion` call. Each entry: question, options, recommended default, rationale.

> Sources:
> - [docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md](../../../docs/plan/2026-05-27-skill-design-v1-to-v2-transformer.md) §3 Phase 2
> - [docs/others/zbounce-v1-to-v2-upgrade.md](../../../docs/others/zbounce-v1-to-v2-upgrade.md) §2

---

## D1 — Data sourcing tier

**Header**: `Data tier`

**Question**: "How should the backtest data be sourced?"

**Options**:
- **DB-backed loader in container** (Tier 3) — `data_preparation` step runs `network: bridge`, reads DB secrets from `.env`. *(Recommended when a working DB-loader script exists and the repo has no Drive folder shipping every required file.)*
- **Drive-backed raw data** (Tier 2) — `data_sources.raw[]` entry with `kind: google_drive`. `data_preparation` keeps a download command but the verifier skips if the Drive fetch succeeds.
- **Processed CSVs committed** (Tier 1) — `data_sources.processed[]` entry; `data_preparation` step omitted entirely. Requires overriding any `*.csv` in `.gitignore`.
- **Layered (Drive primary + DB fallback)** — Most flexible, most manifest complexity. Recommend against unless explicitly needed.

**Default**: DB-backed (Tier 3). Pick Tier 2 only if a Drive folder ships *all* required files. Pick Tier 1 only if data is small and the maintainer is OK committing it. Avoid layered for v1 of any repo's plutus integration.

---

## D2 — Optimization verification mode

**Header**: `Opt mode`

**Question**: "How should the optimization step be verified?"

**Options**:
- **`artifact_check`** — Verifier confirms `parameter/optimized_parameter.json` exists; no execution. *(Recommended for stochastic optimizers — Optuna, Hyperopt — even with seed pins, since re-runs cost minutes.)*
- **`execute`** — Verifier re-runs the optimizer in-container every check. Validates true reproducibility at the cost of ~5+ minutes per run.

**Default**: `artifact_check`. Matches USER_GUIDES §7.4 recommendation for stochastic optimization stages.

---

## D3 — Paper-trading inclusion

**Header**: `Paper trade`

**Question**: "Should paper/live trading be included as a verified step?"

**Options**:
- **Skip** — Live FIX/Kafka entrypoints aren't reproducibly verifiable. Document in `nine_step_coverage.step_7_paper_trading: {present: true, section: "Paper Trading"}` so the report acknowledges it. *(Recommended.)*
- **`artifact_check` against frozen report** — Requires the repo to commit a static report file that the verifier checks for existence. Only useful if such a file already exists.

**Default**: Skip.

---

## D4 — README claims vs script output as truth

**Header**: `Truth source`

**Question**: "Should the manifest treat README-claimed metrics or current script output as authoritative?"

**Options**:
- **Path A — README claims** — `expected.metrics[].value` = README numbers. Chart baselines under `.plutus/expected/<step>/<path>` also come from README-referenced (v1-committed) files, captured during Phase 3 step 5b before any execution. Any script drift FAILs `plutus check`. *(Recommended — the verifier exists to catch regressions against the public claim.)*
- **Path B — Script output** — `expected.metrics[].value` populated from current run. Chart baselines come from `plutus snapshot --no-run --no-metrics` after the Phase 4 smoke-run. `plutus check` always passes; the script is declared authoritative. Use only if README is intentionally out of date during a research iteration.

**Default**: Path A.

---

## D5 — Env reproducibility (port to uv)

**Always asked**, regardless of whether Phase 1 detected a conflict. A non-uv / lockfile-less env is now reported as `env: NOT reproducible` (a deprecation, becoming a soft-fail exit 1 later), so the env must be brought up to the `manager: uv` + committed-lockfile contract. Declaring deps in `pyproject.toml` and running `uv lock` once surfaces any conflict explicitly at lock time, and committing `uv.lock` makes the env reproducible. The Z-Bounce / ProtoMarketMaker pin conflicts are now resolved by loosening the one offending constraint and re-locking. See G2 in [`known-gotchas.md`](known-gotchas.md).

The target state is `pyproject.toml` + committed `uv.lock` (`env.manager: uv`, `env.lockfile: uv.lock`). A `requirements.txt` (or a pin-only `pyproject.toml` with no lockfile) is a deprecated fallback to be PORTED: declare deps in `pyproject.toml`, run `uv lock`, commit `uv.lock`.

**Header**: `Env reproducibility`

**Question**: "How should the environment be made reproducible (uv lock + committed lockfile)?"

**Options**:
- **Port to uv** *(Recommended; default)* — declare deps in `pyproject.toml`, run `uv lock` once, commit `uv.lock`, and set `env.manager: uv` + `env.lockfile: uv.lock`. Pins are kept and resolved into the lockfile; `uv sync --frozen` is the install path. This is the only option that satisfies the reproducibility contract.
- **Loosen + re-lock** — the conflict-resolution escape hatch: when `uv lock` reports a conflict, loosen the ONE offending constraint in `pyproject.toml` (e.g. relax `numpy`) and re-run `uv lock`. A sub-case of the uv port, never a strip-all.
- **Keep as-is** — only valid when a sound `pyproject.toml` + `uv.lock` already exist: keep them and set `env.manager: uv` + `env.lockfile: uv.lock`. A repo with pins but no lockfile is NOT reproducible — it is reported `env: NOT reproducible` (warn-only now, soft-fail exit 1 later), so this is not a benign do-nothing for lockfile-less repos.

**Default**: Port to uv (run `uv lock`, commit `uv.lock`).

**Why this still asks**: Phase 2 asks because the uv port modifies tracked files — editing `pyproject.toml` deps and adding the committed `uv.lock` (and setting `env.manager` / `env.lockfile` in the manifest). The maintainer is told once, defaults through, and the changes land as a reviewable commit on the `plutus-verify-v2` branch — fully reversible by branch switch.

---

## Output of Phase 2

Five decisions on record. Each is short-lived state used by Phase 3:
- D1 → which manifest template in `manifest-templates/` to load
- D2 → `verification_mode` field on the optimization step
- D3 → whether to add a step or just `nine_step_coverage` entry for paper trading
- D4 → whether `expected.metrics[].value` and `.plutus/expected/<step>/<path>` chart baselines come from README (path A; copied in Phase 3 step 5b) or smoke-run output (path B; captured by `plutus snapshot` in Phase 4 step 2)
- D5 → how the env is ported to uv (`uv lock` + committed `uv.lock`) and the resulting `env.manager: uv` / `env.lockfile: uv.lock` manifest fields

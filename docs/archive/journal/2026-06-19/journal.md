---
archive-date: 2026-06-19
features: [reproducible-env-uv]
captures: "bug-fix: 2, brain-dump: 1, report: 1"
plans: 0
---

# Development Journal — Archived 2026-06-19

## Timeline

### 2026-06-18 17:01 — reproducible-env-uv: Brain dump (precompact)
Pre-compact state snapshot taken right after the 0.4.0 cycle was archived; enriched post-hoc once the follow-on runtime bugs landed.

### 2026-06-18 17:19 — reproducible-env-uv: Bug fix — uv-locked env steps fail at runtime (login shell drops the venv PATH)
A `manager: uv` repo built green but every step exited 1 with `ModuleNotFoundError`: the runner ran steps under a login shell (`bash -lc`) which re-sourced `/etc/profile` on the Debian slim base and reset `PATH`, dropping the `/opt/venv/bin` the uv Dockerfile sets. Fix: `bash -lc` → `bash -c`. Shipped 0.4.1.

### 2026-06-19 10:16 — reproducible-env-uv: Bug fix — `--secrets-from-env` forwarded the entire host environment
After the 0.4.1 fix, uv steps still failed under `--secrets-from-env` (even with `secrets: []`): the CLI built `dict(os.environ)` and the orchestrator injected the whole dict as `-e KEY=VALUE`, so a host `-e PATH` re-hid the venv. Fix: `orchestrator._resolve_step_secrets` injects only declared secret keys scoped per `used_by`, plus a reserved-key denylist. Shipped 0.4.2.

### 2026-06-19 — reproducible-env-uv: Source bug report (from mtime; no frontmatter)
The incoming handoff `plutus-verify-uv-runner-bug.md` from the 9-step dev-tooling session documenting both runtime bugs; updated to mark Bug #1 (0.4.1) and Bug #2 (0.4.2) FIXED.

## Per-feature summary

### reproducible-env-uv
The 0.4.0 feature (uv-locked environments, archived 2026-06-18) shipped the
*contract* but two runtime bugs meant uv steps couldn't actually execute. This
cycle closed both, discovered downstream while the 9-step plugin migrated its
example repo to the uv standard. **0.4.1** fixed the runner's login shell
(`bash -lc` → `bash -c`) that reset `PATH` and hid the `/opt/venv` venv.
**0.4.2** fixed `--secrets-from-env`, which forwarded the entire host
`os.environ` to every container — both a leak (host env contaminating the
"reproducible" container) and a correctness hazard (the injected host `PATH`
re-hid the venv exactly as the login shell had). The fix scopes injection to
declared secret keys per `used_by` (mirroring the long-correct v1 path), with a
reserved-key denylist so a secret named `PATH` can't re-open the channel. The
0.4.2 fix was adversarially verified by a 4-lens workflow (leak-completeness,
correctness, regression, docs-alignment); the reserved-key guard came directly
from that review.

## Summary

This archive covers the post-0.4.0 runtime hardening of **reproducible-env-uv**.
Work spanned 2026-06-18 → 2026-06-19: 2 bug-fix captures, 1 enriched brain-dump,
and the source handoff report. Both bugs shared a signature — *something
overwrites the container's `PATH` and hides the uv venv* — and the same class of
test gap. Notable lessons:

- **`dockerfile_gen` and `runner_docker` are a contract pair.** The venv is
  activated purely by `ENV PATH=/opt/venv/bin:$PATH`; anything that resets or
  overrides `PATH` at run time (a login shell; an injected `-e PATH`) silently
  breaks it. Validate venv activation *through the runner*, not by asserting
  Dockerfile text.
- **Never forward the whole host environment into a "reproducible" container.**
  Inject only declared secrets, scoped to the steps that need them; a reserved-key
  denylist stops a declared `PATH`/`HOME` from re-opening the leak.
- **A Dockerfile-string assertion can't see the runner or the injected env.**
  Both fixes needed runner/orchestrator-level tests (`test_runner_docker.py`,
  `test_orchestrator_secrets.py`); a real docker-gated integration test that runs
  a `manager: uv` step end-to-end is still the missing fuller guard.

## Archived Files

### Captures
- capture/reproducible-env-uv/2026-06-18-1701-brain-dump.md
- capture/reproducible-env-uv/2026-06-18-1719-bug-fix.md
- capture/reproducible-env-uv/2026-06-19-1016-bug-fix.md
- capture/reproducible-env-uv/plutus-verify-uv-runner-bug.md (source report; no frontmatter)

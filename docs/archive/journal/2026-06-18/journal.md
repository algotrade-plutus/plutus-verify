---
archive-date: 2026-06-18
features: [reproducible-env-uv]
captures: "complete: 1"
plans: 0
---

# Development Journal — Archived 2026-06-18

## Timeline

### 2026-06-18 16:18 — reproducible-env-uv: Complete
Gave plutus-verify a first-class notion of a reproducibly-locked environment: a
manifest can declare `env.manager: uv` + a committed `uv.lock`, restored exactly
with `uv sync --frozen` instead of re-resolving at build time. Shipped as B1
(verify-side capability) and B2 (the `plutus-transform` skill reframed to
uv-lock-first), released as 0.4.0.

## Per-feature summary

### reproducible-env-uv
Single-session feature (2026-06-18). **B1** added `env.manager` / `env.lockfile`
to the manifest, a uv build path that restores the lockfile into a venv *outside*
`/srv/repo` (so the per-step staging mount can't shadow it), and an
`env: NOT reproducible` warn-only soft-fail seam (`V2RuntimeResult.env_reproducible`).
**B2** reframed the `plutus-transform` skill from strip-pins / requirements-first
to uv-lock-first: D5 became "env reproducibility — port to uv", G2 became
"loosen the one offending constraint and re-lock". Orchestrated with two
workflows (discovery + adversarial verification, all-pass); 538 tests green;
released 0.4.0.

## Summary

This archive covers development of **reproducible-env-uv**. Work began and
completed on 2026-06-18. One `complete` capture was written (complete: 1).
Notable lessons:

- The 0.2.10 per-step staging mount overlays `/srv/repo` at run time, so a uv
  venv must live outside it (`UV_PROJECT_ENVIRONMENT=/opt/venv`); pip's system
  site-packages survive for the same reason.
- uv-created venvs ship without pip — install the verifier SDK via
  `uv pip install --python /opt/venv/bin/python`.
- A committed lockfile is the real dependency-reproducibility lever; stripping
  pins (the old D5 default) traded reproducibility for buildability, which is the
  wrong tradeoff once uv pins everything via the lockfile.

## Archived Files

### Captures
- capture/reproducible-env-uv/2026-06-18-1618-complete.md

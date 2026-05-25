# plutus-verify v2 — completion reports

The v2 work shipped in four phases on the `feat/spec-v2-foundation` branch
(65 commits ahead of `main`, 485 tests passing). Each phase has its own
completion report.

| Phase | Theme | Reports |
|---|---|---|
| **A** | The v2 manifest format | [phase-a-v2-manifest-format.md](2026-05-25-phase-a-v2-manifest-format.md) (Plans 1–5) |
| **B** | Output-side standardization | [phase-b-output-side-standardization.md](2026-05-25-phase-b-output-side-standardization.md) (Plan 6 + rename) |
| **C** | Production polish | [phase-c-production-polish.md](2026-05-25-phase-c-production-polish.md) (Plans 7–9) |
| **D** | Integrity hardening | [phase-d-integrity-hardening.md](2026-05-25-phase-d-integrity-hardening.md) (Plan 10) |

For the design history (why each decision was made), see [`docs/plan/`](../plan/).

## TL;DR — what shipped

A working Plutus v2 verifier MVP, end-to-end. Validated against the
upstream `ProtoMarketMaker` strategy: ≈90% confirmed working (the user's
phrase — the ≈10% is untested edge cases that may surface in future flows).

**The author workflow:**

```
write strategy code
  → instrument with `import plutus_verify as pv` + `with pv.step(...) as r: r.metric(...)`
  → run scripts locally to produce .plutus/run/<step>/results.json
  → `plutus bootstrap` to auto-generate .plutus/manifest.yaml.draft
  → fill in 8 grep-able TODO_* markers (see .plutus/manifest_TODO.md)
  → rename .draft → .yaml
  → `plutus check .` (Docker run + comparison)
  → review diff, commit
```

**The verifier path:**

```
clone the repo
  → `plutus check .`
  → reads .plutus/manifest.yaml
  → builds Docker image with the SDK auto-bundled
  → runs each step in the container
  → reads .plutus/run/<step>/results.json (SDK-written)
  → compares metrics by snake_case name against expected.metrics within tolerance
  → grouped 9-step report; exit code reflects whether the strategy reproduced
```

**Test coverage end-state:** 485 tests passing (unit + integration).

**Integration evidence:** the `out/transfer-test/ProtoMarketMaker/` sandbox
ran end-to-end via Docker multiple times across Plans 5, 6, 7, 9, and 10.
Final verdict: 6/6 in-sample metrics pass, 3/6 OOS pass (Sharpe/Sortino/HPR
diverge ~26% — surfaced as a real reproducibility finding in the upstream
repo, not a verifier bug).

## Out of scope (future work)

- PyPI publish — runbook ready at [`docs/runbook/publishing-to-pypi.md`](../runbook/publishing-to-pypi.md); pending decision
- GPU support (`env.base=python-cuda`)
- S3 data-source downloader
- `plutus render-readme` (manifest → README templating)
- Deletion of v1 `extract/plan.py` and the legacy LLM pipeline branch

---
name: plutus-scoring
description: Use when scoring a Plutus-v2 compliant repo against the compliance rubric — recognises phrases like "score this repo's plutus compliance", "what's our plutus score", "rate this repo for plutus-verify", "how plutus-compliant is this", "plutus compliance score". Emits per-bucket scores (50/25/10/15), ranked improvement paths, and a copy-pasteable re-run command. Standalone-invokable on any v2 repo, or auto-chained from `plutus-transform` after a clean transform.
---

# plutus-scoring

Apply the 50/25/10/15 PLUTUS compliance rubric to a v2-compliant repo and produce three actionable outputs: a per-bucket score, ranked improvement paths, and a re-run command the maintainer can use to re-verify any time.

Standalone-invokable on any v2 repo. Also auto-chained from [`plutus-transform`](../plutus-transform/SKILL.md) as its final hand-off step after a clean transform — the chain passes context via the transform skill's Phase 4.5 summary (architectural smells worked around but not fixed).

## Pre-flight (before Phase 1)

1. **Confirm target repo path.** Default to CWD; accept an explicit path argument.
2. **Confirm v2-compliance.** Check that `<repo>/.plutus/manifest.yaml` exists and loads:
   ```python
   from plutus_verify.spec.loader import load_manifest
   load_manifest("<repo>/.plutus/manifest.yaml")
   ```
   If missing or invalid, fail fast: "This repo is not v2-compliant — no loadable `.plutus/manifest.yaml`. Run `plutus-transform` to bring it up to v2, or `plutus init` to scaffold from scratch."
3. **Probe `plutus_verify` version.** `python -c "import plutus_verify; print(plutus_verify.__version__)"`. If a matching `references/v<minor>.md` exists, load it for scoring nuances (e.g., 0.2.7+ treats `WARN byte_identical` as a Reproducible pass).
4. **Detect chain context.** If invoked from `plutus-transform`, the parent skill writes a brief "Phase 4.5 summary" into the transcript (architectural smells worked around, decisions made). Capture this so Phase 2 can surface it in item 4 of the rubric output. When invoked standalone, item 4 is omitted.

## Phase 1 — Score

Apply [`references/compliance-rubric.md`](references/compliance-rubric.md).

For each bucket (Reproducible 50, Tidy 25, Standardized 10, Innovative 15):

1. Read the rubric's bucket-by-bucket scoring guide.
2. Inspect the target repo against the criteria:
   - **Reproducible** — does `plutus check` exit 0? Were any manifest-side workarounds applied (network routing, secret routing to non-DB steps, etc.)? Were any tracked config files modified? Use the `plutus check` output (run it if necessary, or rely on the chain-context transcript from `plutus-transform`).
   - **Tidy** — read the README; check for the ~5 sub-points (structure, `.env.example`, documented inputs, parameter pipeline accuracy, Python pin + CI).
   - **Standardized** — check for the canonical 4-step shape, parameter externalization, predictable chart paths, no module-level side effects.
   - **Innovative** — survey the metric set and analytical surface. Novel metrics or non-textbook strategy logic earn this bucket.
3. Emit one line per bucket: `"<Bucket>: <score>/<weight> — <one-line reasoning>"`.

## Phase 2 — Improvement paths

Concrete, ranked, ≤4 items. Each item:

- **Names a specific bucket and a specific delta.** Not "improve Tidy" but "Tidy +5: add `.python-version` (currently relies on system Python)".
- **Maps to a concrete file/line/setting** where possible.
- **Estimates the cost** — typically "one-line change", "ten-minute edit", or "PR-scale rework".

Prefer cheap wins first. A 5-point bump in Tidy from quoting placeholders in `.env.example` outranks a 15-point Innovative bump that needs a research effort.

If invoked as a chain from `plutus-transform`, also emit item 4:

- **"Architectural smells we worked around but didn't fix"** — from the parent skill's Phase 4.5 summary. These are detection-only pointers; the Skill never silently fixes them. Example: "Module-level DB connection at `database/data_service.py:102` — manifest workaround routes DB secrets to backtest steps; clean fix is to make the connection lazy."

When invoked standalone, item 4 is omitted (no chain context).

## Phase 3 — Re-run command

Emit a copy-pasteable terminal block the maintainer can run any time to re-verify, independent of any Skill session. Read the target's `.plutus/manifest.yaml` for `secrets[]` and the current branch:

```bash
git checkout <BRANCH>           # branch where the v2 work landed
source .venv/bin/activate
eval "$(grep -E '^(<SECRET_KEY_1>|<SECRET_KEY_2>|...)=' .env | sed 's/^/export /')"
plutus check . --secrets-from-env
echo "exit=$?"
```

Fill `<BRANCH>` from `git branch --show-current` (or the parent skill's transform branch if chained). Fill `<SECRET_KEY_N>` from the manifest's `secrets[].key`. If the manifest declares no secrets, drop the `eval` line. If `data_sources.processed` covers everything (no network needed), `--secrets-from-env` can also be dropped.

## Verification before completion

Mechanical checks before declaring done:

- Per-bucket score is emitted with one-line reasoning for each of the four buckets.
- Total score is emitted, rounded to 5%.
- Improvement paths are concrete (each names a file, line, or specific change) and ranked by cost.
- Re-run command block is visible in the transcript with concrete `<BRANCH>` and `<SECRET_KEY_N>` substitutions made.
- If chained from `plutus-transform`, item 4 (worked-around smells) is also present.

If any check fails, do **not** declare done. Re-read the target's manifest / source state and re-score.

## Interaction model

- Non-interactive. The Skill applies the rubric and emits its output; no user decisions required.
- Does **not** modify the repo. Read-only on the target tree. The re-run command is a recipe for the maintainer to invoke later, not something the Skill runs.
- Does **not** invoke `plutus check`. The score is derived from inspecting the repo state (manifest, scripts, README, recent check output if present in transcript). If a fresh `plutus check` is needed, the maintainer runs the re-run command emitted in Phase 3.

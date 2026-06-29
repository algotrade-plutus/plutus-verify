---
feature: plutus-standardize
type: skill-feedback
date: 2026-06-29
time: 08:32
source-skill: plutus-standardize
tags: [skill, standardize, tier-2, google-drive, gdown, dockerignore, install, github-release, "0.5.1"]
---

# Skill feedback → fix — Tier-2 Drive `gdown`, hand-written `.dockerignore`, and the GitHub-release install path

> Surfaced while running `plutus-standardize` (0.5.1) end-to-end on a **Tier-2,
> Drive-backed** strategy repo (ProtoSmartBeta). The run produced a `skill-feedback.md`
> with two ready-to-promote divergences; both are now folded into the skill, along with
> a third change — making the GitHub release wheel the single canonical install path.
> Promotions landed in [`skills/plutus-standardize/`](../../../skills/plutus-standardize/):
> SKILL.md, `references/known-gotchas.md` (new **G13**), `references/v0.5.0.md`,
> `references/v0.2.8.md`.

---

## Problem 1 — `google_drive` data source fails host-side with `ModuleNotFoundError: gdown`

**Symptom.** The first real `plutus check` aborted the Drive fetch:

```
gdown failed for https://drive.google.com/drive/folders/...: No module named 'gdown'
```

The verifier fell back to the `data_preparation` command (`python data_loader.py`),
which crashed (no DB secrets), and every downstream backtest step then FAILed
`FileNotFoundError: data/is/pe_dps.csv`.

**Diagnosis.** The Drive fetch runs in the **host** `.venv`, not in-container. `gdown`
ships only in plutus-verify's `runner` extra
(`runner = ["docker>=7.0", "jupyter-repo2docker>=2024.3", "build>=1.0", "gdown>=5.0"]`),
but the skill's pre-flight installed the **base** wheel (`uv pip install plutus-verify`),
which doesn't pull extras. So any **D1 = Drive-backed (Tier-2)** repo hits a missing-`gdown`
error exactly where the fetch needs it. The skill's own `references/v0.5.0.md` claimed
`google_drive` sources "work out of the box (no more `ModuleNotFoundError: gdown`)" — true
only when the SDK is installed **with the `runner` extra**, which the skill never did.

**Fix (skill).** Install the `runner` extra into the smoke `.venv` for Tier-2 repos:

```bash
uv pip install "plutus-verify[runner] @ $WHL"   # $WHL = the GitHub release wheel URL
# or, minimally:
uv pip install 'gdown>=5.0'
```

Promoted as **G13** in `references/known-gotchas.md`; the "out of the box" claim in
`references/v0.5.0.md` was corrected; pre-flight step 2 and Phase 3 step 2 in SKILL.md
now install `plutus-verify[runner]` for D1 = Drive repos. This is an env/tooling step,
not a manifest fix — it applies to every Tier-2 repo.

## Problem 2 — a hand-written `.dockerignore` excluded `.plutus/build/` and broke the image build

**Symptom.** `plutus init` was intentionally skipped (it can scaffold a manifest and would
risk clobbering the authored one), so per v0.5.0's note that `init` scaffolds
`.dockerignore`, the operator hand-wrote one. The first version excluded `.plutus/build/`
to keep the build context lean. The image build then failed:

```
COPY .plutus/build/plutus_verify-0.5.1-py3-none-any.whl /tmp/...
  ERROR: failed to compute cache key: ".plutus/build/plutus_verify-...whl": not found
  WARN: CopyIgnoredFile: ... excluded by .dockerignore (line 8)
```

**Diagnosis.** The verifier stages **its own SDK wheel** into `.plutus/build/` and the
generated Dockerfile `COPY`s it. Excluding that dir from the build context breaks the COPY.
The skill said `plutus init` scaffolds `.dockerignore` "so the skill no longer needs to
hand-write it" — but gave no guidance on what a safe hand-written one must preserve when
`init` is deliberately skipped.

**Fix (skill).** Documented in SKILL.md Phase 4 step 2 and `references/v0.5.0.md`: if you
hand-write `.dockerignore`, **never exclude `.plutus/build/`** (or
`.plutus/Dockerfile.generated`). Safe to exclude: `.git`, `.venv`, `__pycache__`,
`.plutus/run/`, `.plutus/results/`, `.plutus/cache/`.

## Change 3 — GitHub release wheel is the single canonical install path

plutus-verify is **not on PyPI**, yet the skill's install lines read `uv pip install
plutus-verify` / `pip install plutus-verify` (which silently fail) or "symlink the local
wheel" (a guess). The wheel is officially downloadable from the GitHub releases:
<https://github.com/algotrade-plutus/plutus-verify/releases>, per-version URL

```
https://github.com/algotrade-plutus/plutus-verify/releases/download/v<version>/plutus_verify-<version>-py3-none-any.whl
```

**Fix (skill).** SKILL.md pre-flight step 2 now states "not on PyPI", links the releases
page, and provides a `WHL=…` snippet; Phase 3 step 2 and the legacy `references/v0.2.8.md`
install lines reference `$WHL` instead of a PyPI name. This matches the pattern
`plutus-document` already used for the README reproduction block — all three plutus skills
now point at the same release-wheel source. No guessing, no PyPI, no local-path assumptions.

---

## Note — Phase-6 trigger did not fire (the real signal was env/tooling)

Phase 4 needed 3 `plutus check` runs to reach exit 0, but **none** were manifest revisions
— the manifest validated and was correct on first authoring. The three runs were:
(1) `.dockerignore` excluded `.plutus/build/` (Problem 2), (2) missing `gdown` (Problem 1),
(3) green. So the "3+ manifest revisions" Phase-6 trigger did not apply; the env/tooling
gotchas above were the real signal worth promoting.

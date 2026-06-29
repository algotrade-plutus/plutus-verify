---
feature: plutus-scoring
type: decision
date: 2026-06-29
time: 15:49
source-skill: user-request
tags: [plutus-scoring, plutus-document, badge, disclaimer, framing, reference-only]
---

# Compliance score + badge are framed as "reference only", not a quality grade

## Context
The `plutus-scoring` skill emits a 50/25/10/15 rubric score (rounded to 5%), and
`plutus-document` renders it as a prominent `PLUTUS-<n>%` README badge. The score is an
**LLM rubric judgment**: only the Reproducible-50 bucket is anchored to an objective fact
(`plutus check` exits 0); the other three (Tidy, Standardized, Innovative) are subjective
and drift with the scoring model's capability. As displayed, a reader naturally reads the
badge as a certified quality grade — overstating what the tool actually guarantees.

## Decision
Keep the scoring **concept and logic unchanged**, but add a clear **reference-only
disclaimer** so the score/badge are not mistaken for a quality rating. The tool's only
guarantee today is **reproducibility** (`plutus check` exit 0). Framing-only change; no
rubric weights, scoring procedure, or badge data source touched.

The disclaimer travels with both the skill and the generated artifact, enforced in five
places:
- [plutus-scoring/SKILL.md](../../../skills/plutus-scoring/SKILL.md) — "Status — reference
  only" callout; Phase 1 emits the disclaimer with the total; verification checklist
  requires it.
- [compliance-rubric.md](../../../skills/plutus-scoring/references/compliance-rubric.md) —
  same callout atop the rubric.
- [readme-template.md](../../../skills/plutus-document/references/readme-template.md) — a
  `<sub>` caveat line rendered directly under the badge row.
- [section-map.md](../../../skills/plutus-document/references/section-map.md) — caveat
  marked **required**, never dropped (even in standalone runs that leave the badge as-is).
- [plutus-document/SKILL.md](../../../skills/plutus-document/SKILL.md) — verification
  checklist enforces the caveat line is present.

Canonical wording: *"PLUTUS score is an LLM-assessed reference signal, not a certified
quality grade, and is subject to change. The verified guarantee is reproducibility —
`plutus check` exits 0."*

## Rationale
- **Honest scope.** Reproducibility is the falsifiable, deterministic guarantee; a rubric
  score is not. The framing matches what the tool can actually stand behind today.
- **LLM variance is real.** The same repo scored by different models (or the same model
  later) can land differently, especially on Tidy/Innovative. A badge implying a fixed
  grade would misrepresent that.
- **Cheapest correct fix.** A framing/disclaimer change preserves the useful signal
  (ranked improvement paths, a rough compliance sense) without pretending it's a
  certification — no logic risk, no re-scoring of existing repos.

## Alternatives considered
- **Drop the score/badge entirely** — rejected; the rubric + improvement paths are still
  a useful steer, just not a grade.
- **Make scoring deterministic / non-LLM** — out of scope now; the rubric's softer buckets
  resist a purely mechanical score. Revisit if/when the score needs to carry more weight.
- **Skill docs only (no README caveat)** — rejected (user chose "render under badge"); the
  badge is the most-seen surface, so the caveat must live where the badge lives.

## Consequences / watch-for
- Every newly generated/refreshed README carries the `<sub>` caveat under the badge;
  existing downstream READMEs only pick it up on the next `plutus-document` run.
- If scoring ever becomes deterministic or certified, this framing must be revisited
  (the "reference only" language would then understate it).
- Wording is duplicated across five files — keep it consistent if edited (the SKILL.md
  callout is the canonical source).

## Files changed
- `skills/plutus-scoring/SKILL.md`
- `skills/plutus-scoring/references/compliance-rubric.md`
- `skills/plutus-document/references/readme-template.md`
- `skills/plutus-document/references/section-map.md`
- `skills/plutus-document/SKILL.md`
</content>

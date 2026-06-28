---
feature: plutus-scoring-skill
date: 2026-06-01
version: 1.0
status: current
---

# `plutus-scoring` Skill

## What It Does

`plutus-scoring` is a Claude Code skill that applies the **PLUTUS compliance
rubric** to a v2-compliant repo and emits a weighted score, a ranked list of
improvement paths, and a copy-pasteable command to re-run the verification. It
recognizes prompts like "score this repo's plutus compliance", "what's our
plutus score", "rate this repo for plutus-verify", "how plutus-compliant is
this", and "plutus compliance score".

It is **read-only**: it does not modify the repo and does not itself run
`plutus check`. The score is derived from inspecting the manifest, scripts, and
README (plus any `plutus check` output already in the transcript). It can be
invoked standalone on any v2 repo, or it runs automatically at the end of
[`plutus-standardize`](plutus-standardize-skill.md).

## How It Works

A **pre-flight** confirms the repo path and v2-compliance (loads
`.plutus/manifest.yaml`, failing fast toward `plutus-standardize`/`plutus init` if
it's missing or invalid), probes the `plutus_verify` version, and detects
whether it was chained from `plutus-standardize`. Then three phases:

### Phase 1 — Score

For each of the four rubric buckets, inspect the repo against the criteria and
emit one line: `"<Bucket>: <score>/<weight> — <reasoning>"`.

### Phase 2 — Improvement paths

A ranked list of ≤4 concrete actions. Each names a specific bucket + score
delta, maps to a file/line/setting, and estimates cost ("one-line change" /
"ten-minute edit" / "PR-scale rework"). Cheap wins are ranked first. A fourth
item — "architectural smells we worked around but didn't fix" — only appears
when chained from `plutus-standardize` (which passes them in via its Phase 4.5
summary).

### Phase 3 — Re-run command

A copy-pasteable terminal block tailored to the repo: `git checkout <BRANCH>`,
activate the venv, optionally `eval` the secrets out of `.env`, then
`plutus check . --secrets-from-env; echo "exit=$?"`. The branch comes from
`git branch --show-current`; secret keys come from the manifest. The `eval` line
is dropped if there are no secrets, and `--secrets-from-env` is dropped if
`data_sources.processed` covers everything.

## The rubric

Four weighted buckets; the total is rounded to the nearest 5%.

| Bucket | Weight | What it measures |
|--------|--------|------------------|
| **Reproducible** | 50% | `plutus check` exits 0 and README metrics match within tolerance. Tiered: **50** clean / **45** after manifest-side workarounds / **35** after touching tracked config (e.g. `requirements.txt`) / **20** host-only / **0** not reproduced. |
| **Tidy / well-documented** | 25% | ~5 sub-points (~5 pts each): README structure + metric tables, `.env.example` parses with `source`, data inputs documented, optimization/parameter pipeline accurately described, `.python-version` + CI present. |
| **Standardized / template** | 10% | **10** = canonical 4-step shape (`data_preparation → in_sample_backtest → optimization → out_of_sample_backtest`), externalized `parameter/*.json`, predictable `result/{backtest,optimization}/` paths, no module-level side effects; **5** = one significant deviation; **0** = needs rework. |
| **Innovative** | 15% | **15** = novel metrics/diagnostics/strategy logic; **8** = thoughtful but conventional; **0** = textbook. |

## Configuration

```bash
bash skills/plutus-scoring/install.sh   # symlinks ~/.claude/skills/plutus-scoring → repo
```

Invoke with `/plutus-scoring` or a trigger phrase, pointing at a v2 repo.

## Usage Examples

### Standalone

```
/plutus-scoring   (then point it at the repo)
```

Produces the four bucket lines, ≤4 ranked improvement paths (no "smells" item),
and the re-run command.

### Auto-chained

Running `/plutus-standardize` to a clean `plutus check` automatically hands off
into `plutus-scoring` in the same session, with the transform's worked-around
smells surfaced as improvement-path item 4.

## Limitations & Caveats

- **Read-only and inference-based** — it does not run `plutus check`; the
  "Reproducible" score reflects check output already in the transcript (or the
  repo's evident state). The re-run command is a recipe to confirm later.
- **Requires a valid v2 manifest** — fails fast toward `plutus-standardize` /
  `plutus init` if the repo isn't v2-compliant.
- **Item 4 of improvement paths is chain-only** — omitted on standalone runs.

## Related Features

- [plutus-standardize-skill](plutus-standardize-skill.md) — the transformer that chains into this skill.
- [authoring-tools](authoring-tools.md) — `plutus check`, whose verdict feeds the Reproducible bucket.

## Source Materials

- Code: `skills/plutus-scoring/SKILL.md`, `skills/plutus-scoring/references/compliance-rubric.md`
- Report: `docs/completion-report/2026-05-27-v0.2.7-byte-fallback-and-skill-split.md`
</content>

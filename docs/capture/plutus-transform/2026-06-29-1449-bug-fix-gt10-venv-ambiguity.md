---
feature: plutus-transform
type: bug-fix
date: 2026-06-29
time: 14:49
source-skill: user-request (skill-feedback.md, ProtoSmartBeta run)
tags: [plutus-transform, GT10, gdown, uv-tool, drive-backed, tier-2, skill-fix]
---

# GT10 sent the gdown install to the wrong venv ("dev venv" was ambiguous)

## Symptom
On a Drive-backed (Tier-2) transform of **ProtoSmartBeta** (2026-06-29), the operator
followed GT10 literally and ran `uv pip install "plutus-verify[runner] @ $WHL"` into the
**project's `.venv`**. `gdown 6.1.0` installed cleanly there, but the next `plutus check`
still aborted the Drive fetch with:

```
gdown failed for https://drive.google.com/.../1bXCa...: No module named 'gdown'
```

Cost: one wasted `plutus check` run plus the diagnosis of the wrong-venv install.

## Root cause
The Google-Drive fetch runs **host-side, in the same interpreter that runs the `plutus`
CLI** — not the container, and not the repo being transformed. In code:
[data_resolver.py:173-187](../../../plutus_verify/spec/runtime/data_resolver.py#L173-L187)
→ [fetch.py:45-54](../../../plutus_verify/fetch.py#L45-L54), where `import gdown` happens
in the CLI process; on `ImportError` the resolver returns `False` and the fetch silently
fails.

On this run `plutus` was a **`uv tool` install** (global, isolated venv at
`~/.local/share/uv/tools/plutus-verify/`), so the project-`.venv` install was inert — the
fetch never executes from the project venv.

The bug was in the **skill text, not the framework**: GT10's Fix said *"install the runner
extra into the dev venv — `uv pip install ..."`*. "dev venv" reads naturally as the
project `.venv` (the venv you're working in for the repo), and only the `uv pip install`
form was given. That form is correct **only** when `plutus` is invoked from the project
venv (`uv run plutus`); for a `uv tool`/pipx install it does nothing.

## Fix
Narrowed and disambiguated GT10 (gdown-specific; not generalized — deferred until more
cases appear):
- **[references/known-gotchas.md GT10](../../../skills/plutus-transform/references/known-gotchas.md#L143)**
  — Cause now states the fetch runs "in the same interpreter that runs the `plutus` CLI"
  and names the code path. Fix splits into two install cases:
  - `uv tool` / pipx install → `uv tool install --force "plutus-verify[runner] @ $WHL"`
    (and an explicit note that a project-`.venv` install does nothing here);
  - invoked from the project venv → `uv pip install "plutus-verify[runner] @ $WHL"`.
  - Diagnostic added: `head -1 $(which plutus)` reveals the interpreter.
  - A **Provenance** note records the ProtoSmartBeta failure as the audit trail.
- **[SKILL.md Phase 5 step 2](../../../skills/plutus-transform/SKILL.md#L92)** — the
  one-liner now points at "the venv the `plutus` CLI runs out of" with the
  `uv tool install --force` form inline.

The fix is a doc/skill change only — no framework code changed; the verifier's behavior
was always correct, the gotcha just mis-described where to install the extra.

## Watch-for
- **The verifier swallows the failure as a WARNING, not a hard error** — `gdown failed
  ... No module named 'gdown'` is logged and the resolver returns `False`; the abort only
  surfaces downstream as missing `data/*.csv`. Easy to misread as a data-layout problem.
- **GT6 still holds**: this is dev-env tooling — `plutus_verify`/`gdown` never go in the
  project's `pyproject.toml`.
- **GT6's own "dev venv" wording** (known-gotchas.md ~L93) was left as-is — it's about
  *not* putting `plutus_verify` in `pyproject.toml`, a different concern. If the same
  ambiguity bites there, generalize the "host-side fetch runs in the CLI's interpreter"
  rule across both (deferred decision).

## Files changed
- `skills/plutus-transform/references/known-gotchas.md` (GT10 rewrite + provenance note)
- `skills/plutus-transform/SKILL.md` (Phase 5 step 2 pointer)

## Source
- `skill-feedback.md` (ProtoSmartBeta run, 2026-06-29) — the originating divergence report.
</content>

# Plutus v2 Spec — Live Verification Gap Closure (Plan 5 of 4+1)

> **Retrospective plan.** This work was not designed up-front — it emerged
> while running `plutus check` against a real ProtoMarketMaker repo end-to-end
> for the first time. The plan is documented after the fact so the gaps and
> the fixes are discoverable, and so a future reader can understand which
> parts of the v2 pipeline only exist because of contact with reality.

**Goal:** Close the gaps between the v2 native runtime (Plans 1–4) and what's
needed to actually run `plutus check` on a real Plutus repo with a real Docker
daemon. No new features — only the production gaps the live workflow surfaced.

**Commits:** `900b459` (five runtime fixes + `real_image_builder`),
`88ceaf3` (CLI: transfer prewarm + per-call progress).

**Architecture:** No new modules of significance; one new helper
(`real_image_builder.py`) and surgical changes to existing runtime modules.

---

## Why this plan exists

Plans 1–4 landed the v2 spec, native runtime, scaffold CLI, and legacy
transfer. They were unit-tested and passed integration tests with fake
in-process runners and stub image builders. The `plutus check` CLI subcommand
was wired but raised `NotImplementedError` because no real Docker
image-builder was attached. Running it end-to-end against ProtoMarketMaker
surfaced five distinct gaps in 90 minutes:

1. The CLI couldn't actually build images.
2. The data-source downloader didn't honor the manifest's declared layout.
3. The orchestrator couldn't handle `verification_mode: artifact_check`.
4. Docker mounts failed on relative `repo_path`s passed from the CLI.
5. Real scripts print metrics as plain text (`Sharpe ratio: 0.95`), not
   markdown tables — the v2 spec's `stdout_table` locator was insufficient.

Separately, the transfer subcommand felt broken under real LLM loads — the
30–120s model-load latency on the first call looked like a hang because
nothing was emitted until the call returned.

---

## Architectural decisions (recorded)

1. **Real image builder lives in `plutus_verify/spec/runtime/`, not in the
   scaffold CLI.** It's part of the v2 runtime, used by both
   `scaffold_check` and any future CI path. The CLI wires the factory in
   (`make_image_builder()`); the runtime owns the implementation.
2. **Content-addressed image tags.** Tag = `plutus-v2:<sha256(Dockerfile)[:12]>`.
   Same Dockerfile → same tag → Docker's build cache hits naturally; different
   Dockerfile → different tag → never confused.
3. **Generated Dockerfile is committed to `.plutus/Dockerfile.generated`,
   not held in memory.** Authors can `cat` it to debug env issues. The path is
   inside the v2 namespace (`.plutus/`), not the repo root.
4. **New locator kind `stdout_regex` added alongside `stdout_table`.** Strict
   addition; no behavior change for repos using `stdout_table`. The regex must
   have at least one capture group, applied to the captured stdout of the
   step. Markdown-table parsing stays for repos that genuinely use tables.
5. **`verification_mode: artifact_check` is honored at the step level.** No
   command execution, no stdout capture — just `assert_outputs_present`. This
   was always a documented mode but the runtime had no branch for it.
6. **`repo_path = repo_path.resolve()` at orchestrator entry, not at every
   call site.** Single fix point. Also applied inside `build_image` because
   `docker build <ctx>` needs an absolute path too.
7. **`data_resolver` honors `expected_layout`'s common parent dir.** Google
   Drive folders have nested structure (`is/`, `os/`); the manifest's
   declared layout is `data/is/...`. The downloader must land files at
   `<repo>/data/` so the layout matches. Computed via
   `_common_parent_dir(expected_layout)`.
8. **`plutus transfer` prewarms the LLM and emits per-call progress.** Mirrors
   `verify_cmd`'s setup. Adds `--config` and `--no-prewarm` flags.
   `on_attempt` callback piped through `scaffold_transfer` → `extract_plan`
   so the user sees "call_1_repo_metadata_attempt_0..." progress.

---

## File Structure

**New:**
- `plutus_verify/spec/runtime/real_image_builder.py` — `build_image(...)`,
  `make_image_builder(prefix="plutus-v2")`
- `tests/unit/test_runtime_real_image_builder.py`

**Modified:**
- `plutus_verify/spec/runtime/orchestrator.py` — `repo_path.resolve()` at
  entry; new `_run_step` branch for `artifact_check`; `_compare_headlines`
  takes `step_results` and threads stdout into locators;
  `_locate_stdout_table` + `_locate_stdout_regex` added
- `plutus_verify/spec/runtime/data_resolver.py` — `_common_parent_dir(layout)`
  + use it inside `default_downloader` for Google Drive landing paths
- `plutus_verify/spec/runtime/__init__.py` — export `build_image`,
  `make_image_builder`
- `plutus_verify/spec/manifest.py` — `Locate.kind` Literal gains
  `"stdout_regex"`
- `plutus_verify/spec/schema.py` — `_LOCATE.kind` enum gains
  `"stdout_regex"`
- `plutus_verify/__main__.py` — `check_cmd` now uses `make_image_builder()`;
  `transfer_cmd` mirrors `verify_cmd` (loads config, prewarms,
  `on_attempt` progress, `--config`/`--no-prewarm` flags)
- `plutus_verify/scaffold/transfer.py` — adds `on_attempt` parameter, piped
  to `extract_plan`

**Tests added:**
- `test_runtime_real_image_builder.py` — Dockerfile-hash tag stability,
  Docker invocation arg shape
- `test_runtime_orchestrator.py` — `artifact_check` branch, `stdout_regex`
  locator, `stdout_table` locator, `repo_path.resolve()` behavior

---

## What landed (commit 900b459)

### 1. `real_image_builder.py`

```python
def build_image(dockerfile_text: str, repo_path: Path, image_prefix: str = "plutus-v2") -> str:
    repo_path = repo_path.resolve()
    df_path = repo_path / ".plutus" / "Dockerfile.generated"
    df_path.parent.mkdir(parents=True, exist_ok=True)
    df_path.write_text(dockerfile_text)
    digest = hashlib.sha256(dockerfile_text.encode()).hexdigest()[:12]
    tag = f"{image_prefix}:{digest}"
    subprocess.run(["docker", "build", "--tag", tag, "--file", str(df_path), str(repo_path)],
                   check=True)
    return tag


def make_image_builder(image_prefix: str = "plutus-v2") -> ImageBuilder:
    return lambda dockerfile_text, repo_path: build_image(
        dockerfile_text, repo_path, image_prefix=image_prefix
    )
```

Wired into `__main__.py`'s `check_cmd`:

```python
from plutus_verify.spec.runtime import make_image_builder
...
result = scaffold_check(repo_path, image_builder=make_image_builder(), ...)
```

### 2. `stdout_regex` locator

Schema gains the enum value:

```python
# plutus_verify/spec/schema.py
_LOCATE = {
    "kind": {"enum": ["stdout_table", "stdout_regex", "json_file", "file_regex"]},
    ...
}
```

Orchestrator dispatch:

```python
def _locate_value(locate, repo_path, *, stdout=""):
    if locate.kind == "stdout_regex":
        return _locate_stdout_regex(locate, stdout)
    ...

def _locate_stdout_regex(locate, stdout):
    m = re.search(locate.pattern, stdout)
    if m is None:
        raise KeyError(f"pattern {locate.pattern!r} did not match captured stdout")
    return float(m.group(1))
```

### 3. `artifact_check` branch in `_run_step`

```python
if step.verification_mode == "artifact_check":
    sr = StepRuntimeResult(
        step_id=step.id, exit_code=0, duration_seconds=0.0,
        skipped_reason="artifact_check (no execution; outputs verified by preflight)",
    )
    try:
        assert_outputs_present(step, repo_path)
    except PreflightError as exc:
        sr.preflight_error = str(exc)
        sr.exit_code = -1
    return sr
```

### 4. `repo_path.resolve()` at orchestrator entry

```python
def run_v2_pipeline(manifest, *, repo_path, ...):
    repo_path = repo_path.resolve()  # Docker mounts + build ctx need absolute paths
    ...
```

### 5. `_common_parent_dir` in `data_resolver`

```python
def _common_parent_dir(layout: tuple[str, ...]) -> str | None:
    parents = {Path(p).parts[0] for p in layout if "/" in p}
    return parents.pop() if len(parents) == 1 else None
```

Used by `default_downloader` to place Google Drive output at
`<repo_path>/<common_parent>` instead of `<repo_path>` directly.

---

## What landed (commit 88ceaf3)

`transfer_cmd` rewritten to mirror `verify_cmd`:

- Loads `Config` from `--config` flag or default location
- Prewarms the LLM unless `--no-prewarm`
- Wraps `scaffold_transfer(...)` with `on_attempt=` callback that prints
  per-call status to stderr

`scaffold_transfer` signature extended:

```python
def scaffold_transfer(
    repo_path, *, llm_client,
    on_attempt: Callable[[str], None] | None = None,
    first_attempt_idle_seconds: int = 600,
    retry_idle_seconds: int = 60,
    max_retries: int = 3,
) -> TransferResult:
    ...
    plan = extract_plan(repo_path, llm_client=llm_client, on_attempt=on_attempt, ...)
```

---

## Verification (how we knew it worked)

End-to-end run against ProtoMarketMaker (real Docker daemon, real
Gemma-bypassed manifest hand-cleaned from transfer output):

```
out/transfer-test/check5.log:
  building image from .plutus/Dockerfile.generated...
  image: plutus-v2:33d77ec3d2df
  data tier: raw
    ok data_collection: exit=0 (skipped: satisfied_by_data_source)
    ok in_sample_backtest: exit=0
    ok optimization: exit=0 (skipped: artifact_check ...)
    ok out_of_sample_backtest: exit=0
    ok in_sample_backtest.Sharpe Ratio: actual=0.9517 expected=0.9516
    ...
    FAIL out_of_sample_backtest.Sharpe Ratio: actual=0.0815 expected=0.1105
    ...
```

6 of 6 in-sample headlines pass; 3 of 6 OOS headlines diverge ~25%. The
divergence is a genuine reproducibility finding (Sharpe/Sortino/HPR drift
while MDD matches exactly, suggesting risk-free or annualization mismatch
between the README's claim and the script's current behavior), not a
pipeline bug. The verifier behaves correctly: exit 1, headline-level
failure reasons in the output.

Unit tests: 303 passing (+7 new for this plan).

---

## Outcome

After this plan, `plutus check <repo_path>` is end-to-end functional
against a real Plutus repo with a real Docker daemon. The "Still deferred"
list in [2026-05-21-plutus-spec-v2-DONE.md](2026-05-21-plutus-spec-v2-DONE.md)
removes one item (real Docker image builder wired to `plutus check`).

The OOS divergence finding is unrelated to v2 plumbing — it's a real
reproducibility problem in the ProtoMarketMaker repo that the v2 verifier
correctly surfaced. Investigating it is out of scope for this plan.

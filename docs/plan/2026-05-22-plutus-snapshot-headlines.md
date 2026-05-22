# Plutus v2 Spec — `plutus snapshot --headlines` (Plan 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Extend `plutus snapshot` to fill `expected.headlines[].value` in the manifest from the metrics each step produced in `.plutus/run/<step_id>/results.json`. The author runs snapshot, reviews the diff, and `git commit`s — the commit is the verification claim.

**Architecture:** Use `ruamel.yaml` for round-trip-preserving YAML edits (preserves the author's comments and formatting). Extend `scaffold_snapshot` to do reference-output copying *and* headline-value filling in the same pass. CLI defaults to both; flags let authors opt out of either side.

**Tech Stack:** New dependency `ruamel.yaml>=0.18` — well-maintained, designed for exactly this use case (edit YAML, keep comments).

---

## Why this plan exists

Plan 7 made the SDK runnable inside the container. Plan 6 set up the file contract. Now the author workflow is:

1. `plutus init` — scaffold manifest skeleton + example_script.py + CI workflow
2. Instrument scripts with `pv.step(...)` blocks
3. Run `plutus check` to verify
4. ❌ **Toil:** for each headline they want to verify, they hand-type the value from the script's output into the manifest YAML

Step 4 is brittle — typo a digit, get a silent verification failure. Worse, when the author retunes a parameter and re-runs, they have to re-type 12 numbers. They'll either skip the manifest update (verification stays out of date) or copy-paste from terminal output (error-prone).

The fix per [the brainstorm with the user](../../plutus-automation-scoring/.claude_brainstorm_2026_05_22.md):
- Snapshot reads results.json (the script's actual output) and writes `value:` into the manifest
- Author reviews the diff in git, then commits — that commit IS the verification claim
- Subsequent `plutus check` runs verify the *committed* values against fresh results.json
- No auto-pass: the manifest still must be committed (the human-in-the-loop step that makes it a *claim*)

The verification property is preserved because the commit is the gate, not the snapshot run.

---

## Architectural decisions (recorded)

1. **`ruamel.yaml` for round-trip edits.** PyYAML's `safe_load`/`safe_dump` loses comments and reflows whitespace, which would make the diff noisy and discourage authors from snapshot/commit cadence. ruamel.yaml's round-trip API preserves everything except the values we explicitly change.
2. **One default, two opt-outs.** `plutus snapshot` defaults to filling both reference outputs AND headline values. Two CLI flags: `--no-reference-outputs` and `--no-headlines` for authors who want only one side.
3. **No auto-creation of headlines.** If results.json has a metric named `sortino_ratio` but the manifest has no `sortino_ratio` headline declared, snapshot **skips** with a warning. Adding new headlines would be magic — author controls manifest structure.
4. **No auto-creation of expected blocks.** If results.json exists for `out_of_sample_backtest` but the manifest has no `expected: - step_id: out_of_sample_backtest` block, snapshot warns and skips that step entirely.
5. **Skip missing results.json gracefully.** If a step's results.json doesn't exist (script didn't write one, step was skipped, etc.), snapshot reports it in `notes` and leaves the manifest's headline values alone.
6. **Refuse to snapshot on hard-failed checks.** Existing snapshot refuses on `check_result.exit_code == 2` (a required step failed). Keep that. Headline divergence (exit 1) is fine — that's exactly when the author wants to update the values.
7. **Value precision.** Write the value as written by the SDK (full precision). Authors can manually round in the manifest if desired (and snapshot will overwrite again next run — which is the point).

---

## File Structure

**Modified:**

- `plutus_verify/scaffold/snapshot.py` — extend `scaffold_snapshot` to also update headline values
- `plutus_verify/__main__.py` — CLI `snapshot` subcommand gains `--no-reference-outputs` and `--no-headlines` flags
- `pyproject.toml` — add `ruamel.yaml>=0.18` to core dependencies

**New:**

- `plutus_verify/scaffold/manifest_edit.py` — `update_headline_values(manifest_path, updates)` function. Uses ruamel.yaml. Pure function (no I/O outside the manifest file).

**Tests:**

- `tests/unit/test_manifest_edit.py` — round-trip tests, comment preservation, value overwrite, missing-block handling
- `tests/unit/test_scaffold_snapshot.py` (extend) — snapshot now updates headline values; refuses on exit 2; respects flags

---

## Public API

```python
# plutus_verify/scaffold/manifest_edit.py

class ManifestEditError(RuntimeError):
    """The manifest could not be safely edited."""


def update_headline_values(
    manifest_path: Path,
    updates: dict[str, dict[str, float]],
) -> tuple[int, list[str]]:
    """Update `expected.headlines[].value` in-place in the manifest YAML.

    Args:
        manifest_path: Path to `.plutus/manifest.yaml`.
        updates: {step_id: {headline_name: new_value}}. Values are written
            verbatim — no rounding, no truncation. Caller is responsible
            for sanity.

    Returns:
        (count_of_values_updated, list_of_warnings).
        Warnings cover: step_id present in updates but no expected block;
        headline_name present in updates but no declared headline.

    Behavior:
        - Comments, blank lines, and key order are preserved (ruamel.yaml
          round-trip mode).
        - If `updates[step_id]` is empty, the step is ignored.
        - If `updates[headline_name]` doesn't match an existing headline's
          `name:`, that update is dropped with a warning.

    Raises:
        ManifestEditError: file unreadable, not valid YAML, or no
            `expected:` top-level key.
    """
```

```python
# plutus_verify/scaffold/snapshot.py — modified signature

def scaffold_snapshot(
    repo_path: Path,
    *,
    run_check_first: bool = True,
    image_builder: Optional[Callable[[str, Path], str]] = None,
    runner: Optional[Any] = None,
    vision_client: Optional[Any] = None,
    secrets: Optional[dict[str, str]] = None,
    update_reference_outputs: bool = True,    # NEW
    update_headline_values: bool = True,      # NEW
) -> SnapshotResult: ...


@dataclass
class SnapshotResult:
    files_copied: int
    headlines_updated: int = 0                # NEW
    check_result: Optional[CheckResult]
    notes: list[str] = field(default_factory=list)
```

---

## Task 1: `manifest_edit.update_headline_values`

**Files:**
- Create: `plutus_verify/scaffold/manifest_edit.py`
- Test: `tests/unit/test_manifest_edit.py`

TDD sub-steps:
- [ ] **Step 1 — add `ruamel.yaml>=0.18` to `pyproject.toml` deps** (core, not optional)
- [ ] **Step 2 — `pip install -e . --upgrade`** to pick up the new dep
- [ ] **Step 3 — failing test for round-trip preservation**: write a small manifest YAML with comments and blank lines; call `update_headline_values` to change ONE value; assert the output:
  - The changed value is in the new value
  - All comments are still present
  - Blank lines are still present
  - All other values unchanged
- [ ] **Step 4 — failing test for missing step warning**: updates dict has `step_id="foo"` but manifest has no expected block with that step_id; assert warning text mentions the step_id; assert count==0; manifest unchanged on disk.
- [ ] **Step 5 — failing test for missing headline warning**: updates has `headline_name="bogus"` but manifest's expected block doesn't declare it; assert warning text mentions the name; manifest unchanged for that update.
- [ ] **Step 6 — failing test for empty updates**: `updates={}` → 0 changes, no warnings, manifest unchanged byte-for-byte.
- [ ] **Step 7 — failing test for ManifestEditError**: pass a non-YAML file → error; pass a YAML with no `expected:` key → error.
- [ ] **Step 8 — implement `update_headline_values`** with ruamel.yaml round-trip. Use `YAML(typ='rt')`. Mutate values in place. Re-emit to the file.
- [ ] **Step 9 — run tests**: `source .venv/bin/activate && pytest tests/unit/test_manifest_edit.py -v`
- [ ] **Step 10 — commit**.

Commit:
```
feat(scaffold): manifest_edit.update_headline_values via ruamel.yaml

Adds round-trip-preserving manifest editor that overwrites
expected.headlines[].value entries by name. Preserves comments, blank
lines, key order. Warns (does not error) on unknown step_ids and
headline names — those become snapshot notes.

Adds ruamel.yaml>=0.18 to core dependencies.
```

---

## Task 2: Wire into `scaffold_snapshot`

**Files:**
- Modify: `plutus_verify/scaffold/snapshot.py`
- Test: `tests/unit/test_scaffold_snapshot.py` (extend)

Logic to add after the existing reference-output copy block (around line 90):

```python
headlines_updated = 0
if update_headline_values:
    updates: dict[str, dict[str, float]] = {}
    for er in manifest.expected:
        if not er.headlines:
            continue
        try:
            results = load_results(repo_path, step_id=er.step_id)
        except MissingResultsError:
            notes.append(f"step '{er.step_id}': no results.json — headlines not updated")
            continue
        except MalformedResultsError as exc:
            notes.append(f"step '{er.step_id}': malformed results.json — {exc}")
            continue
        # Only update values for headlines that the manifest declares
        declared_names = {h.name for h in er.headlines}
        step_updates = {m.name: m.value for m in results.metrics if m.name in declared_names}
        if step_updates:
            updates[er.step_id] = step_updates

    if updates:
        manifest_path = repo_path / ".plutus" / "manifest.yaml"
        try:
            count, warnings = update_headline_values_in_yaml(manifest_path, updates)
            headlines_updated = count
            notes.extend(warnings)
        except ManifestEditError as exc:
            notes.append(f"manifest edit failed: {exc}")
```

(Rename the imported function to `update_headline_values_in_yaml` to avoid clashing with the kwarg.)

TDD sub-steps:
- [ ] **Step 1 — failing test for happy path**: pre-populate `.plutus/run/in_sample/results.json` via the SDK; call `scaffold_snapshot(run_check_first=False)`; assert `headlines_updated > 0`; read the manifest and verify the value matches the results.json metric.
- [ ] **Step 2 — failing test for `update_headline_values=False`**: same setup; assert `headlines_updated == 0`; manifest unchanged.
- [ ] **Step 3 — failing test for missing results.json**: manifest declares headlines, no results.json written; assert `headlines_updated == 0`; notes contain "no results.json — headlines not updated".
- [ ] **Step 4 — implement**
- [ ] **Step 5 — run tests**: `source .venv/bin/activate && pytest tests/unit/test_scaffold_snapshot.py -v`
- [ ] **Step 6 — commit**.

Commit:
```
feat(scaffold): plutus snapshot fills headline values from results.json

scaffold_snapshot now reads .plutus/run/<step_id>/results.json for every
step that has declared headlines and overwrites the matching
expected.headlines[].value entries in the manifest. Toggleable via
update_headline_values kwarg (default True). Refuses to update from
a failed check (exit 2), same as the existing reference-output path.

Author workflow becomes: write manifest skeleton, run plutus snapshot,
review `git diff manifest.yaml`, commit. The commit IS the
verification claim.
```

---

## Task 3: CLI wiring

**Files:**
- Modify: `plutus_verify/__main__.py`
- Test: `tests/unit/test_cli_group.py` (if it tests snapshot) or add `tests/unit/test_cli_snapshot.py`

Find the existing `snapshot` Click subcommand. Add two flags:

```python
@cli.command("snapshot")
@click.argument("repo_path", type=click.Path(exists=True, path_type=Path))
@click.option("--no-reference-outputs", is_flag=True, help="...")
@click.option("--no-headlines", is_flag=True, help="...")
# ... other existing options ...
def snapshot_cmd(repo_path, no_reference_outputs, no_headlines, ...):
    ...
    result = scaffold_snapshot(
        repo_path,
        update_reference_outputs=not no_reference_outputs,
        update_headline_values=not no_headlines,
        ...
    )
    click.echo(f"  files copied: {result.files_copied}")
    click.echo(f"  headlines updated: {result.headlines_updated}")
    if result.notes:
        click.echo("notes:")
        for note in result.notes:
            click.echo(f"  - {note}")
```

TDD sub-steps:
- [ ] **Step 1 — failing test for `--no-headlines`**: invoke CLI with the flag; assert `update_headline_values=False` was passed to scaffold_snapshot (via mock or by checking the output).
- [ ] **Step 2 — failing test for `--no-reference-outputs`**: similar.
- [ ] **Step 3 — failing test for help text**: `plutus snapshot --help` mentions both new flags.
- [ ] **Step 4 — implement**.
- [ ] **Step 5 — run tests**.
- [ ] **Step 6 — commit**.

Commit:
```
feat(cli): plutus snapshot --no-headlines / --no-reference-outputs

CLI surface for the snapshot extensions. Default behavior unchanged
from previous Plan 3 → still snapshots reference outputs; now also
fills headline values from results.json by default. The two opt-out
flags let authors pick one side or the other.
```

---

## Task 4: Integration verification

**Files:**
- Modify in-place: `out/transfer-test/ProtoMarketMaker/.plutus/manifest.yaml` (set a few headline values to deliberately wrong numbers; gitignored, so no commit)
- Run: `plutus snapshot out/transfer-test/ProtoMarketMaker`
- Verify the wrong values get overwritten with the real ones

Steps:
- [ ] **Step 1 — corrupt the manifest**: change `value: 0.9516` (sharpe_ratio) to `value: 999.0` in the manifest.
- [ ] **Step 2 — run snapshot**:
  ```bash
  cd /Users/dan/algotrade-research/plutus-automation-scoring
  source .venv/bin/activate
  python -m plutus_verify snapshot out/transfer-test/ProtoMarketMaker 2>&1 | tee out/transfer-test/snapshot.log
  ```
  This runs `plutus check` first (~6-10 min) then snapshots. Expected: `headlines updated: 12` (6 in-sample + 6 OOS).
- [ ] **Step 3 — verify the manifest** now has `value: 0.9517...` (or whatever the real number is) where you had `999.0`. Diff against the previous version to confirm comments and structure are preserved.
- [ ] **Step 4 — re-run `plutus check`** against the now-snapshotted manifest. Same headline pass pattern as before (6/6 in-sample, 3/6 OOS) — the OOS divergence comes back because the OOS headlines snapshot now matches the SCRIPT's actual values (not the README's claimed values).

  Wait — actually this is interesting. If snapshot overwrites OOS values to match the script's output, then `plutus check` will PASS for all OOS too (because manifest matches script's actual output). The 3/6 OOS divergence from the README's claimed numbers becomes invisible — the manifest no longer reflects the README.

  This is the *correct* behavior of snapshot. The author is choosing to "lock in" the current script's values as the new expected. If they want to preserve the README's claimed values, they shouldn't run snapshot OR they should revert specific lines.

  Document this in the snapshot output / the runbook: "running snapshot overwrites manifest values; verify the diff is what you actually intend to claim."

- [ ] **Step 5 — commit** the verification log (out/ is gitignored, so just update DONE.md to note Plan 8 complete).

Commit:
```
docs: Plan 8 complete — plutus snapshot now writes headline values

plutus snapshot now extracts values from .plutus/run/<step_id>/results.json
and writes them into expected.headlines[].value via ruamel.yaml
round-trip (comments + formatting preserved). Author workflow becomes
snapshot → review diff → commit; the commit IS the verification claim.

DONE.md updated to reflect Plan 8 complete.
```

---

## Verification

**Unit:** ~15 new tests across manifest_edit + scaffold_snapshot + CLI.

**Integration:** corrupt a manifest value, run snapshot, confirm it's restored to match results.json. Comments and blank lines preserved in the diff.

**Regression:** full suite passes.

---

## Out of scope

- **Auto-creating headlines** for metrics in results.json that aren't declared in the manifest. Author controls structure.
- **Tolerance updates.** Only `value:` is touched. Tolerance is the author's claim about acceptable drift; snapshot doesn't change it.
- **Reverse direction** — propagating manifest changes back to the script. The script is the source of truth for what gets produced; the manifest is the claim about what's expected. One-way only.
- **Multi-run aggregation** — snapshot uses the most recent run's results.json. No averaging across runs.

---

## Connection to Plan 6 + 7

Plan 6 made `.plutus/run/<step_id>/results.json` the verification contract. Plan 7 made the SDK available in the Docker image. Plan 8 closes the author loop: the manifest is no longer hand-maintained — it's snapshotted from the script's own output, reviewed in `git diff`, and committed. The commit gate is what preserves the verification property.

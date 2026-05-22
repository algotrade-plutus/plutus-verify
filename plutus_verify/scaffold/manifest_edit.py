"""Round-trip-preserving editor for `.plutus/manifest.yaml`.

Used by `plutus snapshot` to update `expected.headlines[].value` entries
from the script-produced `.plutus/run/<step_id>/results.json`. Comments,
blank lines, and key order in the author's manifest are preserved so the
resulting `git diff` only shows the value changes.

Wraps ruamel.yaml — pyyaml's safe_load/safe_dump destroys comments.
"""
from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML, YAMLError


class ManifestEditError(RuntimeError):
    """The manifest could not be safely edited."""


def update_headline_values(
    manifest_path: Path,
    updates: dict[str, dict[str, float]],
) -> tuple[int, list[str]]:
    """Update `expected.headlines[].value` entries in place.

    Args:
        manifest_path: Path to `.plutus/manifest.yaml`.
        updates: {step_id: {headline_name: new_value}}.

    Returns:
        (count_of_values_updated, list_of_warnings).
    """
    if not updates:
        return 0, []

    try:
        text = manifest_path.read_text()
    except OSError as exc:
        raise ManifestEditError(
            f"could not read {manifest_path}: {exc}"
        ) from exc

    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        data = yaml.load(text)
    except YAMLError as exc:
        raise ManifestEditError(
            f"could not parse {manifest_path}: {exc}"
        ) from exc

    if data is None or "expected" not in data:
        raise ManifestEditError(
            f"{manifest_path} has no top-level 'expected' key"
        )

    expected = data["expected"]
    by_step = {block.get("step_id"): block for block in expected}

    count = 0
    warnings: list[str] = []

    for step_id, headline_updates in updates.items():
        if not headline_updates:
            continue
        block = by_step.get(step_id)
        if block is None:
            warnings.append(
                f"snapshot: step_id '{step_id}' has results but no expected "
                "block in manifest — skipped"
            )
            continue
        headlines = block.get("headlines") or []
        headlines_by_name = {h.get("name"): h for h in headlines}
        for name, new_value in headline_updates.items():
            h = headlines_by_name.get(name)
            if h is None:
                warnings.append(
                    f"snapshot: metric '{name}' (step '{step_id}') has no "
                    "matching headline declared in manifest — skipped"
                )
                continue
            h["value"] = new_value
            count += 1

    if count > 0:
        with manifest_path.open("w") as f:
            yaml.dump(data, f)

    return count, warnings

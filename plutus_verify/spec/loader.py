"""YAML → dict → schema-validate → Manifest pipeline.

Use :func:`load_manifest(repo_path)` for "is there a .plutus/ directory here?"
flow, or :func:`load_manifest_from_yaml_text` / :func:`load_manifest_from_dict`
when the caller already has the data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from plutus_verify.spec.manifest import (
    Artifact,
    DataSource,
    DataSourceTiers,
    Env,
    ExpectedBlock,
    ExpectedMetric,
    Manifest,
    NineStepCoverage,
    Repo,
    Secret,
    Step,
    SubProcess,
    SubProcesses,
    Tolerance,
)
from plutus_verify.spec.schema import MANIFEST_SCHEMA


class ManifestLoadError(ValueError):
    """Raised for any failure to load a v2 manifest (file, YAML, schema)."""


_VALIDATOR = Draft202012Validator(MANIFEST_SCHEMA)


def load_manifest(repo_path: Path) -> Manifest:
    """Load `.plutus/manifest.yaml` from inside `repo_path`."""
    manifest_path = repo_path / ".plutus" / "manifest.yaml"
    if not manifest_path.exists():
        raise ManifestLoadError(f"no .plutus/manifest.yaml in {repo_path}")
    # Pass repo_path so invariants that need the filesystem (e.g. install_project
    # requires a pyproject.toml at the repo root) can be checked.
    return load_manifest_from_yaml_text(manifest_path.read_text(), repo_path=repo_path)


def load_manifest_from_yaml_text(text: str, *, repo_path: Path | None = None) -> Manifest:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestLoadError(f"YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestLoadError("manifest YAML root must be a mapping")
    return load_manifest_from_dict(data, repo_path=repo_path)


def load_manifest_from_dict(data: dict[str, Any], *, repo_path: Path | None = None) -> Manifest:
    try:
        _VALIDATOR.validate(data)
    except ValidationError as exc:
        raise ManifestLoadError(f"schema violation: {exc.message}") from exc
    m = _build(data)
    from plutus_verify.spec.validator import ManifestInvariantError, check_invariants

    try:
        check_invariants(m, repo_path=repo_path)
    except ManifestInvariantError as exc:
        raise ManifestLoadError(str(exc)) from exc
    return m


def _build(d: dict[str, Any]) -> Manifest:
    repo = Repo(name=d["repo"]["name"], primary_language=d["repo"]["primary_language"])
    env = Env(
        base=d["env"]["base"],
        python_version=d["env"]["python_version"],
        manager=d["env"].get("manager", "pip"),
        lockfile=d["env"].get("lockfile"),
        requirements_file=d["env"].get("requirements_file"),
        os_packages=tuple(d["env"].get("os_packages", ())),
        gpu_required=d["env"].get("gpu_required", False),
        install_project=d["env"].get("install_project", False),
    )
    secrets = tuple(
        Secret(
            key=s["key"],
            purpose=s.get("purpose", ""),
            used_by=tuple(s.get("used_by", ())),
        )
        for s in d["secrets"]
    )
    data_sources = DataSourceTiers(
        processed=tuple(_build_data_source(x) for x in d["data_sources"]["processed"]),
        raw=tuple(_build_data_source(x) for x in d["data_sources"]["raw"]),
    )
    steps = tuple(_build_step(x) for x in d["steps"])
    expected = tuple(_build_expected(x) for x in d["expected"])
    coverage = {
        k: NineStepCoverage(present=v["present"], section=v.get("section"))
        for k, v in d.get("nine_step_coverage", {}).items()
    }
    return Manifest(
        schema_version=d["schema_version"],
        repo=repo,
        env=env,
        secrets=secrets,
        data_sources=data_sources,
        steps=steps,
        expected=expected,
        nine_step_coverage=coverage,
    )


def _build_data_source(d: dict[str, Any]) -> DataSource:
    return DataSource(
        kind=d["kind"],
        url=d["url"],
        expected_layout=tuple(d["expected_layout"]),
        satisfies=tuple(d["satisfies"]),
        secrets_required=tuple(d.get("secrets_required", ())),
        label=d.get("label"),
    )


def _build_step(d: dict[str, Any]) -> Step:
    return Step(
        id=d["id"],
        nine_step=d["nine_step"],
        required=d["required"],
        command=d.get("command"),
        label=d.get("label"),
        network=d.get("network", "none"),
        timeout_seconds=d.get("timeout_seconds", 1800),
        inputs=tuple(d.get("inputs", ())),
        outputs=tuple(d.get("outputs", ())),
        depends_on=tuple(d.get("depends_on", ())),
        verification_mode=d.get("verification_mode", "execute"),
        sub_processes=(
            _build_sub_processes(d["sub_processes"]) if "sub_processes" in d else None
        ),
    )


def _build_sub_process(d: dict[str, Any]) -> SubProcess:
    return SubProcess(
        description=d["description"],
        command=d.get("command"),
        inputs=tuple(d.get("inputs", ())),
        outputs=tuple(d.get("outputs", ())),
    )


def _build_sub_processes(d: dict[str, Any]) -> SubProcesses:
    return SubProcesses(
        collection=_build_sub_process(d["collection"]) if "collection" in d else None,
        processing=_build_sub_process(d["processing"]) if "processing" in d else None,
    )


def _build_expected(d: dict[str, Any]) -> ExpectedBlock:
    metrics = tuple(
        ExpectedMetric(
            name=h["name"],
            value=h["value"],
            display_name=h.get("display_name"),
            tolerance=Tolerance(
                kind=h["tolerance"]["kind"], value=h["tolerance"]["value"]
            ),
        )
        for h in d.get("metrics", [])
    )
    artifacts = tuple(
        Artifact(
            path=r["path"],
            compare=r["compare"],
            threshold=r.get("threshold"),
        )
        for r in d.get("artifacts", [])
    )
    return ExpectedBlock(step_id=d["step_id"], metrics=metrics, artifacts=artifacts)

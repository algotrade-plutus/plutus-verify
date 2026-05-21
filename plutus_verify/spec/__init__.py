"""Plutus v2 manifest: dataclasses, schema, loader, validator, adapter.

The v2 manifest is the source of truth for repos that ship a .plutus/
directory. Versus the LLM-extracted ExtractedPlan, it is author-authored,
declaratively types the runtime environment, lists step inputs+outputs as a
hard contract, and tiers data acquisition (download > preprocess > run).
"""
from plutus_verify.spec.manifest import (
    DataSource,
    DataSourceTiers,
    Env,
    ExpectedBlock,
    Headline,
    Locate,
    Manifest,
    NineStepCoverage,
    ReferenceOutput,
    Repo,
    Secret,
    Step,
    Tolerance,
)
# from plutus_verify.spec.loader import ManifestLoadError, load_manifest  # re-enabled in Task 3

__all__ = [
    "DataSource",
    "DataSourceTiers",
    "Env",
    "ExpectedBlock",
    "Headline",
    "Locate",
    "Manifest",
    "NineStepCoverage",
    "ReferenceOutput",
    "Repo",
    "Secret",
    "Step",
    "Tolerance",
]

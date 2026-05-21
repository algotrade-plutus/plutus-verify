"""Plutus SDK — authors emit canonical ``results.json`` from inside a step.

The SDK is intentionally tiny: a context manager (``step``) that accumulates
headline metrics, artifact references, and metadata, then writes a strictly
validated JSON file at ``.plutus/run/<step_id>/results.json`` on clean exit.

The verifier (separate pipeline) reads these files; that direction is not
implemented in this module.
"""
from __future__ import annotations

from plutus_verify.sdk.run import Run, step

__all__ = ["Run", "step"]

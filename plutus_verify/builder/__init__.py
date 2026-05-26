"""Build stage: turn a repo on disk into a runnable Docker image.

Two entry points:

* :func:`build_image` — legacy, shells out to ``jupyter-repo2docker``. Kept for
  back-compat with callers that want repo2docker behaviour. Slow / fragile on
  some platforms (we saw 30+ min stalls on macOS arm64 with the
  ``buildpack-deps:24.04`` base).

* :func:`build_with_fixers` — the new auto-fixing path (default for the CLI).
  Generates a minimal ``python:3.11-slim`` Dockerfile, runs a deterministic
  pre-build fixer pass on the repo, builds, on failure runs deterministic
  post-build fixers, builds again, on failure invokes a constrained-op LLM
  suggester for one more attempt. All applied fixes are returned in the
  result so the report can surface them as findings.

Public surface deliberately small: :class:`BuildError`, :class:`BuildResult`,
:func:`build_image`, :func:`build_with_fixers`.
"""
from __future__ import annotations

from plutus_verify.builder.runner import (
    BuildAdjustment,
    BuildError,
    BuildResult,
    build_image,
    build_with_fixers,
)

__all__ = [
    "BuildAdjustment",
    "BuildError",
    "BuildResult",
    "build_image",
    "build_with_fixers",
]

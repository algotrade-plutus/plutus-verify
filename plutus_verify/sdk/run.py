"""Run context manager + step() factory — the author-facing SDK surface.

A ``Run`` accumulates metrics, artifact references, and metadata
inside a reproducibility step. On clean ``__exit__`` it writes a strictly
validated ``results.json`` at ``<repo>/.plutus/run/<step_id>/results.json``.

Design notes:
- Validation happens twice. ``metric`` / ``artifact`` / ``metadata`` raise
  ``ValueError`` at call time so authors get an immediate stack pointing at
  the offending line. ``flush`` re-validates the assembled payload against
  the JSON Schema as a defense-in-depth check.
- Writes are atomic: serialize to ``results.json.tmp`` then ``os.replace``.
- Auto-injected metadata (``duration_seconds``, ``git_commit``) yields to
  user-supplied values via ``r.metadata(...)``.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from plutus_verify.sdk.schema import (
    ARTIFACT_KINDS,
    NAME_PATTERN,
    UNIT_KINDS,
    validate_results,
)

_SCHEMA_VERSION = "1.0"
_NAME_RE = re.compile(NAME_PATTERN)


def _require_snake_case(label: str, value: str) -> None:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise ValueError(
            f"{label} must match {NAME_PATTERN!r} (snake_case identifier); got {value!r}"
        )


def _short_git_commit(repo_path: Path) -> Optional[str]:
    """Best-effort short SHA of HEAD; returns None on any failure."""
    if not (repo_path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    if not sha:
        return None
    return sha[:7]


def _find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` looking for a ``.plutus/`` directory.

    Returns the first directory containing ``.plutus``. If none is found
    before hitting the filesystem root, returns ``start``.
    """
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".plutus").is_dir():
            return candidate
    return start


class Run:
    """Accumulator + writer for a single reproducibility step.

    Not thread-safe; one ``Run`` corresponds to one ``with step(...)`` block.
    """

    def __init__(self, step_id: str, repo_path: Path) -> None:
        _require_snake_case("step_id", step_id)
        self.step_id: str = step_id
        self.repo_path: Path = Path(repo_path)
        self._metrics: list[dict[str, Any]] = []
        self._artifacts: list[dict[str, Any]] = []
        self._metadata: dict[str, Any] = {}
        self._metric_names: set[str] = set()
        self._artifact_names: set[str] = set()
        self._t_start: Optional[float] = None
        self._flushed: bool = False

    # -- context manager ------------------------------------------------

    def __enter__(self) -> "Run":
        self._t_start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if exc_type is not None:
            # User code raised; skip the write entirely.
            return None
        if not self._flushed:
            self.flush()
        return None

    # -- accumulators ---------------------------------------------------

    def metric(self, name: str, value: float, *, unit: str = "ratio") -> None:
        _require_snake_case("metric name", name)
        if name in self._metric_names:
            raise ValueError(f"duplicate metric name: {name!r}")
        if unit not in UNIT_KINDS:
            raise ValueError(
                f"unit must be one of {UNIT_KINDS}; got {unit!r} "
                f"(use 'fraction' for percent-like metrics — write 42% as 0.42 — "
                f"and 'ratio' for unbounded dimensionless like Sharpe; "
                f"'percent' is rejected to keep representation decimal)"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric value must be a number; got {type(value).__name__}")
        if not math.isfinite(value):
            raise ValueError(f"metric value must be finite; got {value!r}")
        self._metrics.append({"name": name, "value": value, "unit": unit})
        self._metric_names.add(name)

    def artifact(self, name: str, path: "str | Path", *, kind: str = "chart") -> None:
        _require_snake_case("artifact name", name)
        if name in self._artifact_names:
            raise ValueError(f"duplicate artifact name: {name!r}")
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"artifact kind must be one of {ARTIFACT_KINDS}; got {kind!r}")
        self._artifacts.append({"name": name, "path": str(path), "kind": kind})
        self._artifact_names.add(name)

    def metadata(self, **kwargs: Any) -> None:
        # Probe JSON-serializability up front so the error points at the
        # caller, not at flush().
        for k, v in kwargs.items():
            try:
                json.dumps(v)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"metadata value for {k!r} is not JSON-serializable: {exc}") from exc
            self._metadata[k] = v  # last-write-wins per key

    # -- writer ---------------------------------------------------------

    def _assemble_payload(self) -> dict[str, Any]:
        metadata = dict(self._metadata)  # shallow copy; user-supplied values win

        if "duration_seconds" not in metadata and self._t_start is not None:
            elapsed = time.monotonic() - self._t_start
            metadata["duration_seconds"] = round(elapsed, 3)

        if "git_commit" not in metadata:
            sha = _short_git_commit(self.repo_path)
            if sha is not None:
                metadata["git_commit"] = sha

        return {
            "schema_version": _SCHEMA_VERSION,
            "step_id": self.step_id,
            "metrics": list(self._metrics),
            "artifacts": list(self._artifacts),
            "metadata": metadata,
        }

    def flush(self) -> None:
        """Validate the accumulated payload and write it atomically."""
        payload = self._assemble_payload()
        validate_results(payload)

        out_dir = self.repo_path / ".plutus" / "run" / self.step_id
        out_dir.mkdir(parents=True, exist_ok=True)
        final = out_dir / "results.json"
        tmp = out_dir / "results.json.tmp"

        # ``allow_nan=False`` is belt-and-braces; we already reject NaN/Inf
        # in ``metric``, but metadata values pass through json.dumps too.
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=False, allow_nan=False))
        os.replace(tmp, final)
        self._flushed = True


def step(step_id: str, *, repo_path: Optional[Path] = None) -> Run:
    """Open a new ``Run`` for ``step_id``.

    If ``repo_path`` is ``None``, walk up from the current working directory
    looking for a ``.plutus/`` directory and use that as the repo root. If
    no ancestor contains ``.plutus``, fall back to the current directory.
    """
    if repo_path is None:
        repo_path = _find_repo_root(Path.cwd())
    return Run(step_id, Path(repo_path))

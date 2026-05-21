"""Tee'd progress emitter for the verification CLI.

Each event prints a single line to a user-visible stream (defaults to stderr)
AND appends to ``out/<run_id>/run.log`` for the audit trail. The format is

    [stage] message            # stage()
    [stage]   message          # substep() — indented 2 spaces
    [stage] ERROR: message     # error()

Bracketed stage prefixes are grep-friendly:

    grep '^\\[build\\]' out/<id>/run.log

The emitter is deliberately tiny — no log levels, no JSON lines, no rotation.
It exists so the pipeline can stop being silent for 2-5 minutes between "go"
and the final verdict.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import IO, Optional


class Progress:
    """Tee'd stage/substep/error emitter.

    ``run_dir`` is optional — pass ``None`` (or use :class:`NullProgress`) to
    suppress disk output (handy for tests). The user stream is always written
    to unless ``stream`` is ``None``.
    """

    def __init__(
        self,
        run_dir: Optional[Path] = None,
        *,
        stream: Optional[IO[str]] = sys.stderr,
    ) -> None:
        self._stream = stream
        self._log: Optional[IO[str]] = None
        if run_dir is not None:
            run_dir.mkdir(parents=True, exist_ok=True)
            self._log = (run_dir / "run.log").open("a", encoding="utf-8")
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._log.write(f"# plutus-verify run.log started {ts}\n")
            self._log.flush()

    # ---- core emit ----

    def _emit(self, line: str) -> None:
        if self._stream is not None:
            self._stream.write(line + "\n")
            self._stream.flush()
        if self._log is not None:
            self._log.write(line + "\n")
            self._log.flush()

    # ---- public API ----

    def stage(self, stage: str, message: str) -> None:
        """Emit a top-level stage event: ``[stage] message``."""
        self._emit(f"[{stage}] {message}")

    def substep(self, stage: str, message: str) -> None:
        """Emit an indented substep event: ``[stage]   message``."""
        self._emit(f"[{stage}]   {message}")

    def error(self, stage: str, message: str) -> None:
        """Emit an error event: ``[stage] ERROR: message``."""
        self._emit(f"[{stage}] ERROR: {message}")

    def close(self) -> None:
        """Flush and close the run.log handle (idempotent)."""
        if self._log is not None:
            try:
                self._log.flush()
                self._log.close()
            finally:
                self._log = None

    # context-manager sugar
    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class NullProgress(Progress):
    """Drop all events. Useful for tests that don't care about the trail."""

    def __init__(self) -> None:  # noqa: D401 - trivial wrapper
        super().__init__(run_dir=None, stream=None)

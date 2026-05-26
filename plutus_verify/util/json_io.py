"""Thin Path-aware wrappers around json.load / json.dump.

Consolidates the ``json.loads(path.read_text())`` and
``path.write_text(json.dumps(obj, indent=2))`` patterns that were scattered
across the pipeline so indentation and encoding stay consistent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def save_json(obj: Any, path: Path, *, indent: int = 2) -> None:
    Path(path).write_text(json.dumps(obj, indent=indent))


__all__ = ["load_json", "save_json"]

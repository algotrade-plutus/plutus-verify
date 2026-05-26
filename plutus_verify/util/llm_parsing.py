"""Shared helpers for parsing LLM responses."""
from __future__ import annotations

import re

_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL
)


def strip_markdown_fences(text: str) -> str:
    """Strip a single outer ```...``` markdown fence, if present.

    Leaves bare text unchanged (after stripping leading/trailing whitespace).
    """
    m = _FENCE_RE.match(text)
    return m.group("body") if m else text.strip()


__all__ = ["strip_markdown_fences"]

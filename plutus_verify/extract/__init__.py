"""Extract stage: README -> ExtractedPlan via decomposed form-filling.

The single free-form extraction call was replaced (Iteration 4) by 4 small
form-filling calls assembled deterministically by the stitcher. See
``plutus_verify/extract/decompose.py`` and ``plutus_verify/extract/stitch.py``.
"""
from __future__ import annotations

from typing import Callable, Optional

from plutus_verify.extract.client import LLMClient, OpenAICompatClient
from plutus_verify.extract.decompose import DecomposeError, decompose
from plutus_verify.extract.plan import (
    ExtractedPlan,
    PlanValidationError,
    parse_plan,
)
from plutus_verify.extract.stitch import stitch

__all__ = [
    "ExtractError",
    "LLMClient",
    "OpenAICompatClient",
    "extract_plan",
]


class ExtractError(RuntimeError):
    """Decomposed extraction failed after per-call retry budgets were exhausted."""


_AttemptCallback = Callable[[str, str, Optional[Exception]], None]
"""Called once per LLM call (including retries) with
``(label, raw_text, error_or_None)``. Pipeline uses this to tee each call's
response to disk for auditing. The ``label`` is short and filename-safe
(e.g., ``"call_0_repo_attempt_0"``)."""


def extract_plan(
    readme_text: str,
    client: LLMClient,
    *,
    temperature: float = 0.0,
    max_retries: int = 1,
    first_attempt_idle_seconds: float = 180.0,
    retry_idle_seconds: Optional[float] = None,
    on_attempt: Optional[_AttemptCallback] = None,
) -> ExtractedPlan:
    """Run the decomposed extractor and return a validated ``ExtractedPlan``.

    The signature is preserved for pipeline.py compatibility, but the
    semantics differ from the pre-Iteration-4 single-call extractor:

    - ``max_retries`` now applies *per call* (4 calls × up to N retries each).
    - ``retry_idle_seconds`` is accepted but ignored — each call's prompt is
      small enough that the same idle timeout works for first and retry.
    - ``on_attempt`` receives a string label, not an integer attempt number.
      See the type alias above.
    """
    _ = retry_idle_seconds  # kept in signature for compat; not used.
    try:
        elements = decompose(
            readme_text,
            client,
            temperature=temperature,
            idle_timeout_seconds=first_attempt_idle_seconds,
            per_call_max_retries=max_retries,
            on_attempt=on_attempt,
        )
        return stitch(**elements)
    except DecomposeError as exc:
        raise ExtractError(str(exc)) from exc
    except PlanValidationError as exc:
        raise ExtractError(f"stitched plan failed schema check: {exc}") from exc

"""Real :class:`VisionClient` against an OpenAI-compatible multimodal endpoint."""
from __future__ import annotations

import base64
from typing import Optional

from plutus_verify.compare.charts import CHART_PROMPT, VisionClient


def _b64_data_url(image: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


class OpenAIVisionClient(VisionClient):
    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str = "not-needed",
        timeout_seconds: float = 120.0,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed. Install with: pip install 'plutus-verify[llm]'"
            ) from exc
        self._client = OpenAI(
            base_url=endpoint, api_key=api_key, timeout=timeout_seconds
        )
        self._model = model

    def judge_chart(
        self, *, chart_name: str, produced_png: bytes, reference_png: Optional[bytes]
    ) -> str:
        content: list[dict] = [
            {
                "type": "text",
                "text": (
                    f"Chart name: {chart_name}\n"
                    "CHART_A (reference) follows, then CHART_B (produced).\n\n"
                    f"{CHART_PROMPT}"
                ),
            }
        ]
        if reference_png is not None:
            content.append(
                {"type": "image_url", "image_url": {"url": _b64_data_url(reference_png)}}
            )
        content.append(
            {"type": "image_url", "image_url": {"url": _b64_data_url(produced_png)}}
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

"""Tests for the streaming LLM client.

We exercise the client against an in-process httpx mock transport, simulating
SSE streams from Ollama. Two behaviours we care about most (per
docs/ollama-knowledge-base.md):
  - The content-idle timer fires when no real token arrives for N seconds, even
    if SSE keep-alives keep socket reads alive (§2).
  - The client does NOT pass ``response_format`` (§5) and DOES pass
    ``options.num_ctx`` (§4).
"""
import json
import time
from typing import Iterable

import httpx
import pytest

from plutus_verify.extract.client import OpenAICompatClient


def _sse(data: dict) -> bytes:
    """Encode one Ollama /api/chat NDJSON line."""
    return (json.dumps(data) + "\n").encode("utf-8")


def _sse_done() -> bytes:
    """Final Ollama NDJSON line with done=true."""
    return _sse({"model": "stub", "message": {"role": "assistant", "content": ""}, "done": True})


def _delta(text: str) -> dict:
    return {"model": "stub", "message": {"role": "assistant", "content": text}, "done": False}


def _byte_iter(items: Iterable[bytes]):
    for it in items:
        yield it


def _mock_transport(stream_bytes: Iterable[bytes], captured: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"".join(stream_bytes)),
            headers={"content-type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)


def test_client_streams_chunks_and_returns_full_string():
    captured: dict = {}
    chunks = [
        _sse(_delta("{")),
        _sse(_delta('"a"')),
        _sse(_delta(":1}")),
        _sse_done(),
    ]
    client = OpenAICompatClient(
        endpoint="http://example/v1",
        model="gemma4:26b",
        idle_timeout_seconds=5.0,
        echo_stream=False,
        transport=_mock_transport(chunks, captured),
    )
    out = client.complete_json("sys", "user", temperature=0.1)
    assert out == '{"a":1}'


def test_client_does_not_pass_response_format():
    """Per §5: constrained JSON sampling deadlocks Gemma; must NOT be sent."""
    captured: dict = {}
    client = OpenAICompatClient(
        endpoint="http://example/v1",
        model="gemma4:26b",
        echo_stream=False,
        transport=_mock_transport([_sse(_delta("{}")), _sse_done()], captured),
    )
    client.complete_json("sys", "user")
    # Neither the OpenAI-style `response_format` nor Ollama's `format:json`.
    assert "response_format" not in captured["body"]
    assert captured["body"].get("format") != "json"


def test_client_targets_ollama_api_chat_endpoint():
    """We must NOT hit /v1/chat/completions — it silently ignores num_ctx."""
    captured: dict = {}
    client = OpenAICompatClient(
        endpoint="http://example:11434",
        model="gemma4:26b",
        echo_stream=False,
        transport=_mock_transport([_sse(_delta("{}")), _sse_done()], captured),
    )
    client.complete_json("sys", "user")
    assert captured["url"].endswith("/api/chat"), captured["url"]


def test_client_strips_v1_suffix_from_endpoint():
    """Accept both '...:11434' and '...:11434/v1' (we still hit /api/chat)."""
    captured: dict = {}
    client = OpenAICompatClient(
        endpoint="http://example:11434/v1",
        model="gemma4:26b",
        echo_stream=False,
        transport=_mock_transport([_sse(_delta("{}")), _sse_done()], captured),
    )
    client.complete_json("sys", "user")
    assert captured["url"] == "http://example:11434/api/chat"


def test_client_passes_num_ctx_in_options():
    """Per §4: explicit num_ctx avoids the 256K default's KV-cache bloat."""
    captured: dict = {}
    client = OpenAICompatClient(
        endpoint="http://example/v1",
        model="gemma4:26b",
        num_ctx=16384,
        echo_stream=False,
        transport=_mock_transport([_sse(_delta("{}")), _sse_done()], captured),
    )
    client.complete_json("sys", "user")
    assert captured["body"]["options"]["num_ctx"] == 16384


def test_client_idle_timeout_fires_when_stream_goes_silent():
    """Per §2: a stream that emits keep-alive whitespace but no real content
    must trigger the content-idle timer."""
    captured: dict = {}

    # A stream that emits one real chunk, then SSE keep-alives (empty lines)
    # forever. The mock transport returns all bytes at once, so we simulate
    # silence via a generator that the client must iter through under a tight
    # idle budget.
    def slow_handler(request):
        captured["body"] = json.loads(request.content.decode("utf-8"))

        def gen():
            # First useful chunk
            yield _sse(_delta("partial"))
            # Then 200 empty keep-alive lines; the client should fire idle
            # timeout long before iterating them all (sleep so wall time
            # actually passes between yields).
            for _ in range(200):
                time.sleep(0.05)
                yield b"\n"

        return httpx.Response(
            200,
            stream=httpx.AsyncByteStream() if False else _IterStream(gen()),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(slow_handler)
    client = OpenAICompatClient(
        endpoint="http://example/v1",
        model="gemma4:26b",
        idle_timeout_seconds=0.3,
        echo_stream=False,
        transport=transport,
    )
    with pytest.raises(TimeoutError):
        client.complete_json("sys", "user")


class _IterStream(httpx.SyncByteStream):
    def __init__(self, gen):
        self._gen = gen

    def __iter__(self):
        yield from self._gen

    def close(self):
        pass


def test_client_warmup_sends_tiny_request():
    """Per §8: pre-warm with a 1-token request to avoid cold-start tax."""
    captured: dict = {}
    client = OpenAICompatClient(
        endpoint="http://example/v1",
        model="gemma4:26b",
        echo_stream=False,
        transport=_mock_transport([_sse(_delta("ok")), _sse_done()], captured),
    )
    client.prewarm()
    # tiny request body; specifically caps num_predict at 1
    assert captured["body"]["options"].get("num_predict") == 1

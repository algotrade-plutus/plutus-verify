"""LLM client for Ollama's native ``/api/chat`` endpoint.

Built specifically to survive the quirks of Ollama hosting Gemma 4. See
``docs/ollama-knowledge-base.md`` for the underlying field report; this
module implements rules §1, §2, §4, §5, §8 of that doc:

  §1  Streaming is mandatory — ``stream=True`` always.
  §2  Per-socket timeout is not enough — we maintain a content-idle timer in
      the iteration loop and raise ``TimeoutError`` if no real token arrives
      for ``idle_timeout_seconds``.
  §4  Pass ``options.num_ctx`` explicitly — Ollama's default is 256K on a
      51 GiB Mac, which bloats KV cache and slows prompt eval. **IMPORTANT:**
      Ollama's OpenAI-compatibility path (``/v1/chat/completions``) silently
      ignores ``options.num_ctx``; only the native ``/api/chat`` endpoint
      honors it. That's why we target the native endpoint.
  §5  No constrained JSON mode (no ``format: json``) — it deadlocks Gemma on
      long prompts. Instruct JSON via the system prompt and parse with
      fence-stripping instead.
  §8  Pre-warm helper: a 1-token request to amortise cold start.

Retry policy (§3) lives in :mod:`plutus_verify.extract`, not here; this client
opens a fresh ``httpx.Client`` per call so a stale connection from a prior
stall can't leak into the next attempt.

The endpoint should be the Ollama base URL (no path), e.g.
``http://localhost:11434``. ``/v1`` suffixes are stripped automatically.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Iterable, Optional, Protocol

import httpx


class LLMClient(Protocol):
    """Minimal interface the extract stage needs from an LLM."""

    def complete_json(
        self, system: str, user: str, *, temperature: float = 0.0
    ) -> str: ...


_DEFAULT_HTTPX_TIMEOUT = httpx.Timeout(
    connect=15.0, read=180.0, write=30.0, pool=5.0
)


class OpenAICompatClient:
    """Streaming client for any OpenAI-compatible ``/chat/completions`` server.

    Constructor params:
      endpoint: e.g. ``http://localhost:11434/v1`` (Ollama)
      model: e.g. ``gemma4:26b``
      idle_timeout_seconds: max time with no new *content* token. Default 90s.
      num_ctx: passed in ``options.num_ctx``. Default 16384 (§4).
      echo_stream: write streamed tokens to stderr as they arrive.
      transport: injectable httpx transport for testing.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        api_key: str = "not-needed",
        idle_timeout_seconds: float = 90.0,
        num_ctx: int = 16384,
        echo_stream: bool = True,
        echo_thinking: bool = True,
        think: bool = True,
        transport: Optional[httpx.BaseTransport] = None,
        # Back-compat: tests + old callers used ``timeout_seconds``
        timeout_seconds: Optional[float] = None,
    ) -> None:
        # Accept either the Ollama base URL ("http://host:11434") or the
        # OpenAI-compat URL ("http://host:11434/v1") — normalise to the base.
        base = endpoint.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self._endpoint = base
        self._model = model
        self._api_key = api_key
        self._idle = float(
            idle_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        self._num_ctx = num_ctx
        self._echo = echo_stream
        self._echo_thinking = echo_thinking
        self._think = think
        self._transport = transport

    def _new_httpx_client(self) -> httpx.Client:
        return httpx.Client(
            timeout=_DEFAULT_HTTPX_TIMEOUT,
            transport=self._transport,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        idle_timeout_seconds: Optional[float] = None,
    ) -> str:
        """One streaming request; returns the assistant's content as a string.

        ``idle_timeout_seconds`` overrides the constructor-time default for
        this call only. Use it to apply the §8 pattern (longer for first
        attempt, shorter for retries).

        Raises:
          TimeoutError: if no token arrives within the idle timeout.
          httpx.HTTPError: on connection/HTTP failures.
        """
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": True,
            "think": self._think,
            # In Ollama native /api/chat, sampling and runtime knobs all live
            # inside `options`; the top-level `temperature` field of the
            # OpenAI-compat path is ignored here.
            "options": {"num_ctx": self._num_ctx, "temperature": temperature},
        }
        return self._stream(payload, idle_override=idle_timeout_seconds)

    def prewarm(self) -> None:
        """Send a tiny 1-token request to warm the runner (§8).

        Critically, this also forces Ollama to load the runner with our
        chosen ``num_ctx``. Skipping prewarm means the first real request
        may load the runner with the global default (262144 on macs with
        51 GiB RAM), which then sticks until the model unloads.
        """
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": "ok"}],
            "stream": True,
            "think": False,
            "options": {
                "num_ctx": self._num_ctx,
                "num_predict": 1,
                "temperature": 0.0,
            },
        }
        try:
            self._stream(payload, _is_prewarm=True)
        except TimeoutError:
            pass  # cold-start may take longer; not fatal

    # ---------- internals ----------

    def _stream(
        self,
        payload: dict,
        _is_prewarm: bool = False,
        idle_override: Optional[float] = None,
    ) -> str:
        """Stream the response by iterating raw byte chunks and parsing SSE
        lines ourselves.

        Why not ``resp.iter_lines()``: empirically with httpx 0.28 + Ollama's
        ``/v1/chat/completions``, ``iter_lines()`` buffers the entire response
        and never yields, while ``iter_bytes()`` streams chunks in real time
        (first chunk @ ~2.5s, subsequent chunks @ ~10ms apart). The likely
        cause is httpx's incremental text decoder waiting for a charset hint
        that never arrives. ``iter_bytes()`` is the safe path.

        Echo policy: writing to stderr on EVERY token from inside the loop
        empirically stalls the stream under some terminal/harness conditions
        (the per-token write+flush appears to interact badly with the
        iter_bytes generator, causing iteration to halt). We use a periodic
        heartbeat — print a dot every ``HEARTBEAT_INTERVAL`` seconds plus a
        running token count — which gives the user a sign of life without
        blocking the loop.
        """
        chunks: list[str] = []
        idle = float(idle_override) if idle_override is not None else self._idle
        last_token_t = time.monotonic()
        last_heartbeat = last_token_t
        token_count = 0
        content_count = 0
        thinking_count = 0
        HEARTBEAT_INTERVAL = 10.0  # seconds — less spammy when live echo is on
        # ANSI styles (TTY-safe; harmless on non-TTY)
        DIM = "\x1b[2m" if not _is_prewarm else ""
        RESET = "\x1b[0m" if not _is_prewarm else ""
        wrote_prefix_thinking = False
        wrote_prefix_content = False
        url = f"{self._endpoint}/api/chat"
        with self._new_httpx_client() as client:
            with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                buf = b""
                done = False
                for raw in resp.iter_bytes():
                    now = time.monotonic()
                    # Idle check on every chunk.
                    if now - last_token_t > idle:
                        raise TimeoutError(
                            f"LLM stalled: no token for {idle:.0f}s"
                        )
                    if not raw:
                        continue
                    buf += raw
                    # Ollama /api/chat streams NDJSON: one JSON object per line.
                    while b"\n" in buf:
                        line_b, buf = buf.split(b"\n", 1)
                        line = line_b.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        # Native shape: {message: {role, content, thinking?}, done, ...}
                        # Gemma 4 streams reasoning in `thinking`; final
                        # answer in `content`. Both reset the idle timer (so
                        # we don't time out during the thinking phase) but
                        # only `content` is captured for the returned string.
                        msg = obj.get("message") or {}
                        thinking = msg.get("thinking")
                        content = msg.get("content")
                        if thinking or content:
                            last_token_t = time.monotonic()
                            token_count += 1
                        if thinking:
                            thinking_count += 1
                            if self._echo_thinking and not _is_prewarm:
                                if not wrote_prefix_thinking:
                                    sys.stderr.write(f"\n{DIM}--- thinking ---\n")
                                    wrote_prefix_thinking = True
                                    wrote_prefix_content = False
                                sys.stderr.write(thinking)
                                sys.stderr.flush()
                        if content:
                            content_count += 1
                            chunks.append(content)
                            if self._echo and not _is_prewarm:
                                if not wrote_prefix_content:
                                    sys.stderr.write(f"{RESET}\n--- content ---\n")
                                    wrote_prefix_content = True
                                    wrote_prefix_thinking = False
                                sys.stderr.write(content)
                                sys.stderr.flush()
                        if obj.get("done"):
                            done = True
                            break
                    # Periodic stats line; useful for tracking rate even when
                    # echo is on. Less frequent than before (10s) so it
                    # doesn't fight with live token output.
                    if (
                        self._echo
                        and not _is_prewarm
                        and now - last_heartbeat > HEARTBEAT_INTERVAL
                    ):
                        sys.stderr.write(
                            f"\n{DIM}[t+{int(now - last_token_t)}s · {thinking_count} thinking · {content_count} content]{RESET}\n"
                        )
                        sys.stderr.flush()
                        last_heartbeat = now
                    if done:
                        break
        if self._echo and not _is_prewarm:
            sys.stderr.write("\n")
            sys.stderr.flush()
        return "".join(chunks)

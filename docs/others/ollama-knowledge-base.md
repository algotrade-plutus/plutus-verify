# Ollama Knowledge Base — Quirks, Errors, and Nuts & Bolts

A field report assembled while building the Algotrade internship screener
against a local Ollama running Gemma 4 26B on Apple Silicon. Each section is
something we got bitten by, including the symptom, the root cause, and the
workaround that actually held up under sustained load.

Target audience: future engineers (and Claude sessions) integrating Python
clients with Ollama. Read the **Cheat-sheet** section first; everything else
is depth.

---

## Cheat-sheet — the rules that matter

1. **Always use `stream=True`.** With `stream=False`, Ollama buffers the
   entire response and httpx hangs indefinitely (well past any timeout). See
   §1.
2. **Per-socket timeout is not enough.** SSE empty-line keep-alives reset the
   read timeout while no tokens arrive. Add a wall-clock "no new content for
   N seconds" timer in your iteration loop. See §2.
3. **Don't trust the first-attempt timeout alone — retry on stall.**
   Empirically ~12% of requests on Gemma 4 26B never produce a token within
   90 s; the very next request almost always succeeds. Implement automatic
   retry on `TimeoutError` / `httpx.ReadTimeout`. See §3.
4. **Set `options.num_ctx` explicitly.** The default on a 51 GiB-RAM Mac is
   `262144` (256 K). For 4–7 K-token prompts this wastes 50× the KV cache
   memory and slows prompt eval. We use `16384`. See §4.
5. **Do NOT pass `response_format: {"type": "json_object"}` to Gemma.**
   Constrained JSON sampling deadlocks the inference loop on long prompts.
   Use prompt-side instructions + fence-stripping in the parser instead. See
   §5.
6. **KV-cache prefix reuse is broken on `/v1/chat/completions`.** Every
   request shows `used=0` in Ollama's debug log, regardless of identical
   system prompt. The OpenAI-compat path is request-stateless. See §6.
7. **`OLLAMA_DEBUG=1` matters, and where it goes matters more.** The macOS
   desktop app writes to `~/.ollama/logs/server.log`. A manually launched
   `ollama serve` writes to stderr — not that file. Redirect stdout+stderr
   to the canonical log path if you want tooling to find it. See §7.
8. **The "stall" is usually slow prompt eval, not a deadlock.** Apple
   Silicon GPU under sustained load takes 30–90 s to chew through 4–7 K
   tokens of prompt. The slow tail crosses naïve 90 s timeouts. Use 180 s
   on first attempt, 90 s on retries. See §8.

---

## §1 — Streaming is mandatory

**Symptom**: `httpx.post(..., timeout=600)` hangs for minutes well past the
deadline. Killing the Python process leaves Ollama still processing; the
next request queues behind it.

**Root cause**: With `stream=False`, Ollama buffers the entire JSON response
server-side before flushing any bytes. For long generations the response
isn't sent until inference completes. If httpx's read timeout fires
mid-buffer, Python disconnects but Ollama keeps generating internally — and
the next request is blocked behind it in the runner queue.

**Fix**:
```python
payload = {"model": MODEL, "messages": [...], "stream": True}
with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
    for line in resp.iter_lines():
        # parse SSE "data: {...}" chunks; accumulate deltas
```

This was the **single biggest unlock** — from "pipeline hangs after 2
applicants" to "pipeline runs end-to-end".

---

## §2 — One timeout is not enough

**Symptom**: Even with streaming, the iteration loop occasionally hangs for
20+ minutes on macOS Ollama (Gemma 4 26B). httpx's `read=120` did not fire.

**Root cause**: httpx's `read` timeout is **per-socket-read**, not
per-content-chunk. Ollama emits SSE keep-alive lines (often empty
`\n\n` framing) every few seconds during slow generation. Each keep-alive
counts as a successful socket read and resets the timeout. The genuine
content stall is invisible to httpx.

**Fix**: maintain a `last_token_t` timestamp and check it on every loop
iteration:

```python
last_token_t = time.monotonic()
for line in resp.iter_lines():
    if time.monotonic() - last_token_t > CONTENT_IDLE_TIMEOUT:
        raise TimeoutError("LLM stalled")
    # ... parse line; if it contained a real delta:
    last_token_t = time.monotonic()
```

The check must run **at the top of every iteration**, before continuing past
empty / `[DONE]` lines, so that a keep-alive stream cannot delay the
detection.

Pair this with a generous-but-finite `httpx.Timeout(read=...)` to catch
genuine socket death (network failure). They guard different failure modes.

---

## §3 — Retries are not optional

**Symptom**: Across 66 requests we observed 8 cases (~12%) where Ollama
returned `HTTP 200` on the stream open but produced zero tokens for 90+
seconds. The very next request after a stall almost always succeeded; back-
to-back stalls were rare but observed (2/8).

**Root cause confirmed via debug logs**: not a true deadlock. The runner
subprocess is genuinely working — prompt eval just takes longer than the
timeout on slow tail requests due to memory pressure, no KV reuse (see §6),
and GPU thermal/scheduling variability.

**Fix**: wrap the per-attempt logic and retry up to `_MAX_ATTEMPTS=3` times.
Empirically 2 retries covers every case we saw, including the 2 back-to-back
ones.

```python
for attempt in range(MAX_ATTEMPTS):
    try:
        return _chat_once(messages, model, temperature, on_token, attempt)
    except (TimeoutError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
        if attempt + 1 < MAX_ATTEMPTS:
            time.sleep(RETRY_BACKOFF)  # 2s
            continue
        raise
```

**Important**: open a **fresh `httpx.Client`** on each retry. Stale
connection state is part of what breaks.

---

## §4 — `num_ctx` defaults are huge and wasteful

**Symptom**: Inference is slower than expected; memory pressure shows up
in `vm_stat` even though the model fits in VRAM.

**Root cause**: Ollama picks a default `num_ctx` based on installed memory.
On a 51 GiB-RAM Apple Silicon Mac, the runner allocates `num_ctx=262144`
(256 K tokens). The KV cache buffer scales with `num_ctx`. For our
4–7 K-token prompts this is 35–50× more allocation than needed. Larger
buffers slow prompt eval and increase host memory pressure.

**Fix**: pass `options.num_ctx` explicitly in every request. We use 16384,
which leaves 2.4× headroom over our worst-case 6 706-token prompt.

```python
payload = {
    "model": MODEL,
    "messages": [...],
    "stream": True,
    "options": {"num_ctx": 16384},
}
```

**Verify it stuck**: Ollama's debug log shows `runner.num_ctx=N` on each
request. After this change you should see `num_ctx=16384` (or whatever you
set), not 262144.

**Risk**: prompts exceeding `num_ctx` fail with an explicit HTTP 400 — loud
and easy to diagnose. The mitigation is to size `num_ctx` to the worst-case
prompt with a comfortable multiplier.

---

## §5 — Don't use `response_format: json_object` with Gemma

**Symptom**: Pipeline appears to hang on the first applicant. No tokens
arrive even after 10+ minutes.

**Root cause**: Constrained JSON sampling (where the sampler is forced to
keep generation valid against a JSON schema/grammar) causes Gemma 4 (and
several other small local models) to deadlock on long prompts. The grammar
evaluator essentially rejects every candidate token.

**Fix**: instruct JSON output in the system prompt; strip any leading/
trailing markdown fences in the parser; rely on the model's natural ability
to produce valid JSON when prompted clearly:

```python
# system message includes:
# "Reply ONLY with the JSON object, no markdown fences, no commentary."

# parser:
def _strip_json_fences(text: str) -> str:
    cleaned = re.sub(r"^\s*```(?:json)?\s*\n?|\n?```\s*$", "", text, flags=re.M).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return cleaned
```

Add a one-shot retry on `json.JSONDecodeError` with a sterner system message
("Your previous response was not valid JSON. Reply ONLY..."). In practice
this catches the rare malformed output.

---

## §6 — KV-cache prefix reuse does not engage on `/v1/chat/completions`

**Symptom**: Designed the prompt with a frozen "prefix" (system message +
rubric + one-shot example, ~3 000 tokens) expecting Ollama to reuse the KV
cache across calls. In practice every request re-evaluates the full prompt
from scratch.

**Root cause confirmed**: Ollama's debug log shows `loading cache slot ...
used=0` on every single request through `/v1/chat/completions`, regardless
of identical system text. The OpenAI-compat layer is stateless — each call
gets fresh slot processing.

**Status**: We added `scripts/probe_cache.py` to verify whether the native
`/api/chat` endpoint with `keep_alive: -1` preserves slot state across
calls. If yes, a migration phase is warranted (would give ~2× speedup on
batch runs).

**Workaround for now**: minimise prompt size, ensure `num_ctx` is right-
sized (§4), and accept the per-call eval cost.

---

## §7 — Ollama logs: where they go, when, and how to read them

### Two distinct launch paths

1. **macOS desktop app** (`/Applications/Ollama.app`): writes logs to
   `~/.ollama/logs/server.log` via a wrapper. Includes the `[GIN] ...`
   request-summary lines.
2. **`ollama serve` directly in a terminal**: writes to stdout/stderr in
   that terminal. Does **not** write to `~/.ollama/logs/server.log`.

### Enabling debug

Required for `cache.go` `loading cache slot used=N` lines, runner subprocess
state, and prompt-eval details. Set as an env var **at launch time**:

```bash
killall Ollama 2>/dev/null; sleep 1
OLLAMA_DEBUG=1 nohup ollama serve > ~/.ollama/logs/server.log 2>&1 &
```

The `> ~/.ollama/logs/server.log 2>&1` redirect is the gotcha. Without it,
your tooling that tails the canonical log path sees stale data from the
previous desktop-app session.

### Detecting debug mode programmatically

Check the recent log for `level=DEBUG` lines:
```python
def _ollama_debug_enabled() -> bool:
    tail = _tail_ollama_log(200)
    return "level=DEBUG" in tail
```

Note: a fresh server with no requests yet may not have produced DEBUG lines.
Send a single small request first if you need a reliable check.

### Useful log signatures

| Pattern | Meaning |
|---|---|
| `[GIN] ... 200 \| 3m0s` | A request that took exactly 3 minutes — almost always our 180s content-idle timeout firing twice (initial + retry). |
| `loading cache slot ... used=0` | No prefix reuse on this call. Expected on `/v1/chat/completions`. |
| `runner with non-zero duration has gone idle, adding timer` | The 5-minute keep-alive started; model will unload if no requests arrive. |
| `evaluating already loaded` | Slot is warm; no model load needed. |
| `context for request finished refCount=0` | Last request done; runner is idle but model still loaded (until keep-alive expires). |

---

## §8 — "Stalls" are usually slow prompt eval

**Diagnosis story**: We initially thought stalls were Ollama deadlocking.
After enabling debug logs we saw: every "stall" request showed
`loading cache slot` at request time, then 90 seconds of complete log
silence, then our HTTP timeout firing. The runner subprocess does not log
per-token progress during prompt eval — it logs once eval completes.

So 90 seconds of silence means: prompt eval is in flight, just slow.

**Why slow?**
- No KV-cache reuse (§6) means every call re-evaluates 4–7 K tokens.
- `num_ctx=262144` (before our fix) bloated KV buffer memory.
- Apple Silicon GPU under sustained load can drop clocks (thermal/power).
- macOS scheduling: foreground/background QoS shifts may demote the runner.

**Mitigation** (what we settled on):
- 180 s content-idle timeout on first attempt (legitimate eval can take this long).
- 90 s on retries (post-stall recovery is fast when it's a true hang).
- `num_ctx=16384` to reduce memory pressure.
- Pre-warm the model with a 1-token request before the batch starts, so the
  first applicant doesn't pay cold-start tax.

---

## §9 — Connection lifecycle gotchas

- **Connection pool**: Use a fresh `httpx.Client()` per attempt when
  retrying. We've not been able to reproduce, but anecdotally reusing a
  client across a stall left it in a bad state.
- **Connect timeout**: Keep modest (15 s). The TCP connect to localhost is
  near-instant; if it takes longer, Ollama isn't healthy.
- **Pool timeout**: Set explicitly (we use 5 s) so a leaked connection in
  another part of the program doesn't block the chat path forever.

```python
timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=5.0)
```

- **`KeyboardInterrupt`**: When you Ctrl-C a Python process holding an open
  Ollama stream, Ollama treats it as "request finished" but the runner
  continues finishing the in-flight token. The next request you send may
  see a small delay (a few seconds) as the runner cleans up. Not a bug, but
  worth knowing.

---

## §10 — Diagnostic recipes

### See what Ollama is doing right now
```bash
tail -f ~/.ollama/logs/server.log
```

### Confirm debug logs are flowing
```bash
grep -c "level=DEBUG" ~/.ollama/logs/server.log
```
Should be > 0 once any request has been processed.

### Inspect cache reuse across a run
```bash
grep "loading cache slot" ~/.ollama/logs/server.log \
  | awk -F'used=' '{print $2}' | awk '{print $1}' \
  | sort | uniq -c
```
Each line `N M` means `N requests had used=M tokens of prefix reuse`.

### Find slow / stalled requests in Ollama's GIN log
```bash
grep "GIN.*chat/completions" ~/.ollama/logs/server.log \
  | awk -F'|' '$3 ~ /m/ {print}'
```
Anything reporting in minutes (`1m30s`, `3m0s`) is either slow eval or our
timeout firing.

### Confirm runner config
```bash
grep "server config" ~/.ollama/logs/server.log | tail -1
```
Look for `OLLAMA_DEBUG:DEBUG`, `OLLAMA_NUM_PARALLEL:1`, `OLLAMA_KEEP_ALIVE:5m0s`.

---

## §11 — Configuration reference

Environment variables Ollama respects at server launch:

| Var | Default | Useful when |
|---|---|---|
| `OLLAMA_DEBUG` | unset (`INFO`) | `1` to enable DEBUG logs — required for runner state visibility |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Override bind address |
| `OLLAMA_KEEP_ALIVE` | `5m` | Set higher (e.g. `24h`) to prevent mid-batch model unload |
| `OLLAMA_MAX_LOADED_MODELS` | `0` (auto) | Force only one model in VRAM |
| `OLLAMA_NUM_PARALLEL` | `1` | Per-model concurrency. Keep at 1 unless you have headroom |
| `OLLAMA_FLASH_ATTENTION` | `false` | Enable for memory savings on some models |
| `OLLAMA_KV_CACHE_TYPE` | `""` | `q8_0` or `q4_0` quantises KV cache; halves memory |

Per-request options (passed in `options:{}` block):

| Option | Default | Notes |
|---|---|---|
| `num_ctx` | host-dependent (256K on 51GiB Mac) | **Set explicitly**, sized to your worst-case prompt |
| `temperature` | model-dependent | We use 0.1 for stable structured output |
| `top_p`, `top_k`, `repeat_penalty` | model-default | Rarely need adjustment for JSON output |
| `num_predict` | -1 (unlimited) | Set if you want to cap generation length |
| `seed` | random | Set for reproducibility |

---

## §12 — What we still don't know

- Whether `/api/chat` with `keep_alive: -1` actually reuses the prefix slot
  across calls. Probe script ready at `scripts/probe_cache.py`.
- Whether the back-to-back stall cases (2/8 observed) are correlated with
  any prompt content. They didn't show any obvious shared feature.
- Whether `OLLAMA_FLASH_ATTENTION=true` or KV cache quantisation would help
  prompt eval speed without affecting score quality.
- Whether the OpenAI-compat path's stateless behaviour is fixable via a
  consistent `user` field or other hint to Ollama (likely no — it's a
  protocol limitation, not a config).

---

## Quick mental model

> Ollama is a layer over llama.cpp's runner subprocess. The Go server handles
> HTTP and scheduling; the runner (one C++ process per loaded model) does the
> actual GPU inference. Most of the surprises come from the seam between
> them: HTTP is healthy when the runner is silent; the runner produces
> tokens that the HTTP layer buffers; the runner stalls while the HTTP layer
> sends keep-alives. Always reason about the two halves separately.

When something feels weird, the first question is: **is the runner working
and the HTTP layer hiding it, or is the runner truly stuck?** The Ollama
debug log answers that question.

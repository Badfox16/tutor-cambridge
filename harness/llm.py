"""Ollama chat (native /api/chat, streamed) with timing metrics.

Ollama reports durations in nanoseconds; everything here is milliseconds.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from . import config


class LLMError(Exception):
    pass


def _ms(ns) -> float:
    return round((ns or 0) / 1e6, 1)


def chat(prompt: str, *, model: str, think: bool = False, temperature: float = 0.2,
         num_ctx: int = 4096, max_tokens: int = 1024, keep_alive: str = "10m",
         base: str | None = None) -> dict:
    """One user message -> {text, thinking_chars, cut_off, metrics...}.

    Retries only connection errors / 5xx (e.g. Ollama still starting).
    """
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "stream": True, "think": think, "keep_alive": keep_alive,
            "options": {"temperature": temperature, "num_ctx": num_ctx,
                        "num_predict": max_tokens}}
    req = urllib.request.Request((base or config.OLLAMA_BASE) + "/api/chat",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.perf_counter()
    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code < 500 or attempt == 2:
                raise LLMError(f"Ollama HTTP {e.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as e:
            if attempt == 2:
                raise LLMError(f"Ollama not responding at {config.OLLAMA_BASE} ({e})") from None
        time.sleep(1 + attempt * 2)

    parts, thinking, ttft, final = [], 0, None, {}
    with resp:
        for line in resp:
            if not line.strip():
                continue
            chunk = json.loads(line)
            msg = chunk.get("message") or {}
            if msg.get("content"):
                ttft = ttft or (time.perf_counter() - t0) * 1000
                parts.append(msg["content"])
            thinking += len(msg.get("thinking") or "")
            if chunk.get("done"):
                final = chunk

    gen_tokens = final.get("eval_count") or 0
    gen_ms = _ms(final.get("eval_duration"))
    return {
        "text": "".join(parts),
        "thinking_chars": thinking,
        "cut_off": final.get("done_reason") == "length",
        "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        "load_ms": _ms(final.get("load_duration")),
        "prompt_tokens": final.get("prompt_eval_count") or 0,
        "prefill_ms": _ms(final.get("prompt_eval_duration")),
        "gen_tokens": gen_tokens,
        "gen_ms": gen_ms,
        "tokens_per_s": round(gen_tokens / (gen_ms / 1000), 2) if gen_ms else 0.0,
        "ttft_ms": None if ttft is None else round(ttft, 1),
    }

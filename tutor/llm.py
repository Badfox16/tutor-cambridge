"""Model providers with first-class performance metrics.

Primary: Ollama native (`POST /api/chat`). Secondary (optional judge):
OpenAI-compatible `/v1/chat/completions`. Both return the same `LLMResult`.

Ollama durations are nanoseconds; we convert to milliseconds. TTFT is measured
wall-clock while streaming (time to the first content token).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import config


class LLMError(Exception):
    def __init__(self, message: str, status: int = 0, transient: bool = False):
        super().__init__(message)
        self.status = status
        self.transient = transient  # safe to retry (connection refused, timeout, 5xx)


@dataclass
class LLMResult:
    text: str = ""
    thinking_chars: int = 0
    finish_reason: str = ""  # stop | length | error
    total_ms: float = 0.0
    load_ms: float = 0.0
    prompt_tokens: int = 0
    prefill_ms: float = 0.0
    gen_tokens: int = 0
    gen_ms: float = 0.0
    tokens_per_s: float = 0.0
    ttft_ms: float | None = None
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "text": self.text, "thinking_chars": self.thinking_chars,
            "finish_reason": self.finish_reason, "total_ms": round(self.total_ms, 1),
            "load_ms": round(self.load_ms, 1), "prompt_tokens": self.prompt_tokens,
            "prefill_ms": round(self.prefill_ms, 1), "gen_tokens": self.gen_tokens,
            "gen_ms": round(self.gen_ms, 1), "tokens_per_s": round(self.tokens_per_s, 2),
            "ttft_ms": None if self.ttft_ms is None else round(self.ttft_ms, 1),
        }


def _ns_to_ms(ns) -> float:
    return (ns or 0) / 1e6


class OllamaProvider:
    """Ollama native chat endpoint. Streams by default to measure TTFT."""

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 keep_alive: str | None = None, *, temperature: float | None = None,
                 num_ctx: int | None = None, max_tokens: int | None = None):
        self.model = model or config.TUTOR_MODEL
        self.base = (base_url or config.OLLAMA_BASE).rstrip("/")
        self.keep_alive = keep_alive or config.KEEP_ALIVE
        # per-instance option defaults (used when chat() gets no explicit value)
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens

    def chat(self, messages: list[dict], *, think: bool = False,
             temperature: float | None = None, num_ctx: int | None = None,
             max_tokens: int | None = None, stream: bool = True) -> LLMResult:
        options = {
            "temperature": self.temperature if temperature is None else temperature,
            "num_ctx": self.num_ctx if num_ctx is None else num_ctx,
            "num_predict": self.max_tokens if max_tokens is None else max_tokens,
        }
        body = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "think": think,
            "options": {k: v for k, v in options.items() if v is not None},
            "keep_alive": self.keep_alive,
        }
        t0 = time.perf_counter()
        if stream:
            return self._chat_stream(body, t0)
        return self._chat_once(body, t0)

    # -- internals -------------------------------------------------------------
    def _post(self, path: str, body: dict, timeout: float | None = None) -> urllib.request.Request:
        return urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    def _chat_once(self, body: dict, t0: float) -> LLMResult:
        data = self._send_with_retries(self._post("/api/chat", body))
        msg = data.get("message") or {}
        result = _metrics_from_final(data, t0)
        result.text = msg.get("content") or ""
        result.thinking_chars = len(msg.get("thinking") or "")
        result.raw = data
        return result

    def _chat_stream(self, body: dict, t0: float) -> LLMResult:
        req = self._post("/api/chat", body)
        text_parts: list[str] = []
        thinking = 0
        ttft: float | None = None
        final: dict = {}
        try:
            resp = self._open_with_retries(req)
        except LLMError:
            raise
        with resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                msg = chunk.get("message") or {}
                piece = msg.get("content") or ""
                if piece:
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000.0
                    text_parts.append(piece)
                thinking += len(msg.get("thinking") or "")
                if chunk.get("done"):
                    final = chunk
        result = _metrics_from_final(final, t0)
        result.text = "".join(text_parts)
        result.thinking_chars = thinking
        if ttft is not None:
            result.ttft_ms = ttft
        result.raw = final
        return result

    def _send_with_retries(self, req: urllib.request.Request) -> dict:
        attempts = 3
        for i in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code >= 500 and i < attempts - 1:
                    time.sleep(0.5 * (2 ** i))
                    continue
                raise LLMError(f"Ollama HTTP {e.code}", status=e.code) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if i < attempts - 1:
                    time.sleep(0.5 * (2 ** i))
                    continue
                raise LLMError(f"Ollama connection failed: {e}", transient=True) from None
        raise LLMError("unreachable")

    def _open_with_retries(self, req: urllib.request.Request):
        attempts = 3
        for i in range(attempts):
            try:
                return urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT)
            except urllib.error.HTTPError as e:
                if e.code >= 500 and i < attempts - 1:
                    time.sleep(0.5 * (2 ** i))
                    continue
                raise LLMError(f"Ollama HTTP {e.code}", status=e.code) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if i < attempts - 1:
                    time.sleep(0.5 * (2 ** i))
                    continue
                raise LLMError(f"Ollama connection failed: {e}", transient=True) from None
        raise LLMError("unreachable")

    # -- health helpers (dashboard) --------------------------------------------
    def tags(self) -> dict:
        try:
            with urllib.request.urlopen(self.base + "/api/tags", timeout=5) as resp:
                return json.load(resp)
        except Exception as e:
            raise LLMError(f"Ollama connection failed: {e}", transient=True) from None

    def ps(self) -> dict:
        try:
            with urllib.request.urlopen(self.base + "/api/ps", timeout=5) as resp:
                return json.load(resp)
        except Exception as e:
            raise LLMError(f"Ollama connection failed: {e}", transient=True) from None


def _metrics_from_final(final: dict, t0: float) -> LLMResult:
    total_ms = (time.perf_counter() - t0) * 1000.0
    gen_tokens = int(final.get("eval_count") or 0)
    gen_ms = _ns_to_ms(final.get("eval_duration"))
    result = LLMResult(
        total_ms=total_ms,
        load_ms=_ns_to_ms(final.get("load_duration")),
        prompt_tokens=int(final.get("prompt_eval_count") or 0),
        prefill_ms=_ns_to_ms(final.get("prompt_eval_duration")),
        gen_tokens=gen_tokens,
        gen_ms=gen_ms,
        tokens_per_s=(gen_tokens / (gen_ms / 1000.0)) if gen_ms > 0 else 0.0,
        finish_reason="stop",
    )
    if gen_tokens and gen_tokens >= (body_num_predict(final)):
        result.finish_reason = "length"
    return result


def body_num_predict(final: dict) -> int:
    """Best-effort cut-off detection: the response does not name the limit."""
    return int((final.get("options") or {}).get("num_predict") or config.MAX_TOKENS)


class OpenAICompatProvider:
    """Optional secondary provider (big model as judge) via /v1/chat/completions."""

    def __init__(self, model: str, base_url: str, api_key: str):
        self.model = model
        self.base = base_url.rstrip("/")
        self.api_key = api_key

    def chat(self, messages: list[dict], *, think: bool = False,
             temperature: float | None = None, num_ctx: int | None = None,
             max_tokens: int | None = None, stream: bool = False) -> LLMResult:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": config.TEMPERATURE if temperature is None else temperature,
            "max_tokens": config.MAX_TOKENS if max_tokens is None else max_tokens,
        }
        req = urllib.request.Request(
            self.base + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            raise LLMError(f"LLM HTTP {e.code}", status=e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(f"LLM connection failed: {e}", transient=True) from None
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = data.get("usage") or {}
        total_ms = (time.perf_counter() - t0) * 1000.0
        gen_tokens = int(usage.get("completion_tokens") or 0)
        return LLMResult(
            text=msg.get("content") or msg.get("reasoning_content") or "",
            thinking_chars=len(msg.get("reasoning_content") or ""),
            finish_reason=choice.get("finish_reason") or "stop",
            total_ms=total_ms,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            gen_tokens=gen_tokens,
            gen_ms=total_ms,  # not separable upstream; conservative
            tokens_per_s=(gen_tokens / (total_ms / 1000.0)) if total_ms > 0 else 0.0,
            raw=data,
        )

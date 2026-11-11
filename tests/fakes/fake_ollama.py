"""Fake Ollama: fixed streaming replies with nanosecond durations, no model."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FINAL = {
    "model": "fake-model",
    "created_at": "2026-01-01T00:00:00Z",
    "done": True,
    "done_reason": "stop",
    "total_duration": 1_500_000_000,        # 1500 ms
    "load_duration": 200_000_000,           # 200 ms
    "prompt_eval_count": 100,
    "prompt_eval_duration": 300_000_000,    # 300 ms
    "eval_count": 40,
    "eval_duration": 800_000_000,           # 800 ms
}


def make_handler(chunks=("Hel", "lo world")):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/tags":
                self._json({"models": [{"name": "fake-model:latest"}]})
            elif self.path == "/api/ps":
                self._json({"models": [{"name": "fake-model:latest", "size": 1, "size_vram": 1, "expires_at": None}]})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path != "/api/chat":
                self._json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            streaming = body.get("stream", True)
            if streaming:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for piece in chunks:
                    self.wfile.write(json.dumps({
                        "model": "fake-model", "created_at": "2026-01-01T00:00:00Z",
                        "message": {"role": "assistant", "content": piece},
                        "done": False,
                    }).encode() + b"\n")
                final = dict(FINAL)
                if body.get("think"):
                    final = {**final, "done_reason": "stop"}
                    self.wfile.write(json.dumps({
                        "model": "fake-model", "created_at": "2026-01-01T00:00:00Z",
                        "message": {"role": "assistant", "content": "", "thinking": "chain of thought"},
                        "done": True, **{k: v for k, v in FINAL.items() if k not in ("done",)},
                    }).encode() + b"\n")
                else:
                    self.wfile.write(json.dumps({
                        "model": "fake-model", "created_at": "2026-01-01T00:00:00Z",
                        "message": {"role": "assistant", "content": ""},
                        "done": True, **{k: v for k, v in FINAL.items() if k != "done"},
                    }).encode() + b"\n")
            else:
                message = {"role": "assistant", "content": "".join(chunks)}
                if body.get("think"):
                    message["thinking"] = "chain of thought"
                self._json({**FINAL, "done": True, "message": message})

    return Handler


def start() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"

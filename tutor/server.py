"""HTTP server: JSON API + static files (student UI, dashboard). Stdlib only.

M1 scope: /api/health, /api/models, static serving, redirect. Tutor/marker/
stats routes are added in later milestones.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config
from .lab import LabClient
from .llm import LLMError, OllamaProvider

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def ollama_health(base: str | None = None) -> dict:
    """GET /api/ps: is Ollama up, and which model is loaded?"""
    base = (base or config.OLLAMA_BASE).rstrip("/")
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=5) as resp:
            data = json.load(resp)
        models = data.get("models") or []
        loaded = models[0] if models else None
        return {
            "up": True,
            "loaded": None if not loaded else {
                "name": loaded.get("name"),
                "size": loaded.get("size"),
                "size_vram": loaded.get("size_vram"),
                "expires_at": loaded.get("expires_at"),
            },
        }
    except Exception as e:
        return {"up": False, "error": f"{type(e).__name__}: {e}"}


def lab_health(client: LabClient | None = None) -> dict:
    try:
        data = (client or LabClient()).dataset_version()
        return {
            "up": True,
            "datasetVersion": data.get("current") or data.get("datasetVersion"),
            "counts": data.get("counts"),
        }
    except Exception as e:
        return {"up": False, "error": str(e)}


def make_handler(*, lab: LabClient | None = None, ollama: OllamaProvider | None = None):
    lab = lab or LabClient()
    ollama = ollama or OllamaProvider()

    class Handler(BaseHTTPRequestHandler):
        server_version = "tutor-cambridge/0.1"

        def log_message(self, fmt, *args):  # quiet default
            pass

        # -- helpers -------------------------------------------------------
        def send_json(self, payload: dict, status: int = 200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_static(self, rel: str):
            path = (STATIC_ROOT / rel).resolve()
            if not str(path).startswith(str(STATIC_ROOT.resolve())) or not path.is_file():
                self.send_json({"error": "not found"}, 404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(path.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # -- routing -------------------------------------------------------
        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/" or path == "":
                self.send_response(302)
                self.send_header("Location", "/student/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/health":
                health = {"ollama": ollama_health(), "lab": lab_health(lab),
                          "model": config.TUTOR_MODEL, "version": "0.1"}
                ok = health["ollama"]["up"]
                self.send_json(health, 200 if ok else 503)
                return
            if path == "/api/models":
                try:
                    tags = ollama.tags()
                    self.send_json({"models": [m.get("name") for m in tags.get("models", [])]})
                except LLMError as e:
                    self.send_json({"error": str(e)}, 503)
                return
            if path.startswith("/student/"):
                self.send_static(path.lstrip("/"))
                return
            if path.startswith("/dashboard/"):
                self.send_static(path.lstrip("/"))
                return
            self.send_json({"error": "not found"}, 404)

        def do_POST(self):
            self.send_json({"error": "not found"}, 404)

    return Handler


def serve(port: int | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port or config.TUTOR_PORT), make_handler())
    print(f"tutor-cambridge listening on http://localhost:{server.server_address[1]}  (student UI at /student/, dashboard at /dashboard/)")
    return server


if __name__ == "__main__":
    serve().serve_forever()

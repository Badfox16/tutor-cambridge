"""HTTP server: JSON API + static files (student UI, dashboard). Stdlib only.

M1 scope: /api/health, /api/models, static serving, redirect. Tutor/marker/
stats routes are added in later milestones.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, stats, tutor as tutor_pipeline
from .db import connect, init_db
from .lab import LabClient, LabError
from .llm import LLMError, OllamaProvider
from .tutor import TutorError

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"


def _default_conn():
    conn = connect(config.DB_PATH, check_same_thread=False)
    init_db(conn)
    return conn


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


def _qs(query: str) -> dict:
    return {k: v[0] for k, v in parse_qs(query).items()}


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def make_handler(*, lab: LabClient | None = None, ollama: OllamaProvider | None = None,
                 conn=None):
    lab = lab or LabClient()
    ollama = ollama or OllamaProvider()
    conn = conn or _default_conn()

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
            rel = rel.rstrip("/") or "index.html"
            path = (STATIC_ROOT / rel).resolve()
            if path.is_dir():
                path = path / "index.html"
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
            parsed = urlparse(self.path)
            path, query = parsed.path, parsed.query
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
            if path == "/api/runs":
                self.send_json({"runs": stats.overview(conn)["recent_runs"]})
                return
            if path == "/api/stats/overview":
                q = _qs(query)
                self.send_json(stats.overview(conn))
                return
            if path == "/api/stats/stages":
                q = _qs(query)
                self.send_json(stats.stages(conn, run_id=_int_or_none(q.get("run_id")),
                                            model=q.get("model") or None))
                return
            if path == "/api/stats/marker":
                q = _qs(query)
                self.send_json(stats.marker(conn, run_id=_int_or_none(q.get("run_id"))))
                return
            if path == "/api/stats/model":
                q = _qs(query)
                self.send_json(stats.model_perf(conn, model=q.get("model") or None,
                                                run_id=_int_or_none(q.get("run_id"))))
                return
            if path == "/api/stats/reliability":
                q = _qs(query)
                self.send_json(stats.reliability(conn, run_id=_int_or_none(q.get("run_id")),
                                                 model=q.get("model") or None))
                return
            if path == "/api/stats/compare":
                q = _qs(query)
                ids = [int(x) for x in (q.get("runs") or "").split(",") if x.strip().isdigit()]
                self.send_json({"runs": stats.compare(conn, ids)})
                return
            if path == "/api/traces":
                q = _qs(query)
                self.send_json(stats.traces_list(
                    conn, run_id=_int_or_none(q.get("run_id")),
                    ok=_int_or_none(q.get("ok")), agree=_int_or_none(q.get("agree")),
                    stage=q.get("stage") or None, model=q.get("model") or None,
                    limit=_int_or_none(q.get("limit")) or 50,
                    offset=_int_or_none(q.get("offset")) or 0))
                return
            if path.startswith("/api/traces/"):
                tid = _int_or_none(path.rsplit("/", 1)[-1])
                detail = stats.trace_detail(conn, tid) if tid else None
                self.send_json(detail or {"error": "trace not found"}, 200 if detail else 404)
                return
            if path == "/api/export":
                q = _qs(query)
                run_id = _int_or_none(q.get("run_id"))
                if not run_id:
                    self.send_json({"error": "run_id is required"}, 400)
                    return
                fmt = q.get("format", "csv")
                content, ctype, filename = stats.export(conn, run_id, fmt)
                body = content.encode()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/questions":
                try:
                    self.send_json({"questions": tutor_pipeline.list_questions(conn, lab)})
                except TutorError as e:
                    self.send_json({"error": str(e)}, e.status)
                return
            if path == "/api/sessions":
                self.send_json({"error": "POST to /api/sessions"}, 405)
                return
            if path.startswith("/api/questions/"):
                qid = path.removeprefix("/api/questions/").split("/")[0]
                try:
                    payload, _scheme = tutor_pipeline.fetch_question(conn, lab, qid)
                    self.send_json({"question": payload})
                except TutorError as e:
                    self.send_json({"error": str(e)}, e.status)
                except LabError as e:
                    self.send_json({"error": str(e)}, e.status or 502)
                return
            session_m = re.fullmatch(r"/api/sessions/(\d+)", path)
            if session_m:
                try:
                    session = tutor_pipeline.get_session(conn, int(session_m.group(1)))
                    payload, _ = tutor_pipeline.fetch_question(conn, lab, session["question_id"])
                    self.send_json({"session": session, "question": payload})
                except TutorError as e:
                    self.send_json({"error": str(e)}, e.status)
                return
            if path.startswith("/student/"):
                self.send_static(path.lstrip("/"))
                return
            if path.startswith("/dashboard/"):
                self.send_static(path.lstrip("/"))
                return
            self.send_json({"error": "not found"}, 404)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise TutorError("body must be JSON")

        def stream_ndjson(self, run_fn):
            """NDJSON event stream: {status}, {delta}, {done} / {error}."""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def on_event(event: dict) -> None:
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()

            try:
                run_fn(on_event)
            except TutorError as e:
                on_event({"type": "error", "message": str(e)})
            except (LLMError, LabError) as e:
                on_event({"type": "error", "message": str(e)})
            except Exception as e:  # never hide errors, but keep the stream open
                on_event({"type": "error", "message": f"{type(e).__name__}: {e}"})

        def do_POST(self):
            path = urlparse(self.path).path
            body = {}
            try:
                body = self._read_json()
            except TutorError as e:
                self.send_json({"error": str(e)}, e.status)
                return

            if path == "/api/sessions":
                question_id = str(body.get("question_id") or "")
                if not question_id:
                    self.send_json({"error": "question_id is required"}, 400)
                    return
                try:
                    session = tutor_pipeline.create_session(
                        conn, question_id, str(body.get("student_label") or ""))
                    payload, _ = tutor_pipeline.fetch_question(conn, lab, question_id)
                except TutorError as e:
                    self.send_json({"error": str(e)}, e.status)
                    return
                except LabError as e:
                    self.send_json({"error": str(e)}, e.status or 502)
                    return
                self.send_json({"session": session, "question": payload}, 201)
                return

            m = re.fullmatch(r"/api/sessions/(\d+)/(answer|reveal|hint)", path)
            if m:
                sid, action = int(m.group(1)), m.group(2)
                if action == "hint":
                    try:
                        self.send_json({"hint_level": tutor_pipeline.bump_hint(conn, sid)})
                    except TutorError as e:
                        self.send_json({"error": str(e)}, e.status)
                    return
                if action == "answer":
                    lines = body.get("lines")
                    if not isinstance(lines, dict) or not lines:
                        self.send_json({"error": 'send "lines": {"b": "..."}'}, 400)
                        return
                    self.stream_ndjson(lambda on_event: tutor_pipeline.answer_turn(
                        conn, lab, ollama, sid, lines, think=body.get("think") is True,
                        on_event=on_event))
                    return
                # reveal
                self.stream_ndjson(lambda on_event: tutor_pipeline.reveal(
                    conn, lab, ollama, sid, think=body.get("think") is True,
                    on_event=on_event))
                return

            m = re.fullmatch(r"/api/turns/(\d+)/rating", path)
            if m:
                try:
                    tutor_pipeline.rate_turn(conn, int(m.group(1)), int(body.get("rating", 0)))
                    self.send_json({"ok": True})
                except (TutorError, ValueError) as e:
                    status = getattr(e, "status", 400)
                    self.send_json({"error": str(e)}, status)
                return

            self.send_json({"error": "not found"}, 404)

    return Handler


def serve(port: int | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port or config.TUTOR_PORT), make_handler())
    print(f"tutor-cambridge listening on http://localhost:{server.server_address[1]}  (student UI at /student/, dashboard at /dashboard/)")
    return server


if __name__ == "__main__":
    serve().serve_forever()

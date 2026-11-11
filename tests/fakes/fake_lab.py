"""Fake Marking Lab built from tests/fixtures, for offline contract tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

KEY = "msk_test"


def load_fixtures() -> dict:
    data = json.loads((FIXTURES / "smoke-open.json").read_text())
    questions = {q["id"]: q for q in data["questions"]}
    schemes = {f["question"]["id"]: f["scheme"] for f in data["fixtures"]}
    answers = [{"id": f["answer"]["id"], "questionId": f["answer"]["questionId"],
                "source": "synthetic", "split": "open", "tags": f["answer"].get("tags", []),
                "lines": f["answer"]["lines"]} for f in data["fixtures"]]
    return {"version": data["datasetVersion"], "questions": questions,
            "schemes": schemes, "answers": answers}


def make_handler():
    state = load_fixtures()
    runs: dict[int, dict] = {}
    next_run = {"n": 1}
    next_result = {"n": 1}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, payload, status=200):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {KEY}"

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            if not self._authed():
                return self._send({"error": "Missing or unknown API key."}, 401)
            path, _, query = self.path.partition("?")
            parts = [p for p in path.split("/") if p]
            if parts and parts[0] == "api":
                parts = parts[1:]  # comparisons are relative to /api
            if parts == ["dataset", "version"]:
                return self._send({"datasetVersion": state["version"], "current": state["version"]})
            if parts == ["questions"]:
                return self._send({"datasetVersion": state["version"], "page": 1,
                                   "pageSize": 100, "total": len(state["questions"]),
                                   "questions": list(state["questions"].values())})
            if len(parts) == 2 and parts[0] == "questions":
                q = state["questions"].get(parts[1])
                return self._send({"datasetVersion": state["version"], "question": q}, 200 if q else 404)
            if len(parts) == 3 and parts[0] == "questions" and parts[2] == "scheme":
                scheme = state["schemes"].get(parts[1])
                return self._send({"datasetVersion": state["version"], "scheme": scheme}, 200 if scheme else 404)
            if parts == ["answers"]:
                return self._send({"datasetVersion": state["version"], "split": "open", "page": 1,
                                   "pageSize": 500, "total": len(state["answers"]), "answers": state["answers"]})
            if parts == ["runs"]:
                return self._send({"runs": [r["run"] for r in runs.values()]})
            if len(parts) == 2 and parts[0] == "runs":
                run = runs.get(int(parts[1]))
                return self._send({"run": run["run"]}, 200 if run else 404)
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "score":
                run = runs.get(int(parts[1]))
                if not run:
                    return self._send({"error": "Run does not exist"}, 404)
                return self._send({"runId": run["run"]["id"], "split": "open", "closed": run["closed"],
                                   "detail": run["closed"], "overall": run["overall"],
                                   "disagreements": run["disagreements"] if run["closed"] else []})
            return self._send({"error": "not found"}, 404)

        def do_POST(self):
            if not self._authed():
                return self._send({"error": "Missing or unknown API key."}, 401)
            path = self.path.split("?")[0]
            parts = [p for p in path.split("/") if p]
            if parts and parts[0] == "api":
                parts = parts[1:]  # comparisons are relative to /api
            if parts == ["runs"]:
                body = self._body()
                for field in ("harnessName", "gitCommit", "model", "usedMarkingScheme"):
                    if field not in body:
                        return self._send({"error": f"{field} is required"}, 400)
                if body.get("split", "open") not in ("open", "hidden"):
                    return self._send({"error": "split must be 'open' or 'hidden'"}, 400)
                run_id = next_run["n"]
                next_run["n"] += 1
                runs[run_id] = {"run": {**body, "id": run_id}, "closed": False,
                                "results": [], "overall": {}, "disagreements": []}
                return self._send({"runId": run_id, "datasetVersion": state["version"],
                                   "run": runs[run_id]["run"]}, 201)
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "results":
                run = runs.get(int(parts[1]))
                if not run:
                    return self._send({"error": "Run does not exist"}, 404)
                if run["closed"]:
                    return self._send({"error": "Run is closed"}, 409)
                body = self._body()
                items = body.get("results") if isinstance(body, dict) else body
                ids = []
                for item in items:
                    if "answerId" not in item or "prompt" not in item:
                        return self._send({"error": "invalid result"}, 400)
                    ids.append(next_result["n"])
                    next_result["n"] += 1
                run["results"].extend(items)
                return self._send({"stored": len(items), "runId": run["run"]["id"],
                                   "datasetVersion": state["version"], "resultIds": ids}, 201)
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "close":
                run = runs.get(int(parts[1]))
                if not run:
                    return self._send({"error": "Run does not exist"}, 404)
                if run["closed"]:
                    return self._send({"error": "Run is already closed"}, 409)
                run["closed"] = True
                return self._send({"runId": run["run"]["id"], "closed": True})
            return self._send({"error": "not found"}, 404)

    return Handler


def start() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"

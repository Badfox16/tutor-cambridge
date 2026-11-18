"""Marking Lab client (see docs/marking-lab-contract.md).

Loop: create run -> answers -> question + scheme -> submit results -> close -> score.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import config


class LabError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"Lab {status}: {message}")
        self.status = status


def merge_scheme(question: dict, scheme: dict) -> dict:
    """Attach each marked line's scheme points to the public question."""
    points = {line["label"]: line["points"] for line in scheme["lines"]}
    lines = [{**line, "points": points.get(line["label"], [])} if line.get("marked") else line
             for line in question["lines"]]
    return {**question, "lines": lines}


class Lab:
    def __init__(self, base: str | None = None, key: str | None = None):
        self.base = (base or config.MARKING_BASE).rstrip("/")
        self.key = config.MARKING_KEY if key is None else key

    def _req(self, method: str, path: str, body: dict | None = None, **query) -> dict:
        qs = urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
        req = urllib.request.Request(
            f"{self.base}/api{path}" + (f"?{qs}" if qs else ""),
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            method=method)
        try:
            # long timeout: `next dev` compiles each route on its first request
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("error", e.reason)
            except Exception:
                msg = e.reason
            raise LabError(e.code, msg) from None
        except (urllib.error.URLError, OSError) as e:
            raise LabError(0, f"no connection to {self.base} ({e})") from None

    def version(self) -> dict:
        return self._req("GET", "/dataset/version")

    def create_run(self, **body) -> dict:
        return self._req("POST", "/runs", body)

    def answers(self, run_id: int, question_id: str = "") -> list[dict]:
        return self._req("GET", "/answers", runId=run_id, questionId=question_id,
                         pageSize=500)["answers"]

    def question(self, qid: str, run_id: int) -> dict:
        """Public question merged with its scheme points (the public one has none)."""
        q = self._req("GET", f"/questions/{qid}", runId=run_id)["question"]
        scheme = self._req("GET", f"/questions/{qid}/scheme", runId=run_id)["scheme"]
        return merge_scheme(q, scheme)

    def submit(self, run_id: int, results: list[dict]) -> dict:
        return self._req("POST", f"/runs/{run_id}/results", {"results": results})

    def close(self, run_id: int) -> dict:
        return self._req("POST", f"/runs/{run_id}/close")

    def score(self, run_id: int) -> dict:
        return self._req("GET", f"/runs/{run_id}/score")

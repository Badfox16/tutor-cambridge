"""Client for the Marking Lab server. See docs/marking-lab-contract.md.

The server is the source of truth; this module only ports the HTTP loop
(create run -> fetch answers/questions/schemes -> submit -> close -> score).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import config


class LabError(Exception):
    """An error reported by (or while talking to) the Marking Lab."""

    def __init__(self, status: int, message: str, details: list | None = None):
        super().__init__(f"Lab {status}: {message}")
        self.status = status
        self.message = message
        self.details = details or []


class LabClient:
    def __init__(self, base_url: str | None = None, key: str | None = None, timeout: float | None = None):
        self.base = (base_url or config.MARKING_BASE).rstrip("/")
        self.key = key if key is not None else config.MARKING_KEY
        self.timeout = timeout or config.HTTP_TIMEOUT

    # -- low level -----------------------------------------------------------
    def request(self, method: str, path: str, body: dict | list | None = None) -> dict:
        req = urllib.request.Request(
            self.base + "/api" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            payload = {}
            try:
                payload = json.loads(e.read() or b"{}")
            except Exception:
                pass
            raise LabError(e.code, payload.get("error", e.reason), payload.get("details")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LabError(0, f"connection failed: {e}") from None

    # -- data ----------------------------------------------------------------
    def dataset_version(self, number: int | None = None) -> dict:
        return self.request("GET", "/dataset/version" + (f"?number={number}" if number else ""))

    def questions(self, **filters) -> dict:
        qs = "&".join(f"{k}={v}" for k, v in filters.items())
        return self.request("GET", "/questions" + (f"?{qs}" if qs else ""))

    def question(self, question_id: str, run_id: int | None = None) -> dict:
        return self.request("GET", f"/questions/{question_id}" + (f"?runId={run_id}" if run_id else ""))["question"]

    def scheme(self, question_id: str, run_id: int | None = None) -> dict:
        return self.request("GET", f"/questions/{question_id}/scheme" + (f"?runId={run_id}" if run_id else ""))["scheme"]

    def answers(self, run_id: int | None = None, page_size: int = 500) -> dict:
        qs = f"pageSize={page_size}"
        if run_id is not None:
            qs += f"&runId={run_id}"
        return self.request("GET", f"/answers?{qs}")

    # -- run loop --------------------------------------------------------------
    def create_run(self, *, harness_name: str, model: str, used_scheme: bool,
                   git_commit: str, dirty: bool = False, split: str = "open",
                   prompt_template: str = "", model_settings: dict | None = None,
                   notes: str = "", extra: dict | None = None) -> dict:
        return self.request("POST", "/runs", {
            "harnessName": harness_name,
            "gitCommit": git_commit,
            "dirty": dirty,
            "model": model,
            "modelSettings": model_settings or {},
            "split": split,
            "usedMarkingScheme": used_scheme,
            "promptTemplate": prompt_template,
            "notes": notes,
            "extra": extra or {},
        })

    def submit_results(self, run_id: int, results: list[dict]) -> dict:
        return self.request("POST", f"/runs/{run_id}/results", {"results": results})

    def close_run(self, run_id: int) -> dict:
        return self.request("POST", f"/runs/{run_id}/close")

    def score(self, run_id: int) -> dict:
        return self.request("GET", f"/runs/{run_id}/score")

"""Contract test: student-facing routes NEVER return the mark scheme.

Automated guarantee required by the AGENTS guide (§8, §14). Runs the real
server handler stack against the fake Lab + fake Ollama and inspects every
payload a student route produces.
"""

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fakes import fake_lab, fake_ollama  # noqa: E402
from tutor.db import connect, init_db  # noqa: E402
from tutor.lab import LabClient  # noqa: E402
from tutor.llm import OllamaProvider  # noqa: E402
from tutor.server import make_handler  # noqa: E402
import tempfile  # noqa: E402


def scheme_secrets() -> set[str]:
    """Distinctive strings that exist only inside schemes."""
    secrets = set()
    for scheme in fake_lab.load_fixtures()["schemes"].values():
        for line in scheme.get("lines", []):
            for point in line.get("points", []):
                text = (point.get("text") or "").strip()
                if text:
                    secrets.add(text)
                    secrets.add(text.split(" OR ")[0].strip())
    secrets.discard("")
    return secrets


class TestStudentRoutesNeverLeakScheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ollama_server, cls.ollama_base = fake_ollama.start()
        cls.lab_server, cls.lab_base = fake_lab.start()
        cls.tmp = tempfile.TemporaryDirectory()
        conn = connect(Path(cls.tmp.name) / "c.db", check_same_thread=False)
        init_db(conn)
        lab = LabClient(base_url=cls.lab_base, key=fake_lab.KEY)
        provider = OllamaProvider(model="fake-model", base_url=cls.ollama_base)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(lab=lab, ollama=provider, conn=conn))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.ollama_server.shutdown()
        cls.lab_server.shutdown()
        cls.tmp.cleanup()

    # -- helpers -------------------------------------------------------------
    def get_json(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return resp.status, json.load(resp)

    def post(self, path, body, stream=False):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            if stream:
                events = [json.loads(line) for line in resp if line.strip()]
                return resp.status, events
            return resp.status, json.load(resp)

    def assertNoScheme(self, payload):
        raw = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('"points"', raw)
        for secret in scheme_secrets():
            self.assertNotIn(secret, raw, f"scheme text leaked: {secret!r}")

    # -- the actual contract ---------------------------------------------------
    def test_questions_list_is_safe(self):
        _, data = self.get_json("/api/questions")
        self.assertNoScheme(data)

    def test_single_question_is_safe(self):
        qid = fixture_question_id()
        _, data = self.get_json(f"/api/questions/{qid}")
        self.assertNoScheme(data)

    def test_session_create_get_answer_and_rating_are_safe(self):
        qid = fixture_question_id()
        _, created = self.post("/api/sessions", {"question_id": qid})
        self.assertEqual(len(created["session"]["turns"]), 0)
        sid = created["session"]["id"]
        self.assertNoScheme(created)

        _, got = self.get_json(f"/api/sessions/{sid}")
        self.assertNoScheme(got)

        answer = fake_lab.load_fixtures()["answers"][0]["lines"]
        _, events = self.post(f"/api/sessions/{sid}/answer",
                              {"lines": {"b": answer.get("b", "resposta do aluno")}}, stream=True)
        kinds = [e["type"] for e in events]
        self.assertIn("delta", kinds)
        self.assertEqual(kinds[-1], "done")
        self.assertNoScheme(events)

        turn_id = events[-1]["turn_id"]
        _, out = self.post(f"/api/turns/{turn_id}/rating", {"rating": 1})
        self.assertTrue(out["ok"])

        _, again = self.get_json(f"/api/sessions/{sid}")
        self.assertNoScheme(again)

    def test_reveal_is_safe(self):
        qid = fixture_question_id()
        _, created = self.post("/api/sessions", {"question_id": qid})
        _, events = self.post(f"/api/sessions/{created['session']['id']}/reveal", {}, stream=True)
        self.assertEqual(events[-1]["hint_level"], 3)
        # reveal explains the solution, but still never echoes the scheme layout
        self.assertNoScheme(events)


def fixture_question_id():
    return fake_lab.load_fixtures()["answers"][0]["questionId"]


if __name__ == "__main__":
    unittest.main()

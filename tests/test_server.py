import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fakes import fake_lab, fake_ollama  # noqa: E402
from tutor.lab import LabClient  # noqa: E402
from tutor.llm import OllamaProvider  # noqa: E402
from tutor.server import make_handler  # noqa: E402


class TestServerM1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ollama_server, cls.ollama_base = fake_ollama.start()
        cls.lab_server, cls.lab_base = fake_lab.start()
        lab = LabClient(base_url=cls.lab_base, key=fake_lab.KEY)
        ollama = OllamaProvider(model="fake-model", base_url=cls.ollama_base)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(lab=lab, ollama=ollama))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.ollama_server.shutdown()
        cls.lab_server.shutdown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return resp.status, json.load(resp)

    def get_text(self, path) -> tuple[int, str]:
        with urllib.request.urlopen(self.base + path, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")

    def test_health_reports_both_upstreams(self):
        status, data = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ollama"]["up"])
        self.assertTrue(data["lab"]["up"])
        self.assertEqual(data["lab"]["datasetVersion"], fake_lab.load_fixtures()["version"])

    def test_models_lists_ollama_tags(self):
        status, data = self.get("/api/models")
        self.assertEqual(status, 200)
        self.assertIn("fake-model:latest", data["models"])

    def test_root_redirects_to_student(self):
        req = urllib.request.Request(self.base + "/")

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(req, timeout=10)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 302)
            self.assertEqual(e.headers["Location"], "/student/")
        else:
            self.fail("expected redirect")

    def test_static_served_from_student_dir(self):
        index = Path(ROOT / "static" / "student" / "index.html")
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text("<html><body>aluno</body></html>", encoding="utf-8")
        status, body = self.get_text("/student/index.html")
        self.assertEqual(status, 200)
        self.assertIn("aluno", body)
        with self.subTest("dashboard"):
            dash = Path(ROOT / "static" / "dashboard" / "index.html")
            dash.parent.mkdir(parents=True, exist_ok=True)
            dash.write_text("<html><body>painel</body></html>", encoding="utf-8")
            status, body = self.get_text("/dashboard/index.html")
            self.assertEqual(status, 200)
            self.assertIn("painel", body)

    def test_unknown_route_404(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as ctx:
            self.get("/api/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()

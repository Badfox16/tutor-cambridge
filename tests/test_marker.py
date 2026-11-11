import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fakes import fake_lab, fake_ollama  # noqa: E402
from tutor import db  # noqa: E402
from tutor.lab import LabClient  # noqa: E402
from tutor.llm import OllamaProvider  # noqa: E402
from tutor.marker import run_marker  # noqa: E402


class TestMarkerEndToEnd(unittest.TestCase):
    """Full run against fake Lab + fake Ollama: no real services needed."""

    @classmethod
    def setUpClass(cls):
        cls.ollama_server, cls.ollama_base = fake_ollama.start()
        cls.lab_server, cls.lab_base = fake_lab.start()

    @classmethod
    def tearDownClass(cls):
        cls.ollama_server.shutdown()
        cls.lab_server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")
        db.init_db(self.conn)
        self.client = LabClient(base_url=self.lab_base, key=fake_lab.KEY)
        self.provider = OllamaProvider(model="fake-model", base_url=self.ollama_base)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_run_creates_traces_spans_and_scores(self):
        # fake reply is "Hello world", which never parses: parse failures are data
        summary = run_marker(self.client, self.provider, self.conn, limit=2,
                             prompt_variant="marker-full", think=False)
        self.assertEqual(summary["marked"], 2)
        self.assertEqual(summary["parse_failed"], 2)
        self.assertEqual(summary["errors"], [])

        runs = self.conn.execute("SELECT * FROM runs").fetchall()
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["kind"], "marker")
        self.assertEqual(run["lab_run_id"], summary["lab_run_id"])

        traces = self.conn.execute(
            "SELECT * FROM traces WHERE run_id = ? ORDER BY id", (run["id"],)).fetchall()
        stages = {t["id"]: [s["stage"] for s in
                            self.conn.execute("SELECT stage FROM spans WHERE trace_id = ? ORDER BY id", (t["id"],))]
                  for t in traces}
        # every answer trace walked the full pipeline
        answer_traces = [t for t in traces if t["answer_id"]]
        self.assertEqual(len(answer_traces), 2)
        for t in answer_traces:
            names = [s["stage"] for s in self.conn.execute(
                "SELECT stage FROM spans WHERE trace_id = ? ORDER BY id", (t["id"],))]
            self.assertEqual(names, ["render", "model.load", "model.prefill",
                                     "model.generate", "parse", "lab.submit"])
            self.assertEqual(t["parse_failed"], 1)

        # run-level stages recorded too
        run_stage_names = [s["stage"] for s in self.conn.execute(
            "SELECT stage FROM spans WHERE trace_id IN (SELECT id FROM traces WHERE answer_id = '')")]
        self.assertIn("lab.fetch", run_stage_names)
        self.assertIn("lab.submit", run_stage_names)
        self.assertIn("lab.score", run_stage_names)

        # score persisted
        score_rows = self.conn.execute("SELECT * FROM scores").fetchall()
        self.assertEqual(len(score_rows), 1)

    def test_model_generate_span_carries_metrics(self):
        run_marker(self.client, self.provider, self.conn, limit=1)
        span = self.conn.execute(
            "SELECT * FROM spans WHERE stage = 'model.generate' ORDER BY id DESC LIMIT 1").fetchone()
        import json
        meta = json.loads(span["meta_json"])
        self.assertEqual(span["tokens_in"], 100)
        self.assertEqual(span["tokens_out"], 40)
        self.assertAlmostEqual(meta["load_ms"], 200.0, places=1)
        self.assertAlmostEqual(meta["gen_ms"], 800.0, places=1)
        self.assertIn("ttft_ms", meta)


if __name__ == "__main__":
    unittest.main()

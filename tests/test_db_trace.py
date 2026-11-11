import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tutor import db, trace  # noqa: E402


class TestDbAndTrace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "test.db")
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_schema_and_indexes(self):
        names = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
        for expected in ("runs", "traces", "spans", "scores", "sessions", "turns",
                         "eval_results", "idx_traces_run", "idx_spans_trace",
                         "idx_spans_stage", "idx_turns_session"):
            self.assertIn(expected, names)

    def test_trace_with_spans(self):
        tr = trace.start_trace(self.conn, run_id=None, kind="mark", model="m",
                               question_id="dens-002", answer_id="dens-002-a05")
        with tr.span("render") as span:
            span.tokens_in = 120
            span.meta["chars"] = 500
        try:
            with tr.span("parse"):
                raise ValueError("bad layout")
        except ValueError:
            pass
        tr.finish(ok=False, parse_failed=True, prompt="P", raw_output="R", reason="bad layout")

        row = self.conn.execute("SELECT * FROM traces WHERE id = ?", (tr.id,)).fetchone()
        self.assertEqual(row["ok"], 0)
        self.assertEqual(row["parse_failed"], 1)
        self.assertEqual(row["prompt"], "P")

        spans = trace.spans_for(self.conn, tr.id)
        self.assertEqual([s["stage"] for s in spans], ["render", "parse"])
        self.assertEqual([s["ok"] for s in spans], [1, 0])
        self.assertIn("ValueError", spans[1]["error"])
        self.assertEqual(json_load(spans[0]["meta_json"])["chars"], 500)
        self.assertEqual(spans[0]["tokens_in"], 120)

    def test_span_error_recorded_and_reraised(self):
        tr = trace.start_trace(self.conn, run_id=None, kind="mark")
        with self.assertRaises(RuntimeError):
            with tr.span("model.generate"):
                raise RuntimeError("boom")
        spans = trace.spans_for(self.conn, tr.id)
        self.assertEqual(spans[0]["ok"], 0)

    def test_scores_and_turns_rows(self):
        db.insert(self.conn, "scores", {"run_id": 1, "accuracy_json": "{}",
                                        "disagreements_json": "[]", "fetched_at": db.now()})
        session = db.insert(self.conn, "sessions", {"student_label": "aluno-a",
                                                    "question_id": "dens-002", "started_at": db.now()})
        turn = db.insert(self.conn, "turns", {
            "session_id": session, "attempt": 1, "student_answer": "rho = m/V",
            "marks_json": "{}", "feedback": "bom começo...", "hint_level": 0,
            "leak_flag": 0, "regenerated": 0, "rating": None, "created_at": db.now()})
        row = self.conn.execute("SELECT * FROM turns WHERE id = ?", (turn,)).fetchone()
        self.assertEqual(row["hint_level"], 0)


def json_load(s):
    import json
    return json.loads(s)


if __name__ == "__main__":
    unittest.main()

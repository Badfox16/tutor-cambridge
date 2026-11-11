import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tutor import db, stats  # noqa: E402


def seed(conn):
    """A marker run: 2 answers marked (1 agree, 1 disagree), spans + score."""
    run = db.insert(conn, "runs", {"kind": "marker", "model": "m", "prompt_variant": "p",
                                   "settings_json": "{}", "split": "open", "git_commit": "x",
                                   "dirty": 0, "lab_run_id": 1, "started_at": db.now(),
                                   "status": "done"})
    t1 = db.insert(conn, "traces", {"run_id": run, "kind": "mark", "question_id": "q1",
                                    "answer_id": "a1", "model": "m", "started_at": db.now(),
                                    "ok": 1, "agree": 1, "total_ms": 5000, "attempt": 1})
    t2 = db.insert(conn, "traces", {"run_id": run, "kind": "mark", "question_id": "q2",
                                    "answer_id": "a2", "model": "m", "started_at": db.now(),
                                    "ok": 1, "agree": 0, "total_ms": 15000, "attempt": 1,
                                    "reason": "missing point b.1"})
    for tid, gen_ms, load_ms in ((t1, 800, 0), (t2, 900, 95000)):
        db.insert(conn, "spans", {"trace_id": tid, "stage": "render", "started_at": db.now(),
                                  "duration_ms": 2, "ok": 1})
        db.insert(conn, "spans", {"trace_id": tid, "stage": "model.generate", "started_at": db.now(),
                                  "duration_ms": gen_ms, "ok": 1, "tokens_in": 100,
                                  "tokens_out": 30,
                                  "meta_json": json.dumps({"tokens_per_s": 40, "ttft_ms": 300,
                                                           "load_ms": load_ms,
                                                           "prompt_tokens": 100,
                                                           "gen_tokens": 30, "thinking_chars": 0})})
    db.insert(conn, "spans", {"trace_id": t2, "stage": "parse", "started_at": db.now(),
                              "duration_ms": 1, "ok": 0, "error": "boom"})
    db.insert(conn, "scores", {"run_id": run,
                               "accuracy_json": json.dumps({"overall": {
                                   "results": 2, "parseFailures": 0,
                                   "exactTotalAgreement": 0.5, "lineAgreement": 0.5,
                                   "pointAgreement": 0.75, "meanAbsError": 0.5, "bias": -0.5},
                                   "clearCases": {}}),
                               "disagreements_json": json.dumps([
                                   {"answerId": "a2", "repeat": 1, "questionId": "q2",
                                    "harness": {"total": 1}, "reference": {"total": 2}}]),
                               "fetched_at": db.now()})
    return run, t1, t2


class TestStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "s.db")
        db.init_db(self.conn)
        self.run, self.t1, self.t2 = seed(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_overview_counts_and_success(self):
        ov = stats.overview(self.conn)
        self.assertEqual(ov["counts"]["answer_traces"], 2)
        self.assertEqual(ov["success_rate"], 1.0)
        self.assertEqual(ov["recent_runs"][0]["id"], self.run)

    def test_stages_aggregation(self):
        st = stats.stages(self.conn)
        self.assertEqual(st["render"]["n"], 2)
        self.assertEqual(st["model.generate"]["p50_ms"], 850.0)
        self.assertEqual(st["model.generate"]["p95_ms"], 895.0)
        self.assertEqual(st["parse"]["fail_pct"], 1.0)

    def test_model_perf_cold_vs_warm(self):
        p = stats.model_perf(self.conn)
        self.assertEqual(p["n"], 2)
        self.assertEqual(p["load_cold_warm"], {"cold": 1, "warm": 1})
        self.assertEqual(p["tokens_per_s"]["mean"], 40.0)
        self.assertEqual(p["prompt_tokens"]["mean"], 100.0)
        self.assertEqual(sum(b["n"] for b in p["latency_histogram"]), 2)

    def test_marker_score_and_disagreement_link(self):
        m = stats.marker(self.conn)
        self.assertEqual(m["score"]["overall"]["exactTotalAgreement"], 0.5)
        self.assertEqual(len(m["disagreements"]), 1)
        self.assertEqual(m["disagreements"][0]["trace_id"], self.t2)
        self.assertEqual(m["agreement"], {"agree": 1, "disagree": 1, "n": 2})

    def test_reliability(self):
        r = stats.reliability(self.conn)
        self.assertEqual(r["parse"]["ok"], 2)
        self.assertEqual(r["parse"]["failed"], 0)
        self.assertEqual(r["span_failures"][0]["stage"], "parse")
        self.assertEqual(r["span_failures"][0]["n"], 1)

    def test_traces_list_filters(self):
        data = stats.traces_list(self.conn, agree=0)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["traces"][0]["answer_id"], "a2")
        data = stats.traces_list(self.conn, ok=1)
        self.assertEqual(data["total"], 2)

    def test_trace_detail_has_spans_and_prompt(self):
        db.update(self.conn, "traces", self.t1, {"prompt": "PROMPT", "raw_output": "RAW"})
        d = stats.trace_detail(self.conn, self.t1)
        self.assertEqual(d["prompt"], "PROMPT")
        self.assertEqual([s["stage"] for s in d["spans"]], ["render", "model.generate"])
        self.assertEqual(d["spans"][1]["meta"]["ttft_ms"], 300)
        self.assertIsNone(stats.trace_detail(self.conn, 999))

    def test_export_csv_and_json(self):
        content, ctype, name = stats.export(self.conn, self.run, "csv")
        self.assertTrue(ctype.startswith("text/csv"))
        self.assertIn("question_id", content)
        content, ctype, name = stats.export(self.conn, self.run, "json")
        self.assertEqual(ctype, "application/json")
        self.assertEqual(json.loads(content)["traces"][0]["answer_id"], "a1")

    def test_compare(self):
        out = stats.compare(self.conn, [self.run, 999])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["accuracy"]["exactTotalAgreement"], 0.5)


if __name__ == "__main__":
    unittest.main()

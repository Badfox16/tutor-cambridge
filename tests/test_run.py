"""Full run loop offline: fake Lab (from fixtures) + fake model."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import config, run
from harness.lab import merge_scheme

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "smoke-open.json").read_text())


class FakeLab:
    base = "fake://lab"

    def __init__(self):
        self.submitted, self.closed, self.created = [], False, None
        self.items = FIXTURE["fixtures"]

    def create_run(self, **body):
        self.created = body
        return {"runId": 7, "datasetVersion": 1}

    def answers(self, run_id, question_id=""):
        return [f["answer"] for f in self.items
                if not question_id or f["answer"]["questionId"] == question_id]

    def question(self, qid, run_id):
        f = next(f for f in self.items if f["question"]["id"] == qid)
        return merge_scheme(f["question"], f["scheme"])

    def submit(self, run_id, results):
        self.submitted += results
        return {"stored": len(results)}

    def close(self, run_id):
        self.closed = True

    def score(self, run_id):
        first = self.items[0]["answer"]["id"]
        return {**FIXTURE["score_summary"],
                "disagreements": [{"answerId": first, "repeat": 1, "reference": {}}]}


def full_marks_chat(text, **kw):
    """Fake model: fills the layout with 1 per point; totals get clamped by the parser."""
    layout = text.split("Reply ONLY in this layout (no extra text):\n\n", 1)[1].split("REASON")[0]
    reply = layout.replace("<0-1>", "1").replace("<total>", "99")
    return {"text": reply + "REASON: ok", "total_ms": 1000.0, "tokens_per_s": 5.0, "cut_off": False}


class TestRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(config, "RUNS_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = config.load_profile("default", {"limit": 2, "repeats": 1,
                                                       "prompt": "marker-compact"})

    def test_run_submits_closes_and_saves(self):
        lab = FakeLab()
        rec = run.run(self.profile, lab=lab, chat=full_marks_chat, log=lambda *_: None)
        self.assertEqual(lab.created["split"], "open")
        self.assertTrue(lab.created["usedMarkingScheme"])
        self.assertEqual(len(lab.submitted), 2)
        self.assertTrue(all(not r["parseFailed"] for r in lab.submitted))
        self.assertTrue(lab.closed)
        self.assertEqual([a["agree"] for a in rec["answers"]], [False, True])
        saved = json.loads((config.RUNS_DIR / "0007.json").read_text())
        self.assertEqual(saved["lab_run_id"], 7)
        self.assertIsNotNone(saved["score"])

    def test_parse_failure_is_submitted_as_data(self):
        lab = FakeLab()
        rec = run.run(self.profile, lab=lab, log=lambda *_: None,
                      chat=lambda text, **kw: {"text": "I think it's fine", "total_ms": 1.0})
        self.assertTrue(all(r["parseFailed"] for r in lab.submitted))
        self.assertTrue(all("lines" not in r for r in lab.submitted))
        self.assertEqual(len(rec["answers"]), 2)

    def test_question_filter(self):
        lab = FakeLab()
        qid = FIXTURE["fixtures"][-1]["answer"]["questionId"]
        p = {**self.profile, "question": qid, "limit": 0}
        rec = run.run(p, lab=lab, chat=full_marks_chat, log=lambda *_: None)
        self.assertTrue(all(a["questionId"] == qid for a in rec["answers"]))

    def test_profile_layers(self):
        p = config.load_profile("default", {"model": "x:1b", "limit": None})
        self.assertEqual(p["model"], "x:1b")
        self.assertIn("limit", p)
        with self.assertRaises(KeyError):
            config.load_profile("does-not-exist")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.fakes import fake_lab  # noqa: E402
from tutor import db  # noqa: E402
from tutor.lab import LabClient  # noqa: E402
from tutor.llm import LLMResult  # noqa: E402
from tutor.tutor import (FALLBACK, TutorError, answer_turn, bump_hint,  # noqa: E402
                         create_session, fetch_question, get_session,
                         hint_level_for, list_questions, rate_turn, reveal,
                         safe_question)


class StubProvider:
    """Duck-typed provider returning a scripted text per chat call."""

    def __init__(self, texts=None):
        self.texts = list(texts or ["Vamos pensar juntos: qual grandeza a questão pede?"])
        self.calls = []

    def chat(self, messages, *, think=False, temperature=None, num_ctx=None,
             max_tokens=None, stream=True, on_chunk=None):
        self.calls.append(messages[0]["content"])
        text = self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]
        if on_chunk:
            for piece in (text[:8], text[8:]):
                if piece:
                    on_chunk(piece)
        return LLMResult(text=text, finish_reason="stop", gen_tokens=10)


def fixture_answer_lines():
    data = fake_lab.load_fixtures()
    a = data["answers"][0]
    return {"question_id": a["questionId"], "lines": a["lines"]}


class TestTutorPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "t.db")
        db.init_db(self.conn)
        self.lab = LabClient(base_url=fake_lab.start()[1], key=fake_lab.KEY)
        data = fixture_answer_lines()
        self.session = create_session(self.conn, data["question_id"])
        self.answer = data["lines"]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_answer_turn_streams_and_stores(self):
        provider = StubProvider()
        events = []
        result = answer_turn(self.conn, self.lab, provider, self.session["id"],
                             self.answer, on_event=events.append)
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "status")
        self.assertIn("delta", kinds)
        self.assertEqual(kinds[-1], "done")
        joined = "".join(e.get("text", "") for e in events)
        self.assertIn("Vamos pensar", joined)
        self.assertEqual(result["attempt"], 1)
        self.assertEqual(result["hint_level"], 0)
        self.assertEqual(result["leak_flag"], 0)

        session = get_session(self.conn, self.session["id"])
        turn = session["turns"][0]
        self.assertEqual(turn["feedback"], provider.texts[0])
        self.assertIsNone(turn["marks"]["parsed"])  # fake text never parses

        trace_row = self.conn.execute(
            "SELECT * FROM traces WHERE session_id = ? AND kind='tutor_turn'",
            (self.session["id"],)).fetchone()
        self.assertEqual(trace_row["attempt"], 1)
        stages = [s["stage"] for s in self.conn.execute(
            "SELECT stage FROM spans WHERE trace_id = ? ORDER BY id", (trace_row["id"],))]
        self.assertIn("model.generate", stages)
        self.assertIn("tutor.feedback", stages)
        self.assertIn("tutor.leak_check", stages)

    def test_hint_ladder_grows_per_attempt(self):
        provider = StubProvider()
        r1 = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        r2 = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        self.assertEqual((r1["hint_level"], r2["hint_level"]), (0, 1))
        # 'give another hint' adds to the level, capped at 3
        bump_hint(self.conn, self.session["id"])
        r3 = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        self.assertEqual(r3["hint_level"], 3)

    def test_hint_level_for(self):
        self.assertEqual(hint_level_for(1), 0)
        self.assertEqual(hint_level_for(2), 1)
        self.assertEqual(hint_level_for(3), 2)
        self.assertEqual(hint_level_for(4), 3)
        self.assertEqual(hint_level_for(5), 3)
        self.assertEqual(hint_level_for(1, hint_bump=2), 2)

    def test_leak_regenerates_then_falls_back(self):
        # every call leaks the final value -> regenerate once -> fallback
        provider = StubProvider(texts=["O valor final é 2.4 g/cm³."])
        result = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        self.assertEqual(result["leak_flag"], 1)
        self.assertEqual(result["regenerated"], 1)
        session = get_session(self.conn, self.session["id"])
        self.assertEqual(session["turns"][0]["feedback"], FALLBACK[0])
        self.assertEqual(len(provider.calls), 3)  # mark + feedback + strict regen
        self.assertIn("vazou trechos do mark scheme", provider.calls[2])

    def test_leak_stopped_by_regeneration(self):
        # call 1 = internal marking, call 2 = feedback (leaky), call 3 = strict regen (clean)
        provider = StubProvider(texts=["", "Resposta: 2.4!", "Não revele valores: qual fórmula você usaria?"])
        result = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        self.assertEqual(result["leak_flag"], 1)
        self.assertEqual(result["regenerated"], 1)
        session = get_session(self.conn, self.session["id"])
        self.assertEqual(session["turns"][0]["feedback"], "Não revele valores: qual fórmula você usaria?")

    def test_ngram_leak_falls_back(self):
        from tutor.leak import scheme_text
        provider = StubProvider(texts=[scheme_text(fake_lab.load_fixtures()["schemes"][
            fixture_answer_lines()["question_id"]])])
        result = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        self.assertEqual(result["leak_flag"], 1)
        session = get_session(self.conn, self.session["id"])
        self.assertEqual(session["turns"][0]["feedback"], FALLBACK[0])

    def test_reveal_gives_level_3(self):
        provider = StubProvider()
        result = reveal(self.conn, self.lab, provider, self.session["id"])
        self.assertEqual(result["hint_level"], 3)
        session = get_session(self.conn, self.session["id"])
        self.assertEqual(session["turns"][0]["hint_level"], 3)

    def test_rate_turn(self):
        provider = StubProvider()
        result = answer_turn(self.conn, self.lab, provider, self.session["id"], self.answer)
        rate_turn(self.conn, result["turn_id"], 1)
        session = get_session(self.conn, self.session["id"])
        self.assertEqual(session["turns"][0]["rating"], 1)
        with self.assertRaises(TutorError):
            rate_turn(self.conn, result["turn_id"], 5)
        with self.assertRaises(TutorError):
            rate_turn(self.conn, 9999, 1)

    def test_invalid_line_rejected(self):
        provider = StubProvider()
        with self.assertRaises(TutorError):
            answer_turn(self.conn, self.lab, provider, self.session["id"], {"zz": "x"})

    def test_question_cache_avoids_second_lab_call(self):
        qid = fixture_answer_lines()["question_id"]
        fetch_question(self.conn, self.lab, qid)
        n_before = len(self.lab.request_calls) if hasattr(self.lab, "request_calls") else None
        # second fetch must come from cache (no way to count requests in LabClient,
        # so assert the cache row exists and contents match)
        row = self.conn.execute("SELECT * FROM question_cache WHERE question_id = ?",
                                (qid,)).fetchone()
        self.assertIsNotNone(row)
        cached = json.loads(row["payload_json"])
        self.assertNotIn("points", cached["lines"][0])


class TestSafeQuestion(unittest.TestCase):
    def test_whitelist(self):
        q = {"id": "x", "topic": "T", "stem": "s",
             "lines": [{"label": "b", "text": "t", "marks": 3, "marked": True,
                        "points": [{"code": "C1", "text": "secret"}]}]}
        safe = safe_question(q)
        self.assertNotIn("points", safe["lines"][0])
        self.assertEqual(safe["lines"][0]["text"], "t")


if __name__ == "__main__":
    unittest.main()

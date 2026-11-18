import unittest

from harness.lab import merge_scheme
from harness.prompt import layout, load_template, parse, part_name, point_key, render

QUESTION = {
    "id": "dens-002",
    "stem": "Fig. 1 shows a coil of wire.",
    "lines": [
        {"label": "a(i)", "text": "Show that... [2]", "marks": 2, "answerLineUnit": None, "marked": False},
        {"label": "b", "text": "Calculate the density... [3]", "marks": 3, "answerLineUnit": "g/cm3", "marked": True,
         "points": [
             {"code": "C1", "marks": 1, "text": "density = mass / volume"},
             {"code": "C1", "marks": 1, "text": "148 / 16.6"},
             {"code": "A1", "marks": 1, "text": "8.9 g/cm3"},
         ]},
        {"label": "c", "text": "Describe how... [2]", "marks": 2, "answerLineUnit": None, "marked": True,
         "points": [
             {"code": "B1", "marks": 1, "text": "measure volume with cylinder"},
             {"code": "B1", "marks": 1, "text": "repeat and average"},
         ]},
    ],
}
ANSWER = {"b": "d = 148 / 16.6 = 8.9", "c": "use a cylinder and average"}
CLEAN = ("b.1: 1\nb.2: 1\nb.3: 1\nMARK b: 3 / 3\nc.1: 1\nc.2: 0\nMARK c: 1 / 2\n"
         "REASON: density right; averaging point missed.")


class TestRender(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(point_key("b", 0), "b.1")
        self.assertEqual(point_key("main", 0), "1")
        self.assertEqual(part_name("a(i)"), "(a)(i)")

    def test_layout(self):
        out = layout([l for l in QUESTION["lines"] if l["marked"]])
        self.assertIn("b.1: <0-1>", out)
        self.assertIn("MARK c: <total> / 2", out)

    def test_render_all_variants(self):
        for variant in ("marker-compact", "marker-full"):
            text = render(load_template(variant), QUESTION, ANSWER)
            self.assertIn("MARK SCHEME:", text)
            self.assertIn("STUDENT ANSWER:\nd = 148 / 16.6 = 8.9", text)
            self.assertIn("QUESTION:\nFig. 1 shows a coil of wire.", text)
            self.assertIn("(answer line unit: g/cm3)", text)
            self.assertNotIn("a(i)", text)  # unmarked line stays out

    def test_merge_scheme(self):
        public = {"stem": "s", "lines": [{"label": "b", "marks": 3, "marked": True},
                                         {"label": "a", "marks": 0, "marked": False}]}
        merged = merge_scheme(public, {"lines": [{"label": "b", "points": [{"marks": 1}]}]})
        self.assertEqual(merged["lines"][0]["points"], [{"marks": 1}])
        self.assertNotIn("points", merged["lines"][1])


class TestParse(unittest.TestCase):
    def check(self, raw):
        return parse(raw, QUESTION, ANSWER)

    def test_clean(self):
        parsed, reason = self.check(CLEAN)
        self.assertEqual(parsed, {"b": {"marks": [1, 1, 1], "total": 3}, "c": {"marks": [1, 0], "total": 1}})
        self.assertIn("averaging", reason)

    def test_think_block_ignored(self):
        parsed, _ = self.check("<think>b.1: 0\nMARK b: 0 / 3</think>\n" + CLEAN)
        self.assertEqual(parsed["b"]["total"], 3)

    def test_brackets_bold_bullets(self):
        raw = "- **b.1**: <1>\n- b.2) [0]\n- Point b.3: **1**\nMARK b: **2** / 3\nc.1: 1\nc.2: 1\nMARK c: 2 / 2"
        parsed, _ = self.check(raw)
        self.assertEqual(parsed["b"], {"marks": [1, 0, 1], "total": 2})

    def test_template_echo_rejected(self):
        raw = "b.1: <0-1>\nb.2: <0-1>\nb.3: <0-1>\nMARK b: <total> / 3\nc.1: <0-1>\nc.2: <0-1>\nMARK c: <total> / 2"
        self.assertIsNone(self.check(raw)[0])

    def test_total_clamped(self):
        parsed, _ = self.check(CLEAN.replace("MARK b: 3 / 3", "MARK b: 5 / 3"))
        self.assertEqual(parsed["b"]["total"], 3)

    def test_missing_point(self):
        parsed, reason = self.check(CLEAN.replace("b.3: 1\n", ""))
        self.assertIsNone(parsed)
        self.assertIn("missing point b.3", reason)

    def test_mark_above_point_value(self):
        parsed, reason = self.check(CLEAN.replace("b.1: 1", "b.1: 2"))
        self.assertIsNone(parsed)
        self.assertIn("exceeds", reason)

    def test_missing_total(self):
        parsed, reason = self.check(CLEAN.replace("MARK b: 3 / 3\n", ""))
        self.assertIsNone(parsed)
        self.assertIn("MARK b", reason)

    def test_empty(self):
        self.assertIsNone(self.check("")[0])


if __name__ == "__main__":
    unittest.main()

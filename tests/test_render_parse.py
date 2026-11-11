import unittest

from tutor.parse import parse_marker_reply
from tutor.render import build_layout, part_name, point_key, render_marker_prompt

QUESTION = {
    "id": "dens-002",
    "stem": "Fig. 1 shows a coil of wire.",
    "lines": [
        {"label": "a(i)", "text": "Show that... [2]", "marks": 2, "answerLineUnit": None, "marked": False, "points": []},
        {"label": "b", "text": "Calculate the density... [3]", "marks": 3, "answerLineUnit": "g/cm3", "marked": True,
         "points": [
             {"code": "C1", "type": "method", "marks": 1, "text": "density = mass / volume"},
             {"code": "C1", "type": "method", "marks": 1, "text": "148 / 16.6"},
             {"code": "A1", "type": "final_answer", "marks": 1, "text": "8.9 g/cm3"},
         ]},
        {"label": "c", "text": "Describe how... [2]", "marks": 2, "answerLineUnit": None, "marked": True,
         "points": [
             {"code": "B1", "type": "statement", "marks": 1, "text": "measure volume with cylinder"},
             {"code": "B1", "type": "statement", "marks": 1, "text": "repeat and average"},
         ]},
    ],
}
ANSWER_LINES = {"b": "d = 148 / 16.6 = 8.9", "c": "use a cylinder and average"}
SCHEME = {"markedMarks": 5, "lines": [l for l in QUESTION["lines"] if l["marked"]]}


def clean_reply():
    return ("b.1: 1\nb.2: 1\nb.3: 1\nMARK b: 3 / 3\nc.1: 1\nc.2: 0\nMARK c: 1 / 2\n"
            "REASON: density right; averaging point missed.")


class TestRender(unittest.TestCase):
    def test_point_and_part_keys(self):
        self.assertEqual(point_key("b", 0), "b.1")
        self.assertEqual(point_key("main", 0), "1")
        self.assertEqual(part_name("b"), "(b)")
        self.assertEqual(part_name("a(i)"), "(a)(i)")

    def test_layout_shape(self):
        lines = [l for l in QUESTION["lines"] if l["marked"]]
        layout = build_layout(lines)
        self.assertIn("b.1: <0-1>", layout)
        self.assertIn("MARK b: <total> / 3", layout)
        self.assertIn("MARK c: <total> / 2", layout)

    def test_full_prompt_has_all_sections(self):
        prompt, lines = render_marker_prompt(QUESTION, ANSWER_LINES, with_scheme=True)
        self.assertEqual([l["label"] for l in lines], ["b", "c"])
        self.assertIn("MARK SCHEME:", prompt)
        self.assertIn("STUDENT ANSWER:\nd = 148 / 16.6 = 8.9", prompt)
        self.assertIn("QUESTION:\nFig. 1 shows a coil of wire.", prompt)
        self.assertIn("(answer line unit: g/cm3)", prompt)
        self.assertNotIn("a(i)", prompt)  # unmarked context line stays out

    def test_variants_render(self):
        for variant in ("marker-full", "marker-compact"):
            prompt, _ = render_marker_prompt(QUESTION, ANSWER_LINES, with_scheme=True, variant=variant)
            self.assertIn("MARK b: <total> / 3", prompt)

    def test_merge_scheme_fills_points(self):
        from tutor.render import merge_scheme
        public = {"id": "dens-002", "stem": "s", "lines": [
            {"label": "b", "text": "t", "marks": 3, "marked": True},
            {"label": "a", "text": "u", "marks": 0, "marked": False},
        ]}
        scheme = {"markedMarks": 3, "lines": [
            {"label": "b", "marks": 3, "points": [{"code": "C1", "marks": 1, "text": "p1"}]},
        ]}
        merged = merge_scheme(public, scheme)
        self.assertEqual(merged["lines"][0]["points"], [{"code": "C1", "marks": 1, "text": "p1"}])
        self.assertNotIn("points", merged["lines"][1])


class TestParse(unittest.TestCase):
    def test_clean_reply(self):
        parsed, reason = parse_marker_reply(clean_reply(), QUESTION, ANSWER_LINES)
        self.assertEqual(parsed, {"b": {"marks": [1, 1, 1], "total": 3},
                                  "c": {"marks": [1, 0], "total": 1}})
        self.assertIn("averaging", reason)

    def test_bracketed_values_accepted(self):
        raw = "b.1: <1>\nb.2: <0>\nb.3: <1>\nMARK b: <2> / 3\nc.1: [1]\nc.2: 1\nMARK c: 2 / 2\nREASON: ok"
        parsed, _ = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertEqual(parsed["b"], {"marks": [1, 0, 1], "total": 2})

    def test_template_echo_rejected(self):
        # the model copies the layout literally: `<0-1>` is a range, not a mark
        raw = "b.1: <0-1>\nb.2: <0-1>\nb.3: <0-1>\nMARK b: <total> / 3\nc.1: <0-1>\nc.2: <0-1>\nMARK c: <total> / 2\nREASON: x"
        parsed, reason = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertIsNone(parsed)

    def test_markdown_bold_and_bullets(self):
        raw = "- **b.1**: 1\n- b.2) 0\n- Point b.3: 1\nMARK b: 2 / 3\nc.1: 1\nc.2: 1\nMARK c: 2 / 2\nREASON: ok"
        parsed, _ = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertEqual(parsed["b"], {"marks": [1, 0, 1], "total": 2})

    def test_total_clamped_to_line_marks(self):
        raw = "b.1: 1\nb.2: 1\nb.3: 1\nMARK b: 5 / 3\nc.1: 1\nc.2: 1\nMARK c: 2 / 2\nREASON: x"
        parsed, _ = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertEqual(parsed["b"]["total"], 3)

    def test_missing_point_line_rejected(self):
        raw = "b.1: 1\nb.2: 1\nMARK b: 2 / 3\nc.1: 1\nc.2: 1\nMARK c: 2 / 2\nREASON: x"
        parsed, reason = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertIsNone(parsed)
        self.assertIn("missing point b.3", reason)

    def test_mark_above_point_value_rejected(self):
        raw = "b.1: 2\nb.2: 1\nb.3: 1\nMARK b: 3 / 3\nc.1: 1\nc.2: 1\nMARK c: 2 / 2\nREASON: x"
        parsed, reason = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertIsNone(parsed)
        self.assertIn("exceeds", reason)

    def test_missing_total_rejected(self):
        raw = "b.1: 1\nb.2: 1\nb.3: 1\nc.1: 1\nc.2: 1\nMARK c: 2 / 2\nREASON: x"
        parsed, reason = parse_marker_reply(raw, QUESTION, ANSWER_LINES)
        self.assertIsNone(parsed)
        self.assertIn("MARK b", reason)

    def test_empty_reply(self):
        parsed, reason = parse_marker_reply("", QUESTION, ANSWER_LINES)
        self.assertIsNone(parsed)


if __name__ == "__main__":
    unittest.main()

import unittest

from tutor.leak import final_answer_values, leak_check, scheme_text

SCHEME = {
    "markedMarks": 3,
    "lines": [{
        "label": "b", "marks": 3, "points": [
            {"code": "C1", "type": "method", "marks": 1, "text": "density = mass ÷ volume OR ρ = m / V in any form"},
            {"code": "C1", "type": "method", "marks": 1, "text": "148 ÷ 16.6"},
            {"code": "A1", "type": "final_answer", "marks": 1, "text": "(ρ =) 8.9 (g/cm³)"},
        ],
    }],
}


class TestFinalValues(unittest.TestCase):
    def test_extracts_final_answer_numbers_only(self):
        values = final_answer_values(SCHEME)
        self.assertEqual(values, ["8.9"])  # 148 ÷ 16.6 are method points, not final

    def test_no_final_points(self):
        scheme = {"lines": [{"label": "b", "marks": 1, "points": [
            {"code": "C1", "type": "method", "marks": 1, "text": "42"}]}]}
        self.assertEqual(final_answer_values(scheme), [])


class TestLeakCheck(unittest.TestCase):
    def test_clean_feedback_passes(self):
        leaked, reasons = leak_check(
            "Boa estrutura! Qual fórmula liga massa e volume? Tente escrevê-la em símbolos.",
            SCHEME, hint_level=0)
        self.assertFalse(leaked)
        self.assertEqual(reasons, [])

    def test_final_value_leak(self):
        leaked, reasons = leak_check("A resposta é 8.9 g/cm³.", SCHEME, hint_level=0)
        self.assertTrue(leaked)
        self.assertTrue(any("8.9" in r for r in reasons))

    def test_comma_decimal_variant_leaks(self):
        leaked, _ = leak_check("A resposta é 8,9 g/cm³.", SCHEME, hint_level=0)
        self.assertTrue(leaked)

    def test_numeric_allowed_at_level_3(self):
        leaked, reasons = leak_check("A resposta final é 8.9 g/cm³.", SCHEME, hint_level=3)
        self.assertFalse(leaked)

    def test_ngram_copy_leak(self):
        text = scheme_text(SCHEME)  # feed scheme words back to the student
        feedback = "Repare: density = mass ÷ volume OR ρ = m / V in any form."
        leaked, reasons = leak_check(feedback, SCHEME, hint_level=0)
        self.assertTrue(leaked)
        self.assertTrue(any("n-gram" in r for r in reasons))

    def test_short_feedback_no_false_positive(self):
        leaked, _ = leak_check("Use a fórmula da densidade.", SCHEME, hint_level=0)
        self.assertFalse(leaked)

    def test_mark_scheme_header_leaks_at_any_level(self):
        feedback = "MARK SCHEME: 8.9"
        leaked, reasons = leak_check(feedback, SCHEME, hint_level=3)
        self.assertTrue(leaked)
        self.assertTrue(any("MARK SCHEME" in r for r in reasons))

    def test_empty_feedback(self):
        leaked, _ = leak_check("", SCHEME, 0)
        self.assertFalse(leaked)


if __name__ == "__main__":
    unittest.main()

import unittest

from harness import post

Q_CALC = {"lines": [{"label": "a(ii)", "marks": 3, "marked": True, "points": [
    {"code": "C1", "marks": 1, "text": "(density =) mass ÷ volume"},
    {"code": "C1", "marks": 1, "text": "12 ÷ 0.88"},
    {"code": "A1", "marks": 1, "text": "14 (g/cm³)"}]}]}
Q_B1 = {"lines": [{"label": "main", "marks": 3, "marked": True, "points": [
    {"code": "B1", "marks": 1, "text": "x"}] * 5}]}


class TestPost(unittest.TestCase):
    def test_parse_rules_order_and_unknown(self):
        self.assertEqual(post.parse_rules("sum, implied"), ["implied", "sum"])
        self.assertEqual(post.parse_rules(""), [])
        with self.assertRaises(ValueError):
            post.parse_rules("magic")

    def test_scheme_value(self):
        self.assertEqual(post.scheme_value("2.4(0) (g/cm³)"), "2.4")
        self.assertEqual(post.scheme_value("(ρ =) 8.9 (g/cm³)"), "8.9")
        self.assertEqual(post.scheme_value("14 (g/cm³)"), "14")
        self.assertIsNone(post.scheme_value("(density =) 98.4 ÷ 41.0"))
        self.assertIsNone(post.scheme_value("good reflector"))

    def test_final_number_ignores_unit_exponents(self):
        self.assertEqual(post.final_number("= 12 ÷ 0.88\n= 13.6 g/cm3"), "13.6")
        self.assertEqual(post.final_number("2.40 g/cm³"), "2.40")
        self.assertIsNone(post.final_number("it rises"))

    def test_matches_rounding(self):
        self.assertTrue(post.matches("13.6", "14"))
        self.assertTrue(post.matches("2.40", "2.4"))
        self.assertTrue(post.matches("2.3976", "2.4"))
        self.assertFalse(post.matches("1.36", "14"))
        self.assertFalse(post.matches("2.5", "2.4"))

    def test_numeric_then_implied(self):
        parsed = {"a(ii)": {"marks": [0, 1, 0], "total": 1}}
        out, ch = post.apply(parsed, Q_CALC, {"a(ii)": "d = 12/0.88 = 13.6 g/cm3"},
                             ["numeric", "implied", "sum"])
        self.assertEqual(out["a(ii)"], {"marks": [1, 1, 1], "total": 3})
        self.assertTrue(any("A1" in c for c in ch))
        self.assertEqual(parsed["a(ii)"]["marks"], [0, 1, 0])  # input untouched

    def test_numeric_never_lowers(self):
        parsed = {"a(ii)": {"marks": [1, 1, 1], "total": 3}}
        out, ch = post.apply(parsed, Q_CALC, {"a(ii)": "= 9.1"}, ["numeric"])
        self.assertEqual(out, parsed)
        self.assertEqual(ch, [])

    def test_implied_needs_a1(self):
        parsed = {"a(ii)": {"marks": [0, 1, 0], "total": 1}}
        out, _ = post.apply(parsed, Q_CALC, {"a(ii)": "= 9.1"}, ["implied"])
        self.assertEqual(out["a(ii)"]["marks"], [0, 1, 0])

    def test_sum_caps_total(self):
        parsed = {"main": {"marks": [1, 1, 1, 1, 0], "total": 2}}
        out, _ = post.apply(parsed, Q_B1, {"main": "..."}, ["sum"])
        self.assertEqual(out["main"]["total"], 3)

    def test_no_rules_is_identity(self):
        parsed = {"main": {"marks": [1, 0, 0, 0, 0], "total": 1}}
        self.assertEqual(post.apply(parsed, Q_B1, {}, []), (parsed, []))


if __name__ == "__main__":
    unittest.main()

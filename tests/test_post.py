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


class TestUnits(unittest.TestCase):
    def test_normalize_unit(self):
        for raw, want in [("g/cm³", "g/cm3"), ("kg m⁻³", "kg/m3"), ("kgm-3", "kg/m3"),
                          ("g cm-3", "g/cm3"), ("m s-1", "m/s"), ("ohms", "Ω"), ("N.", "N")]:
            self.assertEqual(post.normalize_unit(raw), want, raw)

    def test_unit_info(self):
        self.assertEqual(post.unit_info("g/cm³"), ("density", 1e3))
        self.assertEqual(post.unit_info("g/mL"), ("density", 1e3))
        self.assertEqual(post.unit_info("MW")[1], 1e6)
        self.assertEqual(post.unit_info("mW")[1], 1e-3)
        self.assertIsNone(post.unit_info("bananas"))

    def test_scheme_unit(self):
        self.assertEqual(post.scheme_unit("14 (g/cm³)"), "g/cm³")
        self.assertEqual(post.scheme_unit("2.4(0) (g/cm³)"), "g/cm³")
        self.assertIsNone(post.scheme_unit("coil submerged in water (owtte)"))

    def test_final_value_forms(self):
        self.assertEqual(post.final_value("= 13 600 kg/m³"), ("13600", 0, "kg/m³"))
        self.assertEqual(post.final_value("= 1.36 × 10⁴ kg/m3"), ("1.36", 4, "kg/m3"))
        self.assertEqual(post.final_value("= 1.36x10^4 kg/m3"), ("1.36", 4, "kg/m3"))
        self.assertEqual(post.final_value("= 8.8 x 10^-7 m3"), ("8.8", -7, "m3"))
        self.assertEqual(post.final_value("2.4 g/cm³ so it sinks"), ("2.4", 0, "g/cm³"))
        self.assertEqual(post.final_value("2 x 100"), ("100", 0, None))
        self.assertEqual(post.final_value("= 12 ÷ 0.88\n= 13.6"), ("13.6", 0, None))

    def test_value_matches_with_conversion(self):
        real = "m = 0.012 kg, V = 0.88 × 10⁻⁶ m³\nρ = m / V = 0.012 / 0.88 × 10⁻⁶\n= 13 600 kg/m³"
        self.assertTrue(post.value_matches(real, "14", "g/cm³")[0])        # dens-003-a06
        self.assertTrue(post.value_matches("= 1.36 × 10⁴ kg/m³", "14", "g/cm³")[0])
        self.assertTrue(post.value_matches("= 2400 kg/m3", "2.4", "g/cm³")[0])
        self.assertTrue(post.value_matches("= 13.6", "14", "g/cm³")[0])    # no unit: as written
        self.assertTrue(post.value_matches("= 13.6 g/cm3", "14", "g/cm³")[0])

    def test_value_matches_rejects_wrong_unit(self):
        self.assertFalse(post.value_matches("= 14 kg/m³", "14", "g/cm³")[0])  # same number, wrong unit
        self.assertFalse(post.value_matches("= 14 kg", "14", "g/cm³")[0])     # other quantity
        self.assertFalse(post.value_matches("= 136 kg/m³", "14", "g/cm³")[0])

    def test_apply_uses_answer_line_unit(self):
        q = {"lines": [{"label": "b", "marks": 3, "marked": True, "answerLineUnit": "g/cm³",
                        "points": [{"code": "C1", "marks": 1, "text": "m ÷ V"},
                                   {"code": "C1", "marks": 1, "text": "98.4 ÷ 41.0"},
                                   {"code": "A1", "marks": 1, "text": "2.4(0)"}]}]}
        parsed = {"b": {"marks": [1, 1, 0], "total": 2}}
        out, ch = post.apply(parsed, q, {"b": "= 2400 kg/m³"}, ["numeric", "sum"])
        self.assertEqual(out["b"], {"marks": [1, 1, 1], "total": 3})
        self.assertIn("kg/m³", ch[0])
        out, _ = post.apply(parsed, q, {"b": "= 2.4 kg/m³"}, ["numeric", "sum"])
        self.assertEqual(out["b"]["total"], 2)


if __name__ == "__main__":
    unittest.main()

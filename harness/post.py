"""Deterministic post-processing of the parsed marks (Cambridge conventions).

Small models do not apply general marking rules reliably when told to in the
prompt (experiment log [10]), so the conventions that need no judgment live here.
The model only decides point by point; these rules fix the bookkeeping.

Rules (profile key `post`, comma-separated, applied in this order):
  numeric  A1 = 0 but the student's final value rounds to the A1 value -> A1 = 1.
           A correct answer in another correct unit counts (13 600 kg/m³ = 13.6 g/cm³);
           the same number in a different unit of the same quantity does not (14 kg/m³).
  a1check  A1 = 1 but no value in the answer equals the A1 value -> A1 = 0
           (the model accepts power-of-ten slips: 0.14 or 1.4 for 14)
  subst    a substitution C1 (scheme text is only numbers, e.g. "12 ÷ 0.88") is
           awarded, A1 is not, and one of those numbers is not in the answer -> C1 = 0
  implied  A1 awarded -> every C1 of that part awarded (C marks are implied)
  sum      part total = min(sum of points, part marks), ignoring the model's MARK line
"""

from __future__ import annotations

import re

RULES = ("numeric", "a1check", "subst", "implied", "sum")

# A number not glued to a letter (so the 3 in "cm3" / "m3" is not a value).
_NUM = re.compile(r"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)(?![\d])")

# A value as students write it: "13 600", "1.36 × 10⁴", "1.36x10^4", "2.4", then the unit.
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_VALUE = re.compile(
    r"(?<![A-Za-z\d.])"
    r"(\d{1,3}(?:[ \u00a0\u2009\u202f]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"  # 13 600 | 2.4 | 2,4
    r"(?:\s*[×xX*]\s*10\s*(?:\^\s*\(?\s*(-?\d+)\)?|([⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)))?"  # × 10⁻⁶ | x 10^-6
    r"(?![\d])"
    r"[ \t]*((?:[A-Za-zμµΩ°%]|/(?=[A-Za-zμµΩ]))[^\s=,;()]*(?:[ \t]+[A-Za-zμµΩ][^\s=,;()]*)*)?")  # unit: words, not "/16.6"

# Units by quantity, as a factor to the SI unit. Temperature (offsets) left out on purpose.
UNITS = {
    "density": {"kg/m3": 1, "g/cm3": 1e3, "g/m3": 1e-3, "kg/cm3": 1e6, "g/ml": 1e3, "kg/l": 1e3, "g/l": 1},
    "mass": {"kg": 1, "g": 1e-3, "mg": 1e-6, "t": 1e3},
    "length": {"m": 1, "cm": 1e-2, "mm": 1e-3, "km": 1e3, "μm": 1e-6, "nm": 1e-9},
    "area": {"m2": 1, "cm2": 1e-4, "mm2": 1e-6, "km2": 1e6},
    "volume": {"m3": 1, "cm3": 1e-6, "mm3": 1e-9, "dm3": 1e-3, "l": 1e-3, "ml": 1e-6},
    "time": {"s": 1, "ms": 1e-3, "min": 60, "h": 3600},
    "speed": {"m/s": 1, "km/h": 1 / 3.6, "cm/s": 1e-2},
    "force": {"N": 1, "kN": 1e3, "mN": 1e-3},
    "pressure": {"Pa": 1, "kPa": 1e3, "MPa": 1e6, "N/m2": 1, "N/cm2": 1e4},
    "energy": {"J": 1, "kJ": 1e3, "MJ": 1e6},
    "power": {"W": 1, "kW": 1e3, "MW": 1e6, "mW": 1e-3},
    "current": {"A": 1, "mA": 1e-3},
    "voltage": {"V": 1, "kV": 1e3, "mV": 1e-3},
    "resistance": {"Ω": 1, "kΩ": 1e3, "MΩ": 1e6},
    "frequency": {"Hz": 1, "kHz": 1e3, "MHz": 1e6},
}
_CASELESS = {"density", "volume"}  # g/ml = g/mL, l = L; elsewhere case matters (mW vs MW)


def normalize_unit(unit: str | None) -> str | None:
    """'g/cm³' -> 'g/cm3', 'kg m⁻³' -> 'kg/m3', 'kgm-3' -> 'kg/m3', 'ohm' -> 'Ω'."""
    if not unit:
        return None
    u = unit.strip().rstrip(".").translate(_SUP).replace("µ", "μ")
    u = re.sub(r"\bohms?\b", "Ω", u, flags=re.IGNORECASE)
    u = re.sub(r"\s*(?:/|per)\s*", "/", u)
    per = lambda m: f"/{m.group(1)}{'' if m.group(2) == '1' else m.group(2)}"  # noqa: E731
    u = re.sub(r"\s+([A-Za-zμ]+)\^?-(\d)", per, u)                         # kg m-3 -> kg/m3, m s-1 -> m/s
    u = re.sub(r"^(kg|g)(m|cm)-(\d)$", r"\1/\2\3", u)                      # kgm-3 -> kg/m3
    u = u.replace(" ", "")
    return u or None


def unit_info(unit: str | None) -> tuple[str, float] | None:
    """-> (quantity, factor to SI) for a known unit, else None."""
    u = normalize_unit(unit)
    if not u:
        return None
    for quantity, table in UNITS.items():
        for name, factor in table.items():
            if u == name or (quantity in _CASELESS and u.lower() == name.lower()):
                return quantity, factor
    return None


def parse_rules(spec: str) -> list[str]:
    rules = [r.strip() for r in (spec or "").split(",") if r.strip()]
    bad = [r for r in rules if r not in RULES]
    if bad:
        raise ValueError(f"unknown post rule(s) {bad} (available: {', '.join(RULES)})")
    return [r for r in RULES if r in rules]  # fixed order


def scheme_value(text: str) -> str | None:
    """The answer value of an A1 point: '2.4(0) (g/cm³)' -> '2.4', '14 (g/cm³)' -> '14'.
    None when there is not exactly one number (ranges, words, formulas)."""
    text = re.sub(r"(\d)\(\d+\)", r"\1", text)     # 2.4(0) -> 2.4 (optional figures)
    nums = _NUM.findall(text)
    return nums[0] if len(nums) == 1 else None


def scheme_unit(text: str) -> str | None:
    """'14 (g/cm³)' -> 'g/cm³'; the unit in the last bracket after the value."""
    text = re.sub(r"(\d)\(\d+\)", r"\1", text)     # 2.4(0) -> 2.4
    m = re.search(r"\d[^()]*\(([^()]+)\)\s*$", text)
    return m.group(1).strip() if m and unit_info(m.group(1)) else None


def sig_figs(value: str) -> int:
    digits = value.replace(".", "").lstrip("0")
    if "." not in value:
        digits = digits.rstrip("0") or "0"
    return max(len(digits), 1)


def round_sf(x: float, sf: int) -> float:
    if x == 0:
        return 0.0
    from math import floor, log10
    return round(x, sf - 1 - floor(log10(abs(x))))


def matches(student: str, ref: str) -> bool:
    """Student value equals the scheme value after rounding to the scheme's figures."""
    s, r = float(student), float(ref)
    return s == r or round_sf(s, sig_figs(ref)) == r


def final_number(answer_text: str) -> str | None:
    v = final_value(answer_text)
    return v[0] if v else None


def readings(raw: str) -> list[str]:
    """Decimal strings a written number can mean, most likely first.
    '13 600' -> ['13600']; '2,4' -> ['2.4'] (decimal comma);
    '13,600' -> ['13600', '13.600'] (English thousands, or a decimal comma)."""
    s = re.sub(r"[ \u00a0\u2009\u202f]", "", raw)
    if "," not in s:
        return [s]
    if re.fullmatch(r"\d{1,3},\d{3}", s):
        return [s.replace(",", ""), s.replace(",", ".")]
    return [s.replace(",", ".")]


def final_value(answer_text: str) -> tuple[str, int, str | None] | None:
    """Last value in the answer -> (mantissa as written, power of ten, unit or None).
    '= 13 600 kg/m³' -> ('13600', 0, 'kg/m³'); '1.36 × 10⁴ kg/m3' -> ('1.36', 4, 'kg/m3')."""
    found = list(_VALUE.finditer(answer_text or ""))
    if not found:
        return None
    m = found[-1]
    mantissa = readings(m.group(1))[0]
    power = m.group(2) or m.group(3)
    exp = int(power.translate(_SUP)) if power else 0
    unit = (m.group(4) or "").strip() or None
    if unit and not unit_info(unit) and unit_info(unit.split()[0]):
        unit = unit.split()[0]                     # "g/cm³ so it sinks" -> "g/cm³"
    return mantissa, exp, unit


def value_matches(answer_text: str, ref: str, ref_unit: str | None) -> tuple[bool, str]:
    """Does the student's final value equal the scheme value? -> (ok, description).
    Units are compared only when both are known: then the student's value is converted
    to the scheme unit; a known unit of another quantity never matches."""
    v = final_value(answer_text)
    if not v:
        return False, ""
    mantissa, exp, unit = v
    value = float(mantissa) * 10 ** exp
    shown = f"{mantissa}{f'e{exp}' if exp else ''}{f' {unit}' if unit else ''}"
    s_info, r_info = unit_info(unit), unit_info(ref_unit)
    if s_info and r_info:
        if s_info[0] != r_info[0]:
            return False, shown
        converted = value * s_info[1] / r_info[1]
        return close(converted, ref), f"{shown} = {converted:g} {ref_unit}"
    return close(value, ref), shown


def any_value_matches(answer_text: str, ref: str, ref_unit: str | None) -> bool:
    """True if the final value (unit-aware) or any number written in the answer equals
    the scheme value. Generous on purpose: a1check only removes A1 when this is False."""
    if value_matches(answer_text, ref, ref_unit)[0]:
        return True
    return any(close(float(n), ref) for n in answer_numbers(answer_text))


def answer_numbers(text: str) -> set[float]:
    """Every number written in the answer ("13 600" -> 13600), ignoring unit exponents."""
    return {float(r) for m in _VALUE.finditer(text or "") for r in readings(m.group(1))}


def substitution_numbers(text: str) -> list[float] | None:
    """'(ρ =) 148 ÷ 16.6' -> [148.0, 16.6]; None if the point is not a pure substitution."""
    body = re.sub(r"^\s*\([^)]*=\s*\)\s*", "", text)          # drop "(ρ =)" / "(density =)"
    if not re.fullmatch(r"[\d.\s÷×x*/+\-()]+", body) or not re.search(r"[÷×x*/+\-]", body):
        return None
    nums = [float(n) for n in _NUM.findall(body)]
    return nums if len(nums) >= 2 else None


def close(value: float, ref: str) -> bool:
    """value rounds to ref at ref's significant figures (float-safe)."""
    r = float(ref)
    if abs(value - r) <= 1e-9 * max(abs(r), 1):
        return True
    return abs(round_sf(value, sig_figs(ref)) - r) <= 1e-9 * max(abs(r), 1)


def apply(parsed: dict, question: dict, answer: dict, rules: list[str]) -> tuple[dict, list[str]]:
    """-> (new parsed marks, list of human-readable changes). Input is not mutated."""
    if not parsed or not rules:
        return parsed, []
    out, changes = {}, []
    points_by_label = {l["label"]: l for l in question["lines"]}
    for label, part in parsed.items():
        line = points_by_label[label]
        points, marks = line["points"], list(part["marks"])
        codes = [p.get("code", "").upper() for p in points]

        if "numeric" in rules:
            for i, code in enumerate(codes):
                ref = scheme_value(points[i]["text"]) if code == "A1" else None
                if marks[i] or not ref:
                    continue
                ref_unit = scheme_unit(points[i]["text"]) or line.get("answerLineUnit")
                ok, shown = value_matches(answer.get(label, ""), ref, ref_unit)
                if ok:
                    marks[i] = points[i]["marks"]
                    changes.append(f"{label}.{i + 1} A1 0->1 ({shown} ~ {ref})")

        text = answer.get(label, "")
        if "a1check" in rules:
            for i, code in enumerate(codes):
                ref = scheme_value(points[i]["text"]) if code == "A1" else None
                if marks[i] and ref:
                    ref_unit = scheme_unit(points[i]["text"]) or line.get("answerLineUnit")
                    if not any_value_matches(text, ref, ref_unit):
                        marks[i] = 0
                        changes.append(f"{label}.{i + 1} A1 1->0 (no value = {ref})")

        if "subst" in rules and not any(c == "A1" and marks[i] for i, c in enumerate(codes)):
            have = answer_numbers(text)
            for i, code in enumerate(codes):
                nums = substitution_numbers(points[i]["text"]) if code == "C1" else None
                if marks[i] and nums:
                    missing = [n for n in nums if not any(abs(n - h) <= 1e-9 * max(abs(n), 1) for h in have)]
                    if missing:
                        marks[i] = 0
                        changes.append(f"{label}.{i + 1} C1 1->0 (missing {', '.join(f'{m:g}' for m in missing)})")

        if "implied" in rules and any(c == "A1" and marks[i] for i, c in enumerate(codes)):
            for i, code in enumerate(codes):
                if code == "C1" and marks[i] == 0:
                    marks[i] = points[i]["marks"]
                    changes.append(f"{label}.{i + 1} C1 0->1 (implied by A1)")

        total = part["total"]
        if "sum" in rules:
            total = min(sum(marks), line["marks"])
        elif marks != part["marks"]:  # points changed: the total must follow
            total = min(max(total, sum(marks)), line["marks"])
        if total != part["total"]:
            changes.append(f"{label} total {part['total']}->{total}")
        out[label] = {"marks": marks, "total": total}
    return out, changes

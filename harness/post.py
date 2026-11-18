"""Deterministic post-processing of the parsed marks (Cambridge conventions).

Small models do not apply general marking rules reliably when told to in the
prompt (experiment log [10]), so the conventions that need no judgment live here.
The model only decides point by point; these rules fix the bookkeeping.

Rules (profile key `post`, comma-separated, applied in this order):
  numeric  A1 = 0 but the student's final number rounds to the A1 value -> A1 = 1
  implied  A1 awarded -> every C1 of that part awarded (C marks are implied)
  sum      part total = min(sum of points, part marks), ignoring the model's MARK line
"""

from __future__ import annotations

import re

RULES = ("numeric", "implied", "sum")

# A number not glued to a letter (so the 3 in "cm3" / "m3" is not a value).
_NUM = re.compile(r"(?<![A-Za-z\d.])(\d+(?:\.\d+)?)(?![\d])")


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
    nums = _NUM.findall(answer_text or "")
    return nums[-1] if nums else None


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
            final = final_number(answer.get(label, ""))
            for i, code in enumerate(codes):
                ref = scheme_value(points[i]["text"]) if code == "A1" else None
                if marks[i] == 0 and ref and final and matches(final, ref):
                    marks[i] = points[i]["marks"]
                    changes.append(f"{label}.{i + 1} A1 0->1 ({final} ~ {ref})")

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

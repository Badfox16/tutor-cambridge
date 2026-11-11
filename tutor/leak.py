"""Leak check: deterministic (no LLM) detection of mark scheme leakage.

A leaked feedback reveals the scheme before the student earned it. Checks:
1. a final numeric answer of the scheme appears in the feedback (hint level < 3);
2. a 6-word n-gram of the feedback matches scheme point text verbatim;
3. the feedback contains a "MARK SCHEME" header line (any level).

Percentages are reported with the check outcome so the leak rate is a
first-class dashboard metric.
"""

from __future__ import annotations

import re

WORD = re.compile(r"[a-zà-öø-ÿ0-9]+")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
NGRAM = 6


def _norm_number(s: str) -> str:
    return s.replace(",", ".").rstrip(".")


def final_answer_values(scheme: dict) -> list[str]:
    """Numbers that appear in the scheme's final-answer points (code A1 or type final_answer)."""
    values = []
    for line in scheme.get("lines", []):
        for point in line.get("points", []):
            if point.get("code") == "A1" or point.get("type") == "final_answer":
                values.extend(_norm_number(n) for n in NUMBER.findall(point.get("text", "")))
    return values


def _words(text: str) -> list[str]:
    return WORD.findall((text or "").lower())


def _ngrams(text: str, n: int = NGRAM) -> set[str]:
    words = _words(text)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def scheme_text(scheme: dict) -> str:
    return "\n".join(p.get("text", "") for line in scheme.get("lines", [])
                     for p in line.get("points", []))


def leak_check(feedback: str, scheme: dict, hint_level: int) -> tuple[bool, list[str]]:
    """Returns (leaked, reasons). Numeric and n-gram checks are skipped at
    hint level >= 3 (revealing the solution is the point there); the "MARK
    SCHEME" header check applies at every level."""
    reasons: list[str] = []
    text = feedback or ""
    if re.search(r"mark\s+scheme", text, re.IGNORECASE):
        reasons.append("mentions 'MARK SCHEME'")

    if hint_level < 3:
        for value in final_answer_values(scheme):
            tokens = {_norm_number(n) for n in NUMBER.findall(text)}
            if value and value in tokens:
                reasons.append(f"reveals final value {value}")

        scheme_grams = _ngrams(scheme_text(scheme))
        overlap = _ngrams(text) & scheme_grams
        if overlap:
            example = sorted(overlap)[0]
            reasons.append(f"scheme n-gram copied: '{example}'")

    return bool(reasons), reasons

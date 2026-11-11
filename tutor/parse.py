"""Marker reply parser (ported from marking-lab-server/lib/llm.ts::parseMarks).

Tolerant of markdown bold, bullets and `Point b.1:` prefixes; rejects when a
point line is missing or a mark exceeds the point's value; clamps a line total
to the line's marks. Parse failure is data, not an exception.
"""

from __future__ import annotations

import re

from .render import answered_lines, mark_key, point_key


def _esc(s: str) -> str:
    return re.escape(s)


def parse_marker_reply(raw: str, question: dict, answer_lines: dict) -> tuple[dict | None, str]:
    """Returns ({label: {marks, total}}, reason) or (None, failure_reason)."""
    lines = answered_lines(question, answer_lines)
    if not lines:
        return None, "no answered marked lines"

    out: dict[str, dict] = {}
    for line in lines:
        label = line["label"]
        marks: list[int] = []
        for i, point in enumerate(line.get("points", [])):
            key = point_key(label, i)
            # one value per point, at end of line; optional brackets `<1>`/`[1]`
            # are tolerated, but a template echo like `<0-1>` is not a value
            pattern = (
                rf"^[^\S\r\n]*(?:[-*]\s*)?(?:\*\*)?(?:point\s+)?{_esc(key)}(?:\*\*)?\s*[:\)]\s*"
                rf"(?:\*\*)?[<\[]?\s*(\d+)\s*[>\]]?\s*$"
            )
            m = re.search(pattern, raw, re.IGNORECASE | re.MULTILINE)
            if not m:
                return None, f"missing point {key}"
            value = int(m.group(1))
            if value > point["marks"]:
                return None, f"point {key} mark {value} exceeds {point['marks']}"
            marks.append(value)

        tkey = mark_key(label)
        t = re.search(rf"{_esc(tkey)}\s*:\s*(?:\*\*)?[<\[]?\s*(\d+)\s*[>\]]?\s*\/\s*\d+", raw, re.IGNORECASE)
        if not t:
            return None, f"missing total line '{tkey}:'"
        total = min(int(t.group(1)), line["marks"])
        out[label] = {"marks": marks, "total": total}

    reason_match = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)
    reason = reason_match.group(1).strip() if reason_match else ""
    return out, reason

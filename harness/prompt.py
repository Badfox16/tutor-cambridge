"""Prompt rendering + reply parsing for the marker.

Ported from marking-lab-server/lib/llm.ts so the layout matches the Lab:
points are keyed `b.1`, `b.2`... (`1`, `2` for a question without parts) and
each part total is `MARK b: <total> / <max>`.
"""

from __future__ import annotations

import re

from . import config


def point_key(label: str, i: int) -> str:
    return f"{i + 1}" if label == "main" else f"{label}.{i + 1}"


def mark_key(label: str) -> str:
    return "MARK" if label == "main" else f"MARK {label}"


def part_name(label: str) -> str:
    """`b` -> `(b)`, `a(i)` -> `(a)(i)`."""
    return "(" + label.replace("(", ")(") if "(" in label else f"({label})"


def answered_lines(question: dict, answer: dict) -> list[dict]:
    """Marked lines the student actually answered, in order."""
    return [l for l in question["lines"] if l.get("marked") and answer.get(l["label"])]


def layout(lines: list[dict]) -> str:
    rows = []
    for line in lines:
        rows += [f"{point_key(line['label'], i)}: <0-{p['marks']}>"
                 for i, p in enumerate(line["points"])]
        rows.append(f"{mark_key(line['label'])}: <total> / {line['marks']}")
    return "\n".join(rows)


def body(lines: list[dict], answer: dict, with_scheme: bool = True) -> str:
    blocks = []
    for line in lines:
        label = line["label"]
        head = (f"QUESTION ({line['marks']} marks)" if label == "main"
                else f"PART {part_name(label)} ({line['marks']} marks)")
        block = f"{head}:\n{line['text']}"
        if line.get("answerLineUnit"):
            block += f"\n(answer line unit: {line['answerLineUnit']})"
        if with_scheme:
            block += "\n\nMARK SCHEME:\n" + "\n".join(
                f"{point_key(label, i)} [{p.get('code', '')}] "
                f"({p['marks']} mark{'s' if p['marks'] > 1 else ''}) {p['text']}"
                for i, p in enumerate(line["points"]))
        block += f"\n\nSTUDENT ANSWER:\n{answer[label]}"
        blocks.append(block)
    return "\n\n---\n\n".join(blocks)


def load_template(variant: str) -> str:
    return (config.PROMPTS_DIR / f"{variant}.txt").read_text(encoding="utf-8")


def render(template: str, question: dict, answer: dict) -> str:
    lines = answered_lines(question, answer)
    return (template
            .replace("{{layout}}", layout(lines))
            .replace("{{question}}", f"QUESTION:\n{question['stem']}" if question.get("stem") else "")
            .replace("{{body}}", body(lines, answer)))


def parse(raw: str, question: dict, answer: dict) -> tuple[dict | None, str]:
    """-> ({label: {marks, total}}, reason) or (None, why it failed).

    Tolerates markdown bold, bullets, `Point b.1:` and `<1>`/`[1]`; ignores
    anything before `</think>`. Rejects a missing point, a mark above the
    point's value, or a template echo like `<0-1>`. Totals are clamped.
    """
    raw = raw.rsplit("</think>", 1)[-1]
    lines = answered_lines(question, answer)
    if not lines:
        return None, "no answered marked lines"
    out = {}
    for line in lines:
        label, marks = line["label"], []
        for i, point in enumerate(line["points"]):
            key = re.escape(point_key(label, i))
            m = re.search(rf"^[^\S\r\n]*(?:[-*]\s*)?(?:\*\*)?(?:point\s+)?{key}(?:\*\*)?\s*[:\)]\s*"
                          rf"(?:\*\*)?[<\[]?\s*(\d+)\s*[>\]]?\s*(?:\*\*)?\s*$",
                          raw, re.IGNORECASE | re.MULTILINE)
            if not m:
                return None, f"missing point {point_key(label, i)}"
            value = int(m.group(1))
            if value > point["marks"]:
                return None, f"point {point_key(label, i)} mark {value} exceeds {point['marks']}"
            marks.append(value)
        t = re.search(rf"{re.escape(mark_key(label))}\s*:\s*(?:\*\*)?[<\[]?\s*(\d+)\s*[>\]]?\s*(?:\*\*)?\s*/\s*\d+",
                      raw, re.IGNORECASE)
        if not t:
            return None, f"missing total line '{mark_key(label)}:'"
        out[label] = {"marks": marks, "total": min(int(t.group(1)), line["marks"])}
    reason = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)
    return out, reason.group(1).strip() if reason else ""

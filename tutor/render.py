"""Prompt rendering for the marker (ported from marking-lab-server/lib/llm.ts).

Layout conventions (shared with the Lab's /prompt page, so scores stay
comparable): marking points are keyed `b.1`, `b.2`... (or `1`, `2` for a
question without parts) and each line total is `MARK b: <total> / <max>`.
"""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def point_key(label: str, index: int) -> str:
    return f"{index + 1}" if label == "main" else f"{label}.{index + 1}"


def mark_key(label: str) -> str:
    return "MARK" if label == "main" else f"MARK {label}"


def part_name(label: str) -> str:
    """`b` -> `(b)`, `a(i)` -> `(a)(i)` (as in scripts/llm-run.mjs)."""
    if "(" in label:
        return "(" + label.replace("(", ")(")
    return f"({label})"


def answered_lines(question: dict, answer_lines: dict) -> list[dict]:
    """Marked question lines that the student actually answered, in order."""
    out = []
    for line in question.get("lines", []):
        if line.get("marked") and answer_lines.get(line["label"]):
            out.append(line)
    return out


def merge_scheme(question: dict, scheme: dict) -> dict:
    """Public question + scheme: attach each marked line's points (in order)."""
    points_by_label = {line["label"]: line["points"] for line in scheme.get("lines", [])}
    merged = {**question, "lines": []}
    for line in question.get("lines", []):
        if line.get("marked"):
            merged["lines"].append({**line, "points": points_by_label.get(line["label"], [])})
        else:
            merged["lines"].append(line)
    return merged


def build_layout(lines: list[dict]) -> str:
    """The exact reply layout the model must follow."""
    parts = []
    for line in lines:
        rows = [f"{point_key(line['label'], i)}: <0-{p['marks']}>"
                for i, p in enumerate(line.get("points", []))]
        rows.append(f"{mark_key(line['label'])}: <total> / {line['marks']}")
        parts.append("\n".join(rows))
    return "\n".join(parts)


def build_body(lines: list[dict], answer_lines: dict, with_scheme: bool) -> str:
    blocks = []
    for line in lines:
        label = line["label"]
        head = (f"QUESTION ({line['marks']} marks)" if label == "main"
                else f"PART {part_name(label)} ({line['marks']} marks)")
        unit = f"\n(answer line unit: {line['answerLineUnit']})" if line.get("answerLineUnit") else ""
        block = f"{head}:\n{line['text']}{unit}"
        if with_scheme:
            scheme = "\n".join(
                f"{point_key(label, i)} [{p.get('code', '')}] ({p['marks']} mark{'s' if p['marks'] > 1 else ''}) {p['text']}"
                for i, p in enumerate(line.get("points", [])))
            block += f"\n\nMARK SCHEME:\n{scheme}"
        block += f"\n\nSTUDENT ANSWER:\n{answer_lines[label]}"
        blocks.append(block)
    return "\n\n---\n\n".join(blocks)


def render_marker_prompt(question: dict, answer_lines: dict, *,
                         with_scheme: bool, variant: str = "marker-full") -> tuple[str, list[dict]]:
    """Full prompt for one answer. Returns (prompt, answered_lines)."""
    lines = answered_lines(question, answer_lines)
    template = (PROMPTS_DIR / f"{variant}.txt").read_text(encoding="utf-8")
    substitutions = {
        "{{layout}}": build_layout(lines),
        "{{question}}": f"QUESTION:\n{question['stem']}" if question.get("stem") else "",
        "{{body}}": build_body(lines, answer_lines, with_scheme),
    }
    prompt = template
    for key, value in substitutions.items():
        prompt = prompt.replace(key, value)
    return prompt, lines

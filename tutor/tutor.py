"""Tutor pipeline: sessions, hint ladder, internal marking, feedback with
leak check, reveal and rating. Feedback streams to the student; the scheme
never leaves the backend.

Ladder (configurable idea; see AGENTS guide §7.2):
  attempt 1 -> level 0  one guiding question
  attempt 2 -> level 1  point at the idea/formula, no values
  attempt 3 -> level 2  step-by-step, last step left to the student
  attempt 4 / reveal -> level 3  full solution + typical error
A session's hint_bump ("give another hint") adds to the level, capped at 3.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import db, leak, trace
from .lab import LabClient
from .render import merge_scheme, render_marker_prompt
from .parse import parse_marker_reply

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MAX_HINT_LEVEL = 3

FALLBACK = {
    0: "Boa tentativa! Antes de calcular: releia o enunciado e me diga qual grandeza a questão pede e quais dados você tem, com unidades.",
    1: "Pense na física da situação: qual relação (fórmula) liga os dados do enunciado à grandeza pedida? Escreva-a em símbolos primeiro, sem números.",
    2: "Vamos por etapas: 1) liste os dados com unidades; 2) escreva a fórmula em símbolos; 3) isole a grandeza pedida. Deixe a substituição dos números para você — me diga o resultado que obteve.",
    3: "Solução: use a relação correta entre as grandezas do enunciado, substitua os valores com unidades consistentes e arredonde como a questão pede. O erro típico aqui é inverter a razão entre as grandezas — confira se as unidades batem no final.",
}


class TutorError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- sessions

def create_session(conn, question_id: str, student_label: str = "") -> dict:
    session_id = db.insert(conn, "sessions", {
        "student_label": student_label, "question_id": question_id,
        "started_at": db.now(), "hint_bump": 0,
    })
    return get_session(conn, session_id)


def get_session(conn, session_id: int) -> dict:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise TutorError(f"session {session_id} does not exist", 404)
    session = dict(row)
    session["turns"] = [dict(t) for t in conn.execute(
        "SELECT id, attempt, student_answer, marks_json, feedback, hint_level, "
        "leak_flag, regenerated, rating, created_at FROM turns "
        "WHERE session_id = ? ORDER BY id", (session_id,))]
    for t in session["turns"]:
        marks_raw = t.pop("marks_json")
        t["marks"] = json.loads(marks_raw) if marks_raw else None
    return session


def bump_hint(conn, session_id: int) -> int:
    session = get_session(conn, session_id)
    level = min(MAX_HINT_LEVEL, session["hint_bump"] + 1)
    db.update(conn, "sessions", session_id, {"hint_bump": level})
    return level


def rate_turn(conn, turn_id: int, rating: int) -> None:
    if rating not in (-1, 0, 1):
        raise TutorError("rating must be -1, 0 or 1")
    if not conn.execute("SELECT id FROM turns WHERE id = ?", (turn_id,)).fetchone():
        raise TutorError(f"turn {turn_id} does not exist", 404)
    db.update(conn, "turns", turn_id, {"rating": rating})


# --------------------------------------------------------------- questions

def safe_question(q: dict) -> dict:
    """The student-facing shape: no scheme, no points, ever."""
    return {
        "id": q["id"], "topic": q.get("topic"), "syllabusRef": q.get("syllabusRef"),
        "tier": q.get("tier"), "ao": q.get("ao"),
        "totalMarks": q.get("totalMarks"), "markedMarks": q.get("markedMarks"),
        "stem": q.get("stem"),
        "lines": [{"label": l["label"], "text": l["text"], "marks": l.get("marks"),
                   "answerLineUnit": l.get("answerLineUnit"), "marked": l.get("marked")}
                  for l in q.get("lines", [])],
    }


def fetch_question(conn, lab: LabClient, question_id: str) -> tuple[dict, dict]:
    """Safe question + scheme (backend-only). Served from the local cache when
    available so the tutor keeps working offline once a question was seen."""
    row = conn.execute("SELECT * FROM question_cache WHERE question_id = ?",
                       (question_id,)).fetchone()
    if row:
        return json.loads(row["payload_json"]), json.loads(row["scheme_json"])
    q = lab.question(question_id)
    scheme = lab.scheme(question_id)
    db.insert(conn, "question_cache", {
        "question_id": question_id, "dataset_version": None,
        "payload_json": db.dumps(safe_question(q)), "scheme_json": db.dumps(scheme),
        "fetched_at": db.now(),
    })
    return safe_question(q), scheme


def list_questions(conn, lab: LabClient) -> list[dict]:
    try:
        out = lab.questions(pageSize=100)
    except Exception as e:  # offline: fall back to the cache
        rows = [dict(r) for r in conn.execute(
            "SELECT payload_json FROM question_cache ORDER BY question_id")]
        if not rows:
            raise TutorError(f"Marking Lab unavailable and no cached questions: {e}", 503)
        return [json.loads(r["payload_json"]) for r in rows]
    return [safe_question(q) for q in out.get("questions", [])]


# ------------------------------------------------------------------ turns

def hint_level_for(attempt: int, hint_bump: int = 0) -> int:
    return min(MAX_HINT_LEVEL, max(0, attempt - 1) + hint_bump)


def _marks_summary(parsed: dict | None, question: dict, answer_lines: dict) -> tuple[str, bool]:
    if parsed is None:
        return "não foi possível corrigir automaticamente", False
    parts, correct = [], True
    for line in question.get("lines", []):
        label = line["label"]
        if not line.get("marked") or label not in parsed:
            continue
        total = parsed[label]["total"]
        parts.append(f"{label} {total}/{line['marks']}")
        correct = correct and total == line["marks"]
    return " · ".join(parts), correct and bool(parts)


def _render_tutor_prompt(question: dict, answer_lines: dict, marks_summary: str,
                         hint_level: int, strict: bool = False) -> str:
    template = (PROMPTS_DIR / "tutor.txt").read_text(encoding="utf-8")
    answered = [l for l in question.get("lines", []) if l.get("marked") and answer_lines.get(l["label"])]
    scheme_block = []
    for line in answered:
        rows = [f"{i + 1}. [{p.get('code', '')}] ({p['marks']} mark{'s' if p['marks'] > 1 else ''}) {p['text']}"
                for i, p in enumerate(line.get("points", []))]
        scheme_block.append(f"PART {line['label']} ({line['marks']} marks):\n" + "\n".join(rows))
    student_block = "\n".join(f"({l['label']}) {answer_lines[l['label']]}" for l in answered)
    substitutions = {
        "{{hint_level}}": str(hint_level),
        "{{strict}}": ("\nATENÇÃO: seu texto anterior vazou trechos do mark scheme. "
                       "Reescreva de forma mais geral: nenhum valor final, nenhuma frase do scheme.") if strict else "",
        "{{question}}": question.get("stem") or "",
        "{{marking_scheme}}": "\n\n".join(scheme_block),
        "{{student_answer}}": student_block or "(sem resposta)",
        "{{marks_summary}}": marks_summary or "—",
    }
    prompt = template
    for key, value in substitutions.items():
        prompt = prompt.replace(key, value)
    return prompt


def _generate_feedback(trace_rec, provider, prompt: str, *, think: bool,
                       on_event, stage: str = "tutor.feedback") -> tuple[str, object]:
    with trace_rec.span(stage) as span:
        llm = provider.chat([{"role": "user", "content": prompt}], think=think,
                            on_chunk=lambda piece: on_event({"type": "delta", "text": piece}))
        span.tokens_in = llm.prompt_tokens
        span.tokens_out = llm.gen_tokens
        span.meta.update(llm.as_dict())
    return llm.text, llm


def _mark_with_spans(trace_rec, provider, question: dict, answer_lines: dict, *,
                     think: bool, prompt_variant: str):
    with trace_rec.span("render") as span:
        prompt, _ = render_marker_prompt(question, answer_lines, with_scheme=True,
                                         variant=prompt_variant)
        span.meta["chars"] = len(prompt)
    with trace_rec.span("model.generate") as span:
        llm = provider.chat([{"role": "user", "content": prompt}], think=think)
        span.tokens_in = llm.prompt_tokens
        span.tokens_out = llm.gen_tokens
        span.meta.update(llm.as_dict())
    with trace_rec.span("parse") as span:
        parsed, reason = parse_marker_reply(llm.text, question, answer_lines)
        span.meta["reason"] = reason
    return parsed, reason


def answer_turn(conn, lab: LabClient, provider, session_id: int,
                answer_lines: dict, *, think: bool = False,
                marking_prompt: str = "marker-compact",
                on_event=lambda event: None) -> dict:
    """One student attempt: internal marking -> feedback -> leak check.
    Streams events: {status}, {delta}, {done} / {error}."""
    session = get_session(conn, session_id)
    if not isinstance(answer_lines, dict) or not answer_lines:
        raise TutorError("send at least one answered line, e.g. {\"b\": \"...\"}")
    question_payload, scheme = fetch_question(conn, lab, session["question_id"])
    for label in answer_lines:
        line = next((l for l in question_payload.get("lines", []) if l["label"] == label), None)
        if line is None or not line.get("marked"):
            raise TutorError(f"line '{label}' is not a marked line of {question_payload['id']}")

    question = merge_scheme(question_payload, scheme)
    attempt = len(session["turns"]) + 1
    hint_level = hint_level_for(attempt, session["hint_bump"])

    tr = trace.start_trace(conn, run_id=None, kind="tutor_turn", session_id=session_id,
                           question_id=question_payload["id"], attempt=attempt,
                           hint_level=hint_level)
    on_event({"type": "status", "stage": "marking", "attempt": attempt,
              "hint_level": hint_level})
    parsed, mark_reason = _mark_with_spans(tr, provider, question, answer_lines,
                                           think=think, prompt_variant=marking_prompt)
    marks_summary, correct = _marks_summary(parsed, question_payload, answer_lines)

    on_event({"type": "status", "stage": "feedback"})
    prompt = _render_tutor_prompt(question_payload, answer_lines, marks_summary, hint_level)
    feedback, _ = _generate_feedback(tr, provider, prompt, think=think, on_event=on_event)

    regenerated = leak_flag = 0
    with tr.span("tutor.leak_check") as span:
        leaked, reasons = leak.leak_check(feedback, scheme, hint_level)
        if leaked:
            leak_flag = 1
            regenerated = 1
            span.meta["regenerated"] = True
            on_event({"type": "status", "stage": "regenerating"})
            strict_prompt = _render_tutor_prompt(question_payload, answer_lines,
                                                 marks_summary, hint_level, strict=True)
            feedback, _ = _generate_feedback(tr, provider, strict_prompt, think=think,
                                             on_event=on_event)
            leaked, reasons = leak.leak_check(feedback, scheme, hint_level)
            if leaked:  # still leaking: deliver the pre-written guiding question
                feedback = FALLBACK[min(hint_level, MAX_HINT_LEVEL)]
                span.meta["fallback"] = True
        span.meta["reasons"] = reasons
        span.ok = not leaked

    turn_id = db.insert(conn, "turns", {
        "session_id": session_id, "attempt": attempt,
        "student_answer": db.dumps(answer_lines),
        "marks_json": db.dumps({"marks_summary": marks_summary, "correct": correct,
                                "parsed": parsed, "mark_reason": mark_reason}),
        "feedback": feedback, "hint_level": hint_level,
        "leak_flag": leak_flag, "regenerated": regenerated,
        "rating": None, "created_at": db.now(),
    })
    tr.finish(ok=True, parse_failed=parsed is None,
              prompt=prompt, raw_output=feedback,
              parsed_json={"marks": parsed}, reason=mark_reason,
              hint_level=hint_level, attempt=attempt)

    result = {"turn_id": turn_id, "attempt": attempt, "hint_level": hint_level,
              "marks_summary": marks_summary, "correct": correct,
              "leak_flag": leak_flag, "regenerated": regenerated}
    on_event({"type": "done", **result})
    return result


def reveal(conn, lab: LabClient, provider, session_id: int, *,
           think: bool = False, on_event=lambda event: None) -> dict:
    """'Mostrar solução': level 3 with the full solution + typical error."""
    session = get_session(conn, session_id)
    question_payload, scheme = fetch_question(conn, lab, session["question_id"])
    question = merge_scheme(question_payload, scheme)
    attempt = len(session["turns"]) + 1

    tr = trace.start_trace(conn, run_id=None, kind="tutor_turn", session_id=session_id,
                           question_id=question_payload["id"], attempt=attempt,
                           hint_level=MAX_HINT_LEVEL)
    on_event({"type": "status", "stage": "marking", "attempt": attempt,
              "hint_level": MAX_HINT_LEVEL})
    # reuse the last marks when the student already tried; otherwise mark nothing
    marks_summary = ""
    if session["turns"]:
        last = session["turns"][-1]["marks"]
        if last:
            marks_summary = last["marks_summary"]

    answer_lines = {}
    if session["turns"]:
        try:
            answer_lines = json.loads(session["turns"][-1]["student_answer"])
        except Exception:
            answer_lines = {}
    prompt = _render_tutor_prompt(question_payload, answer_lines or {},
                                  marks_summary, MAX_HINT_LEVEL)
    on_event({"type": "status", "stage": "feedback"})
    feedback, _ = _generate_feedback(tr, provider, prompt, think=think, on_event=on_event)

    with tr.span("tutor.leak_check") as span:
        leaked, reasons = leak.leak_check(feedback, scheme, MAX_HINT_LEVEL)
        if leaked:
            feedback = FALLBACK[MAX_HINT_LEVEL]
        span.meta["reasons"] = reasons
        span.ok = not leaked

    turn_id = db.insert(conn, "turns", {
        "session_id": session_id, "attempt": attempt,
        "student_answer": db.dumps(answer_lines or {}),
        "marks_json": None, "feedback": feedback, "hint_level": MAX_HINT_LEVEL,
        "leak_flag": 0, "regenerated": 0, "rating": None, "created_at": db.now(),
    })
    tr.finish(ok=True, prompt=prompt, raw_output=feedback,
              parsed_json=None, reason="reveal", hint_level=MAX_HINT_LEVEL,
              attempt=attempt)
    result = {"turn_id": turn_id, "attempt": attempt, "hint_level": MAX_HINT_LEVEL,
              "marks_summary": marks_summary, "correct": None,
              "leak_flag": 0, "regenerated": 0}
    on_event({"type": "done", **result})
    return result

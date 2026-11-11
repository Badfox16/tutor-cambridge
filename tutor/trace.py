"""Traces and spans: every operation is a trace; every stage is a span.

Stage names are fixed (the dashboard depends on them):
lab.fetch, render, model.load, model.prefill, model.generate, parse,
lab.submit, lab.score, tutor.feedback, tutor.leak_check, judge.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time

from . import db


class SpanRecord:
    def __init__(self, stage: str):
        self.stage = stage
        self.started_at = db.now()
        self.t0 = time.perf_counter()
        self.ok = True
        self.error: str | None = None
        self.tokens_in = 0
        self.tokens_out = 0
        self.meta: dict = {}

    def finalize(self) -> dict:
        return {
            "stage": self.stage,
            "started_at": self.started_at,
            "duration_ms": round((time.perf_counter() - self.t0) * 1000.0, 1),
            "ok": 1 if self.ok else 0,
            "error": self.error,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "meta_json": db.dumps(self.meta),
        }


class Trace:
    """One interaction (a mark, a tutor turn, an eval case) with its spans."""

    def __init__(self, conn: sqlite3.Connection, trace_id: int):
        self.conn = conn
        self.id = trace_id
        self.meta: dict = {}  # extra trace columns filled by finish()

    @contextlib.contextmanager
    def span(self, stage: str):
        rec = SpanRecord(stage)
        try:
            yield rec
        except Exception as e:  # never hide errors: record and re-raise
            rec.ok = False
            rec.error = f"{type(e).__name__}: {e}"
            self.write_span(rec)
            raise
        else:
            self.write_span(rec)

    def write_span(self, rec: SpanRecord) -> None:
        db.insert(self.conn, "spans", {"trace_id": self.id, **rec.finalize()})

    def finish(self, ok: bool, *, parse_failed: bool = False, cut_off: bool = False,
               rescued: bool = False, agree: bool | None = None,
               prompt: str = "", raw_output: str = "", parsed_json: dict | None = None,
               reason: str = "", **columns) -> None:
        values: dict = {
            "total_ms": round((time.perf_counter() - self._t0) * 1000.0, 1) if hasattr(self, "_t0") else None,
            "ok": 1 if ok else 0,
            "parse_failed": 1 if parse_failed else 0,
            "cut_off": 1 if cut_off else 0,
            "rescued": 1 if rescued else 0,
            "prompt": prompt,
            "raw_output": raw_output,
            "parsed_json": db.dumps(parsed_json) if parsed_json is not None else None,
            "reason": reason,
        }
        if agree is not None:
            values["agree"] = 1 if agree else 0
        values.update(columns)
        db.update(self.conn, "traces", self.id, values)


def start_trace(conn: sqlite3.Connection, *, run_id: int | None, kind: str,
                model: str = "", question_id: str = "", answer_id: str = "",
                session_id: int | None = None, attempt: int = 1,
                hint_level: int = 0) -> Trace:
    trace_id = db.insert(conn, "traces", {
        "run_id": run_id,
        "kind": kind,
        "session_id": session_id,
        "question_id": question_id,
        "answer_id": answer_id,
        "model": model,
        "started_at": db.now(),
        "attempt": attempt,
        "hint_level": hint_level,
    })
    trace = Trace(conn, trace_id)
    trace._t0 = time.perf_counter()
    return trace


def spans_for(conn: sqlite3.Connection, trace_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM spans WHERE trace_id = ? ORDER BY id", (trace_id,)).fetchall()

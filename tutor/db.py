"""SQLite storage: schema, tiny migrations, helpers."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,              -- marker | tutor_eval
    model TEXT NOT NULL,
    prompt_variant TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    split TEXT NOT NULL DEFAULT 'open',
    git_commit TEXT NOT NULL DEFAULT '',
    dirty INTEGER NOT NULL DEFAULT 0,
    lab_run_id INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',  -- running | done | error | stopped
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    kind TEXT NOT NULL,              -- mark | tutor_turn | eval_case
    session_id INTEGER,
    question_id TEXT NOT NULL DEFAULT '',
    answer_id TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    total_ms REAL,
    ok INTEGER NOT NULL DEFAULT 0,
    parse_failed INTEGER NOT NULL DEFAULT 0,
    cut_off INTEGER NOT NULL DEFAULT 0,
    rescued INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 1,
    hint_level INTEGER NOT NULL DEFAULT 0,
    agree INTEGER,                   -- NULL unknown; 1 agree, 0 disagree (marker)
    prompt TEXT NOT NULL DEFAULT '',
    raw_output TEXT NOT NULL DEFAULT '',
    parsed_json TEXT,
    reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY,
    trace_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    duration_ms REAL,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS scores (
    run_id INTEGER PRIMARY KEY,
    accuracy_json TEXT NOT NULL,
    disagreements_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    student_label TEXT NOT NULL DEFAULT '',
    question_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    student_answer TEXT NOT NULL,
    marks_json TEXT,
    feedback TEXT NOT NULL DEFAULT '',
    hint_level INTEGER NOT NULL DEFAULT 0,
    leak_flag INTEGER NOT NULL DEFAULT 0,
    regenerated INTEGER NOT NULL DEFAULT 0,
    rating INTEGER,                  -- -1, 0, 1
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY,
    run_id INTEGER,
    case_id TEXT NOT NULL,
    model TEXT NOT NULL,
    checks_json TEXT NOT NULL DEFAULT '{}',
    judge_score REAL,
    judge_notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_stage ON spans(stage);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
"""


def connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the HTTP server answers requests from worker
    # threads; WAL + short transactions keep this safe for our read-mostly use.
    conn = sqlite3.connect(path, timeout=30, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def insert(conn: sqlite3.Connection, table: str, values: dict) -> int:
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
    conn.commit()
    return cur.lastrowid


def update(conn: sqlite3.Connection, table: str, row_id: int, values: dict) -> None:
    sets = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*values.values(), row_id))
    conn.commit()

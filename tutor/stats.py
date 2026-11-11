"""Aggregations for the dashboard. All queries run on the local SQLite db.

Numbers keep their units; percentages carry the sample size (n) because small
samples are noisy (see AGENTS guide §12).
"""

from __future__ import annotations

import json
import sqlite3

from . import db


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def overview(conn: sqlite3.Connection) -> dict:
    counts = {
        "runs": conn.execute("SELECT COUNT(*) c FROM runs").fetchone()["c"],
        "traces": conn.execute("SELECT COUNT(*) c FROM traces").fetchone()["c"],
        "answer_traces": conn.execute(
            "SELECT COUNT(*) c FROM traces WHERE answer_id != ''").fetchone()["c"],
        "sessions": conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"],
        "turns": conn.execute("SELECT COUNT(*) c FROM turns").fetchone()["c"],
    }
    marked = conn.execute(
        "SELECT COUNT(*) c, SUM(ok) ok FROM traces WHERE answer_id != ''").fetchone()
    success = round(marked["ok"] / marked["c"], 4) if marked["c"] and marked["ok"] is not None else None
    runs = [dict(r) for r in conn.execute(
        "SELECT id, kind, model, prompt_variant, status, started_at, finished_at, lab_run_id, notes "
        "FROM runs ORDER BY id DESC LIMIT 15")]
    return {"counts": counts, "success_rate": success, "recent_runs": runs}


def stages(conn: sqlite3.Connection, run_id: int | None = None, model: str | None = None) -> dict:
    rows = conn.execute(
        """SELECT s.stage, s.duration_ms d, s.ok
           FROM spans s
           JOIN traces t ON s.trace_id = t.id
           LEFT JOIN runs r ON t.run_id = r.id
           WHERE (? IS NULL OR t.run_id = ?) AND (? IS NULL OR r.model = ?)
             AND s.duration_ms IS NOT NULL""",
        (run_id, run_id, model, model)).fetchall()
    by_stage: dict[str, dict] = {}
    for r in rows:
        st = by_stage.setdefault(r["stage"], {"durations": [], "failures": 0, "n": 0})
        st["n"] += 1
        if r["d"] is not None:
            st["durations"].append(r["d"])
        if not r["ok"]:
            st["failures"] += 1
    out = {}
    for stage, st in sorted(by_stage.items()):
        out[stage] = {
            "n": st["n"],
            "mean_ms": round(_mean(st["durations"]) or 0, 1),
            "p50_ms": round(_pct(st["durations"], 0.5) or 0, 1),
            "p95_ms": round(_pct(st["durations"], 0.95) or 0, 1),
            "fail_pct": round(st["failures"] / st["n"], 4) if st["n"] else 0.0,
        }
    return out


def model_perf(conn: sqlite3.Connection, model: str | None = None,
               run_id: int | None = None) -> dict:
    rows = conn.execute(
        """SELECT s.meta_json m, t.total_ms, t.parse_failed, t.cut_off
           FROM spans s
           JOIN traces t ON s.trace_id = t.id
           LEFT JOIN runs r ON t.run_id = r.id
           WHERE s.stage = 'model.generate'
             AND (? IS NULL OR t.run_id = ?) AND (? IS NULL OR r.model = ?)""",
        (run_id, run_id, model, model)).fetchall()
    tps, ttft, load, t_in, t_out, think, totals = [], [], [], [], [], [], []
    cold = warm = 0
    for r in rows:
        m = json.loads(r["m"] or "{}")
        if m.get("tokens_per_s"):
            tps.append(m["tokens_per_s"])
        if m.get("ttft_ms") is not None:
            ttft.append(m["ttft_ms"])
        load_ms = m.get("load_ms") or 0
        load.append(load_ms)
        if load_ms > 1000:
            cold += 1
        else:
            warm += 1
        t_in.append(m.get("prompt_tokens") or 0)
        t_out.append(m.get("gen_tokens") or 0)
        think.append(m.get("thinking_chars") or 0)
        if r["total_ms"] is not None:
            totals.append(r["total_ms"])
    buckets = [("0–5 s", 5000), ("5–10 s", 10000), ("10–20 s", 20000),
               ("20–40 s", 40000), ("40 s +", None)]
    hist = []
    for label, upper in buckets:
        count = sum(1 for t in totals if t <= (upper if upper else float("inf"))) - sum(h["n"] for h in hist)
        hist.append({"bucket": label, "n": max(0, count)})
    return {
        "n": len(rows),
        "tokens_per_s": {"mean": _round(_mean(tps)), "p50": _round(_pct(tps, 0.5)), "p95": _round(_pct(tps, 0.95))},
        "ttft_ms": {"mean": _round(_mean(ttft)), "p50": _round(_pct(ttft, 0.5)), "p95": _round(_pct(ttft, 0.95))},
        "load_ms": {"mean": _round(_mean(load)), "p50": _round(_pct(load, 0.5)), "p95": _round(_pct(load, 0.95))},
        "load_cold_warm": {"cold": cold, "warm": warm},
        "prompt_tokens": {"mean": _round(_mean(t_in), 0)},
        "gen_tokens": {"mean": _round(_mean(t_out), 0)},
        "thinking_chars": {"mean": _round(_mean(think), 0)},
        "latency_histogram": hist,
    }


def _round(v, nd=1):
    return None if v is None else round(v, nd)


def marker(conn: sqlite3.Connection, run_id: int | None = None) -> dict:
    """Score from the Lab + per-trace agreement, for one run (or the latest)."""
    row = (conn.execute("SELECT * FROM scores WHERE run_id = ?", (run_id,)).fetchone()
           if run_id else conn.execute("SELECT * FROM scores ORDER BY run_id DESC LIMIT 1").fetchone())
    if not row:
        return {"score": None, "note": "nenhuma run fechada ainda"}
    accuracy = json.loads(row["accuracy_json"])
    disagreements = json.loads(row["disagreements_json"])
    local_run = row["run_id"]
    traces = {t["answer_id"]: t for t in conn.execute(
        "SELECT id, answer_id, attempt, ok, parse_failed, reason FROM traces WHERE run_id = ? AND answer_id != ''",
        (local_run,)).fetchall()}
    for d in disagreements:
        t = traces.get(d.get("answerId"))
        d["trace_id"] = t["id"] if t else None
    agree_counts = conn.execute(
        """SELECT SUM(agree = 1) yes, SUM(agree = 0) no, COUNT(*) n
           FROM traces WHERE run_id = ? AND answer_id != '' AND agree IS NOT NULL""",
        (local_run,)).fetchone()
    return {
        "run_id": local_run,
        "score": accuracy,
        "disagreements": disagreements,
        "agreement": {"agree": agree_counts["yes"] or 0, "disagree": agree_counts["no"] or 0,
                      "n": agree_counts["n"]},
    }


def reliability(conn: sqlite3.Connection, run_id: int | None = None,
                model: str | None = None) -> dict:
    where, params = [], []
    if run_id:
        where.append("t.run_id = ?")
        params.append(run_id)
    if model:
        where.append("r.model = ?")
        params.append(model)
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM traces t LEFT JOIN runs r ON t.run_id = r.id {cond}"
    answer_cond = (" AND t.answer_id != ''" if where else "WHERE t.answer_id != ''")
    fails = [dict(r) for r in conn.execute(
        f"""SELECT t.reason reason, COUNT(*) n {base}{answer_cond} AND t.parse_failed = 1
            GROUP BY t.reason ORDER BY n DESC""", params)]
    cut = conn.execute(
        f"SELECT COUNT(*) c {base}{answer_cond} AND t.cut_off = 1", params).fetchone()["c"]
    span_fails = [dict(r) for r in conn.execute(
        f"""SELECT s.stage stage, COUNT(*) n
            FROM spans s
            JOIN traces t ON s.trace_id = t.id
            LEFT JOIN runs r ON t.run_id = r.id
            {('WHERE ' + ' AND '.join(where) + ' AND') if where else 'WHERE'} s.ok = 0
            GROUP BY s.stage ORDER BY n DESC""", params)]
    parse_ok = conn.execute(
        f"SELECT COUNT(*) c {base}{answer_cond} AND t.parse_failed = 0", params).fetchone()["c"]
    parse_fail_n = sum(f["n"] for f in fails)
    return {
        "parse": {"ok": parse_ok, "failed": parse_fail_n,
                  "rate": round(parse_fail_n / (parse_ok + parse_fail_n), 4) if (parse_ok + parse_fail_n) else None,
                  "reasons": fails},
        "cut_off": cut,
        "span_failures": span_fails,
    }


def traces_list(conn: sqlite3.Connection, *, run_id: int | None = None, ok: int | None = None,
                agree: int | None = None, stage: str | None = None, model: str | None = None,
                limit: int = 50, offset: int = 0) -> dict:
    where, params = ["t.answer_id != ''"], []
    if run_id:
        where.append("t.run_id = ?")
        params.append(run_id)
    if ok is not None:
        where.append("t.ok = ?")
        params.append(ok)
    if agree is not None:
        where.append("t.agree = ?")
        params.append(agree)
    if model:
        where.append("r.model = ?")
        params.append(model)
    if stage:
        where.append("EXISTS (SELECT 1 FROM spans s WHERE s.trace_id = t.id AND s.stage = ?)")
        params.append(stage)
    cond = "WHERE " + " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) c FROM traces t LEFT JOIN runs r ON t.run_id = r.id {cond}",
                         params).fetchone()["c"]
    rows = [dict(r) for r in conn.execute(
        f"""SELECT t.id, t.run_id, t.question_id, t.answer_id, t.model, t.attempt,
                   t.ok, t.parse_failed, t.cut_off, t.agree, t.total_ms, t.reason
            FROM traces t LEFT JOIN runs r ON t.run_id = r.id
            {cond} ORDER BY t.id DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset))]
    for r in rows:
        r["reason"] = (r["reason"] or "")[:120]
    return {"total": total, "limit": limit, "offset": offset, "traces": rows}


def trace_detail(conn: sqlite3.Connection, trace_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM traces WHERE id = ?", (trace_id,)).fetchone()
    if not row:
        return None
    spans = [dict(s) for s in conn.execute(
        "SELECT id, stage, started_at, duration_ms, ok, error, tokens_in, tokens_out, meta_json "
        "FROM spans WHERE trace_id = ? ORDER BY id", (trace_id,))]
    for s in spans:
        s["meta"] = json.loads(s.pop("meta_json") or "{}")
    d = dict(row)
    d["parsed"] = json.loads(row["parsed_json"]) if row["parsed_json"] else None
    return {**d, "spans": spans}


def export(conn: sqlite3.Connection, run_id: int, fmt: str) -> tuple[str, str, str]:
    """Returns (content, content_type, filename)."""
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, question_id, answer_id, attempt, ok, parse_failed, cut_off, agree, "
        "total_ms, reason, raw_output FROM traces WHERE run_id = ? AND answer_id != '' ORDER BY id",
        (run_id,))]
    if fmt == "json":
        payload = {"run": dict(run) if run else None, "traces": rows}
        return (json.dumps(payload, ensure_ascii=False, indent=2),
                "application/json", f"run-{run_id}.json")
    header = ["id", "question_id", "answer_id", "attempt", "ok", "parse_failed",
              "cut_off", "agree", "total_ms", "reason"]
    import csv as _csv
    import io
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(header)
    for r in rows:
        writer.writerow([r.get(h) if h != "reason" else (r.get("reason") or "").replace("\n", " ")
                         for h in header])
    return buf.getvalue(), "text/csv", f"run-{run_id}.csv"


def compare(conn: sqlite3.Connection, run_ids: list[int]) -> list[dict]:
    out = []
    for rid in run_ids:
        run = conn.execute("SELECT id, model, prompt_variant, status, started_at FROM runs WHERE id = ?",
                           (rid,)).fetchone()
        score = conn.execute("SELECT accuracy_json FROM scores WHERE run_id = ?", (rid,)).fetchone()
        if not run:
            continue
        accuracy = json.loads(score["accuracy_json"]) if score else None
        out.append({"run_id": rid, "model": run["model"], "prompt_variant": run["prompt_variant"],
                    "status": run["status"], "accuracy": (accuracy or {}).get("overall")})
    return out

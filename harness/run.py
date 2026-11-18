"""Marker run against the Marking Lab, saved to runs/<id>.json.

    python -m harness.run                              # profile [default]
    python -m harness.run --profile gemma --limit 3
    python -m harness.run --question dens-001 --notes "test prompt v2"
    python -m harness.run list                         # past runs, side by side
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

from . import config, llm, prompt
from .lab import Lab, LabError

HARNESS_NAME = "tutor-cambridge"
SCORE_KEYS = ("results", "parseFailures", "exactTotalAgreement", "lineAgreement",
              "pointAgreement", "meanAbsError", "bias")


def spread(items: list, n: int) -> list:
    """n items evenly spaced over the list (deterministic), so a small sample
    covers every question instead of the first one only. n <= 0 -> all."""
    if n <= 0 or n >= len(items):
        return items
    return [items[i * len(items) // n] for i in range(n)]


def run(p: dict, *, lab: Lab, chat=llm.chat, notes: str = "", log=print) -> dict:
    """One full run. `lab` and `chat` are injectable for tests."""
    template = prompt.load_template(p["prompt"])
    commit, dirty = config.git_state()
    settings = {k: p[k] for k in ("think", "temperature", "num_ctx", "max_tokens",
                                  "keep_alive", "profile")}
    lab_run = lab.create_run(
        harnessName=HARNESS_NAME, gitCommit=commit, dirty=dirty, model=p["model"],
        modelSettings=settings, split="open", usedMarkingScheme=True,
        promptTemplate=template, notes=notes or f"prompt={p['prompt']}", extra={"limit": p["limit"]})
    run_id, version = lab_run["runId"], lab_run["datasetVersion"]

    record = {"lab_run_id": run_id, "dataset_version": version, "lab": lab.base,
              "started_at": datetime.now().isoformat(timespec="seconds"),
              "git_commit": commit, "dirty": dirty, "notes": notes,
              "profile": p, "template": template, "answers": [], "score": None}
    path = config.RUNS_DIR / f"{run_id:04d}.json"

    def save():
        config.RUNS_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    answers = spread(lab.answers(run_id, p["question"]), int(p["limit"]))
    questions: dict[str, dict] = {}
    log(f"Lab run {run_id} · {len(answers)} respostas · {p['model']} · prompt {p['prompt']}")

    t_run = time.perf_counter()
    for repeat in range(1, int(p["repeats"]) + 1):
        for n, a in enumerate(answers, 1):
            qid = a["questionId"]
            if qid not in questions:
                questions[qid] = lab.question(qid, run_id)
            q = questions[qid]
            text = prompt.render(template, q, a["lines"])
            try:
                out = chat(text, model=p["model"], think=p["think"] == "on",
                           temperature=float(p["temperature"]), num_ctx=int(p["num_ctx"]),
                           max_tokens=int(p["max_tokens"]), keep_alive=p["keep_alive"])
                parsed, reason = prompt.parse(out["text"], q, a["lines"])
            except llm.LLMError as e:
                out, parsed, reason = {"text": "", "error": str(e)}, None, str(e)

            result = {"answerId": a["id"], "datasetVersion": version, "repeat": repeat,
                      "prompt": text, "rawOutput": out["text"], "reason": reason[:300],
                      "parseFailed": parsed is None}
            if parsed is not None:
                result["lines"] = parsed
            lab.submit(run_id, [result])

            record["answers"].append({
                "answerId": a["id"], "questionId": qid, "repeat": repeat,
                "parsed": parsed, "reason": reason, "raw": out["text"],
                "metrics": {k: v for k, v in out.items() if k != "text"}})
            save()
            marks = ("  ".join(f"{k} {v['total']}" for k, v in parsed.items())
                     if parsed else f"PARSE FAIL ({reason})")
            secs = out.get("total_ms", 0) / 1000
            log(f"  [{n}/{len(answers)}] {a['id']:<16} {marks:<28} "
                f"{secs:6.1f} s  {out.get('tokens_per_s', 0):5.1f} tok/s"
                + ("  CUT-OFF" if out.get("cut_off") else ""))

    lab.close(run_id)
    score = lab.score(run_id)
    bad = {(d.get("answerId"), d.get("repeat", 1)) for d in score.get("disagreements", [])}
    for a in record["answers"]:
        a["agree"] = (a["answerId"], a["repeat"]) not in bad
    record["score"] = score
    record["elapsed_s"] = round(time.perf_counter() - t_run, 1)
    save()
    return record


def summary_row(rec: dict) -> dict:
    o = (rec.get("score") or {}).get("overall") or {}
    m = [a["metrics"] for a in rec["answers"] if a["metrics"].get("total_ms")]
    avg = lambda k: sum(x.get(k) or 0 for x in m) / len(m) if m else 0  # noqa: E731
    return {"run": rec["lab_run_id"], "model": rec["profile"]["model"],
            "prompt": rec["profile"]["prompt"], "think": rec["profile"]["think"],
            "n": len(rec["answers"]), **{k: o.get(k) for k in SCORE_KEYS},
            "s/answer": round(avg("total_ms") / 1000, 1), "tok/s": round(avg("tokens_per_s"), 1),
            "notes": rec.get("notes", "")}


def print_summary(rec: dict) -> None:
    r = summary_row(rec)
    pct = lambda v: "—" if v is None else f"{v * 100:.0f}%"  # noqa: E731
    print(f"\nRun {r['run']} (n={r['n']}): acordo total {pct(r['exactTotalAgreement'])} · "
          f"por parte {pct(r['lineAgreement'])} · por ponto {pct(r['pointAgreement'])} · "
          f"MAE {r['meanAbsError']} · bias {r['bias']} · parse failures {r['parseFailures']}")
    print(f"Tempo: {rec.get('elapsed_s')} s no total, {r['s/answer']} s/resposta, {r['tok/s']} tok/s")
    for d in rec["score"].get("disagreements", []):
        print(f"  discorda: {d.get('answerId')}  referência={json.dumps(d.get('reference'))}")
    print(f"Detalhes: runs/{rec['lab_run_id']:04d}.json")


def list_runs() -> None:
    rows = []
    for f in sorted(config.RUNS_DIR.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        if rec.get("score"):
            rows.append(summary_row(rec))
    if not rows:
        print("Nenhuma run concluída em runs/.")
        return
    cols = ["run", "model", "prompt", "think", "n", "exactTotalAgreement", "pointAgreement",
            "bias", "parseFailures", "s/answer", "notes"]
    head = ["run", "modelo", "prompt", "think", "n", "acordo", "ponto", "bias", "falhas", "s/resp", "notas"]
    fmt = lambda c, v: f"{v * 100:.0f}%" if c.endswith("Agreement") and v is not None else str(v)  # noqa: E731
    table = [head] + [[fmt(c, r[c]) for c in cols] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(cols))]
    for row in table:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harness.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "list"])
    ap.add_argument("--profile", default="default")
    for flag in ("model", "prompt", "keep_alive", "question"):
        ap.add_argument(f"--{flag.replace('_', '-')}", dest=flag)
    ap.add_argument("--think", choices=["on", "off"])
    ap.add_argument("--limit", type=int, help="max answers (0 = all)")
    ap.add_argument("--repeats", type=int)
    ap.add_argument("--num-ctx", type=int, dest="num_ctx")
    ap.add_argument("--max-tokens", type=int, dest="max_tokens")
    ap.add_argument("--temperature", type=float)
    ap.add_argument("--notes", default="", help="what changed vs. the previous run")
    args = ap.parse_args(argv)

    if args.command == "list":
        list_runs()
        return 0
    try:
        p = config.load_profile(args.profile, vars(args))
    except KeyError as e:
        ap.error(str(e))
    try:
        rec = run(p, lab=Lab(), notes=args.notes)
    except LabError as e:
        print(f"Erro do Lab: {e}", file=sys.stderr)
        return 1
    print_summary(rec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

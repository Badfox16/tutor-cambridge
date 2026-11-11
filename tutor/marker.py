"""Marker pipeline: a full run against the Marking Lab (ported flow of
scripts/llm-run.mjs, with traces/spans for every stage).

CLI:  python -m tutor.marker run --model qwen3.5:9b --prompt marker-compact \
           --think off --limit 30
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time

from . import config, db, trace
from .lab import LabClient, LabError
from .llm import LLMError, OllamaProvider
from .parse import parse_marker_reply
from .render import answered_lines, merge_scheme, render_marker_prompt

HARNESS_NAME = "tutor-cambridge"


def run_marker(client: LabClient, provider: OllamaProvider, conn,
               *, limit: int | None = None, prompt_variant: str = "marker-full",
               think: bool = False, repeats: int = 1, on_progress=None,
               profile_name: str = "", settings: dict | None = None) -> dict:
    """One marker run: create lab run, mark, submit, close, score, store.

    Every answer is a trace; every stage is a span. Parse failures are data
    (they are submitted with parseFailed=true and count as wrong at the lab).
    `settings` overrides temperature/num_ctx/max_tokens for this run (profile).
    """
    effective = {"temperature": config.TEMPERATURE, "num_ctx": config.NUM_CTX,
                 "max_tokens": config.MAX_TOKENS}
    effective.update(settings or {})
    commit, dirty = config.git_state()
    settings_json = {**effective, "think": think, "profile": profile_name}
    t0 = time.perf_counter()

    # -- create the lab run -----------------------------------------------------
    lab_run_id, dataset_version = None, None
    with run_stage(conn, None, "lab.fetch") as span:
        lab_run = client.create_run(
            harness_name=HARNESS_NAME, model=provider.model, used_scheme=True,
            git_commit=commit, dirty=dirty, split="open",
            prompt_template=prompt_variant, model_settings=settings_json,
            notes=f"marker run (limit={limit}, repeats={repeats})")
        lab_run_id = lab_run["runId"]
        dataset_version = lab_run["datasetVersion"]
        span.meta["lab_run_id"] = lab_run_id

    settings_json["dataset_version"] = dataset_version
    local_run = db.insert(conn, "runs", {
        "kind": "marker", "model": provider.model, "prompt_variant": prompt_variant,
        "settings_json": db.dumps(settings_json), "split": "open",
        "git_commit": commit, "dirty": 1 if dirty else 0, "lab_run_id": lab_run_id,
        "started_at": db.now(), "status": "running",
        "notes": f"limit={limit} repeats={repeats}",
    })

    summary = {"lab_run_id": lab_run_id, "local_run_id": local_run, "marked": 0,
               "parse_failed": 0, "submit_errors": 0, "errors": []}
    try:
        # -- fetch answers + questions + schemes --------------------------------
        with run_stage(conn, local_run, "lab.fetch") as span:
            answers = client.answers(run_id=lab_run_id)["answers"]
            if limit is not None:
                answers = answers[:limit]
            questions, schemes = {}, {}
            for a in answers:
                qid = a["questionId"]
                if qid not in questions:
                    # public question has no points; merge them in from the scheme
                    questions[qid] = merge_scheme(client.question(qid, run_id=lab_run_id),
                                                  client.scheme(qid, run_id=lab_run_id))
            span.meta["answers"] = len(answers)
            span.meta["questions"] = len(questions)

        # -- mark each answer (repeat = new attempt number) -----------------------
        for repeat in range(1, repeats + 1):
            for a in answers:
                qid = a["questionId"]
                tr = trace.start_trace(conn, run_id=local_run, kind="mark",
                                       model=provider.model, question_id=qid,
                                       answer_id=a["id"], attempt=repeat)
                _mark_one(conn, tr, client, provider, lab_run_id, dataset_version,
                          questions[qid], a, prompt_variant, think, repeat,
                          summary)
                if on_progress:
                    on_progress(summary)
    except (LabError, LLMError) as e:
        summary["errors"].append(str(e))
        db.update(conn, "runs", local_run, {"status": "error", "finished_at": db.now(),
                                            "notes": db.dumps({"error": str(e)})})
        summary["total_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return summary

    # -- close + score ------------------------------------------------------------
    try:
        with run_stage(conn, local_run, "lab.submit", meta={"close": True, "lab_run_id": lab_run_id}):
            client.close_run(lab_run_id)
        with run_stage(conn, local_run, "lab.score", meta={"lab_run_id": lab_run_id}):
            score = client.score(lab_run_id)
        db.insert(conn, "scores", {
            "run_id": local_run,
            "accuracy_json": db.dumps({k: score.get(k) for k in (
                "overall", "clearCases", "greyCases", "repeatConsistency",
                "errorHistogram", "answersMarked", "answersInSplit", "detail")}),
            "disagreements_json": db.dumps(score.get("disagreements", [])),
            "fetched_at": db.now(),
        })
        _mark_agreement(conn, local_run, score.get("disagreements", []))
        db.update(conn, "runs", local_run, {"status": "done", "finished_at": db.now()})
        overall = score.get("overall") or {}
        summary["score"] = {k: overall.get(k) for k in (
            "results", "parseFailures", "exactTotalAgreement", "lineAgreement",
            "pointAgreement", "meanAbsError", "bias")}
        summary["disagreements"] = len(score.get("disagreements", []))
    except LabError as e:
        summary["errors"].append(str(e))
        db.update(conn, "runs", local_run, {"status": "error", "finished_at": db.now()})
    summary["total_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return summary


def _mark_one(conn, tr, client, provider, lab_run_id, dataset_version,
              question, answer, prompt_variant, think, repeat, summary) -> None:
    """Render, generate, parse, submit one answer. Failures become spans/data."""
    answer_lines = answer["lines"]  # {label: text}
    prompt = raw = ""
    parsed = None
    reason = ""
    cut_off = False
    ok = False
    try:
        with tr.span("render") as span:
            prompt, _lines = render_marker_prompt(question, answer_lines,
                                                  with_scheme=True, variant=prompt_variant)
            span.meta["chars"] = len(prompt)
        with tr.span("model.load") as span:
            span.meta["note"] = "cold-start load reported by Ollama inside model.generate"
        with tr.span("model.prefill") as span:
            span.meta["note"] = "prefill reported by Ollama inside model.generate"
        with tr.span("model.generate") as span:
            llm = provider.chat([{"role": "user", "content": prompt}], think=think)
            span.tokens_in = llm.prompt_tokens
            span.tokens_out = llm.gen_tokens
            span.meta.update(llm.as_dict())
            cut_off = llm.finish_reason == "length"
            raw = llm.text
        with tr.span("parse") as span:
            parsed, reason = parse_marker_reply(raw, question, answer_lines)
            span.tokens_out = 0 if parsed is None else sum(len(v["marks"]) for v in parsed.values())
            span.meta["reason"] = reason
        ok = parsed is not None
    except (LLMError, LabError) as e:
        # the model call itself failed: record the span, keep going as parseFailed
        reason = str(e)
        summary["errors"].append(reason)

    with tr.span("lab.submit") as span:
        body = _result_body(answer, dataset_version, repeat=repeat,
                            parsed=parsed, prompt=prompt, raw=raw, reason=reason)
        try:
            out = client.submit_results(lab_run_id, [body])
            span.meta["stored"] = out.get("stored")
        except LabError as e:
            span.ok = False
            span.error = str(e)
            summary["submit_errors"] += 1
            summary["errors"].append(str(e))

    summary["marked"] += 1
    if parsed is None:
        summary["parse_failed"] += 1
    tr.finish(ok=ok, parse_failed=parsed is None, cut_off=cut_off,
              prompt=prompt, raw_output=raw, parsed_json=parsed, reason=reason,
              model=provider.model)


def _result_body(answer, dataset_version, *, repeat, parsed, prompt, raw, reason) -> dict:
    body = {"answerId": answer["id"], "datasetVersion": dataset_version,
            "repeat": repeat, "prompt": prompt, "rawOutput": raw,
            "reason": reason[:300], "parseFailed": parsed is None}
    if parsed is not None:
        body["lines"] = parsed
    return body


def _mark_agreement(conn, local_run, disagreements: list) -> None:
    """Set `agree` per trace from the lab's closed-run disagreements."""
    bad = {(d.get("answerId"), d.get("repeat", 1)) for d in disagreements}
    for row in conn.execute("SELECT id, answer_id, attempt FROM traces WHERE run_id = ?",
                            (local_run,)).fetchall():
        agree = (row["answer_id"], row["attempt"]) not in bad
        db.update(conn, "traces", row["id"], {"agree": 1 if agree else 0})


@contextlib.contextmanager
def run_stage(conn, run_id: int | None, stage: str, meta: dict | None = None):
    """Run-level stage (lab.fetch / lab.submit / lab.score) as its own trace."""
    tr = trace.start_trace(conn, run_id=run_id, kind="mark", model="")
    ok = True
    try:
        with tr.span(stage) as span:
            span.meta.update(meta or {})
            yield span
    except BaseException:
        ok = False
        raise
    finally:
        tr.finish(ok=ok)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutor.marker",
                                     description="Marker run against the Marking Lab")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one marking run")
    run.add_argument("--profile", default=None,
                     help="profile from profiles.toml (default: [default]; flags below override it)")
    run.add_argument("--model", default=None, help="exact Ollama tag (overrides profile)")
    run.add_argument("--prompt", default=None, help="prompt variant in tutor/prompts/ (overrides profile)")
    run.add_argument("--think", default=None, choices=["off", "on"], help="overrides profile")
    run.add_argument("--limit", type=int, default=None, help="max answers to mark (overrides profile)")
    run.add_argument("--repeats", type=int, default=None, help="mark each answer N times (overrides profile)")
    args = parser.parse_args(argv)

    overrides = {"model": args.model, "prompt": args.prompt,
                 "think": args.think, "limit": args.limit, "repeats": args.repeats}
    try:
        profile = config.resolve_profile(args.profile, overrides)
    except KeyError as e:
        parser.error(str(e))

    think = profile["think"] == "on"
    limit = profile["limit"] or None  # 0 = all answers
    repeats = int(profile["repeats"])

    conn = db.connect(config.DB_PATH)
    db.init_db(conn)
    client = LabClient()
    provider = OllamaProvider(
        model=profile["model"], keep_alive=profile["keep_alive"],
        temperature=float(profile["temperature"]),
        num_ctx=int(profile["num_ctx"]), max_tokens=int(profile["max_tokens"]))

    def progress(s):
        print(f"\rmarked {s['marked']}  (parse failures {s['parse_failed']}, "
              f"submit errors {s['submit_errors']})", end="", flush=True)

    summary = run_marker(client, provider, conn, limit=limit,
                         prompt_variant=profile["prompt"], think=think,
                         repeats=repeats, on_progress=progress,
                         profile_name=profile["name"], settings={
                             "temperature": float(profile["temperature"]),
                             "num_ctx": int(profile["num_ctx"]),
                             "max_tokens": int(profile["max_tokens"]),
                         })
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

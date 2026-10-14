"""Online tests: a bought paper, taken by a class on their phones.

A teacher (or parent) makes a test from a paper they have paid for. They say
how many questions each student gets; each student who opens the link and
types their name is dealt their own random selection, in their own order,
with the options of each multiple-choice question shuffled and lettered
afresh — so neighbours cannot copy. Answers are marked as they are handed in:

* multiple choice: right or wrong;
* a short answer that is a number or a plain value: compared by value
  (3/4, 0.75 and 6/8 agree);
* anything else: left for the teacher, who sees it with the marking scheme.

After handing in, a student sees what the teacher allowed: the score only,
or also the right answers, the marking scheme and the animated walkthrough.

A student needs no account: the attempt's own secret token is their key.
Their name is kept with the test and goes when the test is deleted.
"""
from __future__ import annotations

import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from ..errors import raise_api_error

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no 0/O, 1/I: read aloud in a classroom
MAX_ATTEMPTS = 500
SHOW = ("after_submit", "after_close", "never")


# ── making and running a test ────────────────────────────────────────────────

def _code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def create(*, owner: str, role: str, draft_id: str, title: str = "", per_student: int = 0, minutes: int = 0,
           show: str = "after_submit", shuffle_options: bool = True, days_open: int = 14) -> dict[str, Any]:
    """A test from one of the owner's papers. The paper must be paid for:
    a test hands every question in it to the class."""
    from ..infra.db import execute, fetch_one, to_json
    from . import billing, exam_drafts

    row = exam_drafts.get(draft_id, f"{role}:{owner}")
    paper = exam_drafts.paper_for(row)
    pool = [str(q.get("question_id")) for q in paper.items if q.get("question_id")]
    if not pool:
        raise_api_error("VALIDATION_FAILED", "Put questions on the paper first.")
    quote = billing.quote_paper(owner, role, list(paper.items))
    if not quote.get("paid"):
        raise_api_error("PAYMENT_REQUIRED", f"Buy the paper first (KSh {quote.get('total_ksh', 0):g}); then the class can take it online.",
                        detail={"total_ksh": quote.get("total_ksh", 0)})
    if show not in SHOW:
        show = "after_submit"
    per = max(1, min(int(per_student or len(pool)), len(pool)))
    for _ in range(5):
        code = _code()
        if not fetch_one("SELECT 1 AS x FROM online_tests WHERE code = :c", {"c": code}):
            break
    test_id = "test-" + secrets.token_urlsafe(8)
    execute("""INSERT INTO online_tests (test_id, owner, draft_id, title, code, pool, per_student, minutes, show_answers,
                                         shuffle_options, status, closes_at)
               VALUES (:id, :o, :d, :t, :c, CAST(:p AS jsonb), :n, :m, :s, :sh, 'open', NOW() + make_interval(days => :days))""",
            {"id": test_id, "o": owner, "d": draft_id, "t": (title or row.get("title") or "Test")[:120], "c": code,
             "p": to_json(pool), "n": per, "m": max(0, min(int(minutes or 0), 600)), "s": show, "sh": bool(shuffle_options),
             "days": max(1, min(int(days_open or 14), 180))})
    return get(owner, test_id)


def _public(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: row.get(k) for k in ("test_id", "title", "code", "per_student", "minutes", "show_answers",
                                   "shuffle_options", "status")}
    out["pool_size"] = len(row.get("pool") or [])
    for k in ("created_at", "closes_at"):
        v = row.get(k)
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def get(owner: str, test_id: str) -> dict[str, Any]:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM online_tests WHERE test_id = :t AND owner = :o", {"t": test_id, "o": owner})
    if not row:
        raise_api_error("NOT_FOUND", "No such test.")
    counts = fetch_one("""SELECT COUNT(*) AS started, COUNT(submitted_at) AS handed_in FROM test_attempts
                          WHERE test_id = :t""", {"t": test_id}) or {}
    return {**_public(row), "draft_id": row.get("draft_id"), "started": int(counts.get("started") or 0),
            "handed_in": int(counts.get("handed_in") or 0)}


def list_for(owner: str) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    rows = fetch_all("SELECT test_id FROM online_tests WHERE owner = :o ORDER BY created_at DESC LIMIT 200", {"o": owner}) or []
    return [get(owner, r["test_id"]) for r in rows]


def set_status(owner: str, test_id: str, status: str) -> dict[str, Any]:
    from ..infra.db import execute

    get(owner, test_id)
    if status not in ("open", "closed"):
        raise_api_error("VALIDATION_FAILED", "A test is open or closed.")
    execute("UPDATE online_tests SET status = :s WHERE test_id = :t AND owner = :o", {"s": status, "t": test_id, "o": owner})
    return get(owner, test_id)


def delete(owner: str, test_id: str) -> None:
    from ..infra.db import execute

    get(owner, test_id)
    execute("DELETE FROM test_attempts WHERE test_id = :t", {"t": test_id})
    execute("DELETE FROM online_tests WHERE test_id = :t AND owner = :o", {"t": test_id, "o": owner})


# ── the questions a student sees ─────────────────────────────────────────────

def _load(owner: str, qid: str) -> dict[str, Any] | None:
    from . import user_questions

    try:
        return user_questions.load(qid, owner)
    except Exception:  # noqa: BLE001
        return None


def _marks(q: dict[str, Any]) -> float:
    try:
        return float((q.get("pedagogy") or {}).get("max_marks") or q.get("marks") or 1)
    except (TypeError, ValueError):
        return 1.0


def _figure(q: dict[str, Any]) -> str:
    binding = q.get("diagram")
    if not isinstance(binding, dict) or not binding.get("diagram_id"):
        return ""
    try:
        from .question_paper import figure_markup, figures_for

        return _safe_svg(figure_markup(q, figures_for([q]), answers=False) or "")
    except Exception:  # noqa: BLE001
        return ""


def _safe_svg(svg: str) -> str:
    """A figure as the student's page may insert it: a drawing only — no
    script, no event handler, no embedded page, no outside link."""
    svg = re.sub(r"(?is)<(script|foreignObject|iframe|object|embed)\b.*?</\1\s*>", "", svg)
    svg = re.sub(r"(?is)<(script|foreignObject|iframe|object|embed)\b[^>]*/?>", "", svg)
    svg = re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", svg)
    svg = re.sub(r"(?i)(href|xlink:href)\s*=\s*(\"(?!#|data:image/)[^\"]*\"|'(?!#|data:image/)[^']*')", "", svg)
    svg = re.sub(r"(?i)javascript:", "", svg)
    return svg.strip() if svg.strip().startswith("<svg") else ""


def _student_view(q: dict[str, Any], order: list[str] | None) -> dict[str, Any]:
    """What the student sees: never the answer. Options in the attempt's
    order, lettered A, B, C… afresh."""
    options = [o for o in (q.get("options") or []) if isinstance(o, dict)]
    by_id = {str(o.get("id")): o for o in options}
    shown = [by_id[i] for i in (order or list(by_id)) if i in by_id]
    return {"question_id": q.get("question_id"), "type": q.get("question_type") or "",
            "context": q.get("stimulus_context") or "", "question": q.get("question_text") or "",
            "options": [{"letter": "ABCDEFGH"[n], "text": o.get("text")} for n, o in enumerate(shown)],
            "parts": [{"label": p.get("label") or p.get("part") or "", "text": p.get("text") or p.get("question") or ""}
                      for p in (q.get("structured_parts") or []) if isinstance(p, dict)],
            "marks": _marks(q), "figure": _figure(q)}


def start(code: str, name: str, *, seed: str = "") -> dict[str, Any]:
    """A student opens the test: their own deal of questions."""
    from ..infra.db import execute, fetch_one, to_json

    test = fetch_one("SELECT * FROM online_tests WHERE code = :c", {"c": code.strip().upper()})
    if not test or test["status"] != "open" or (test.get("closes_at") and test["closes_at"] < datetime.now(timezone.utc)):
        raise_api_error("NOT_FOUND", "This test is not open. Check the code with your teacher.")
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:60]
    if len(name) < 2:
        raise_api_error("VALIDATION_FAILED", "Type your name, so your teacher knows whose answers these are.")
    started = (fetch_one("SELECT COUNT(*) AS n FROM test_attempts WHERE test_id = :t", {"t": test["test_id"]}) or {}).get("n") or 0
    if int(started) >= MAX_ATTEMPTS:
        raise_api_error("VALIDATION_FAILED", "This test is full.")
    rng = random.Random(seed or secrets.token_hex(8))
    pool = list(test.get("pool") or [])
    picked = rng.sample(pool, min(int(test["per_student"] or len(pool)), len(pool)))
    questions, orders = [], {}
    for qid in picked:
        q = _load(test["owner"], qid)
        if not q:
            continue
        ids = [str(o.get("id")) for o in (q.get("options") or []) if isinstance(o, dict)]
        if ids and test.get("shuffle_options"):
            rng.shuffle(ids)
        orders[qid] = ids
        questions.append(_student_view(q, ids))
    token = secrets.token_urlsafe(24)
    execute("""INSERT INTO test_attempts (attempt_id, token, test_id, student_name, question_ids, option_orders)
               VALUES (:a, :tok, :t, :n, CAST(:q AS jsonb), CAST(:o AS jsonb))""",
            {"a": "att-" + secrets.token_urlsafe(8), "tok": token, "t": test["test_id"], "n": name,
             "q": to_json([q["question_id"] for q in questions]), "o": to_json(orders)})
    return {"token": token, "title": test["title"], "minutes": test["minutes"], "name": name, "questions": questions}


def _attempt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    from ..infra.db import fetch_one

    att = fetch_one("SELECT * FROM test_attempts WHERE token = :t", {"t": token})
    if not att:
        raise_api_error("NOT_FOUND", "No such attempt.")
    test = fetch_one("SELECT * FROM online_tests WHERE test_id = :t", {"t": att["test_id"]})
    if not test:
        raise_api_error("NOT_FOUND", "This test was removed.")
    return att, test


def resume(token: str) -> dict[str, Any]:
    """The same student, back on the page: their questions again, or their result."""
    att, test = _attempt(token)
    if att.get("submitted_at"):
        return {"submitted": True, **result(token)}
    questions = []
    for qid in att.get("question_ids") or []:
        q = _load(test["owner"], qid)
        if q:
            questions.append(_student_view(q, (att.get("option_orders") or {}).get(qid)))
    return {"submitted": False, "token": token, "title": test["title"], "minutes": test["minutes"],
            "name": att["student_name"], "questions": questions,
            "started_at": att["started_at"].isoformat() if hasattr(att["started_at"], "isoformat") else att["started_at"]}


# ── marking ──────────────────────────────────────────────────────────────────

def _plain(value: str) -> str:
    """The answer's final value as typed text: the part after the last "=",
    without LaTeX, units words or spaces."""
    text = str(value or "")
    text = re.sub(r"\\text\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:circ|degree)", "°", text)
    text = text.replace("$", "").replace("\\,", "").replace("\\!", "")
    text = re.sub(r"\\(?:d?frac)\{([^}]*)\}\{([^}]*)\}", r"(\1)/(\2)", text)
    if "=" in text:
        text = text.rsplit("=", 1)[1]
    text = re.sub(r"\s+", "", text).strip().lower().rstrip(".")
    # Degrees and units are not the value: 3°C, 3 cm, KSh 50, 25% read as 3, 3, 50, 25.
    text = re.sub(r"\^?°[cf]?$", "", text)
    text = re.sub(r"^(ksh\.?|kshs\.?|sh\.?)", "", text)
    text = re.sub(r"(?<=[\d)])(cm²|cm2|cm³|cm3|m²|m2|m³|m3|mm|cm|km|m|kg|g|ml|l|min|hours?|hrs?|h|s|kshs?|shillings|%)$", "", text)
    return text


def mark_one(q: dict[str, Any], given: Any, order: list[str] | None) -> dict[str, Any]:
    """{status: right | wrong | to_mark, score, out_of}."""
    from . import play_engine

    out_of = _marks(q)
    options = [o for o in (q.get("options") or []) if isinstance(o, dict)]
    if options:
        shown = [str(i) for i in (order or [str(o.get("id")) for o in options])]
        letter = str(given or "").strip().upper()[:1]
        if not letter or "ABCDEFGH".find(letter) < 0 or "ABCDEFGH".find(letter) >= len(shown):
            return {"status": "wrong", "score": 0.0, "out_of": out_of}
        chosen = shown["ABCDEFGH".find(letter)]
        right = next((str(o.get("id")) for o in options if o.get("is_correct")), None)
        ok = chosen == right
        return {"status": "right" if ok else "wrong", "score": out_of if ok else 0.0, "out_of": out_of}
    typed = str(given or "").strip()
    if not typed:
        return {"status": "wrong", "score": 0.0, "out_of": out_of}
    expected = _plain(str(q.get("correct_answer") or ""))
    if q.get("question_type") in ("structured", "essay", "extended_response") or len(expected) > 40 or not expected:
        return {"status": "to_mark", "score": 0.0, "out_of": out_of}
    if _plain(typed) == expected or play_engine.check_answer(expected.rstrip("°%"), _plain(typed).rstrip("°%")):
        return {"status": "right", "score": out_of, "out_of": out_of}
    # A typed answer the engine could not read as a value may still be right
    # in other words: the teacher decides.
    reads = play_engine.check_answer(expected.rstrip("°%"), expected.rstrip("°%"))
    return {"status": "wrong" if reads else "to_mark", "score": 0.0, "out_of": out_of}


def submit(token: str, answers: dict[str, Any]) -> dict[str, Any]:
    from ..infra.db import execute, to_json

    att, test = _attempt(token)
    if att.get("submitted_at"):
        return result(token)
    marks: dict[str, Any] = {}
    for qid in att.get("question_ids") or []:
        q = _load(test["owner"], qid)
        if not q:
            continue
        given = str((answers or {}).get(qid, "") or "")[:4000]
        marks[qid] = {**mark_one(q, given, (att.get("option_orders") or {}).get(qid)), "given": given}
    score = sum(m["score"] for m in marks.values())
    out_of = sum(m["out_of"] for m in marks.values())
    late = bool(test.get("minutes")) and isinstance(att.get("started_at"), datetime) and \
        datetime.now(timezone.utc) > att["started_at"] + timedelta(minutes=int(test["minutes"]) + 2)
    execute("""UPDATE test_attempts SET answers = CAST(:m AS jsonb), score = :s, out_of = :o, late = :l,
                                        submitted_at = NOW() WHERE token = :t AND submitted_at IS NULL""",
            {"m": to_json(marks), "s": score, "o": out_of, "l": late, "t": token})
    return result(token)


def _may_show(test: dict[str, Any]) -> bool:
    if test.get("show_answers") == "after_submit":
        return True
    if test.get("show_answers") == "after_close":
        return test.get("status") == "closed" or bool(test.get("closes_at") and test["closes_at"] < datetime.now(timezone.utc))
    return False


def result(token: str) -> dict[str, Any]:
    """The student's result: the score, and — if the teacher allows it now —
    the right answers, the marking scheme and the walkthroughs."""
    att, test = _attempt(token)
    if not att.get("submitted_at"):
        raise_api_error("VALIDATION_FAILED", "Hand the test in first.")
    marks = att.get("answers") or {}
    show = _may_show(test)
    items = []
    for qid in att.get("question_ids") or []:
        m = marks.get(qid) or {}
        entry = {"question_id": qid, "status": m.get("status"), "score": m.get("score"), "out_of": m.get("out_of"),
                 "given": m.get("given", "")}
        if show:
            q = _load(test["owner"], qid) or {}
            order = (att.get("option_orders") or {}).get(qid) or []
            right = next((str(o.get("id")) for o in (q.get("options") or []) if isinstance(o, dict) and o.get("is_correct")), None)
            entry.update(question=q.get("question_text") or "", answer=q.get("correct_answer") or "",
                         right_letter=("ABCDEFGH"[order.index(right)] if right in order else None),
                         marking_scheme=q.get("marking_scheme") or "", worked_answer=q.get("model_answer") or "",
                         walkthrough_url=f"/api/v1/tests/attempts/{token}/walkthrough/{qid}")
        items.append(entry)
    pending = sum(1 for i in items if i["status"] == "to_mark")
    return {"submitted": True, "name": att["student_name"], "title": test["title"], "score": float(att.get("score") or 0),
            "out_of": float(att.get("out_of") or 0), "to_mark": pending, "answers_shown": show, "items": items,
            "late": bool(att.get("late"))}


def walkthrough_question(token: str, qid: str) -> dict[str, Any]:
    """A question the student was dealt, for its walkthrough — only after
    handing in, and only when the teacher shows answers."""
    att, test = _attempt(token)
    if not att.get("submitted_at") or qid not in (att.get("question_ids") or []) or not _may_show(test):
        raise_api_error("NOT_FOUND", "Not available.")
    q = _load(test["owner"], qid)
    if not q:
        raise_api_error("NOT_FOUND", "Not available.")
    return q


# ── the teacher's view ───────────────────────────────────────────────────────

def results(owner: str, test_id: str) -> dict[str, Any]:
    from ..infra.db import fetch_all

    test = get(owner, test_id)
    rows = fetch_all("""SELECT attempt_id, student_name, score, out_of, late, started_at, submitted_at, answers, question_ids
                        FROM test_attempts WHERE test_id = :t ORDER BY submitted_at DESC NULLS LAST, started_at DESC""",
                     {"t": test_id}) or []
    out = []
    for r in rows:
        answers = r.get("answers") or {}
        out.append({"attempt_id": r["attempt_id"], "name": r["student_name"], "score": float(r.get("score") or 0),
                    "out_of": float(r.get("out_of") or 0), "late": bool(r.get("late")),
                    "submitted": bool(r.get("submitted_at")),
                    "to_mark": [{"question_id": q, "given": a.get("given", ""), "out_of": a.get("out_of")}
                                for q, a in answers.items() if a.get("status") == "to_mark"]})
    return {"test": test, "attempts": out}


def to_mark_detail(owner: str, test_id: str) -> dict[str, Any]:
    """Every question on the test with its answer and marking scheme, for
    marking the written answers."""
    from ..infra.db import fetch_one

    get(owner, test_id)
    test = fetch_one("SELECT pool FROM online_tests WHERE test_id = :t", {"t": test_id}) or {}
    out = {}
    for qid in test.get("pool") or []:
        q = _load(owner, qid)
        if q:
            out[qid] = {"question": q.get("question_text") or "", "answer": q.get("correct_answer") or "",
                        "marking_scheme": q.get("marking_scheme") or "", "marks": _marks(q)}
    return out


def mark_written(owner: str, test_id: str, attempt_id: str, question_id: str, score: float) -> dict[str, Any]:
    from sqlalchemy import text

    from ..infra.db import get_engine, to_json

    get(owner, test_id)
    with get_engine().begin() as c:
        row = c.execute(text("SELECT answers FROM test_attempts WHERE attempt_id = :a AND test_id = :t FOR UPDATE"),
                        {"a": attempt_id, "t": test_id}).mappings().first()
        if not row or question_id not in (row["answers"] or {}):
            raise_api_error("NOT_FOUND", "No such answer.")
        answers = dict(row["answers"])
        entry = dict(answers[question_id])
        entry["score"] = max(0.0, min(float(score), float(entry.get("out_of") or 1)))
        entry["status"] = "marked"
        answers[question_id] = entry
        total = sum(float(a.get("score") or 0) for a in answers.values())
        c.execute(text("UPDATE test_attempts SET answers = CAST(:a AS jsonb), score = :s WHERE attempt_id = :id"),
                  {"a": to_json(answers), "s": total, "id": attempt_id})
    return {"attempt_id": attempt_id, "question_id": question_id, "score": entry["score"], "total": total}

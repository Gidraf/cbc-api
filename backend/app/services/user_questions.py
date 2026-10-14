"""A teacher's or parent's own questions: private, free, and theirs alone.

Kept apart from the bank (question_dna) so an account's questions never reach
the content API, another account, or the factory's checks. Their id starts
with "uq-", and `load` serves them in the same flattened shape as a bank
question, so a paper, a test, the play engine and the walkthrough take them
as they are.
"""
from __future__ import annotations

import secrets
from typing import Any

from ..errors import raise_api_error

PREFIX = "uq-"
TYPES = ("multiple_choice", "short_answer", "structured", "true_false")
MAX_PER_OWNER = 2000


def is_own(question_id: str) -> bool:
    return str(question_id).startswith(PREFIX)


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    def text(key: str, limit: int) -> str:
        return str(payload.get(key) or "").strip()[:limit]

    qtype = text("question_type", 40) or "short_answer"
    if qtype not in TYPES:
        raise_api_error("VALIDATION_FAILED", f"A question is one of: {', '.join(TYPES)}.")
    question = text("question_text", 4000)
    if len(question) < 3:
        raise_api_error("VALIDATION_FAILED", "Write the question.")
    options = []
    for n, o in enumerate(payload.get("options") or []):
        if not isinstance(o, dict) or not str(o.get("text") or "").strip():
            continue
        options.append({"id": "ABCDEFGH"[len(options)], "text": str(o["text"]).strip()[:500],
                        "is_correct": bool(o.get("is_correct"))})
        if len(options) == 8:
            break
    if qtype in ("multiple_choice", "true_false"):
        if len(options) < 2 or sum(o["is_correct"] for o in options) != 1:
            raise_api_error("VALIDATION_FAILED", "Give at least two options and mark exactly one as correct.")
    else:
        options = []
    try:
        marks = max(0.5, min(float(payload.get("marks") or 1), 50))
    except (TypeError, ValueError):
        marks = 1.0
    answer = text("correct_answer", 1000)
    if qtype in ("multiple_choice", "true_false"):
        answer = next(o["text"] for o in options if o["is_correct"])
    elif not answer:
        raise_api_error("VALIDATION_FAILED", "Give the answer: it marks the online tests and prints on the scheme.")
    return {"question_text": question, "question_type": qtype, "stimulus_context": text("stimulus_context", 2000),
            "options": options, "correct_answer": answer, "marking_scheme": text("marking_scheme", 3000),
            "model_answer": text("model_answer", 3000), "marks": marks}


def _curriculum(payload: dict[str, Any]) -> dict[str, Any]:
    from .grade_order import normalize_grade

    grade = str(payload.get("grade") or "").strip()
    return {"grade": normalize_grade(grade) if grade else "", "subject": str(payload.get("subject") or "").strip()[:80],
            "strand": str(payload.get("strand") or "").strip()[:120],
            "sub_strand": str(payload.get("sub_strand") or "").strip()[:120]}


def create(owner: str, payload: dict[str, Any]) -> dict[str, Any]:
    from ..infra.db import execute, fetch_one, to_json

    count = (fetch_one("SELECT COUNT(*) AS n FROM user_questions WHERE owner = :o", {"o": owner}) or {}).get("n") or 0
    if int(count) >= MAX_PER_OWNER:
        raise_api_error("VALIDATION_FAILED", f"An account keeps up to {MAX_PER_OWNER} questions of its own.")
    qid = PREFIX + secrets.token_urlsafe(9).replace("_", "x").replace("-", "y")
    execute("""INSERT INTO user_questions (question_id, owner, content, curriculum) VALUES
               (:q, :o, CAST(:c AS jsonb), CAST(:k AS jsonb))""",
            {"q": qid, "o": owner, "c": to_json(_clean(payload)), "k": to_json(_curriculum(payload))})
    return get(owner, qid)


def update(owner: str, question_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from ..infra.db import execute, to_json

    get(owner, question_id)
    execute("""UPDATE user_questions SET content = CAST(:c AS jsonb), curriculum = CAST(:k AS jsonb), updated_at = NOW()
               WHERE question_id = :q AND owner = :o""",
            {"q": question_id, "o": owner, "c": to_json(_clean(payload)), "k": to_json(_curriculum(payload))})
    return get(owner, question_id)


def delete(owner: str, question_id: str) -> None:
    from ..infra.db import execute

    get(owner, question_id)
    execute("DELETE FROM user_questions WHERE question_id = :q AND owner = :o", {"q": question_id, "o": owner})


def get(owner: str, question_id: str) -> dict[str, Any]:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM user_questions WHERE question_id = :q AND owner = :o", {"q": question_id, "o": owner})
    if not row:
        raise_api_error("NOT_FOUND", "No such question of yours.")
    return flatten(row)


def list_for(owner: str, *, grade: str = "", subject: str = "", limit: int = 500) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all
    from .grade_order import normalize_grade

    rows = fetch_all("""SELECT * FROM user_questions WHERE owner = :o
                        AND (:g = '' OR curriculum->>'grade' = :g)
                        AND (:s = '' OR LOWER(curriculum->>'subject') = LOWER(:s))
                        ORDER BY updated_at DESC LIMIT :n""",
                     {"o": owner, "g": normalize_grade(grade) if grade else "", "s": subject, "n": limit}) or []
    return [flatten(r) for r in rows]


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    """The bank's flattened shape, so everything downstream takes it."""
    content = dict(row.get("content") or {})
    marks = content.pop("marks", 1)
    return {**content, "question_id": row["question_id"], "status": "own", "version": 1, "own": True,
            "owner": row.get("owner"), "curriculum": dict(row.get("curriculum") or {}),
            "pedagogy": {"max_marks": marks, "question_type": content.get("question_type")},
            "diagram": None,
            "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at")}


def load(question_id: str, owner: str = "") -> dict[str, Any]:
    """Any question a paper or test may hold, flattened: the account's own
    (only for that account) or the bank's."""
    from . import question_rows
    from .question_dna import question_dna_service

    if is_own(question_id):
        return get(owner, question_id)
    return question_rows.flatten(question_dna_service.get_question(question_id))

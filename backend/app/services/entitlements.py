"""Who may see what: a question's answers, its animations, its video.

* Staff (admin, operator, reviewer, developer) see everything.
* A parent's or teacher's account ("user") owns the questions it paid for
  (on a paper it bought) and the questions it wrote itself. For those it gets
  the answers, the marking scheme, the games and the animated walkthrough.
* Every account has free plays (billing_free_play_items, 100): the first time
  it opens a question in Play — its video, game or walkthrough — one is spent,
  and that question stays open for good.
* The play pass — KSh 50 a day by default (billing_video_plan_ksh / _days),
  paid from the wallet — opens every question's video, game and walkthrough.
  Videos are only ever streamed (services/streaming.py), never handed out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

STAFF = {"admin", "operator", "reviewer", "developer"}
# What a question gives away: never sent for a question the account does not own.
ANSWER_FIELDS = ("correct_answer", "marking_scheme", "model_answer", "rubric", "worked_solution", "solution",
                 "explanation", "answer")


def staff(role: str) -> bool:
    return role in STAFF


def plan_price() -> tuple[int, int]:
    """(cents a period, days a period). 0 cents: not on sale."""
    from . import platform_settings as ps

    try:
        cents = max(0, int(round(float(ps.get("billing_video_plan_ksh", 50) or 0) * 100)))
    except (TypeError, ValueError):
        cents = 0
    try:
        days = max(1, int(ps.get("billing_video_plan_days", 1) or 1))
    except (TypeError, ValueError):
        days = 1
    return cents, days


def plan_until(owner: str) -> datetime | None:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT until FROM subscriptions WHERE owner = :o AND plan = 'video'", {"o": owner})
    return row["until"] if row and row.get("until") else None


def has_video_plan(owner: str, role: str) -> bool:
    if staff(role):
        return True
    until = plan_until(owner)
    return bool(until and until > datetime.now(timezone.utc))


def subscribe(owner: str, role: str) -> dict[str, Any]:
    """Pay one period of the video plan from the wallet; a plan still running
    is extended from its end, so nothing paid for is lost."""
    from sqlalchemy import text

    from ..infra.db import get_engine
    from . import billing

    cents, days = plan_price()
    if staff(role):
        return {"plan": "video", "active": True, "staff": True}
    if not cents:
        from ..errors import raise_api_error

        raise_api_error("VALIDATION_FAILED", "The video plan is not on sale yet.")
    with get_engine().begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:o))"), {"o": "wallet:" + owner})
        billing._debit(c, owner, cents, kind="plan", ref="video", note=f"Video plan, {days} days")
        row = c.execute(text("""
            INSERT INTO subscriptions (owner, plan, until, updated_at)
            VALUES (:o, 'video', NOW() + make_interval(days => :d), NOW())
            ON CONFLICT (owner, plan) DO UPDATE SET
                until = GREATEST(subscriptions.until, NOW()) + make_interval(days => :d), updated_at = NOW()
            RETURNING until"""), {"o": owner, "d": days}).mappings().first()
    return {"plan": "video", "active": True, "until": row["until"].isoformat(), "charged_ksh": billing.ksh(cents)}


def plan_status(owner: str, role: str) -> dict[str, Any]:
    from . import billing

    cents, days = plan_price()
    until = plan_until(owner)
    return {"on_sale": bool(cents), "price_ksh": billing.ksh(cents), "days": days,
            "active": has_video_plan(owner, role), "staff": staff(role),
            "until": until.isoformat() if until else None,
            "free_plays": free_plays(), "free_left": free_left(owner) if not staff(role) else None}


# ── owning questions ─────────────────────────────────────────────────────────

def owned_ids(owner: str, question_ids: list[str]) -> set[str]:
    """Of these, the ones the account paid for or wrote."""
    from ..infra.db import fetch_all

    ids = [str(q) for q in question_ids if q]
    if not ids:
        return set()
    rows = fetch_all("""SELECT question_id FROM question_purchases WHERE owner = :o AND question_id = ANY(:ids)
                        UNION SELECT question_id FROM user_questions WHERE owner = :o AND question_id = ANY(:ids)""",
                     {"o": owner, "ids": ids}) or []
    return {r["question_id"] for r in rows}


def free_plays() -> int:
    from . import platform_settings as ps

    try:
        return max(0, int(ps.get("billing_free_play_items", 100)))
    except (TypeError, ValueError):
        return 100


def opened_ids(owner: str, question_ids: list[str]) -> set[str]:
    """Of these, the ones the account already opened with a free play."""
    from ..infra.db import fetch_all

    ids = [str(q) for q in question_ids if q]
    if not ids:
        return set()
    rows = fetch_all("SELECT question_id FROM play_opens WHERE owner = :o AND question_id = ANY(:ids)",
                     {"o": owner, "ids": ids}) or []
    return {r["question_id"] for r in rows}


def free_left(owner: str) -> int:
    from ..infra.db import fetch_one

    used = (fetch_one("SELECT COUNT(*) AS n FROM play_opens WHERE owner = :o", {"o": owner}) or {}).get("n") or 0
    return max(0, free_plays() - int(used))


def _use_free_play(owner: str, question_id: str) -> bool:
    """Spend one free play on this question (once per question, ever)."""
    from sqlalchemy import text

    from ..infra.db import get_engine

    with get_engine().begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:o))"), {"o": "plays:" + owner})
        if c.execute(text("SELECT 1 FROM play_opens WHERE owner = :o AND question_id = :q"),
                     {"o": owner, "q": question_id}).first():
            return True
        used = c.execute(text("SELECT COUNT(*) FROM play_opens WHERE owner = :o"), {"o": owner}).scalar() or 0
        if int(used) >= free_plays():
            return False
        c.execute(text("INSERT INTO play_opens (owner, question_id) VALUES (:o, :q) ON CONFLICT DO NOTHING"),
                  {"o": owner, "q": question_id})
        return True


def may_open(owner: str, role: str, question_id: str, *, spend: bool = True) -> bool:
    """One question's video, game, walkthrough and answers: staff and the
    pass open everything; a question owned (bought or written) is open; else
    one of the account's free plays opens it — for good, the first time."""
    if staff(role) or has_video_plan(owner, role):
        return True
    if question_id in owned_ids(owner, [question_id]):
        return True
    if not spend:
        return question_id in opened_ids(owner, [question_id]) or free_left(owner) > 0
    return _use_free_play(owner, question_id)


def redact(question: dict[str, Any]) -> dict[str, Any]:
    """The question without what gives the answer away."""
    out = {k: v for k, v in question.items() if k not in ANSWER_FIELDS}
    if isinstance(out.get("options"), list):
        out["options"] = [{k: v for k, v in o.items() if k not in ("is_correct", "why", "feedback")}
                          if isinstance(o, dict) else o for o in out["options"]]
    if isinstance(out.get("structured_parts"), list):
        out["structured_parts"] = [{k: v for k, v in p.items() if k not in ANSWER_FIELDS + ("marks_scheme",)}
                                   if isinstance(p, dict) else p for p in out["structured_parts"]]
    return out


def locked_reason(role: str) -> str:
    from . import billing

    cents, days = plan_price()
    period = "a day" if days == 1 else f"for {days} days"
    if cents:
        return (f"Your {free_plays()} free plays are used up. The play pass (KSh {billing.ksh(cents):g} {period}) opens "
                "every video, game and walkthrough — or buy a paper with this question.")
    return "Your free plays are used up. Buy a paper with this question to open it."


def days_left(owner: str) -> int:
    until = plan_until(owner)
    if not until:
        return 0
    return max(0, (until - datetime.now(timezone.utc) + timedelta(hours=23)).days)

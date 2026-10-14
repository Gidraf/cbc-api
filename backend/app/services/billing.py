"""The wallet: what people pay for, and how much.

Money is kept in cents of a shilling (KSh 1.50 is 150), so the developer
prices are exact. A wallet is topped up with M-Pesa (services/mpesa.py) and
spent on two things:

* Papers — a parent's or teacher's account gets `billing_free_questions`
  questions free, then pays per question the first time it goes on a paper
  they download: a text question and a diagram question are priced apart.
  A question paid for once is theirs: it never costs again on another paper.
* The content API — a developer's key gets `billing_api_free_daily` calls a
  day and `billing_api_free_monthly` a month free; past either, each question
  a call returns is charged at the developer prices.

Staff (admin, operator, reviewer) are never charged. Every movement is a row
in `wallet_entries`, so a balance can always be explained.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("cbc-billing")

EAT = timezone(timedelta(hours=3))
STAFF = {"admin", "operator", "reviewer"}


class PaymentRequired(Exception):
    """Not enough in the wallet: `needed` cents more would do it."""

    def __init__(self, message: str, *, needed: int, price: int, balance: int):
        super().__init__(message)
        self.needed, self.price, self.balance = needed, price, balance

    def detail(self) -> dict[str, Any]:
        return {"needed_ksh": ksh(self.needed), "price_ksh": ksh(self.price), "balance_ksh": ksh(self.balance)}


@dataclass(frozen=True)
class Prices:
    text: int                 # a paper's text question, cents
    diagram: int              # a paper's diagram question, cents
    free_questions: int       # questions free on papers, once per account
    api_text: int             # a text question through the API, cents
    api_diagram: int
    api_free_daily: int       # free calls a day
    api_free_monthly: int     # free calls a month
    min_topup: int            # shillings
    max_topup: int

    def public(self) -> dict[str, Any]:
        return {"paper": {"text_ksh": ksh(self.text), "diagram_ksh": ksh(self.diagram),
                          "free_questions": self.free_questions},
                "api": {"text_ksh": ksh(self.api_text), "diagram_ksh": ksh(self.api_diagram),
                        "free_calls_per_day": self.api_free_daily, "free_calls_per_month": self.api_free_monthly},
                "topup": {"min_ksh": self.min_topup, "max_ksh": self.max_topup}}


def ksh(cents: int) -> float:
    return round(int(cents or 0) / 100, 2)


def prices() -> Prices:
    from . import platform_settings as ps

    def cents(key: str, default: float) -> int:
        try:
            return max(0, int(round(float(ps.get(key, default)) * 100)))
        except (TypeError, ValueError):
            return int(round(default * 100))

    def whole(key: str, default: int) -> int:
        try:
            return max(0, int(ps.get(key, default)))
        except (TypeError, ValueError):
            return default

    return Prices(text=cents("billing_paper_text_ksh", 5), diagram=cents("billing_paper_diagram_ksh", 8),
                  free_questions=whole("billing_free_questions", 10),
                  api_text=cents("billing_api_text_ksh", 1.5), api_diagram=cents("billing_api_diagram_ksh", 2.5),
                  api_free_daily=whole("billing_api_free_daily", 100),
                  api_free_monthly=whole("billing_api_free_monthly", 1000),
                  min_topup=max(1, whole("billing_min_topup_ksh", 10)),
                  max_topup=max(1, whole("billing_max_topup_ksh", 70000)))


def exempt(role: str) -> bool:
    return role in STAFF


def has_figure(question: dict[str, Any]) -> bool:
    """A diagram question: one that prints a figure."""
    if not isinstance(question, dict):
        return False
    if "has_figure" in question:                   # the content API's public shape
        return bool(question["has_figure"])
    binding = question.get("diagram")
    return isinstance(binding, dict) and bool(binding.get("diagram_id") or binding.get("svg_markup"))


# ── the wallet ───────────────────────────────────────────────────────────────

def balance(owner: str) -> int:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT balance_cents FROM wallets WHERE owner = :o", {"o": owner})
    return int((row or {}).get("balance_cents") or 0)


def credit(owner: str, cents: int, *, kind: str, ref: str = "", note: str = "", conn: Any = None) -> int:
    """Add to a wallet (a top-up, a refund, an admin's gift). The new balance."""
    from sqlalchemy import text

    if cents <= 0:
        raise ValueError("A credit is more than nothing.")

    def run(c: Any) -> int:
        row = c.execute(text("""
            INSERT INTO wallets (owner, balance_cents, updated_at) VALUES (:o, :c, NOW())
            ON CONFLICT (owner) DO UPDATE SET balance_cents = wallets.balance_cents + EXCLUDED.balance_cents,
                                              updated_at = NOW()
            RETURNING balance_cents"""), {"o": owner, "c": cents}).mappings().first()
        c.execute(text("""INSERT INTO wallet_entries (owner, amount_cents, kind, ref, note)
                          VALUES (:o, :c, :k, :r, :n)"""), {"o": owner, "c": cents, "k": kind, "r": ref, "n": note[:300]})
        return int(row["balance_cents"])

    if conn is not None:
        return run(conn)
    from ..infra.db import get_engine

    with get_engine().begin() as c:
        return run(c)


def _debit(c: Any, owner: str, cents: int, *, kind: str, ref: str, note: str) -> int:
    """Take from a wallet inside a transaction, never below zero."""
    from sqlalchemy import text

    row = c.execute(text("""UPDATE wallets SET balance_cents = balance_cents - :c, updated_at = NOW()
                            WHERE owner = :o AND balance_cents >= :c RETURNING balance_cents"""),
                    {"o": owner, "c": cents}).mappings().first()
    if row is None:
        have = c.execute(text("SELECT balance_cents FROM wallets WHERE owner = :o"), {"o": owner}).scalar() or 0
        raise PaymentRequired(f"This costs KSh {ksh(cents):g} and the wallet has KSh {ksh(have):g}. Top up with M-Pesa.",
                              needed=cents - int(have), price=cents, balance=int(have))
    c.execute(text("""INSERT INTO wallet_entries (owner, amount_cents, kind, ref, note)
                      VALUES (:o, :c, :k, :r, :n)"""), {"o": owner, "c": -cents, "k": kind, "r": ref, "n": note[:300]})
    return int(row["balance_cents"])


def entries(owner: str, limit: int = 50) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT amount_cents, kind, ref, note, created_at FROM wallet_entries WHERE owner = :o
                        ORDER BY created_at DESC, entry_id DESC LIMIT :n""", {"o": owner, "n": limit}) or []
    return [{"amount_ksh": ksh(r["amount_cents"]), "kind": r["kind"], "ref": r["ref"], "note": r["note"],
             "at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else r["created_at"]}
            for r in rows]


# ── papers ───────────────────────────────────────────────────────────────────

def _owned(owner: str, question_ids: list[str]) -> set[str]:
    from ..infra.db import fetch_all

    if not question_ids:
        return set()
    rows = fetch_all("SELECT question_id FROM question_purchases WHERE owner = :o AND question_id = ANY(:ids)",
                     {"o": owner, "ids": list(question_ids)}) or []
    return {r["question_id"] for r in rows}


def free_used(owner: str) -> int:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT COUNT(*) AS n FROM question_purchases WHERE owner = :o AND free", {"o": owner})
    return int((row or {}).get("n") or 0)


def quote_paper(owner: str, role: str, questions: list[dict[str, Any]]) -> dict[str, Any]:
    """What downloading this paper would cost now: the questions not yet
    paid for, the free ones first (diagram questions before text, as they
    cost more), the rest at their price."""
    p = prices()
    seen: dict[str, bool] = {}
    for q in questions:
        qid = str(q.get("question_id") or "")
        if qid and qid not in seen:
            seen[qid] = has_figure(q)
    if exempt(role):
        return {"exempt": True, "total_ksh": 0, "unpaid": 0, "owned": len(seen), "free": 0, "lines": [],
                "paid": True, "prices": p.public()}
    owned = _owned(owner, list(seen))
    unpaid = [(qid, fig) for qid, fig in seen.items() if qid not in owned]
    unpaid.sort(key=lambda x: not x[1])              # diagrams take the free places first
    free_left = max(0, p.free_questions - free_used(owner))
    lines = []
    for n, (qid, fig) in enumerate(unpaid):
        free = n < free_left
        lines.append({"question_id": qid, "diagram": fig, "free": free,
                      "price_cents": 0 if free else (p.diagram if fig else p.text)})
    total = sum(x["price_cents"] for x in lines)
    return {"exempt": False, "total_ksh": ksh(total), "total_cents": total, "unpaid": len(unpaid),
            "owned": len(owned), "free": sum(1 for x in lines if x["free"]), "free_left": free_left,
            "diagram": sum(1 for x in lines if x["diagram"] and not x["free"]),
            "text": sum(1 for x in lines if not x["diagram"] and not x["free"]),
            "lines": lines, "paid": not unpaid, "balance_ksh": ksh(balance(owner)), "prices": p.public()}


def buy_paper(owner: str, role: str, questions: list[dict[str, Any]], *, ref: str) -> dict[str, Any]:
    """Pay for the paper's unpaid questions in one transaction: the wallet
    is charged and the questions become the owner's, or neither happens."""
    from sqlalchemy import text

    from ..infra.db import get_engine

    quote = quote_paper(owner, role, questions)
    if quote.get("exempt") or quote["paid"]:
        return {**quote, "charged_ksh": 0}
    total = int(quote["total_cents"])
    with get_engine().begin() as c:
        # One purchase at a time per owner, so two clicks cannot pay twice.
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:o))"), {"o": "wallet:" + owner})
        already = {r[0] for r in c.execute(text(
            "SELECT question_id FROM question_purchases WHERE owner = :o AND question_id = ANY(:ids)"),
            {"o": owner, "ids": [x["question_id"] for x in quote["lines"]]}).all()}
        lines = [x for x in quote["lines"] if x["question_id"] not in already]
        total = sum(x["price_cents"] for x in lines)
        if total:
            _debit(c, owner, total, kind="paper", ref=ref,
                   note=f"{sum(1 for x in lines if not x['free'])} question(s) on {ref}")
        for x in lines:
            c.execute(text("""INSERT INTO question_purchases (owner, question_id, price_cents, free, ref)
                              VALUES (:o, :q, :p, :f, :r) ON CONFLICT (owner, question_id) DO NOTHING"""),
                      {"o": owner, "q": x["question_id"], "p": x["price_cents"], "f": x["free"], "r": ref})
    logger.info("Paper %s bought by %s for KSh %s", ref, owner, ksh(total))
    return {**quote_paper(owner, role, questions), "charged_ksh": ksh(total)}


# ── the content API ──────────────────────────────────────────────────────────

def _periods(now: datetime | None = None) -> tuple[Any, Any]:
    local = (now or datetime.now(timezone.utc)).astimezone(EAT)
    return local.date(), local.date().replace(day=1)


def api_usage(owner: str, now: datetime | None = None) -> dict[str, Any]:
    from ..infra.db import fetch_one

    day, month = _periods(now)
    row = fetch_one("""SELECT COALESCE(SUM(calls) FILTER (WHERE day = :d), 0) AS today,
                              COALESCE(SUM(calls), 0) AS month,
                              COALESCE(SUM(charged_cents), 0) AS charged
                       FROM api_usage WHERE owner = :o AND day >= :m""", {"o": owner, "d": day, "m": month}) or {}
    p = prices()
    today, this_month = int(row.get("today") or 0), int(row.get("month") or 0)
    return {"calls_today": today, "calls_this_month": this_month,
            "free_left_today": max(0, min(p.api_free_daily - today, p.api_free_monthly - this_month)),
            "charged_this_month_ksh": ksh(int(row.get("charged") or 0)),
            "balance_ksh": ksh(balance(owner)), "prices": p.public()["api"]}


def meter_api(owner: str, role: str, questions: list[dict[str, Any]], *, ref: str,
              now: datetime | None = None) -> dict[str, Any]:
    """Count one call and charge for it if it is past the free calls. Raises
    PaymentRequired (nothing is counted) when the wallet cannot pay."""
    from sqlalchemy import text

    from ..infra.db import get_engine

    p = prices()
    day, month = _periods(now)
    figures = sum(1 for q in questions if has_figure(q))
    cost = figures * p.api_diagram + (len(questions) - figures) * p.api_text
    with get_engine().begin() as c:
        c.execute(text("SELECT pg_advisory_xact_lock(hashtext(:o))"), {"o": "wallet:" + owner})
        row = c.execute(text("""SELECT COALESCE(SUM(calls) FILTER (WHERE day = :d), 0) AS today,
                                       COALESCE(SUM(calls), 0) AS month
                                FROM api_usage WHERE owner = :o AND day >= :m"""),
                        {"o": owner, "d": day, "m": month}).mappings().first()
        free = exempt(role) or (int(row["today"]) < p.api_free_daily and int(row["month"]) < p.api_free_monthly)
        charged = 0
        if not free and cost:
            _debit(c, owner, cost, kind="api", ref=ref, note=f"{len(questions)} question(s), {figures} with figures")
            charged = cost
        c.execute(text("""INSERT INTO api_usage (owner, day, calls, questions, charged_cents) VALUES (:o, :d, 1, :q, :c)
                          ON CONFLICT (owner, day) DO UPDATE SET calls = api_usage.calls + 1,
                              questions = api_usage.questions + EXCLUDED.questions,
                              charged_cents = api_usage.charged_cents + EXCLUDED.charged_cents"""),
                  {"o": owner, "d": day, "q": len(questions), "c": charged})
    return {"free": free, "charged_ksh": ksh(charged)}

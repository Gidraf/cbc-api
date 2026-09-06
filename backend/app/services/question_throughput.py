"""What a day is supposed to produce, and what it actually produced.

Selling this content means knowing whether today's work happened — not whether
the generator can be run. The shape of the operation is a funnel with three
different daily capacities:

    generate   500   what a machine can write
    review     250   what a person can actually read
    approve     50   what somebody will put their name to

Those numbers are not a ratio to be enforced; they are three separate rates
that only balance over weeks. What matters is that each is visible against its
target, and that the queue between two stages is visible too — because the
number that kills this operation is not "we generated 400 today", it is
"there are 3,000 items waiting to be reviewed and nobody noticed".

Progress is counted from EVENTS rather than from a status column. A status
column holds only the latest thing that happened, so an item generated,
reviewed, rejected and regenerated on the same day shows as one generation —
and the reviewer's day disappears from the record.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, date as _date, timedelta as _timedelta

_day = _timedelta(days=1)
from typing import Any

logger = logging.getLogger("cbc-question-throughput")

GENERATED = "generated"
REVIEWED = "reviewed"
APPROVED = "approved"
REJECTED = "rejected"
BLOCKED = "blocked"          # stopped by the structure gate, never seen by a person

STAGES = (GENERATED, REVIEWED, APPROVED)

DEFAULTS = {"generate_per_day": 500, "review_per_day": 250, "approve_per_day": 50}


def target_id_for(grade: str, subject: str, strand: str = "") -> str:
    seed = f"{grade}|{subject}|{strand}".lower()
    return f"tgt_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


@dataclass
class Target:
    grade: str = ""
    subject: str = ""
    strand: str = ""
    generate_per_day: int = DEFAULTS["generate_per_day"]
    review_per_day: int = DEFAULTS["review_per_day"]
    approve_per_day: int = DEFAULTS["approve_per_day"]
    active: bool = True

    # The event is past tense and the rate is not: "generated" is counted
    # against `generate_per_day`. Mapped rather than derived, because deriving
    # it from the string is how "reviewed" quietly becomes "reviewe_per_day".
    _RATE = {GENERATED: "generate_per_day", REVIEWED: "review_per_day",
             APPROVED: "approve_per_day"}

    def per_day(self, stage: str) -> int:
        return int(getattr(self, self._RATE.get(stage, ""), 0) or 0)

    def to_dict(self) -> dict[str, Any]:
        return {"target_id": target_id_for(self.grade, self.subject, self.strand),
                "grade": self.grade, "subject": self.subject, "strand": self.strand,
                "generate_per_day": self.generate_per_day,
                "review_per_day": self.review_per_day,
                "approve_per_day": self.approve_per_day, "active": self.active}


@dataclass
class DayProgress:
    """One scope, one day, against its target."""
    grade: str = ""
    subject: str = ""
    strand: str = ""
    on: str = ""
    done: dict[str, int] = field(default_factory=dict)
    target: Target = field(default_factory=Target)
    # What is waiting between stages, which is the number that actually warns.
    awaiting_review: int = 0
    awaiting_approval: int = 0
    blocked_today: int = 0

    def share(self, stage: str) -> float:
        goal = self.target.per_day(stage)
        if not goal:
            return 0.0
        return round(min(1.0, self.done.get(stage, 0) / goal) * 100, 1)

    @property
    def warnings(self) -> list[str]:
        out: list[str] = []
        # A backlog only matters against what a person can clear in a day.
        if self.target.review_per_day and self.awaiting_review > self.target.review_per_day * 5:
            days = self.awaiting_review / self.target.review_per_day
            out.append(
                f"{self.awaiting_review} items are waiting to be reviewed — "
                f"{days:.0f} days of reading at {self.target.review_per_day} a "
                f"day. Generating more today makes that worse, not better.")
        if self.target.approve_per_day and self.awaiting_approval > self.target.approve_per_day * 5:
            days = self.awaiting_approval / self.target.approve_per_day
            out.append(
                f"{self.awaiting_approval} reviewed items are waiting for "
                f"approval — {days:.0f} days at {self.target.approve_per_day} a "
                f"day. Nothing here can be sold until somebody signs it.")
        if self.blocked_today:
            out.append(
                f"{self.blocked_today} item(s) were stopped by the structure "
                f"gate today and never reached a reviewer.")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade, "subject": self.subject, "strand": self.strand,
            "on": self.on,
            "stages": [
                {"stage": stage, "done": self.done.get(stage, 0),
                 "target": self.target.per_day(stage),
                 "share": self.share(stage),
                 "short_by": max(0, self.target.per_day(stage) - self.done.get(stage, 0))}
                for stage in STAGES
            ],
            "awaiting_review": self.awaiting_review,
            "awaiting_approval": self.awaiting_approval,
            "blocked_today": self.blocked_today,
            "warnings": self.warnings,
            "target": self.target.to_dict(),
        }


# ── writing ─────────────────────────────────────────────────────────────────


def record(event: str, *, question_id: str = "", grade: str = "", subject: str = "",
           strand: str = "", sub_strand: str = "", actor: str = "",
           detail: dict[str, Any] | None = None) -> bool:
    """One thing that happened to one question.

    Never raises. A day's counting is worth less than the work it counts, so a
    failure here is logged and the generation or the review carries on.
    """
    from ..infra.db import execute

    try:
        execute(
            """
            INSERT INTO question_events
                (question_id, grade, subject, strand, sub_strand, event, actor, detail)
            VALUES (:qid, :grade, :subject, :strand, :sub_strand, :event, :actor,
                    CAST(:detail AS JSONB))
            """,
            {"qid": question_id, "grade": grade, "subject": subject,
             "strand": strand, "sub_strand": sub_strand, "event": event,
             "actor": actor, "detail": json.dumps(detail or {})},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record %s for %s: %s", event, question_id, exc)
        return False


def record_batch(event: str, questions: list[dict[str, Any]], *, grade: str = "",
                 subject: str = "", strand: str = "", sub_strand: str = "",
                 actor: str = "", detail: dict[str, Any] | None = None) -> int:
    """A generation run is one event per item, not one event per run.

    Counting runs would say "3 generations today" where the target is written
    in questions, and a run of 4 would look the same as a run of 400.
    """
    written = 0
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        if record(event,
                  question_id=str(question.get("question_id") or ""),
                  grade=grade or str((question.get("curriculum") or {}).get("grade") or ""),
                  subject=subject, strand=strand, sub_strand=sub_strand,
                  actor=actor, detail=detail):
            written += 1
    return written


def set_target(grade: str, subject: str, strand: str = "", **rates: Any) -> dict[str, Any]:
    """What this scope is meant to produce a day."""
    from ..infra.db import execute

    target = Target(
        grade=grade, subject=subject, strand=strand,
        generate_per_day=int(rates.get("generate_per_day") or DEFAULTS["generate_per_day"]),
        review_per_day=int(rates.get("review_per_day") or DEFAULTS["review_per_day"]),
        approve_per_day=int(rates.get("approve_per_day") or DEFAULTS["approve_per_day"]),
        active=bool(rates.get("active", True)),
    )
    execute(
        """
        INSERT INTO question_targets
            (target_id, grade, subject, strand, generate_per_day,
             review_per_day, approve_per_day, active)
        VALUES (:id, :grade, :subject, :strand, :gen, :rev, :app, :active)
        ON CONFLICT (target_id) DO UPDATE SET
            generate_per_day = EXCLUDED.generate_per_day,
            review_per_day = EXCLUDED.review_per_day,
            approve_per_day = EXCLUDED.approve_per_day,
            active = EXCLUDED.active,
            updated_at = NOW()
        """,
        {"id": target_id_for(grade, subject, strand), "grade": grade,
         "subject": subject, "strand": strand,
         "gen": target.generate_per_day, "rev": target.review_per_day,
         "app": target.approve_per_day, "active": target.active},
    )
    return target.to_dict()


# ── reading ─────────────────────────────────────────────────────────────────


def get_target(grade: str, subject: str, strand: str = "") -> Target:
    """The target for this scope, falling back to the strand-less one.

    A target set for "Grade 9 Mathematics" covers every strand in it until a
    strand is given its own — otherwise adding a strand silently drops it out
    of the day's plan.
    """
    from ..infra.db import fetch_all

    try:
        rows = fetch_all(
            """
            SELECT grade, subject, strand, generate_per_day, review_per_day,
                   approve_per_day, active
            FROM question_targets
            WHERE LOWER(grade) = LOWER(:grade) AND LOWER(subject) = LOWER(:subject)
              AND (LOWER(strand) = LOWER(:strand) OR strand = '')
            ORDER BY LENGTH(strand) DESC
            """,
            {"grade": grade, "subject": subject, "strand": strand}) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the target for %s/%s: %s", grade, subject, exc)
        rows = []

    if not rows:
        return Target(grade=grade, subject=subject, strand=strand)
    row = rows[0]
    return Target(
        grade=str(row.get("grade") or ""), subject=str(row.get("subject") or ""),
        strand=str(row.get("strand") or ""),
        generate_per_day=int(row.get("generate_per_day") or 0),
        review_per_day=int(row.get("review_per_day") or 0),
        approve_per_day=int(row.get("approve_per_day") or 0),
        active=bool(row.get("active", True)),
    )


def _counts_today(grade: str, subject: str, strand: str, on: str) -> dict[str, int]:
    from ..infra.db import fetch_all

    # The day's boundaries are computed HERE, not cast in SQL. `:on::date` is
    # read by SQLAlchemy as a bind parameter named `o` followed by the literal
    # `n::date` — so the query asked for a parameter nothing supplies, raised,
    # was swallowed by the guard below, and every count came back zero. The
    # board read "Written 0 / 500" beside "22 waiting", which is impossible.
    start = _date.fromisoformat(on)
    conditions = ["LOWER(grade) = LOWER(:grade)", "LOWER(subject) = LOWER(:subject)",
                  "happened_at >= :start", "happened_at < :end"]
    params: dict[str, Any] = {"grade": grade, "subject": subject,
                              "start": start, "end": start + _day}
    if strand:
        conditions.append("LOWER(strand) = LOWER(:strand)")
        params["strand"] = strand

    try:
        rows = fetch_all(
            f"""
            SELECT event, COUNT(DISTINCT question_id) AS n
            FROM question_events
            WHERE {' AND '.join(conditions)}
            GROUP BY event
            """, params) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not count today's work for %s/%s: %s", grade, subject, exc)
        return {}
    return {str(r.get("event")): int(r.get("n") or 0) for r in rows}


def _waiting(grade: str, subject: str, strand: str) -> tuple[int, int]:
    """How many items sit between stages, at any age.

    A question is awaiting review when it has been generated and not reviewed
    since; awaiting approval when reviewed and not approved since. Both are
    computed from the latest event per question, because an item rejected and
    regenerated is waiting again.
    """
    from ..infra.db import fetch_all

    conditions = ["LOWER(grade) = LOWER(:grade)", "LOWER(subject) = LOWER(:subject)"]
    params: dict[str, Any] = {"grade": grade, "subject": subject}
    if strand:
        conditions.append("LOWER(strand) = LOWER(:strand)")
        params["strand"] = strand

    try:
        rows = fetch_all(
            f"""
            SELECT latest.event AS event, COUNT(*) AS n FROM (
                SELECT DISTINCT ON (question_id) question_id, event
                FROM question_events
                WHERE {' AND '.join(conditions)} AND question_id <> ''
                ORDER BY question_id, happened_at DESC
            ) AS latest
            GROUP BY latest.event
            """, params) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not measure the queues for %s/%s: %s", grade, subject, exc)
        return 0, 0

    latest = {str(r.get("event")): int(r.get("n") or 0) for r in rows}
    return latest.get(GENERATED, 0), latest.get(REVIEWED, 0)


def progress(grade: str, subject: str, strand: str = "",
             on: str | None = None) -> DayProgress:
    """One scope's day: what was done, against what was meant to be."""
    when = on or date.today().isoformat()
    counts = _counts_today(grade, subject, strand, when)
    awaiting_review, awaiting_approval = _waiting(grade, subject, strand)

    return DayProgress(
        grade=grade, subject=subject, strand=strand, on=when,
        done={stage: counts.get(stage, 0) for stage in STAGES},
        target=get_target(grade, subject, strand),
        awaiting_review=awaiting_review,
        awaiting_approval=awaiting_approval,
        blocked_today=counts.get(BLOCKED, 0),
    )


def history(grade: str, subject: str, strand: str = "", days: int = 14) -> list[dict[str, Any]]:
    """The last fortnight, for the board's chart.

    A day's numbers on their own say nothing. Whether the queue is growing is
    the only question the board exists to answer.
    """
    from ..infra.db import fetch_all

    since = _date.today() - _timedelta(days=int(days))
    conditions = ["LOWER(grade) = LOWER(:grade)", "LOWER(subject) = LOWER(:subject)",
                  "happened_at >= :since"]
    params: dict[str, Any] = {"grade": grade, "subject": subject, "since": since}
    if strand:
        conditions.append("LOWER(strand) = LOWER(:strand)")
        params["strand"] = strand

    try:
        rows = fetch_all(
            f"""
            SELECT CAST(happened_at AS DATE) AS on, event,
                   COUNT(DISTINCT question_id) AS n
            FROM question_events
            WHERE {' AND '.join(conditions)}
            GROUP BY 1, 2 ORDER BY 1
            """, params) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the history for %s/%s: %s", grade, subject, exc)
        return []

    by_day: dict[str, dict[str, int]] = {}
    for row in rows:
        day = str(row.get("on"))
        by_day.setdefault(day, {})[str(row.get("event"))] = int(row.get("n") or 0)
    return [{"on": day, **{stage: counts.get(stage, 0) for stage in STAGES},
             BLOCKED: counts.get(BLOCKED, 0)}
            for day, counts in sorted(by_day.items())]

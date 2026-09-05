"""Keeping the pieces of a lesson material run that has not finished.

The station writes one piece per directive, one model call each, and a
sub-strand runs to twenty or more. Nothing was written down until the last one
landed: the loop filled a list in memory and filed a version after it.

So a run that died on piece 19 of 21 — a timeout, a worker restart, a browser
closed, a container redeployed — threw away nineteen paid-for model calls and
left nothing behind. Retrying started from piece one and paid for them again.
The queue's own retry did exactly this, every time.

A draft is written after each piece. It is not a version: nobody reviews it,
nothing downstream reads it, and it is deleted the moment a real version is
filed. It exists so that what has been paid for survives the thing that
interrupted it, and so a retry resumes rather than restarts.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger("cbc-material-draft")


def key_for(grade: str, subject: str, sub_strand: str, plan_artifact_id: str) -> str:
    """One draft per sub-strand PER PLAN VERSION.

    Keyed on the plan too, because material written from version 2 of a lesson
    plan is not a resumable half of material for version 3 — the directives
    themselves have changed, and resuming across that would splice two
    different lessons together.
    """
    seed = f"{grade}|{subject}|{sub_strand}|{plan_artifact_id}".lower()
    return f"draft_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"


def load(draft_key: str) -> list[dict[str, Any]]:
    """The pieces already written for this run, in the order they were written."""
    from ..infra.db import fetch_one

    try:
        row = fetch_one(
            "SELECT pieces FROM material_drafts WHERE draft_key = :k",
            {"k": draft_key},
        )
    except Exception as exc:  # noqa: BLE001
        # A draft is an optimisation. Losing it costs money; failing the
        # generation over it costs the whole run.
        logger.warning("Could not read draft %s: %s", draft_key, exc)
        return []
    if not row:
        return []
    pieces = row.get("pieces")
    return [p for p in pieces if isinstance(p, dict)] if isinstance(pieces, list) else []


def done_indexes(pieces: list[dict[str, Any]]) -> set[tuple[Any, Any]]:
    """Which directives already have words, by (lesson, index).

    A piece that came back empty or errored is NOT done: it cost a call and
    produced nothing, and resuming should try it again rather than ship the
    gap it left.
    """
    return {
        (p.get("module_number"), p.get("index"))
        for p in pieces
        if str(p.get("say") or "").strip()
    }


def save(draft_key: str, pieces: list[dict[str, Any]], *, grade: str = "",
         subject: str = "", strand: str = "", sub_strand: str = "",
         plan_artifact_id: str = "", plan_version: int = 0,
         model: str = "", llm_calls: int = 0) -> None:
    """Write down what has been produced so far. Never raises."""
    from ..infra.db import execute, to_json

    try:
        execute(
            """
            INSERT INTO material_drafts (
                draft_key, grade, subject, strand, sub_strand,
                plan_artifact_id, plan_version, pieces, model, llm_calls, updated_at
            ) VALUES (
                :k, :grade, :subject, :strand, :sub_strand,
                :plan_id, :plan_version, CAST(:pieces AS jsonb), :model, :calls, NOW()
            )
            ON CONFLICT (draft_key) DO UPDATE SET
                pieces = EXCLUDED.pieces,
                model = EXCLUDED.model,
                llm_calls = EXCLUDED.llm_calls,
                updated_at = NOW()
            """,
            {
                "k": draft_key, "grade": grade, "subject": subject,
                "strand": strand, "sub_strand": sub_strand,
                "plan_id": plan_artifact_id, "plan_version": plan_version,
                "pieces": to_json(pieces), "model": model, "calls": llm_calls,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not save draft %s: %s", draft_key, exc)


def clear(draft_key: str) -> None:
    """Delete the draft. Called once a real version is filed."""
    from ..infra.db import execute

    try:
        execute("DELETE FROM material_drafts WHERE draft_key = :k", {"k": draft_key})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not clear draft %s: %s", draft_key, exc)


def pending(grade: str = "", subject: str = "") -> list[dict[str, Any]]:
    """Unfinished runs, so an operator can see what was interrupted."""
    from ..infra.db import fetch_all
    from .grade_sql import clause

    conditions = ["1=1"]
    params: dict[str, Any] = {}
    if grade:
        conditions.append(clause("grade", "grade"))
        params["grade"] = grade
    if subject:
        conditions.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject

    try:
        rows = fetch_all(
            f"""
            SELECT draft_key, grade, subject, strand, sub_strand,
                   plan_artifact_id, plan_version, model, llm_calls, updated_at,
                   jsonb_array_length(pieces) AS pieces_written
            FROM material_drafts
            WHERE {' AND '.join(conditions)}
            ORDER BY updated_at DESC
            """,
            params,
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list drafts: %s", exc)
        return []
    return rows

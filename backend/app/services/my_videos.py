"""The questions an account owns, as videos.

A question bought on a paper opens its video (services/entitlements.py), so
"My videos" lists every bought question with its video: ready to stream,
being made, or not made yet. Buying a paper queues the missing ones ahead of
the daily batch (priority), so what someone paid for is what gets drawn next.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-my-videos")

BOUGHT_PRIORITY = 10
MAX_QUEUE = 150                 # a paper is rarely longer; a bigger list is queued in later visits


def _video_states(ids: list[str]) -> dict[str, str]:
    """ready / queued / failed / none, from the registry and the queue."""
    from ..infra.db import fetch_all
    from .whiteboard import JOB_KIND

    if not ids:
        return {}
    out = {q: "none" for q in ids}
    for r in fetch_all("""SELECT payload->>'artifact_id' AS q, status FROM jobs WHERE kind = :k
                          AND payload->>'artifact_id' = ANY(:ids) AND status IN ('queued', 'running', 'failed')
                          ORDER BY created_at""", {"k": JOB_KIND, "ids": ids}) or []:
        out[r["q"]] = "being made" if r["status"] in ("queued", "running") else "failed"
    for r in fetch_all("SELECT question_id FROM question_videos WHERE kind = 'lesson' AND question_id = ANY(:ids)",
                       {"ids": ids}) or []:
        out[r["question_id"]] = "ready"
    return out


def queue_missing(question_ids: list[str], *, by: str) -> int:
    """Queue, at the front, the videos these (bank) questions do not have yet."""
    from . import whiteboard

    bank = [q for q in dict.fromkeys(question_ids) if q and not q.startswith("uq-")]
    states = _video_states(bank)
    queued = 0
    for qid in [q for q in bank if states.get(q) in ("none", "failed")][:MAX_QUEUE]:
        try:
            got = whiteboard.enqueue(qid, queued_by=f"bought:{by}", priority=BOUGHT_PRIORITY)
            queued += got.get("status") == "queued"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not queue the video of %s: %s", qid, exc)
    return queued


def missing(question_ids: list[str]) -> list[str]:
    """Of these (bank) questions, the ones with no video made or being made."""
    bank = [q for q in dict.fromkeys(question_ids) if q and not q.startswith("uq-")]
    states = _video_states(bank)
    return [q for q in bank if states.get(q) in ("none", "failed")][:MAX_QUEUE]


def queue_missing_soon(question_ids: list[str], *, by: str) -> int:
    """Queue them in the background, so buying a paper (or pressing "make")
    answers at once. Returns how many will be queued."""
    import threading

    todo = missing(question_ids)
    if todo:
        threading.Thread(target=queue_missing, args=(todo,), kwargs={"by": by},
                         name="queue-bought-videos", daemon=True).start()
    return len(todo)


def library(owner: str, *, draft_ids: list[str] | None = None, limit: int = 300) -> dict[str, Any]:
    """Every question the account bought (on one paper, if asked), with its video."""
    from ..infra.db import fetch_all

    if draft_ids is not None:
        ids = [q for q in draft_ids if q and not q.startswith("uq-")]
        owned = {r["question_id"] for r in (fetch_all(
            "SELECT question_id FROM question_purchases WHERE owner = :o AND question_id = ANY(:ids)",
            {"o": owner, "ids": ids}) or [])}
        ids = [q for q in ids if q in owned][:limit]
    else:
        ids = [r["question_id"] for r in (fetch_all(
            "SELECT question_id FROM question_purchases WHERE owner = :o ORDER BY created_at DESC LIMIT :n",
            {"o": owner, "n": limit}) or [])]
    if not ids:
        return {"items": [], "ready": 0, "being_made": 0}
    rows = {r["question_id"]: r for r in (fetch_all(
        "SELECT question_id, content, curriculum_link FROM question_dna WHERE question_id = ANY(:ids)", {"ids": ids}) or [])}
    states = _video_states(ids)
    items = []
    for qid in ids:
        row = rows.get(qid)
        if not row:
            continue
        content, link = row.get("content") or {}, row.get("curriculum_link") or {}
        binding = content.get("diagram")
        items.append({"question_id": qid, "question_text": content.get("question_text") or "",
                      "grade": link.get("grade"), "subject": link.get("subject"), "sub_strand": link.get("sub_strand"),
                      "has_figure": isinstance(binding, dict) and bool(binding.get("diagram_id")),
                      "video": states.get(qid, "none")})
    return {"items": items, "ready": sum(1 for i in items if i["video"] == "ready"),
            "being_made": sum(1 for i in items if i["video"] == "being made")}

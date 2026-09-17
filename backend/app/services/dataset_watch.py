"""Keep the platform level with Langfuse without anyone pressing a button.

A design uploaded to a grade's dataset used to sit there until an operator
opened the Datasets screen and pressed Sync, then Process. This is the same
pass — every grade synced, every unread document queued, the spine built
behind each — run once on demand by the console button and, when the
setting is on, again every N minutes by a thread that outlives the click.

Queueing is idempotent (a document already queued or running is not queued
twice), so a second API instance running the same watch is harmless.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("cbc-dataset-watch")

_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()

# What the last pass did, for the console. Module state: a restart forgets it,
# which is fine — the next tick writes it again.
_last: dict[str, Any] = {"at": 0.0, "result": None, "error": "", "trigger": ""}

_TICK_SECONDS = 30.0


def run_pass(*, force: bool = False, then_structure: bool = True,
             queued_by: str = "auto-ingest", trigger: str = "manual") -> dict[str, Any]:
    """Sync every grade's dataset and queue every document not yet ingested."""
    from ..infra.db import fetch_all
    from . import grade_sql, job_queue
    from .dataset_ingest import INGESTED, PROCESSING, SELECTED, sync_grade
    from .grade_order import GRADE_SEQUENCE

    synced: dict[str, dict[str, Any]] = {}
    queued: list[dict[str, Any]] = []
    skipped = 0
    for slug, _label, _band in GRADE_SEQUENCE:
        try:
            synced[slug] = sync_grade(slug)
        except Exception as exc:  # noqa: BLE001
            synced[slug] = {"error": str(exc)[:120]}
            continue
        rows = fetch_all(
            "SELECT item_id, status, resolved_subject, declared_subject, title "
            f"FROM dataset_ingest_status WHERE {grade_sql.clause()} ORDER BY title",
            {"grade": slug},
        ) or []
        for row in rows:
            status = str(row.get("status") or "")
            if status in (PROCESSING, SELECTED) or (status == INGESTED and not force):
                skipped += 1
                continue
            job = job_queue.enqueue(
                "dataset_item", grade=slug,
                subject=str(row.get("resolved_subject") or row.get("declared_subject")
                            or row.get("title") or row["item_id"]),
                payload={"item_id": str(row["item_id"]), "force": bool(force),
                         "then_structure": bool(then_structure)},
                queued_by=queued_by,
            )
            queued.append({"grade": slug, "item_id": row["item_id"], "job_id": job.job_id,
                           "title": row.get("title", "")})
    structure: list[dict[str, Any]] = []
    if then_structure:
        try:
            structure = queue_missing_structure()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not queue missing structure: %s", exc)
    if queued or structure:
        job_queue.start_worker()
    result = {
        "queued": len(queued), "skipped": skipped, "grades_synced": len(synced),
        "jobs": queued, "synced": synced, "structure_queued": structure,
        "note": (f"{len(queued)} document(s) queued across {len(synced)} grade(s); they run one at a "
                 f"time. Strands and sub-strands follow each document automatically where the "
                 f"extractor left a learning area without them."),
    }
    _last.update(at=time.time(), result=result, error="", trigger=trigger)
    return result


def missing_structure(grade: str = "", subject: str = "") -> list[dict[str, Any]]:
    """Every ingested learning area whose spine is incomplete, and what it lacks.

    Two shapes. A design with no strands at all (the extractor could not read
    its summary table) needs strands, then sub-strands. A design whose strands
    are known but some have no sub-strands — Grade 9 Mathematics had Term 1's
    and none after — needs sub-strands for just those strands. The second was
    invisible to a count of zero, and orders for Terms 2 and 3 were refused
    while the console read "ingested".
    """
    from ..infra.db import fetch_all

    designs = fetch_all(
        """
        SELECT design_id, grade, subject, metadata FROM curriculum_designs
        WHERE subject <> ''
          AND (:grade = '' OR REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND (:subject = '' OR LOWER(subject) = LOWER(:subject))
        ORDER BY grade, subject, updated_at DESC
        """,
        {"grade": grade, "subject": subject},
    ) or []
    counts: dict[tuple[str, str, str], int] = {}
    for row in fetch_all(
        "SELECT LOWER(grade) AS grade, LOWER(subject) AS subject, LOWER(strand_name) AS strand, "
        "COUNT(*) AS n FROM curriculum_substrands GROUP BY 1, 2, 3"
    ) or []:
        counts[(str(row["grade"]), str(row["subject"]), str(row["strand"]))] = int(row["n"])

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for d in designs:
        key = (str(d["grade"]).lower(), str(d["subject"]).lower())
        if key in seen:
            continue  # the newest design for the area is the one that counts
        seen.add(key)
        strands = [s for s in ((d.get("metadata") or {}).get("strands") or []) if isinstance(s, dict)]
        names = [str(s.get("strand_name") or s.get("name") or "") for s in strands]
        names = [n for n in names if n]
        if not names:
            out.append({"grade": d["grade"], "subject": d["subject"], "needs": "strands",
                        "strands": []})
            continue
        bare = [{"strand": n, "strand_id": str(next((s.get("strand_id") for s in strands
                                                       if str(s.get("strand_name") or s.get("name") or "") == n), "") or "")}
                for n in names if counts.get((key[0], key[1], n.lower()), 0) == 0]
        if bare:
            out.append({"grade": d["grade"], "subject": d["subject"], "needs": "substrands",
                        "strands": bare, "of": len(names)})
    return out


def queue_missing_structure(grade: str = "", subject: str = "") -> list[dict[str, Any]]:
    """Queue what `missing_structure` names, saving as it goes — the spine
    every station reads, with nobody needed at the console to accept it."""
    from . import job_queue

    queued: list[dict[str, Any]] = []
    for area in missing_structure(grade, subject):
        g, s = str(area["grade"]), str(area["subject"])
        if area["needs"] == "strands":
            job = job_queue.enqueue(
                "pipeline", g, s,
                {"steps": ["strands", "substrands"], "index": 0, "custom_instructions": "",
                 "auto_save": True},
                queued_by="datasets",
            )
            queued.append({"grade": g, "subject": s, "job_id": job.job_id, "needs": "strands + sub-strands"})
            continue
        for strand in area["strands"]:
            job = job_queue.enqueue(
                "pipeline", g, s,
                {"steps": ["substrands"], "index": 0, "custom_instructions": "",
                 "auto_save": True, "strand_id": strand.get("strand_id") or ""},
                strand=str(strand["strand"]),
                queued_by="datasets",
            )
            queued.append({"grade": g, "subject": s, "strand": strand["strand"], "job_id": job.job_id,
                           "needs": "sub-strands"})
    return queued


# ── The watch ────────────────────────────────────────────────────────────────

def enabled() -> bool:
    from . import platform_settings

    return bool(platform_settings.get("auto_ingest_enabled", False))


def interval_seconds() -> int:
    from . import platform_settings

    minutes = int(platform_settings.get("auto_ingest_interval_minutes", 30) or 30)
    return max(5, minutes) * 60


def due() -> bool:
    return enabled() and (time.time() - float(_last["at"] or 0.0)) >= interval_seconds()


def status() -> dict[str, Any]:
    result = _last["result"] or {}
    return {
        "enabled": enabled(),
        "interval_minutes": interval_seconds() // 60,
        "running": _thread is not None and _thread.is_alive() and not _stop.is_set(),
        "last_run_at": _last["at"] or None,
        "last_trigger": _last["trigger"],
        "last_error": _last["error"],
        "last_queued": result.get("queued"),
        "last_skipped": result.get("skipped"),
        "next_run_in_seconds": (
            max(0, int(interval_seconds() - (time.time() - float(_last["at"] or 0.0))))
            if enabled() else None
        ),
    }


def tick() -> dict[str, Any] | None:
    """One check: run the pass if the setting is on and the interval has passed."""
    if not due():
        return None
    with _lock:
        if not due():
            return None
        try:
            result = run_pass(trigger="schedule")
        except Exception as exc:  # noqa: BLE001
            # A Langfuse outage must not kill the watch; the next tick retries.
            _last.update(at=time.time(), error=str(exc)[:200], trigger="schedule")
            logger.error("Auto-ingest pass failed: %s", exc)
            return None
        if result["queued"]:
            logger.info("Auto-ingest queued %d document(s) from Langfuse.", result["queued"])
        return result


def _loop() -> None:
    while not _stop.is_set():
        try:
            tick()
        except Exception as exc:  # noqa: BLE001
            logger.error("Dataset watch error: %s", exc)
        _stop.wait(_TICK_SECONDS)


def start() -> bool:
    """Start the watch thread; the setting decides whether it does anything."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="cbc-dataset-watch", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()


# ── Controls over a running ingest ───────────────────────────────────────────
#
# The ingest is a set of queued jobs, so its controls are queue operations
# scoped to the jobs the ingest queues: `dataset_item` for the documents and
# the `strands → substrands` pipelines queued behind them. A RUNNING job is
# never interrupted — killing an extractor mid-design leaves a half-written
# design with no record of which half — so pause and stop take effect at the
# next document boundary, which is at most one design away.

_OURS = """
    (kind = 'dataset_item'
     OR (kind = 'pipeline' AND queued_by = 'datasets'
         AND payload->'steps' = '["strands", "substrands"]'::jsonb))
"""


def pause() -> int:
    """Hold every queued ingest job. The one running finishes."""
    from ..infra.db import execute, fetch_one

    n = fetch_one(f"SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' AND {_OURS}")
    execute(f"UPDATE jobs SET status = 'paused' WHERE status = 'queued' AND {_OURS}")
    return int((n or {}).get("n") or 0)


def resume() -> int:
    from ..infra.db import execute, fetch_one
    from . import job_queue

    n = fetch_one(f"SELECT COUNT(*) AS n FROM jobs WHERE status = 'paused' AND {_OURS}")
    execute(f"UPDATE jobs SET status = 'queued' WHERE status = 'paused' AND {_OURS}")
    count = int((n or {}).get("n") or 0)
    if count:
        job_queue.start_worker()
    return count


def skip(*, job_id: str = "", item_id: str = "", grade: str = "") -> int:
    """Drop one document (or one grade's documents) from the ingest without
    touching the rest. Its status row goes back to what it was."""
    from ..infra.db import execute, fetch_one
    from . import grade_sql

    where = ["status IN ('queued', 'paused')", _OURS]
    params: dict[str, Any] = {}
    if job_id:
        where.append("job_id = :job_id")
        params["job_id"] = job_id
    elif item_id:
        where.append("payload->>'item_id' = :item_id")
        params["item_id"] = item_id
    elif grade:
        where.append(grade_sql.clause())
        params["grade"] = grade
    else:
        return 0
    clause = " AND ".join(where)
    n = fetch_one(f"SELECT COUNT(*) AS n FROM jobs WHERE {clause}", params)
    execute(f"UPDATE jobs SET status = 'cancelled', finished_at = NOW(), "
            f"error = 'skipped by operator' WHERE {clause}", params)
    _release_status_rows(clause, params)
    return int((n or {}).get("n") or 0)


def stop() -> int:
    """Cancel every waiting ingest job. The running one finishes."""
    from ..infra.db import execute, fetch_one

    clause = f"status IN ('queued', 'paused') AND {_OURS}"
    n = fetch_one(f"SELECT COUNT(*) AS n FROM jobs WHERE {clause}")
    execute(f"UPDATE jobs SET status = 'cancelled', finished_at = NOW(), "
            f"error = 'stopped by operator' WHERE {clause}")
    _release_status_rows(clause, {})
    return int((n or {}).get("n") or 0)


def _release_status_rows(job_clause: str, params: dict[str, Any]) -> None:
    """A document queued for ingest is marked `selected`; once its job is
    dropped that would read as Queued forever."""
    from ..infra.db import execute

    execute(
        f"""
        UPDATE dataset_ingest_status SET status = 'pending', selected_at = NULL, updated_at = NOW()
        WHERE status = 'selected' AND item_id IN (
            SELECT payload->>'item_id' FROM jobs WHERE {job_clause}
        )
        """,
        params,
    )


def uningest_all(*, purge_generated: bool = False, purge_orphans: bool = True) -> dict[str, Any]:
    """Undo every ingest in every grade: stop what is waiting, remove the
    designs and sub-strands each document produced, purge designs nothing
    claims, and return every document to Not processed."""
    from ..infra.db import fetch_all
    from .dataset_ingest import FAILED, INGESTED, purge_orphaned_designs, uningest_item
    from .grade_order import GRADE_SEQUENCE

    stopped = stop()
    results: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    orphans: dict[str, dict[str, Any]] = {}
    rows = fetch_all(
        "SELECT item_id, grade, status FROM dataset_ingest_status "
        "WHERE status IN (:ingested, :failed) ORDER BY grade, item_id",
        {"ingested": INGESTED, "failed": FAILED},
    ) or []
    for row in rows:
        try:
            out = uningest_item(str(row["item_id"]), purge_generated=purge_generated)
            results.append({"item_id": row["item_id"], "grade": row["grade"], "ok": True, **out})
            for key, value in (out.get("removed") or {}).items():
                totals[key] = totals.get(key, 0) + int(value)
        except Exception as exc:  # noqa: BLE001
            results.append({"item_id": row["item_id"], "grade": row["grade"], "ok": False,
                            "error": str(exc)[:300]})
    if purge_orphans:
        for slug, _label, _band in GRADE_SEQUENCE:
            try:
                got = purge_orphaned_designs(slug)
            except Exception as exc:  # noqa: BLE001
                got = {"error": str(exc)[:120]}
            if got.get("designs") or got.get("error"):
                orphans[slug] = got
                totals["design"] = totals.get("design", 0) + int(got.get("designs") or 0)
                totals["substrands"] = totals.get("substrands", 0) + int(got.get("substrands") or 0)
    return {
        "stopped": stopped,
        "uningested": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "removed": totals,
        "orphans_purged": orphans,
        "results": results,
    }


def progress() -> dict[str, Any]:
    """Where the ingest stands, every grade on one screen."""
    from ..infra.db import fetch_all, fetch_one
    from .dataset_ingest import STATUSES
    from .grade_order import GRADE_SEQUENCE

    labels = {slug: label for slug, label, _ in GRADE_SEQUENCE}
    order = {slug: i for i, (slug, _, _) in enumerate(GRADE_SEQUENCE)}
    per_grade: dict[str, dict[str, Any]] = {
        slug: {"grade": slug, "label": label, "counts": {s: 0 for s in STATUSES},
               "total": 0, "structure_queued": 0, "structure_running": 0}
        for slug, label, _ in GRADE_SEQUENCE
    }
    for row in fetch_all(
        "SELECT grade, status, COUNT(*) AS n FROM dataset_ingest_status GROUP BY grade, status"
    ) or []:
        g = per_grade.setdefault(str(row["grade"]), {
            "grade": row["grade"], "label": labels.get(str(row["grade"]), str(row["grade"])),
            "counts": {s: 0 for s in STATUSES}, "total": 0,
            "structure_queued": 0, "structure_running": 0,
        })
        g["counts"][str(row["status"])] = int(row["n"])
        g["total"] += int(row["n"])
    for row in fetch_all(
        "SELECT grade, status, COUNT(*) AS n FROM jobs "
        "WHERE kind = 'pipeline' AND queued_by = 'datasets' "
        "  AND payload->'steps' = '[\"strands\", \"substrands\"]'::jsonb "
        "  AND status IN ('queued', 'paused', 'running') GROUP BY grade, status"
    ) or []:
        g = per_grade.get(str(row["grade"]))
        if g is None:
            continue
        key = "structure_running" if row["status"] == "running" else "structure_queued"
        g[key] += int(row["n"])

    jobs = {row["status"]: int(row["n"]) for row in (fetch_all(
        f"SELECT status, COUNT(*) AS n FROM jobs WHERE {_OURS} GROUP BY status"
    ) or [])}
    current = fetch_one(
        f"SELECT job_id, kind, grade, subject, started_at, result->'progress' AS progress "
        f"FROM jobs WHERE status = 'running' AND {_OURS} ORDER BY started_at ASC LIMIT 1"
    )
    waiting = fetch_all(
        f"SELECT job_id, kind, grade, subject, status, payload->>'item_id' AS item_id "
        f"FROM jobs WHERE status IN ('queued', 'paused') AND {_OURS} "
        f"ORDER BY created_at ASC LIMIT 200"
    ) or []

    grades = sorted(per_grade.values(), key=lambda g: order.get(g["grade"], 99))
    total = sum(g["total"] for g in grades)
    ingested = sum(g["counts"].get("ingested", 0) for g in grades)
    failed = sum(g["counts"].get("failed", 0) for g in grades)
    in_flight = jobs.get("queued", 0) + jobs.get("paused", 0) + jobs.get("running", 0)
    return {
        "grades": grades,
        "total": total,
        "ingested": ingested,
        "failed": failed,
        "percentage": round(ingested / total * 100) if total else 0,
        "jobs": jobs,
        "active": in_flight > 0,
        "paused": jobs.get("paused", 0) > 0 and jobs.get("queued", 0) == 0,
        "current": current,
        "waiting": waiting,
        "watch": status(),
    }

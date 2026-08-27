"""Repeatable repairs for content that was saved before a guard existed.

A schema migration runs once. A data repair is different: content keeps
arriving, and a guard added today does nothing about what was written
yesterday. A chunk the model could not parse saved as a sixth CRE strand called
"4.0 CHRISTIAN VALUES", holding one sub-strand whose `values` list was two
hundred lines of page debris. The guard stops new ones; this removes the ones
already there, and keeps sweeping every grade and subject on every boot until
they stop appearing.

Each repair is idempotent and reports what it touched. A repair that keeps
finding rows is a signal that something upstream is still producing them, so
the count is recorded rather than swallowed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from . import substrand_hygiene as hygiene

logger = logging.getLogger("cbc-data-repairs")


@dataclass(slots=True)
class RepairResult:
    repair_id: str
    rows_affected: int = 0
    detail: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "repair_id": self.repair_id,
            "rows_affected": self.rows_affected,
            "detail": self.detail[:50],
            "detail_truncated": max(0, len(self.detail) - 50),
            "error": self.error,
            "dry_run": self.dry_run,
        }


def _purge_debris(dry_run: bool) -> RepairResult:
    """Remove sub-strands that are raw source text rather than content."""
    from ..infra.db import execute, fetch_all

    result = RepairResult("001_purge_substrand_debris", dry_run=dry_run)
    rows = fetch_all(
        """
        SELECT id, grade, subject, strand_name, sub_strand_name, slos,
               learning_experiences, key_inquiry_questions, core_competencies,
               values, assessment_rubrics, pertinent_contemporary_issues
        FROM curriculum_substrands
        """
    ) or []

    for row in rows:
        payload = {k: v for k, v in row.items() if k not in ("id", "grade", "subject")}
        reason = hygiene.inspect(str(row.get("strand_name") or ""), payload)
        if not reason:
            continue

        result.rows_affected += 1
        result.detail.append({
            "grade": row.get("grade"), "subject": row.get("subject"),
            "strand_name": row.get("strand_name"),
            "sub_strand_name": row.get("sub_strand_name"),
            "reason": reason,
        })
        if not dry_run:
            execute("DELETE FROM curriculum_substrands WHERE id = :id", {"id": row["id"]})

    return result


def _denumber_names(dry_run: bool) -> RepairResult:
    """Store one name per strand, with the numbering left in the id column.

    The design numbers some entries and not others ("4.1 Love for God" beside
    "A House of God"), and the row's unique key is the NAME — so one strand
    became two and the same sub-strand was savable twice.
    """
    from ..infra.db import execute, fetch_all

    result = RepairResult("002_denumber_strand_names", dry_run=dry_run)
    rows = fetch_all(
        "SELECT id, grade, subject, strand_name, sub_strand_name FROM curriculum_substrands"
    ) or []

    for row in rows:
        strand = str(row.get("strand_name") or "")
        sub = str(row.get("sub_strand_name") or "")
        clean_strand = hygiene.strip_numbering(strand)
        clean_sub = hygiene.strip_numbering(sub)
        if clean_strand == strand and clean_sub == sub:
            continue

        result.rows_affected += 1
        result.detail.append({
            "grade": row.get("grade"), "subject": row.get("subject"),
            "from": f"{strand} / {sub}", "to": f"{clean_strand} / {clean_sub}",
        })
        if dry_run:
            continue
        try:
            execute(
                "UPDATE curriculum_substrands SET strand_name = :strand, "
                "sub_strand_name = :sub, updated_at = NOW() WHERE id = :id",
                {"strand": clean_strand, "sub": clean_sub, "id": row["id"]},
            )
        except Exception as exc:  # noqa: BLE001
            # The de-numbered name may already exist — that IS the duplicate
            # this repair is here to collapse. Drop the numbered copy.
            logger.info("Collapsing duplicate '%s / %s': %s", strand, sub, exc)
            execute("DELETE FROM curriculum_substrands WHERE id = :id", {"id": row["id"]})

    return result


def _drop_documentless_designs(dry_run: bool) -> RepairResult:
    """Remove design rows minted by a save, which hold no document.

    Saving sub-strands used to upsert a parent row like "cd_grade-pp1_chri". It
    carried no document and was newer than the real design, so it won every
    "ORDER BY updated_at DESC LIMIT 1" lookup and quietly ungrounded the next
    generation. Rows with sub-strands attached are left alone.
    """
    from ..infra.db import execute, fetch_all

    result = RepairResult("003_drop_documentless_designs", dry_run=dry_run)
    rows = fetch_all(
        """
        SELECT d.design_id, d.grade, d.subject
        FROM curriculum_designs d
        WHERE COALESCE(d.raw_payload->>'source_text', d.raw_payload->>'raw_text',
                       d.raw_payload->>'text', d.raw_payload->>'output', '') = ''
          AND NOT EXISTS (
              SELECT 1 FROM curriculum_substrands s WHERE s.design_id = d.design_id
          )
          AND EXISTS (
              SELECT 1 FROM curriculum_designs o
              WHERE o.grade = d.grade AND LOWER(o.subject) = LOWER(d.subject)
                AND o.design_id <> d.design_id
                AND COALESCE(o.raw_payload->>'source_text', o.raw_payload->>'raw_text',
                             o.raw_payload->>'text', o.raw_payload->>'output', '') <> ''
          )
        """
    ) or []

    for row in rows:
        result.rows_affected += 1
        result.detail.append({
            "design_id": row.get("design_id"), "grade": row.get("grade"),
            "subject": row.get("subject"),
            "reason": "holds no document while a real design exists for the same subject",
        })
        if not dry_run:
            execute("DELETE FROM curriculum_designs WHERE design_id = :id",
                    {"id": row["design_id"]})

    return result


# Order matters: debris first, then names, then the orphan designs those left.
REPAIRS: list[tuple[str, Callable[[bool], RepairResult]]] = [
    ("001_purge_substrand_debris", _purge_debris),
    ("002_denumber_strand_names", _denumber_names),
    ("003_drop_documentless_designs", _drop_documentless_designs),
]


def _record(result: RepairResult) -> None:
    from ..infra.db import execute, to_json

    try:
        execute(
            """
            INSERT INTO data_repairs (
                repair_id, runs, rows_affected_total, rows_affected_last,
                last_detail, first_run_at, last_run_at
            )
            VALUES (:id, 1, :rows, :rows, CAST(:detail AS jsonb), NOW(), NOW())
            ON CONFLICT (repair_id) DO UPDATE SET
                runs = data_repairs.runs + 1,
                rows_affected_total = data_repairs.rows_affected_total + EXCLUDED.rows_affected_last,
                rows_affected_last = EXCLUDED.rows_affected_last,
                last_detail = EXCLUDED.last_detail,
                last_run_at = NOW()
            """,
            {"id": result.repair_id, "rows": result.rows_affected,
             "detail": to_json(result.detail[:50])},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record repair '%s': %s", result.repair_id, exc)


def run_repairs(dry_run: bool = False, only: str = "") -> dict[str, Any]:
    """Sweep every repair. Safe on every boot: a clean database is a no-op."""
    results: list[RepairResult] = []

    for repair_id, run in REPAIRS:
        if only and only != repair_id:
            continue
        try:
            result = run(dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Repair '%s' failed: %s", repair_id, exc)
            result = RepairResult(repair_id, error=str(exc)[:300], dry_run=dry_run)

        results.append(result)
        if result.rows_affected:
            logger.warning(
                "Repair %s %s %d row(s).", repair_id,
                "would touch" if dry_run else "fixed", result.rows_affected,
            )
        if not dry_run and not result.error:
            _record(result)

    total = sum(r.rows_affected for r in results)
    return {
        "status": "ok" if not any(r.error for r in results) else "partial",
        "dry_run": dry_run,
        "rows_affected": total,
        "clean": total == 0,
        "repairs": [r.to_dict() for r in results],
    }

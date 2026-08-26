"""Track each grade dataset item from arrival to ingested design.

The dataset is where a grade's production starts, so "what is in the dataset and
how far has it got" is the question the console has to answer. Langfuse knows
what was uploaded; it does not know what this system has done with it. This
module holds that second half and joins the two.

Status moves in one direction:

    pending -> selected -> processing -> ingested
                              |
                              +-------> failed  (retryable: back to pending)

``pending`` means present in the grade's Langfuse dataset and not yet worked on.
Ingestion is manual for now — nothing advances an item except an explicit call.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..infra.db import execute, fetch_all, fetch_one
from .grade_order import normalize_grade
from .langfuse_context import langfuse_context_service

logger = logging.getLogger("cbc-dataset-ingest")

PENDING = "pending"
SELECTED = "selected"
PROCESSING = "processing"
INGESTED = "ingested"
FAILED = "failed"

STATUSES = (PENDING, SELECTED, PROCESSING, INGESTED, FAILED)

# Terminal for display purposes; failed items can be retried back to pending.
ACTIVE_STATUSES = (SELECTED, PROCESSING)

# Below this a dataset item cannot be a curriculum design. A real design runs to
# tens of thousands of characters; the shortest in the corpus is over 50,000.
MIN_DOCUMENT_CHARS = 500


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _item_fields(item: dict[str, Any]) -> dict[str, str]:
    """Pull the identifying fields out of a Langfuse dataset item."""
    inp = item.get("input") if isinstance(item.get("input"), dict) else {}
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "file_id": _text(inp.get("file_id") or meta.get("file_id")),
        "title": _text(inp.get("title") or meta.get("name")),
        "declared_subject": _text(inp.get("subject") or meta.get("subject")),
    }


# ── Finding a grade's documents wherever they actually live ──────────────────
# Curriculum designs are not necessarily filed one dataset per grade. The
# extractor originally wrote every document into one combined dataset, and
# requiring a re-upload before anything works is a worse answer than reading
# what is there and routing by each item's own grade.

_GRADE_IN_TEXT = re.compile(r"\bgrade\s*(\d{1,2})\b", re.IGNORECASE)

# "Grade 1-3", "Grades 1 to 3" — a single document covering a span of grades.
# Checked before the single-grade pattern, which would otherwise read
# "Grade 1-3 CRE" as Grade 1 and leave Grades 2 and 3 with nothing.
_GRADE_RANGE = re.compile(
    r"\bgrades?\s*(\d{1,2})\s*(?:-|–|—|to)\s*(\d{1,2})\b", re.IGNORECASE
)

_LEVEL_TO_GRADES: dict[str, list[str]] = {
    "pre-primary 1 (pp1)": ["grade-pp1"], "pre-primary 1": ["grade-pp1"],
    "pre-primary 2 (pp2)": ["grade-pp2"], "pre-primary 2": ["grade-pp2"],
    # One combined design covers Grades 1-3, so it belongs to each of them.
    "lower primary (grades 1-3)": ["grade-1", "grade-2", "grade-3"],
    "lower primary": ["grade-1", "grade-2", "grade-3"],
    "diploma in teacher education": ["grade-dte"],
}
for _n in range(1, 13):
    _LEVEL_TO_GRADES[f"grade {_n}"] = [f"grade-{_n}"]


def grades_for_item(item: dict[str, Any]) -> list[str]:
    """Which grade(s) a dataset item belongs to, from the item itself."""
    inp = item.get("input") if isinstance(item.get("input"), dict) else {}
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}

    # A flattened raw-datasets row carries these at the top level.
    def field(name: str) -> str:
        return _text(inp.get(name) or meta.get(name) or item.get(name))

    explicit = normalize_grade(field("grade"))
    if explicit:
        return [explicit]

    level = field("level").lower()
    if level in _LEVEL_TO_GRADES:
        return list(_LEVEL_TO_GRADES[level])

    for source in (level, field("title"), field("name")):
        span = _GRADE_RANGE.search(source)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            if 1 <= low <= high <= 12:
                return [f"grade-{n}" for n in range(low, high + 1)]

        match = _GRADE_IN_TEXT.search(source)
        if match and 1 <= int(match.group(1)) <= 12:
            return [f"grade-{int(match.group(1))}"]

    haystack = f"{level} {field('title')}".lower()
    if "diploma" in haystack or haystack.strip().startswith("dte"):
        return ["grade-dte"]
    if re.search(r"\bpp\s*2\b|pre-?primary\s*2", haystack):
        return ["grade-pp2"]
    if re.search(r"\bpp\s*1\b|pre-?primary", haystack):
        return ["grade-pp1"]

    return []


def candidate_items(grade_slug: str) -> list[dict[str, Any]]:
    """Every document that belongs to this grade, from any dataset.

    Reads the grade's own dataset first, then sweeps the rest and keeps whatever
    resolves to this grade. An item found in both is returned once.
    """
    found: dict[str, dict[str, Any]] = {}

    # Placeholders are passed through, not filtered here: sync_grade owns the
    # decision to skip them and the count it reports.
    for item in langfuse_context_service.get_grade_dataset(grade_slug):
        item_id = _text(item.get("id"))
        if item_id:
            found[item_id] = item

    try:
        raw = langfuse_context_service.fetch_raw_datasets_from_langfuse()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not sweep other Langfuse datasets: %s", exc)
        raw = []

    for row in raw:
        if grade_slug not in grades_for_item(row):
            continue
        item_id = _text(row.get("item_id") or row.get("id"))
        if not item_id or item_id in found:
            continue
        # raw-datasets flattens input onto the row; rebuild the item shape.
        found[item_id] = {
            "id": item_id,
            "input": {
                "file_id": _text(row.get("file_id")),
                "title": _text(row.get("title")),
                "subject": _text(row.get("subject")),
                "level": _text(row.get("level")),
            },
            "expected_output": row.get("output") or "",
            "metadata": row.get("metadata") or {},
            "source_dataset": _text(row.get("dataset_name")),
        }

    return list(found.values())


def sync_grade(grade_slug: str) -> dict[str, int]:
    """Register any dataset item not seen before as ``pending``.

    Existing rows are left alone: re-syncing must never reset an item that has
    already been ingested, or a refresh would silently queue duplicate work.
    """
    # Not just this grade's own dataset: documents may sit anywhere, and
    # candidate_items routes each one by the grade it declares.
    items = candidate_items(grade_slug)
    skipped_placeholder = 0

    # execute() returns nothing, so "was this row new?" is answered before the
    # insert rather than inferred from a rowcount that is never there.
    known = {
        r["item_id"]
        for r in fetch_all(
            "SELECT item_id FROM dataset_ingest_status WHERE grade = :grade",
            {"grade": grade_slug},
        )
    }
    added = 0

    skipped_empty = 0

    for item in items:
        if item.get("is_placeholder"):
            skipped_placeholder += 1
            continue

        # An item with no document text is not curriculum waiting to be
        # ingested — it is a result record or a stray write. Queueing it would
        # put a row on screen that can only ever fail.
        text = _text(item.get("expected_output") or item.get("expectedOutput"))
        if len(text) < MIN_DOCUMENT_CHARS:
            skipped_empty += 1
            continue

        source_id = _text(item.get("id"))
        if not source_id:
            continue

        # Scoped by grade so the one Lower Primary design can be tracked and
        # processed independently under Grades 1, 2 and 3.
        tracking_id = f"{grade_slug}__{source_id}"
        if tracking_id in known:
            continue

        execute(
            """
            INSERT INTO dataset_ingest_status (
                item_id, source_item_id, grade, file_id, title, declared_subject, status
            )
            VALUES (
                :item_id, :source_item_id, :grade, :file_id, :title, :declared_subject, 'pending'
            )
            ON CONFLICT (item_id) DO NOTHING
            """,
            {
                "item_id": tracking_id,
                "source_item_id": source_id,
                "grade": grade_slug,
                **_item_fields(item),
            },
        )
        known.add(tracking_id)
        added += 1

    if skipped_placeholder:
        logger.info(
            "Skipped %d placeholder item(s) for %s; these are development stand-ins, not curriculum.",
            skipped_placeholder, grade_slug,
        )

    if skipped_empty:
        logger.info(
            "Skipped %d item(s) in '%s' with no document text; they are not curriculum designs.",
            skipped_empty, grade_slug,
        )

    return {
        "seen": len(items),
        "added": added,
        "placeholders": skipped_placeholder,
        "skipped_empty": skipped_empty,
    }


def set_status(item_id: str, status: str, **fields: Any) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status '{status}'")

    stamps = {
        SELECTED: "selected_at",
        PROCESSING: "started_at",
        INGESTED: "finished_at",
        FAILED: "finished_at",
    }
    sets = ["status = :status", "updated_at = NOW()"]
    params: dict[str, Any] = {"item_id": item_id, "status": status}

    if status in stamps:
        sets.append(f"{stamps[status]} = NOW()")

    for key in ("error", "resolved_subject", "design_id", "char_count"):
        if key in fields:
            sets.append(f"{key} = :{key}")
            params[key] = fields[key]

    # Clearing an error on the way back to pending keeps a retried item from
    # displaying a stale failure reason.
    if status == PENDING and "error" not in fields:
        sets.append("error = ''")

    execute(
        f"UPDATE dataset_ingest_status SET {', '.join(sets)} WHERE item_id = :item_id",
        params,
    )


def list_grade(grade_slug: str) -> dict[str, Any]:
    rows = fetch_all(
        """
        SELECT item_id, grade, file_id, title, declared_subject, resolved_subject,
               design_id, status, char_count, error, selected_at, started_at,
               finished_at, updated_at
        FROM dataset_ingest_status
        WHERE grade = :grade
        ORDER BY
            CASE status WHEN 'failed' THEN 0 WHEN 'processing' THEN 1
                        WHEN 'selected' THEN 2 WHEN 'pending' THEN 3 ELSE 4 END,
            COALESCE(NULLIF(resolved_subject, ''), declared_subject, title)
        """,
        {"grade": grade_slug},
    )

    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1

    total = len(rows)
    return {
        "grade": grade_slug,
        "items": rows,
        "counts": counts,
        "total": total,
        "ingested_percentage": round(counts[INGESTED] / total * 100, 1) if total else 0.0,
        "in_progress": counts[SELECTED] + counts[PROCESSING],
    }


def grade_summaries() -> dict[str, dict[str, Any]]:
    """Per-grade production totals, for the grade picker and the overview."""
    rows = fetch_all(
        """
        SELECT grade, status, COUNT(*) AS n
        FROM dataset_ingest_status
        GROUP BY grade, status
        """
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = out.setdefault(
            row["grade"], {"total": 0, **{status: 0 for status in STATUSES}}
        )
        count = int(row["n"] or 0)
        bucket[row["status"]] = count
        bucket["total"] += count

    for bucket in out.values():
        total = bucket["total"]
        bucket["ingested_percentage"] = round(bucket[INGESTED] / total * 100, 1) if total else 0.0
        bucket["in_progress"] = bucket[SELECTED] + bucket[PROCESSING]
    return out


class AlreadyIngested(RuntimeError):
    """The item has been ingested already and ``force`` was not given."""


def _discard_previous_design(design_id: str, item_id: str) -> None:
    """Remove what a previous run of this item produced.

    Sub-strands cascade from the design, so deleting the design is enough to
    leave no orphans. The design is only removed if this item is the sole
    tracked source for it — two dataset items resolving to the same design
    (the Lower Primary design filed under Grades 1-3) must not delete each
    other's work.
    """
    others = fetch_all(
        """
        SELECT item_id FROM dataset_ingest_status
        WHERE design_id = :design_id AND item_id <> :item_id AND status = 'ingested'
        """,
        {"design_id": design_id, "item_id": item_id},
    )
    if others:
        logger.info(
            "Design %s is also claimed by %d other ingested item(s); rewriting in place "
            "rather than deleting.", design_id, len(others),
        )
        return

    execute("DELETE FROM curriculum_designs WHERE design_id = :design_id", {"design_id": design_id})
    logger.info("Discarded design %s before re-ingesting %s.", design_id, item_id)


def process_item(item_id: str, force: bool = False) -> dict[str, Any]:
    """Run one dataset item through curriculum extraction.

    Manual by design for now: the caller decides what gets processed and when,
    so a bad extraction cannot quietly propagate across a whole grade.

    Processing the same item twice is refused rather than silently repeated.
    With ``force``, the design this item produced last time is replaced in
    place: the same deterministic design_id is rewritten and sub-strands it no
    longer contains are deleted, so a second run leaves one clean design rather
    than a merge of two.
    """
    from .curriculum_extractor import curriculum_extractor

    row = fetch_one(
        "SELECT * FROM dataset_ingest_status WHERE item_id = :item_id",
        {"item_id": item_id},
    )
    if not row:
        raise LookupError(f"no dataset item tracked with id '{item_id}'")
    if row["status"] == PROCESSING:
        raise RuntimeError(f"item '{item_id}' is already being processed")
    if row["status"] == INGESTED and not force:
        raise AlreadyIngested(
            f"'{row.get('resolved_subject') or row.get('title') or item_id}' has already been "
            f"ingested as design {row.get('design_id')}. Re-run with force to replace it."
        )

    # Rows written before tracking became grade-scoped have no source_item_id.
    source_id = _text(row.get("source_item_id")) or item_id

    items = candidate_items(row["grade"])
    source = next((i for i in items if _text(i.get("id")) == source_id), None)
    if source is None:
        set_status(item_id, FAILED, error="Item is no longer in the Langfuse dataset")
        raise LookupError(f"document '{source_id}' is no longer available for '{row['grade']}'")

    if force and row.get("design_id"):
        _discard_previous_design(str(row["design_id"]), item_id)

    set_status(item_id, PROCESSING)

    payload: dict[str, Any] = dict(source.get("input") or {})
    payload["output"] = source.get("expected_output") or ""
    payload.setdefault("file_id", row["file_id"])
    payload.setdefault("grade", row["grade"])

    try:
        result = curriculum_extractor.ingest_raw_curriculum(payload)
    except Exception as exc:  # noqa: BLE001
        set_status(item_id, FAILED, error=str(exc)[:500])
        logger.warning("Ingest failed for %s: %s", item_id, exc)
        raise

    set_status(
        item_id,
        INGESTED,
        resolved_subject=_text(result.get("subject")),
        design_id=_text(result.get("design_id")),
        char_count=len(payload["output"]),
        error="",
    )
    return result


def find_tracked_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Locate the tracked row a raw ingest payload belongs to.

    Ingestion can be triggered outside :func:`process_item` — the legacy console
    posts straight to /curriculum/ingest-raw. Matching the payload back to its
    tracked row is what keeps one source of truth about what has been processed,
    rather than two screens each believing something different.
    """
    item_id = _text(payload.get("item_id") or payload.get("id"))
    if item_id:
        row = fetch_one(
            "SELECT * FROM dataset_ingest_status WHERE item_id = :item_id",
            {"item_id": item_id},
        )
        if row:
            return row

    file_id = _text(payload.get("file_id"))
    if not file_id:
        return None

    # One document can be tracked under several grades (Lower Primary), so an
    # unqualified file_id is only conclusive when it matches exactly one row.
    rows = fetch_all(
        "SELECT * FROM dataset_ingest_status WHERE file_id = :file_id",
        {"file_id": file_id},
    )
    return rows[0] if len(rows) == 1 else None


def record_external_ingest(payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    """Mark a tracked item ingested after it was processed elsewhere."""
    row = find_tracked_item(payload)
    if not row:
        return None

    set_status(
        row["item_id"],
        INGESTED,
        resolved_subject=_text(result.get("subject")),
        design_id=_text(result.get("design_id")),
        char_count=len(_text(payload.get("output"))),
        error="",
    )
    return row["item_id"]

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

import json
import logging
import re
from typing import Any

from ..errors import ApiError
from ..infra.db import execute, fetch_all, fetch_one, to_json
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
            "SELECT item_id FROM dataset_ingest_status WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')",
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

    for key in ("design_ids", "learning_areas_missing"):
        if key in fields:
            sets.append(f"{key} = CAST(:{key} AS jsonb)")
            params[key] = to_json(list(fields[key] or []))

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
        WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')
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


def _other_claimants(design_id: str, item_id: str) -> list[dict[str, Any]]:
    """Other ingested items that still point at this design.

    A design claimed by another item must never be deleted — the Lower Primary
    design is filed under Grades 1-3, and one grade un-ingesting must not wipe
    the others. Checked against both the primary design_id and the full set an
    item produced, since a combined design yields several.
    """
    return fetch_all(
        """
        SELECT item_id FROM dataset_ingest_status
        WHERE (design_id = :design_id OR design_ids::text LIKE :contains)
          AND item_id <> :item_id AND status = 'ingested'
        """,
        {"design_id": design_id, "contains": f'%"{design_id}"%', "item_id": item_id},
    )


def _previous_design_ids(row: dict[str, Any]) -> list[str]:
    """Every design a previous run of this item produced.

    One Pre-Primary document yields seven designs, one per learning area, but
    tracking recorded only the first. Re-processing on that basis deleted one
    design and left six orphaned, then wrote seven more on top of them.
    """
    stored = row.get("design_ids") or []
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            stored = []
    ids = [_text(d) for d in stored if _text(d)]

    primary = _text(row.get("design_id"))
    if primary and primary not in ids:
        ids.append(primary)
    return ids


def _discard_previous_design(design_id: str, item_id: str) -> None:
    """Remove what a previous run of this item produced.

    Sub-strands cascade from the design, so deleting the design is enough to
    leave no orphans. The design is only removed if this item is the sole
    tracked source for it — two dataset items resolving to the same design
    (the Lower Primary design filed under Grades 1-3) must not delete each
    other's work.
    """
    others = _other_claimants(design_id, item_id)
    if others:
        logger.info(
            "Design %s is also claimed by %d other ingested item(s); rewriting in place "
            "rather than deleting.", design_id, len(others),
        )
        return

    execute("DELETE FROM curriculum_designs WHERE design_id = :design_id", {"design_id": design_id})
    logger.info("Discarded design %s before re-ingesting %s.", design_id, item_id)


def _discard_previous_designs(row: dict[str, Any], item_id: str) -> int:
    """Discard all of them, so a forced re-run leaves one clean set."""
    ids = _previous_design_ids(row)
    for design_id in ids:
        _discard_previous_design(design_id, item_id)
    if len(ids) > 1:
        logger.info(
            "Discarded %d design(s) from the previous run of %s before re-ingesting.",
            len(ids), item_id,
        )
    return len(ids)


def _record_outcome(
    item_id: str,
    result: dict[str, Any],
    payload: dict[str, Any],
    *,
    status: str,
    error: str,
) -> None:
    """Write what an ingest produced, complete or not.

    A combined design produces one row per learning area. Recording only the
    first meant a later forced re-run orphaned the rest, and the console
    reported the whole document as ingested under one area's name.
    """
    areas = result.get("learning_areas") or []
    design_ids = [
        _text(a.get("design_id")) for a in areas
        if _text(a.get("design_id")) and a.get("status") == "success"
    ] or [_text(result.get("design_id"))]
    design_ids = [d for d in design_ids if d]

    missing = list(result.get("learning_areas_missing") or [])
    subject = _text(result.get("subject"))
    if len(areas) > 1:
        ingested = [_text(a.get("subject")) for a in areas if a.get("status") == "success"]
        subject = ", ".join(s for s in ingested if s) or subject

    set_status(
        item_id,
        FAILED if missing else status,
        resolved_subject=subject,
        design_id=_text(result.get("design_id")),
        design_ids=design_ids,
        learning_areas_missing=missing,
        char_count=len(payload.get("output") or ""),
        error=error,
    )


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

    if force:
        _discard_previous_designs(row, item_id)

    set_status(item_id, PROCESSING)

    payload: dict[str, Any] = dict(source.get("input") or {})
    payload["output"] = source.get("expected_output") or ""
    payload.setdefault("file_id", row["file_id"])
    payload.setdefault("grade", row["grade"])

    try:
        result = curriculum_extractor.ingest_raw_curriculum(payload)
    except ApiError as exc:
        # A partial ingest still saved several learning areas. Recording only
        # "failed" would lose track of them, and a later forced re-run would
        # then orphan the designs it could no longer see.
        if exc.code == "PARTIAL_INGEST" and isinstance(exc.detail, dict):
            _record_outcome(item_id, exc.detail, payload, status=FAILED,
                            error=exc.message[:500])
            logger.error("Partial ingest for %s: %s", item_id, exc.message)
        else:
            set_status(item_id, FAILED, error=exc.message[:500])
            logger.warning("Ingest failed for %s: %s", item_id, exc.message)
        raise
    except Exception as exc:  # noqa: BLE001
        set_status(item_id, FAILED, error=str(exc)[:500])
        logger.warning("Ingest failed for %s: %s", item_id, exc)
        raise

    _record_outcome(item_id, result, payload, status=INGESTED, error="")
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


def uningest_item(item_id: str, purge_generated: bool = False) -> dict[str, Any]:
    """Undo an ingest: remove the design it produced and return it to pending.

    ``purge_generated`` also deletes the notes, diagrams, activities and
    questions produced from that design's sub-strands. Off by default because
    that is real token spend — but a design re-parsed under a different subject
    leaves its old generated content orphaned under a name nothing references,
    so there are times you want it gone.
    """
    row = fetch_one(
        "SELECT * FROM dataset_ingest_status WHERE item_id = :item_id",
        {"item_id": item_id},
    )
    if not row:
        raise LookupError(f"no dataset item tracked with id '{item_id}'")

    # A combined design produced one row per learning area. Un-ingesting only
    # the primary left the other six behind, so the console reported the item as
    # pending while six learning areas' sub-strands were still in the database.
    design_ids = _previous_design_ids(row)
    design_id = _text(row.get("design_id")) or (design_ids[0] if design_ids else "")
    grade = _text(row.get("grade"))
    subject = _text(row.get("resolved_subject"))
    removed = {"design": 0, "substrands": 0, "bundles": 0, "questions": 0}


    if design_ids:
        # Count before deleting so the caller can be told what actually went.
        for one in design_ids:
            rows = fetch_all(
                "SELECT COUNT(*) AS n FROM curriculum_substrands WHERE design_id = :design_id",
                {"design_id": one},
            )
            removed["substrands"] += int((rows[0] if rows else {}).get("n") or 0)

        if purge_generated and grade and subject:
            for table, column, key in (
                ("substrand_resources", "curriculum", "bundles"),
                ("question_dna", "curriculum_link", "questions"),
            ):
                counted = fetch_all(
                    f"""
                    SELECT COUNT(*) AS n FROM {table}
                    WHERE LOWER({column}->>'grade') = LOWER(:grade)
                      AND LOWER({column}->>'subject') = LOWER(:subject)
                    """,
                    {"grade": grade, "subject": subject},
                )
                removed[key] = int((counted[0] if counted else {}).get("n") or 0)
                execute(
                    f"""
                    DELETE FROM {table}
                    WHERE LOWER({column}->>'grade') = LOWER(:grade)
                      AND LOWER({column}->>'subject') = LOWER(:subject)
                    """,
                    {"grade": grade, "subject": subject},
                )

        # Only designs no other ingested grade still points at.
        for one in design_ids:
            others = _other_claimants(one, item_id)
            if others:
                logger.info(
                    "Design %s is still claimed by %d other ingested item(s); left in place.",
                    one, len(others),
                )
                continue
            execute(
                "DELETE FROM curriculum_designs WHERE design_id = :design_id",
                {"design_id": one},
            )
            removed["design"] += 1

        if removed["design"] == 0:
            removed["substrands"] = 0

    execute(
        """
        UPDATE dataset_ingest_status
        SET status = 'pending', design_id = NULL,
            design_ids = '[]'::jsonb, learning_areas_missing = '[]'::jsonb,
            resolved_subject = '',
            char_count = 0, error = '', selected_at = NULL, started_at = NULL,
            finished_at = NULL, updated_at = NOW()
        WHERE item_id = :item_id
        """,
        {"item_id": item_id},
    )

    logger.info("Un-ingested %s (design %s): %s", item_id, design_id or "none", removed)
    return {"item_id": item_id, "design_id": design_id, "removed": removed}


def attach_source_document(
    design_id: str = "", grade: str = "", subject: str = ""
) -> dict[str, Any]:
    """Backfill a design's source text from the dataset item it came from.

    Designs ingested before the text was stored carry only a character count, so
    every agent that asks for the source finds nothing and generates from its own
    knowledge instead. The document is still in Langfuse — this puts it back on
    the design without re-running extraction, which would overwrite sub-strands
    that may already have been reviewed.
    """
    if design_id:
        design = fetch_one(
            "SELECT design_id, grade, subject, metadata, raw_payload FROM curriculum_designs WHERE design_id = :d",
            {"d": design_id},
        )
    else:
        design = fetch_one(
            """
            SELECT design_id, grade, subject, metadata, raw_payload
            FROM curriculum_designs
            WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"grade": grade, "alt": grade.replace("grade-", ""), "subject": subject},
        )

    if not design:
        raise LookupError(
            f"No ingested design for {subject or design_id} in {grade or 'any grade'}."
        )

    raw_payload = dict(design.get("raw_payload") or {})
    if len(_text(raw_payload.get("source_text"))) > MIN_DOCUMENT_CHARS:
        return {
            "design_id": design["design_id"], "attached": False,
            "chars": len(raw_payload["source_text"]),
            "note": "The design already carries its source text.",
        }

    design_grade = _text(design.get("grade")) or grade
    file_id = _text((design.get("metadata") or {}).get("file_id"))

    # Prefer the item this design was actually ingested from.
    tracked = fetch_one(
        "SELECT source_item_id, item_id, file_id FROM dataset_ingest_status WHERE design_id = :d LIMIT 1",
        {"d": design["design_id"]},
    )
    wanted_ids = {_text(tracked.get("source_item_id")) if tracked else "",
                  _text(tracked.get("item_id")) if tracked else ""} - {""}
    wanted_file = _text(tracked.get("file_id")) if tracked else file_id

    text = ""
    for item in candidate_items(design_grade):
        item_id = _text(item.get("id"))
        item_file = _text((item.get("input") or {}).get("file_id"))
        if (wanted_ids and item_id in wanted_ids) or (wanted_file and item_file == wanted_file):
            text = _text(item.get("expected_output") or item.get("expectedOutput"))
            if text:
                break

    if not text:
        raise LookupError(
            f"Could not find the document for '{design.get('subject')}' in the {design_grade} dataset. "
            f"Sync the grade on the Datasets screen first."
        )

    raw_payload["source_text"] = text[:400_000]
    raw_payload["source_attached_from"] = wanted_file or list(wanted_ids)[0] if (wanted_file or wanted_ids) else ""
    execute(
        "UPDATE curriculum_designs SET raw_payload = CAST(:p AS jsonb), updated_at = NOW() WHERE design_id = :d",
        {"p": to_json(raw_payload), "d": design["design_id"]},
    )
    logger.info("Attached %d chars of source text to design %s.", len(text), design["design_id"])
    return {
        "design_id": design["design_id"], "attached": True, "chars": len(text),
        "subject": design.get("subject"), "grade": design_grade,
    }

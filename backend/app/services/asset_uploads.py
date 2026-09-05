"""Files a person supplies for a figure the plan asked for.

The pipeline plans every picture, clip and simulation a lesson needs, writes a
brief for each, and keeps a place on the page for it. What it could not do was
accept the thing itself. Diagrams live behind the diagram station; photos and
video behind the media registry; and neither takes a file for a figure that was
merely PLANNED — the media upload requires a media row that a station created
first.

So a teacher with the right photograph, or a video nobody can generate, had
nowhere to put it and the plate stayed hatched.

This is that place. It is deliberately one table for all five kinds: an
uploaded diagram and an uploaded video differ in their content type and in
nothing else that matters here, and the renderer asks one question — is there
a file for this requirement?
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger("cbc-asset-uploads")

# What each kind of plate will accept. A video in a slot kept for a diagram is
# not a near miss — the page reserves a printed rectangle for one and a cue for
# the other.
ACCEPTS: dict[str, tuple[str, ...]] = {
    "diagram": ("image/svg+xml", "image/png", "image/jpeg", "image/webp"),
    "image": ("image/png", "image/jpeg", "image/webp", "image/avif", "image/gif"),
    "video": ("video/mp4", "video/webm", "video/quicktime"),
    "audio": ("audio/mpeg", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-wav"),
    "simulation": ("text/html", "image/svg+xml", "application/zip"),
}

# What this system can produce for itself, and what it can only receive.
#
# Video is the honest one: nothing here generates footage, and a station that
# offered a "generate" button for it would be offering to fail. The brief is
# the deliverable, and somebody films it.
GENERATES: frozenset[str] = frozenset({"diagram", "simulation"})

MAX_BYTES = 25 * 1024 * 1024


def can_generate(kind: str) -> bool:
    return kind in GENERATES


def asset_id_for(grade: str, subject: str, sub_strand: str, kind: str,
                 what: str) -> str:
    seed = f"{grade}|{subject}|{sub_strand}|{kind}|{what}".lower()
    return f"ast_{hashlib.sha256(seed.encode()).hexdigest()[:20]}"


def record(*, grade: str, subject: str, strand: str, sub_strand: str, kind: str,
           what: str, storage_url: str = "", svg: str = "", title: str = "",
           alt_text: str = "", content_type: str = "", size: int = 0,
           source: str = "upload", uploaded_by: str = "") -> dict[str, Any]:
    """File one asset against the requirement it answers.

    Keyed on the requirement, so uploading a second file for the same figure
    REPLACES the first rather than leaving the page to choose between them.
    """
    from ..infra.db import execute

    asset_id = asset_id_for(grade, subject, sub_strand, kind, what)
    execute(
        """
        INSERT INTO uploaded_assets (
            asset_id, grade, subject, strand, sub_strand, kind, what, title,
            alt_text, storage_url, svg, content_type, bytes, source, uploaded_by
        ) VALUES (
            :id, :grade, :subject, :strand, :sub_strand, :kind, :what, :title,
            :alt, :url, :svg, :ct, :bytes, :source, :by
        )
        ON CONFLICT (asset_id) DO UPDATE SET
            storage_url = EXCLUDED.storage_url,
            svg = EXCLUDED.svg,
            content_type = EXCLUDED.content_type,
            bytes = EXCLUDED.bytes,
            title = EXCLUDED.title,
            alt_text = EXCLUDED.alt_text,
            source = EXCLUDED.source,
            uploaded_by = EXCLUDED.uploaded_by,
            created_at = NOW()
        """,
        {"id": asset_id, "grade": grade, "subject": subject, "strand": strand,
         "sub_strand": sub_strand, "kind": kind, "what": what,
         "title": title or what[:120], "alt": alt_text or what[:200],
         "url": storage_url, "svg": svg, "ct": content_type, "bytes": size,
         "source": source, "by": uploaded_by},
    )
    return {"asset_id": asset_id, "kind": kind, "what": what,
            "storage_url": storage_url, "source": source}


def list_for(grade: str, subject: str, sub_strand: str = "") -> list[dict[str, Any]]:
    """Everything supplied for this sub-strand, in the renderer's shape."""
    from ..infra.db import fetch_all
    from .grade_sql import clause

    conditions = [clause("grade", "grade"), "LOWER(subject) = LOWER(:subject)"]
    params: dict[str, Any] = {"grade": grade, "subject": subject}
    if sub_strand:
        conditions.append("LOWER(sub_strand) = LOWER(:sub_strand)")
        params["sub_strand"] = sub_strand

    try:
        rows = fetch_all(
            f"""
            SELECT asset_id, kind, what, title, alt_text, storage_url, svg,
                   content_type, source, created_at
            FROM uploaded_assets
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            """,
            params,
        ) or []
    except Exception as exc:  # noqa: BLE001
        # A page that renders with placeholders beats a page that will not
        # render at all.
        logger.warning("Could not read uploaded assets for %s/%s: %s",
                       grade, subject, exc)
        return []
    return rows


def remove(asset_id: str) -> bool:
    """Take the row out, and the stored object with it.

    Removing only the row left the SVG in MinIO for ever: nothing referred to
    it, nothing listed it, and nothing would ever delete it.
    """
    from ..infra.db import execute, fetch_all
    from ..infra.storage import object_storage

    stored = ""
    try:
        rows = fetch_all(
            "SELECT storage_url FROM uploaded_assets WHERE asset_id = :id",
            {"id": asset_id})
        stored = str((rows or [{}])[0].get("storage_url") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read asset %s before removing it: %s",
                       asset_id, exc)

    try:
        execute("DELETE FROM uploaded_assets WHERE asset_id = :id", {"id": asset_id})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not remove asset %s: %s", asset_id, exc)
        return False

    # The row is the record; the object is a copy of it. Failing to delete the
    # copy is worth a log, not a failed delete — the figure is already gone
    # from every page that read it.
    if stored:
        try:
            object_storage.remove_object(object_storage.object_name_of(stored))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Removed %s but left its object behind: %s",
                           asset_id, exc)
    return True


def supersede(grade: str, subject: str, sub_strand: str, title: str, *,
              keep: str) -> list[str]:
    """Delete earlier drawings of the SAME picture, and their stored objects.

    `asset_id` is a hash of the title, so redrawing the same figure replaces
    it. But regenerating a diagram PLAN renames what it plans — "Number Line"
    becomes "Representation of Integers on a Number Line" becomes "Visual
    Representation of Integers on a Number Line" — and each new name filed a
    new row beside the last. One number line printed as three plates, and
    three copies of it sat in the bucket for ever.

    A different picture keeps its own row: "Basic Operations on Integers"
    scores zero against every one of those and is not touched.
    """
    from .lesson_assets import dedupe

    gone: list[str] = []
    try:
        rows = list_for(grade, subject, sub_strand)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not look for older copies of %s: %s", title, exc)
        return gone

    # The same grouping the page uses, with the drawing just filed at the head
    # so it is the survivor. Comparing each row against the new title one pair
    # at a time missed the renamings that are linked only through a third —
    # which is most of them, and the reason four plates appeared.
    candidates = [{"kind": "diagram", "title": title, "asset_id": keep}]
    for row in rows:
        candidates.append({"kind": str(row.get("kind") or ""),
                           "title": str(row.get("title") or row.get("what") or ""),
                           "asset_id": str(row.get("asset_id") or "")})
    survivors = {c["asset_id"] for c in dedupe(candidates)}

    for candidate in candidates[1:]:
        asset_id = candidate["asset_id"]
        if (asset_id and asset_id != keep and asset_id not in survivors
                and candidate["kind"] == "diagram"):
            if remove(asset_id):
                gone.append(asset_id)
    if gone:
        logger.info("Filed %r and replaced %d earlier copy/copies of it",
                    title[:60], len(gone))
    return gone


def file_drawing(*, grade: str, subject: str, strand: str, sub_strand: str,
                 title: str, svg: str, alt_text: str = "",
                 source: str = "drawn", uploaded_by: str = "") -> dict[str, Any]:
    """Store one drawn SVG where the book reads it, and say what happened.

    Drawing filed the SVG here; editing the artifact did not. So an operator
    who fixed a drawing by hand got a new artifact version and a book that
    went on printing the old picture — because this row is what the page
    matches on, and it still held the drawing from before the edit.

    `save_bytes` does not raise when MinIO is unreachable: it logs and returns
    a `local://` URL. The page is fine either way, since the SVG is inlined
    from the row — but the caller is told which happened rather than being
    left to assume the bucket has it.
    """
    from ..infra.storage import object_storage

    asset_id = asset_id_for(grade, subject, sub_strand, "diagram", title)
    storage_url = ""
    try:
        storage_url = object_storage.save_bytes(
            f"assets/{grade}/{subject}/{asset_id}.svg".replace(" ", "-"),
            svg.encode("utf-8"), "image/svg+xml")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not store drawing %s: %s", asset_id, exc)

    record(
        grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
        kind="diagram", what=title, storage_url=storage_url, svg=svg,
        title=title, alt_text=alt_text or title, content_type="image/svg+xml",
        size=len(svg), source=source, uploaded_by=uploaded_by,
    )
    superseded = supersede(grade, subject, sub_strand, title, keep=asset_id)
    return {
        "asset_id": asset_id,
        "storage_url": storage_url,
        "stored_in_minio": bool(storage_url)
                           and not storage_url.startswith("local://"),
        "superseded": superseded,
    }


def refile_diagram_artifact(artifact: Any, *, edited_by: str = "") -> int:
    """Re-file every drawing an edited diagram version carries.

    Editing is how an operator fixes a drawing by hand. Without this the fix
    lands in a new artifact version and the book keeps printing the old one.
    Failures are logged, never raised: an edit that saved must not report
    itself as failed because a bucket was briefly unreachable.
    """
    content = getattr(artifact, "content", None) or {}
    visuals = content.get("visuals") or content.get("diagrams") or []
    filed = 0
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        svg = str(visual.get("diagram_svg") or visual.get("svg") or "").strip()
        title = str(visual.get("diagram_title") or visual.get("title") or "").strip()
        if not (svg and title):
            continue
        try:
            file_drawing(
                grade=getattr(artifact, "grade", ""),
                subject=getattr(artifact, "subject", ""),
                strand=getattr(artifact, "strand_name", ""),
                sub_strand=getattr(artifact, "sub_strand_name", ""),
                title=title, svg=svg,
                alt_text=str((visual.get("accessibility") or {}).get("alt_text") or ""),
                source="edited", uploaded_by=edited_by,
            )
            filed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not re-file %s after an edit: %s", title, exc)
    return filed

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
    from ..infra.db import execute

    try:
        execute("DELETE FROM uploaded_assets WHERE asset_id = :id", {"id": asset_id})
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not remove asset %s: %s", asset_id, exc)
        return False

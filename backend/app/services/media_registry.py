"""Photographs and videos for a sub-strand, planned and stored beside diagrams.

A diagram is SVG — generated as code, deterministic, editable. A photograph and
a video are neither: the factory can author the PROMPT, the shot list, the alt
text and the narration, but the asset itself is produced elsewhere and uploaded
back. Keeping all three in one list means a sub-strand's visual plan is one
thing a reviewer can look at, rather than three places to remember.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-media-registry")

KINDS = ("photo", "video")

# What a browser will actually play or render, by kind.
ALLOWED_CONTENT_TYPES = {
    "photo": ("image/png", "image/jpeg", "image/webp", "image/avif", "image/gif"),
    "video": ("video/mp4", "video/webm", "video/quicktime"),
}

STATUSES = ("planned", "produced", "rejected")


@dataclass(slots=True)
class MediaItem:
    media_id: str = ""
    grade: str = ""
    subject: str = ""
    strand_name: str = ""
    sub_strand_name: str = ""
    kind: str = "photo"
    title: str = ""
    purpose: str = ""
    generation_prompt: str = ""
    negative_prompt: str = ""
    shot_list: list[dict[str, Any]] = field(default_factory=list)
    spec: dict[str, Any] = field(default_factory=dict)
    alt_text: str = ""
    narration: str = ""
    storage_url: str = ""
    content_type: str = ""
    source_pages: list[int] = field(default_factory=list)
    status: str = "planned"
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_id": self.media_id, "grade": self.grade, "subject": self.subject,
            "strand_name": self.strand_name, "sub_strand_name": self.sub_strand_name,
            "kind": self.kind, "title": self.title, "purpose": self.purpose,
            "generation_prompt": self.generation_prompt,
            "negative_prompt": self.negative_prompt, "shot_list": self.shot_list,
            "spec": self.spec, "alt_text": self.alt_text, "narration": self.narration,
            "storage_url": self.storage_url, "content_type": self.content_type,
            "source_pages": self.source_pages, "status": self.status,
            "provenance": self.provenance,
        }


def media_id_for(grade: str, subject: str, sub_strand: str, kind: str, title: str) -> str:
    """Stable across regenerations, so re-planning updates rather than duplicates."""
    seed = f"{grade}|{subject}|{sub_strand}|{kind}|{title}".lower()
    return f"md_{kind}_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def _pages(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for page in value:
        try:
            out.append(int(page))
        except (TypeError, ValueError):
            continue
    return out[:8]


def from_generated(
    entry: dict[str, Any], *, kind: str, grade: str, subject: str,
    strand: str, sub_strand: str, provenance: dict[str, Any] | None = None,
) -> MediaItem | None:
    """One planned asset, or None when the model returned something unusable."""
    if not isinstance(entry, dict):
        return None
    title = str(entry.get("title") or "").strip()
    prompt = str(entry.get("generation_prompt") or "").strip()
    if not title or not prompt:
        # A media item without a prompt is a title nobody can produce from.
        return None

    return MediaItem(
        media_id=media_id_for(grade, subject, sub_strand, kind, title),
        grade=grade, subject=subject, strand_name=strand, sub_strand_name=sub_strand,
        kind=kind, title=title,
        purpose=str(entry.get("purpose") or ""),
        generation_prompt=prompt,
        negative_prompt=str(entry.get("negative_prompt") or ""),
        shot_list=[s for s in (entry.get("shot_list") or []) if isinstance(s, dict)],
        spec=entry.get("spec") if isinstance(entry.get("spec"), dict) else {},
        alt_text=str(entry.get("alt_text") or ""),
        narration=str(entry.get("narration") or ""),
        source_pages=_pages(entry.get("source_pages")),
        status="planned",
        provenance=provenance or {},
    )


def save(item: MediaItem) -> None:
    from ..infra.db import execute, to_json

    execute(
        """
        INSERT INTO substrand_media (
            media_id, grade, subject, strand_name, sub_strand_name, kind, title,
            purpose, generation_prompt, negative_prompt, shot_list, spec,
            alt_text, narration, storage_url, content_type, source_pages,
            status, provenance, updated_at
        )
        VALUES (
            :media_id, :grade, :subject, :strand_name, :sub_strand_name, :kind, :title,
            :purpose, :generation_prompt, :negative_prompt, CAST(:shot_list AS jsonb),
            CAST(:spec AS jsonb), :alt_text, :narration, :storage_url, :content_type,
            CAST(:source_pages AS jsonb), :status, CAST(:provenance AS jsonb), NOW()
        )
        ON CONFLICT (media_id) DO UPDATE SET
            title = EXCLUDED.title,
            purpose = EXCLUDED.purpose,
            generation_prompt = EXCLUDED.generation_prompt,
            negative_prompt = EXCLUDED.negative_prompt,
            shot_list = EXCLUDED.shot_list,
            spec = EXCLUDED.spec,
            alt_text = EXCLUDED.alt_text,
            narration = EXCLUDED.narration,
            source_pages = EXCLUDED.source_pages,
            provenance = EXCLUDED.provenance,
            updated_at = NOW()
        """,
        {
            **item.to_dict(),
            "shot_list": to_json(item.shot_list),
            "spec": to_json(item.spec),
            "source_pages": to_json(item.source_pages),
            "provenance": to_json(item.provenance),
        },
    )


def attach_asset(media_id: str, storage_url: str, content_type: str) -> None:
    """Record the produced file against its plan, without discarding the plan."""
    from ..infra.db import execute

    execute(
        """
        UPDATE substrand_media
           SET storage_url = :url, content_type = :content_type,
               status = 'produced', updated_at = NOW()
         WHERE media_id = :media_id
        """,
        {"media_id": media_id, "url": storage_url, "content_type": content_type},
    )


def list_for(grade: str, subject: str, sub_strand: str = "") -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    sql = """
        SELECT * FROM substrand_media
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
    """
    params: dict[str, Any] = {
        "grade": grade,
        "alt_grade": grade.replace("grade-", "") if grade.startswith("grade-") else f"grade-{grade}",
        "subject": subject,
    }
    if sub_strand:
        sql += " AND LOWER(sub_strand_name) = LOWER(:sub_strand)"
        params["sub_strand"] = sub_strand
    sql += " ORDER BY kind ASC, title ASC"
    return fetch_all(sql, params) or []

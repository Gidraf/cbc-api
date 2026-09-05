"""Everything the other stations made for this sub-strand, for the book.

A guide was rendered from the lesson plan alone. Meanwhile the diagram station
had drawn diagrams, the activity station had written experiments, the media
station had briefed photographs and video, and the questions station had filled
a bank — and none of it appeared on the page a teacher reads. Each station's
output was reachable only from its own panel in the console.

So a teacher printed a guide, and the practical activity KICD funded, which had
been written and reviewed and filed, was not in it.

This gathers them. It reads defensively and returns nothing rather than raising:
a guide that renders without its activities is worth more than a guide that
will not render.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-lesson-extras")


def _items(content: Any, *keys: str) -> list[dict[str, Any]]:
    """The list a station filed, under whichever key it used."""
    if not isinstance(content, dict):
        return []
    for key in keys:
        found = content.get(key)
        if isinstance(found, list) and found:
            return [item for item in found if isinstance(item, dict)]
    return []


def _search(kind: str, grade: str, subject: str, sub_strand: str) -> list[dict[str, Any]]:
    from . import artifact_registry

    try:
        return artifact_registry.search(grade=grade, subject=subject,
                                        sub_strand=sub_strand, kind=kind,
                                        limit=5) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not look for %s in %s/%s: %s",
                       kind, grade, subject, exc)
        return []


def activities(grade: str, subject: str, sub_strand: str) -> list[dict[str, Any]]:
    """The practical work, as the activity station wrote it.

    Newest version first, and only the newest is used: two versions of the same
    activity in one guide reads as two activities.
    """
    for row in _search("activity", grade, subject, sub_strand):
        found = _items(row.get("content"), "activities", "experiments")
        if found:
            return found
    return []


def media(grade: str, subject: str, sub_strand: str) -> list[dict[str, Any]]:
    """Photographs and video the media station briefed."""
    out: list[dict[str, Any]] = []
    try:
        from . import media_registry

        for row in media_registry.list_for(grade, subject, sub_strand):
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            out.append({
                "kind": str(row.get("kind") or "photo"),
                "title": title,
                "purpose": str(row.get("purpose") or ""),
                "narration": str(row.get("narration") or ""),
                "storage_url": str(row.get("storage_url") or ""),
                "alt_text": str(row.get("alt_text") or title),
                "prompt": str(row.get("generation_prompt") or ""),
                # Carried through, not dropped. Rebuilding the row into a
                # tidier shape lost the lesson it belongs to, so every clip and
                # photograph fell into the "no particular lesson" pile at the
                # end of the book — away from the teaching that calls for it.
                "module_number": row.get("module_number"),
                "hour_number": row.get("hour_number"),
                "lesson": row.get("lesson"),
                "target_hour": row.get("target_hour"),
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read media for %s/%s: %s", grade, subject, exc)
    return out


def by_lesson(items: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
    """Group by the lesson each belongs to; 0 means it serves the whole thing.

    Stations disagree about the field name — `module_number`, `hour_number`,
    `lesson` — so all three are read rather than one being made canonical after
    the fact.
    """
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for item in items:
        number = (item.get("module_number") or item.get("hour_number")
                  or item.get("lesson") or item.get("target_hour") or 0)
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = 0
        grouped.setdefault(number, []).append(item)
    return grouped


def gather(grade: str, subject: str, sub_strand: str) -> dict[str, Any]:
    """Everything filed for this sub-strand that belongs in the book."""
    found_activities = activities(grade, subject, sub_strand)
    found_media = media(grade, subject, sub_strand)
    return {
        "activities": found_activities,
        "activities_by_lesson": by_lesson(found_activities),
        "media": found_media,
        "counts": {
            "activities": len(found_activities),
            "media": len(found_media),
        },
    }

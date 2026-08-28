"""What the notes, activities and experiments for a sub-strand actually say.

Media and simulations were planned from the sub-strand's title and outcomes,
which is why they came back generic. The interesting assets are the ones the
teaching content already names: an image of the volcano the notes describe
erupting, a video of learners performing the experiment the activity plan sets
out, a simulation of the very apparatus the teacher will otherwise mime.

Planning from the outcomes alone cannot produce those, because the outcomes do
not mention the volcano. The notes do.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-lesson-content")

# Enough for the planner to see what is taught; not so much that the design
# extract and the register are crowded out of the prompt.
MAX_NOTES_CHARS = 18_000
MAX_ACTIVITY_CHARS = 6_000


@dataclass(slots=True)
class LessonContent:
    notes_summary: str = ""
    activities_summary: str = ""
    module_titles: list[str] = field(default_factory=list)
    found_notes: bool = False
    found_activities: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounded_in_notes": self.found_notes,
            "grounded_in_activities": self.found_activities,
            "modules": len(self.module_titles),
            "notes_chars": len(self.notes_summary),
            "activities_chars": len(self.activities_summary),
        }


def _modules_of(notes: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "key_concepts"):
        value = notes.get(key)
        if isinstance(value, list) and value:
            return [m for m in value if isinstance(m, dict)]
    return []


def _module_text(module: dict[str, Any]) -> str:
    parts = [
        str(module.get(k) or "")
        for k in ("teacher_exposition", "full_lecture_notes", "content",
                  "detailed_exposition", "learning_intent")
    ]
    for phase in module.get("lesson_flow") or []:
        if isinstance(phase, dict):
            parts.append(str(phase.get("what_the_teacher_does") or ""))
    return " ".join(p for p in parts if p)


def summarise_notes(notes: Any) -> tuple[str, list[str]]:
    """The taught content, lesson by lesson, with each lesson's title kept.

    Kept per module rather than flattened: an asset serves one lesson, and a
    planner that cannot see which lesson said what cannot say which lesson its
    asset belongs to.
    """
    if not isinstance(notes, dict):
        return "", []

    modules = _modules_of(notes)
    if not modules:
        return "", []

    titles: list[str] = []
    blocks: list[str] = []
    budget = MAX_NOTES_CHARS
    per_module = max(600, budget // max(1, len(modules)))

    for index, module in enumerate(modules, start=1):
        title = str(
            module.get("title") or module.get("hour_title") or module.get("heading")
            or f"Lesson {index}"
        )
        titles.append(title)
        body = _module_text(module)[:per_module]
        if body:
            blocks.append(f"--- {title} ---\n{body}")

    return "\n\n".join(blocks)[:MAX_NOTES_CHARS], titles


def summarise_activities(activities: Any) -> str:
    """The experiments and activities a teacher will actually run."""
    items: list[dict[str, Any]] = []
    if isinstance(activities, dict):
        for key in ("activities", "experiments"):
            value = activities.get(key)
            if isinstance(value, list):
                items += [a for a in value if isinstance(a, dict)]
    elif isinstance(activities, list):
        items = [a for a in activities if isinstance(a, dict)]

    if not items:
        return ""

    lines: list[str] = []
    for item in items:
        title = str(item.get("title") or item.get("activity_title") or item.get("name") or "")
        aim = str(item.get("aim") or item.get("purpose") or item.get("objective") or "")
        materials = item.get("materials_needed") or item.get("materials") or []
        steps = item.get("procedure") or item.get("steps") or []
        lines.append(
            f"- {title}: {aim}\n"
            f"  Materials: {', '.join(str(m) for m in materials[:12])}\n"
            f"  Steps: {' | '.join(str(s) for s in steps[:8])}"
        )
    return "\n".join(lines)[:MAX_ACTIVITY_CHARS]


def for_sub_strand(grade: str, subject: str, sub_strand: str) -> LessonContent:
    """The stored teaching content for a sub-strand. Never raises."""
    from ..infra.db import fetch_one

    content = LessonContent()
    try:
        row = fetch_one(
            """
            SELECT notes, activities FROM substrand_resources
            WHERE LOWER(curriculum->>'subject') = LOWER(:subject)
              AND (LOWER(curriculum->>'grade') = LOWER(:grade)
                   OR LOWER(curriculum->>'grade') = LOWER(:alt_grade))
              AND LOWER(curriculum->>'sub_strand') = LOWER(:sub_strand)
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"grade": grade, "alt_grade": grade.replace("grade-", ""),
             "subject": subject, "sub_strand": sub_strand},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read lesson content for %s: %s", sub_strand, exc)
        return content

    if not row:
        return content

    content.notes_summary, content.module_titles = summarise_notes(row.get("notes"))
    content.found_notes = bool(content.notes_summary)
    content.activities_summary = summarise_activities(row.get("activities"))
    content.found_activities = bool(content.activities_summary)
    return content

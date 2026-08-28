"""Does the teacher's guide actually plan every lesson the design funds?

A guide with four modules for a seven-lesson sub-strand cannot be turned into a
scheme of work: three lessons have no plan and nobody can see which three. That
used to pass silently — the notes route built hour modules out of whatever
concepts came back, so a short guide and a complete one were indistinguishable
downstream, and coverage counted both as notes.

This is deliberately arithmetic rather than editorial. Whether a module teaches
well is what the review layers are for; whether lesson 5 exists at all is
decidable here, and a teacher discovering the gap mid-term is the alternative.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-notes-coverage")

# Where a module's own teaching content lives, in order of preference. The
# schema settled on `teacher_exposition`; the older shapes are still read so a
# guide generated before the rename is measured rather than reported as empty.
_BODY_FIELDS = ("teacher_exposition", "full_lecture_notes", "content", "detailed_exposition")

_MODULE_LISTS = ("modules", "hour_modules", "key_concepts")

# Below this a module is a heading, not a lesson plan. A teacher cannot teach
# from two sentences, and a guide of them reads complete to every count.
#
# 1,500 characters is roughly half a printed page per lesson, so a seven-lesson
# sub-strand lands near three pages — which is what a guide has to be to be
# taught from without further preparation. The floor was 400 while the prompt
# asked for 800, so a guide averaging 662 characters a module passed the
# validator, failed the instruction, and reported "complete, 100%". One number,
# stated once, in both places.
MIN_BODY_CHARS = 1_500


@dataclass(slots=True)
class LessonCoverage:
    modules_required: int = 0
    modules_found: int = 0
    unit: str = "lessons"
    missing_numbers: list[int] = field(default_factory=list)
    duplicate_numbers: list[int] = field(default_factory=list)
    thin_modules: list[dict[str, Any]] = field(default_factory=list)
    total_body_chars: int = 0
    minutes_planned: int = 0
    minutes_allocated: int = 0
    slos_untaught: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (
            self.modules_required > 0
            and self.modules_found >= self.modules_required
            and not self.missing_numbers
            and not self.duplicate_numbers
            and not self.thin_modules
        )

    @property
    def percentage(self) -> int:
        if self.modules_required <= 0:
            return 0
        sound = self.modules_found - len(self.thin_modules)
        return max(0, min(100, round(sound / self.modules_required * 100)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "percentage": self.percentage,
            "modules_required": self.modules_required,
            "modules_found": self.modules_found,
            "unit": self.unit,
            "missing_numbers": self.missing_numbers,
            "duplicate_numbers": self.duplicate_numbers,
            "thin_modules": self.thin_modules,
            "total_body_chars": self.total_body_chars,
            "estimated_printed_pages": round(self.total_body_chars / 3_000, 1),
            "minutes_planned": self.minutes_planned,
            "minutes_allocated": self.minutes_allocated,
            "slos_untaught": self.slos_untaught,
        }


def _modules_of(notes: dict[str, Any]) -> list[dict[str, Any]]:
    for key in _MODULE_LISTS:
        value = notes.get(key)
        if isinstance(value, list) and value:
            return [m for m in value if isinstance(m, dict)]
    return []


def _body_of(module: dict[str, Any]) -> str:
    parts: list[str] = []
    for field_name in _BODY_FIELDS:
        value = module.get(field_name)
        if isinstance(value, str):
            parts.append(value)

    # The lesson flow is teaching content too, and a guide that puts its
    # substance there is not thin just because the exposition is short.
    for phase in module.get("lesson_flow") or []:
        if isinstance(phase, dict):
            parts += [str(phase.get(k) or "") for k in
                      ("what_the_teacher_does", "what_learners_do")]
    for section in module.get("subsections") or []:
        if isinstance(section, dict):
            parts.append(str(section.get("content") or ""))
    return "\n".join(p for p in parts if p)


def _number_of(module: dict[str, Any], fallback: int) -> int:
    for key in ("module_number", "hour_number", "lesson", "number"):
        value = module.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return fallback


def check(notes: dict[str, Any], allocation: Any, slos: list[Any] | None = None) -> LessonCoverage:
    """Measure a guide against the lessons its sub-strand is funded for."""
    required = int(getattr(allocation, "modules", 0) or 0)
    coverage = LessonCoverage(
        modules_required=required,
        unit=str(getattr(allocation, "unit", "") or "lessons"),
        minutes_allocated=int(getattr(allocation, "total_minutes", 0) or 0),
    )
    if not isinstance(notes, dict):
        return coverage

    modules = _modules_of(notes)
    coverage.modules_found = len(modules)

    seen: dict[int, int] = {}
    for index, module in enumerate(modules, start=1):
        number = _number_of(module, index)
        seen[number] = seen.get(number, 0) + 1

        body = _body_of(module)
        coverage.total_body_chars += len(body)
        if len(body) < MIN_BODY_CHARS:
            coverage.thin_modules.append({
                "module": number,
                "title": str(module.get("title") or module.get("hour_title") or "")[:120],
                "chars": len(body),
                "why": "too short to teach from without further preparation",
            })

        minutes = module.get("duration_minutes")
        if isinstance(minutes, int) and minutes > 0:
            coverage.minutes_planned += minutes

    coverage.duplicate_numbers = sorted(n for n, count in seen.items() if count > 1)
    if required:
        coverage.missing_numbers = [n for n in range(1, required + 1) if n not in seen]

    # An SLO that no module claims is an outcome the guide does not teach.
    if slos:
        claimed = {
            str(s).strip().lower()
            for module in modules
            for s in (module.get("slos_covered") or [])
            if str(s).strip()
        }
        if claimed:
            for slo in slos:
                text = (slo.get("text") if isinstance(slo, dict) else str(slo)) or ""
                key = str(text).strip().lower()
                if key and not any(key in c or c in key for c in claimed):
                    coverage.slos_untaught.append(str(text)[:200])

    return coverage

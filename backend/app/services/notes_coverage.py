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

# A module is written as a handful of small topics rather than one long block.
#
# Asked for 1,500 characters in one go, the model produces about a thousand and
# stops — that held across a repair pass and three review cycles, so it is not
# a matter of wording. Asked for four topics of four hundred, it writes four
# topics of four hundred. Small, named, bounded pieces are what it is good at,
# and the sum clears a floor that the single instruction never did.
MIN_SEGMENTS = 3
MAX_SEGMENTS = 6

# What each topic aims at. Four hundred is a paragraph a teacher can read at a
# glance, and four of them clear the module floor with room to spare.
SEGMENT_TARGET_CHARS = 450

# Below this a topic is a heading with a sentence under it.
MIN_SEGMENT_CHARS = 250


@dataclass(slots=True)
class LessonCoverage:
    modules_required: int = 0
    modules_found: int = 0
    unit: str = "lessons"
    missing_numbers: list[int] = field(default_factory=list)
    duplicate_numbers: list[int] = field(default_factory=list)
    thin_modules: list[dict[str, Any]] = field(default_factory=list)
    experiences_unused: list[str] = field(default_factory=list)
    modules_without_topics: list[int] = field(default_factory=list)
    thin_topics: list[dict[str, Any]] = field(default_factory=list)
    broken_handovers: list[dict[str, Any]] = field(default_factory=list)
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
            and not self.experiences_unused
        )

    @property
    def percentage(self) -> int:
        """How much of this sub-strand is planned AND deep enough to teach from."""
        if self.modules_required <= 0:
            return 0
        sound = self.modules_found - len(self.thin_modules)
        return max(0, min(100, round(sound / self.modules_required * 100)))

    @property
    def planned_percentage(self) -> int:
        """How much of it EXISTS, whatever its depth.

        Two different facts were reported as one number, and the difference is
        what unlocks the next station. A guide with seven lessons, all a little
        short, scored 0 — identical to a sub-strand nobody has generated
        anything for. The stations downstream then said "none exist yet for
        this sub-strand" about a guide that was written, reviewed, scored 87 by
        the gate and signed off by both approvers.

        Thin is a quality problem and belongs in the score. Absent is a
        different problem and is the only one that should stop the next stage.
        """
        if self.modules_required <= 0:
            return 0
        return max(0, min(100, round(self.modules_found / self.modules_required * 100)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "percentage": self.percentage,
            "planned_percentage": self.planned_percentage,
            "modules_required": self.modules_required,
            "modules_found": self.modules_found,
            "unit": self.unit,
            "missing_numbers": self.missing_numbers,
            "duplicate_numbers": self.duplicate_numbers,
            "thin_modules": self.thin_modules,
            "experiences_unused": self.experiences_unused,
            "modules_without_topics": self.modules_without_topics,
            "thin_topics": self.thin_topics,
            # A topic with no bridge is a paragraph that stops. The teacher
            # reads them in order and the children live through them in order.
            "broken_handovers": self.broken_handovers,
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


def segments_of(module: dict[str, Any]) -> list[dict[str, Any]]:
    """The named topics a module is built from, if it was written that way."""
    value = module.get("exposition_segments")
    if isinstance(value, list):
        return [s for s in value if isinstance(s, dict)]
    return []


def thin_segments(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Topics too short to be a topic — a heading with a sentence under it."""
    out: list[dict[str, Any]] = []
    for index, segment in enumerate(segments_of(module), start=1):
        body = str(segment.get("body") or "")
        if len(body) < MIN_SEGMENT_CHARS:
            out.append({
                "index": index,
                "topic": str(segment.get("topic") or "")[:120],
                "chars": len(body),
                "target": SEGMENT_TARGET_CHARS,
            })
    return out


def _body_of(module: dict[str, Any]) -> str:
    parts: list[str] = []
    for field_name in _BODY_FIELDS:
        value = module.get(field_name)
        if isinstance(value, str):
            parts.append(value)

    # The topics carry the substance where a module was written in pieces.
    for segment in segments_of(module):
        parts += [str(segment.get(k) or "") for k in ("topic", "body", "bridge")]

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


def teaching_body(notes: dict[str, Any]) -> str:
    """The guide's actual teaching text, counted once.

    The notes route mirrors `modules` into `hour_modules` and derives
    `key_concepts` from it, so the stored payload carries the same guide twice
    over. Anything measuring depth by flattening the whole payload reads that
    duplication as substance: a guide of 4,299 real characters reported 3,840
    words and scored full marks for depth on the very run this module called
    all seven of its modules too thin.

    One definition of body, read from one place, so the two numbers cannot
    disagree again.
    """
    if not isinstance(notes, dict):
        return ""
    return "\n".join(_body_of(m) for m in _modules_of(notes))


def _number_of(module: dict[str, Any], fallback: int) -> int:
    for key in ("module_number", "hour_number", "lesson", "number"):
        value = module.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return fallback


def _text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "experience", "name", "description"):
            if isinstance(value.get(key), str):
                return value[key]
        return " ".join(str(v) for v in value.values() if isinstance(v, str))
    return str(value or "")


def _unused_experiences(
    modules: list[dict[str, Any]], experiences: list[Any]
) -> list[str]:
    """Which of the design's own lesson steps the guide never picked up.

    The design IS the lesson; the guide explains how to teach it. So a
    suggested learning experience that appears in no module is a step KICD
    funded and nobody planned — and the prompt tells the model to name it in
    `gaps` if it genuinely does not fit.

    On the run this was written for, "listen to a recorded clip of a short
    prayer" was demoted to an optional resource, left out of every module's
    `learning_experiences_used`, and `gaps` came back empty. Nothing noticed.
    """
    from .dna_scoring import containment

    haystack = "\n".join(
        _body_of(m) + "\n" + "\n".join(
            _text_of(e) for e in (m.get("learning_experiences_used") or [])
        )
        for m in modules
    )
    if not haystack.strip():
        return []

    unused: list[str] = []
    for experience in experiences:
        text = _text_of(experience).strip()
        if len(text) < 8:
            continue
        # Half the experience's own meaningful terms is a generous bar: it
        # catches a step that was dropped, not one that was reworded.
        if containment(text, haystack) < 0.5:
            unused.append(text[:200])
    return unused


def check(
    notes: dict[str, Any],
    allocation: Any,
    slos: list[Any] | None = None,
    experiences: list[Any] | None = None,
) -> LessonCoverage:
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

        # Written as topics, or as one block? A module with no topics is not a
        # failure on its own — it is only how the old shape looked — but it is
        # the shape that kept coming back at a third of the required depth.
        module_segments = segments_of(module)
        if not module_segments:
            coverage.modules_without_topics.append(number)
        else:
            for short in thin_segments(module):
                coverage.thin_topics.append({"module": number, **short})
            for index, segment in enumerate(module_segments, start=1):
                if not str(segment.get("bridge") or "").strip():
                    coverage.broken_handovers.append({
                        "module": number, "index": index,
                        "topic": str(segment.get("topic") or "")[:120],
                    })

        minutes = module.get("duration_minutes")
        if isinstance(minutes, int) and minutes > 0:
            coverage.minutes_planned += minutes

    coverage.duplicate_numbers = sorted(n for n, count in seen.items() if count > 1)
    if required:
        coverage.missing_numbers = [n for n in range(1, required + 1) if n not in seen]

    if experiences:
        coverage.experiences_unused = _unused_experiences(modules, experiences)

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

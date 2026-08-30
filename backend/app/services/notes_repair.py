"""Send a thin guide back to be written properly, instead of filing it.

`notes_coverage` already decided the question: on the run that prompted this
module it called all seven modules of a seven-lesson sub-strand too short to
teach from — 498 to 798 characters against a 1,500 floor, 1.4 printed pages
where the guide needed three. Nothing acted on that. The route logged a warning,
stored the guide as artifact v1, and returned HTTP 200 with
`"complete": false, "percentage": 0` buried in the payload.

A validator whose finding changes nothing is a comment. This one now costs a
second call and rewrites the modules it named.

The repair is deliberately narrow. It re-asks for ONLY the modules that failed,
carrying their current text so the model extends rather than restarts, and it
merges field by field, keeping whatever the first pass got right. A module that
comes back shorter than it went in is discarded — a repair that loses content is
not a repair.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import notes_coverage

logger = logging.getLogger("cbc-notes-repair")

# One extra call. Two would double the cost of every thin run for a model that
# has already shown it will not clear the floor, and the second attempt is worth
# far less than telling the operator which model produced the guide.
MAX_ATTEMPTS = 1

# Fields the repair is allowed to replace. Everything else the first pass
# produced — citations, SLO mapping, module numbering — is left alone, because
# the defect being fixed is depth and nothing else.
_EXPANDABLE = (
    "teacher_exposition", "exposition_segments", "lesson_flow", "key_questions",
    "common_misconceptions", "resources_needed", "differentiation",
    "formative_check", "learning_experiences_used",
)


@dataclass(slots=True)
class RepairReport:
    attempted: bool = False
    modules_targeted: list[int] = field(default_factory=list)
    modules_expanded: list[int] = field(default_factory=list)
    modules_still_thin: list[int] = field(default_factory=list)
    chars_before: int = 0
    chars_after: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "modules_targeted": self.modules_targeted,
            "modules_expanded": self.modules_expanded,
            "modules_still_thin": self.modules_still_thin,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "chars_gained": max(0, self.chars_after - self.chars_before),
            "error": self.error,
        }


def _modules_list(notes: dict[str, Any]) -> list[dict[str, Any]]:
    value = notes.get("modules")
    if isinstance(value, list):
        return [m for m in value if isinstance(m, dict)]
    return []


def _number(module: dict[str, Any], fallback: int) -> int:
    value = module.get("module_number")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def _body_len(module: dict[str, Any]) -> int:
    return len(notes_coverage._body_of(module))


def _instruction(
    thin: list[dict[str, Any]],
    design_block: str,
    allocation_phrase: str,
    sub_strand: str,
    unused_experiences: list[str],
) -> str:
    """What to say to get depth rather than more words.

    The first pass was told the floor and missed it, so repeating the floor is
    not the instruction. Naming each module, its measured length, and the exact
    kinds of concrete detail that are missing is.
    """
    import json as json_lib

    lines = []
    for m in thin:
        lines.append(
            f"  - Module {m['number']} \"{m['title']}\": {m['chars']:,} characters"
            + (f", short of the {notes_coverage.MIN_BODY_CHARS:,} a teachable "
               f"module needs."
               if m["chars"] < notes_coverage.MIN_BODY_CHARS
               else ", which has room for the material below.")
        )
        # Naming the exact topic that is short is the difference between "write
        # more" and "this paragraph is 120 characters and needs 450". The model
        # can act on the second.
        for short in notes_coverage.thin_segments(m["module"]):
            lines.append(
                f"      · topic {short['index']} \"{short['topic']}\" is only "
                f"{short['chars']} characters and should be about "
                f"{short['target']}."
            )
    listing = "\n".join(lines)
    payload = json_lib.dumps([m["module"] for m in thin], ensure_ascii=False, indent=1)

    dropped = ""
    if unused_experiences:
        dropped = (
            "\n=== STEPS THE DESIGN FUNDED THAT NO MODULE PICKED UP ===\n"
            + "\n".join(f"  - {e}" for e in unused_experiences)
            + "\nThese are KICD's own suggested learning experiences. The design is the "
              "lesson and your guide explains how to teach it, so a step that appears "
              "in no module is a step nobody planned. Work each one into whichever "
              "module it belongs in, and where the design hands you an actual phrase, "
              "song or prayer, write it out VERBATIM in the language the design gives "
              "it in — including the mother-tongue or Kiswahili wording. That phrase "
              "is the most concrete thing in the specification and the commonest "
              "thing to skip.\n"
        )

    return (
        f"{design_block}\n"
        f"{dropped}\n"
        f"=== THESE MODULES ARE TOO THIN TO TEACH FROM ===\n"
        f"You wrote the teacher's guide for \"{sub_strand}\" ({allocation_phrase}). "
        f"These modules came back too short to hand a teacher:\n\n"
        f"{listing}\n\n"
        f"A teacher handed a module this length still has to prepare the lesson, "
        f"which is the one thing this guide exists to prevent.\n\n"
        f"=== HOW TO EXPAND THEM ===\n"
        f"Work topic by topic in `exposition_segments`, not on the module as a "
        f"whole. Where a module has no topics yet, break its exposition into "
        f"{notes_coverage.MIN_SEGMENTS}-{notes_coverage.MAX_SEGMENTS} named "
        f"topics of about {notes_coverage.SEGMENT_TARGET_CHARS} characters each, "
        f"every one with a `bridge` sentence handing over to the next.\n"
        f"A short topic is a small, bounded thing to fix. A short module is not, "
        f"which is why asking for the module to be longer has not worked.\n\n"
        f"=== WHAT IS MISSING, CONCRETELY ===\n"
        f"The gap is detail, not length. Do NOT lengthen the sentences you have. "
        f"Add the things a teacher cannot supply from the outcome alone:\n"
        f"  - The teacher's ACTUAL WORDS. Not \"explain that God is loving\" but the "
        f"sentences to say, in the order to say them.\n"
        f"  - The ACTUAL song, phrase, story or prayer, written out in full and in "
        f"the language the design gives it in. Where the design hands you a phrase, "
        f"it goes in verbatim — that is the most concrete thing in the whole "
        f"specification and the commonest thing to skip.\n"
        f"  - The questions in the exact order to ask them, and what to say when a "
        f"learner answers wrongly, answers nothing, or answers something unexpected.\n"
        f"  - What to hold up, and at which minute.\n"
        f"  - What a learner who has NOT understood visibly does, and the next move "
        f"when they do it.\n"
        f"  - How the teacher knows, before the lesson ends, that it worked.\n\n"
        f"=== STAY INSIDE THIS SUB-STRAND ===\n"
        f"Go deeper into what \"{sub_strand}\" already teaches. Do not reach into the "
        f"next sub-strand for material — a lesson taught inside the wrong guide is "
        f"taught twice and scheduled once. If a module genuinely has less material "
        f"than the design funds lessons for, spend the space on the teacher's own "
        f"words and on what goes wrong, not on a new topic.\n\n"
        f"=== THE MODULES, AS THEY STAND ===\n"
        f"{payload}\n\n"
        f"Return ONLY valid JSON: an object with one key, \"modules\", holding these "
        f"same modules with the SAME module_number, rewritten to depth. Keep every "
        f"field they already have; keep the citations exactly as they are; keep the "
        f"lesson_flow phase names and minutes. Expand what is inside them."
    )


def repair(
    notes: dict[str, Any],
    coverage: notes_coverage.LessonCoverage,
    *,
    generate: Any,
    model_config: Any,
    base_messages: list[dict[str, str]],
    design_block: str,
    allocation_phrase: str,
    sub_strand: str,
) -> tuple[dict[str, Any], RepairReport]:
    """Rewrite the modules coverage called thin. Returns the guide either way."""
    report = RepairReport()
    if not isinstance(notes, dict):
        return notes, report
    if not coverage.thin_modules and not coverage.experiences_unused:
        return notes, report

    modules = _modules_list(notes)
    if not modules:
        return notes, report

    by_number = {_number(m, i): m for i, m in enumerate(modules, start=1)}
    thin_numbers = [
        int(t["module"]) for t in coverage.thin_modules
        if isinstance(t.get("module"), int) and int(t["module"]) in by_number
    ]
    if not thin_numbers and coverage.experiences_unused:
        # Every module cleared the depth floor but the guide still dropped one
        # of the design's own lesson steps. Rewriting all of them to place it
        # risks more than it fixes, so the shortest few get the work — they have
        # the most room and the least to lose.
        thin_numbers = sorted(by_number, key=lambda n: _body_len(by_number[n]))[:3]
    if not thin_numbers:
        return notes, report

    report.attempted = True
    report.modules_targeted = thin_numbers
    report.chars_before = len(notes_coverage.teaching_body(notes))

    thin = [
        {
            "number": n,
            "title": str(by_number[n].get("title") or "")[:120],
            "chars": _body_len(by_number[n]),
            "module": by_number[n],
        }
        for n in thin_numbers
    ]

    # The system messages carry the register, the faith scope and the curriculum
    # context. Dropping them here is how a repair pass produces depth that is
    # correct for no grade in particular.
    messages = [m for m in base_messages if m.get("role") == "system"]
    messages.append({
        "role": "user",
        "content": _instruction(
            thin, design_block, allocation_phrase, sub_strand,
            list(coverage.experiences_unused),
        ),
    })

    try:
        response = generate(model_config, messages, temperature=0.2)
    except Exception as exc:  # noqa: BLE001
        report.error = f"{type(exc).__name__}: {exc}"
        logger.warning("Notes repair for %s failed: %s", sub_strand, report.error)
        report.chars_after = report.chars_before
        return notes, report

    returned = response.content if isinstance(response.content, dict) else {}
    rewritten = returned.get("modules")
    if not isinstance(rewritten, list):
        report.error = "the repair returned no 'modules' list"
        report.chars_after = report.chars_before
        return notes, report

    for candidate in rewritten:
        if not isinstance(candidate, dict):
            continue
        number = _number(candidate, 0)
        original = by_number.get(number)
        if original is None:
            # A module number nobody asked about. Adding it would invent a
            # lesson the design did not fund.
            continue

        merged = dict(original)
        for key in _EXPANDABLE:
            value = candidate.get(key)
            if value in (None, "", [], {}):
                continue
            existing = original.get(key)
            # Only ever a replacement that carries more than it displaces. A
            # "repair" that swaps four paragraphs for one is a regression that
            # passes every count.
            if isinstance(value, str) and isinstance(existing, str) and len(value) < len(existing):
                continue
            if isinstance(value, list) and isinstance(existing, list) and len(value) < len(existing):
                continue
            merged[key] = value

        if _body_len(merged) <= _body_len(original):
            continue

        original.clear()
        original.update(merged)
        report.modules_expanded.append(number)

    report.modules_expanded.sort()
    report.chars_after = len(notes_coverage.teaching_body(notes))
    report.modules_still_thin = sorted(
        n for n in thin_numbers if _body_len(by_number[n]) < notes_coverage.MIN_BODY_CHARS
    )

    logger.info(
        "Notes repair for %s expanded %d of %d thin module(s), %d -> %d chars.",
        sub_strand, len(report.modules_expanded), len(thin_numbers),
        report.chars_before, report.chars_after,
    )
    return notes, report

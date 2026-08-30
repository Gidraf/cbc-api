"""Check a guide against its own claims about itself.

A PP1 "Our God" guide passed at 97.9 with two plain contradictions in it.

Its `slo_map` said "practice saying short prayers" was taught in lessons 3 and
4 and assessed in 4. Lesson 4 is "Appreciating God's Love", its `slos_covered`
names a different outcome, and no prayer appears in it. Lesson 7 was in no row
of the map at all. A head of department building a scheme of work from this
finds the mismatch on the first read; nothing in the pipeline did.

And three modules listed "appreciate God as a loving heavenly father" under
`learning_experiences_used`. That is a learning OUTCOME. The design's suggested
learning experiences are seven bullets and that is not one of them. The gate
still reported "7 of 7 of the design's suggested learning experiences are
taught".

Neither needs a model to find. Both are the guide disagreeing with itself, and
the check is a comparison.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cbc-notes-integrity")

# Fields the schema asks every module for. Absent, a teacher reaches the lesson
# and finds the part they needed missing.
REQUIRED_MODULE_FIELDS = (
    "title", "module_number", "duration_minutes", "learning_intent",
    "slos_covered", "formative_check", "differentiation", "key_questions",
    "resources_needed", "common_misconceptions", "citations",
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", str(text)).lower()).strip()


def _modules(notes: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "lessons"):
        found = notes.get(key)
        if isinstance(found, list) and found:
            return [m for m in found if isinstance(m, dict)]
    return []


def _label(module: dict[str, Any], index: int) -> str:
    return str(module.get("title") or f"module {index + 1}")


def _number(module: dict[str, Any], index: int) -> int:
    raw = module.get("module_number")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return index + 1


def check_slo_map(notes: dict[str, Any]) -> list[str]:
    """Does every row of the map agree with the modules it names?"""
    modules = _modules(notes)
    if not modules:
        return []
    rows = notes.get("slo_map")
    if not isinstance(rows, list) or not rows:
        return ["The guide has no `slo_map`, so nothing says which lesson "
                "carries which outcome."]

    by_number = {_number(m, i): m for i, m in enumerate(modules)}
    covered: dict[int, set[str]] = {
        n: {_norm(s) for s in (m.get("slos_covered") or [])}
        for n, m in by_number.items()
    }

    findings: list[str] = []
    claimed: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        slo = str(row.get("slo") or "")
        key = _norm(slo)
        for field in ("taught_in", "assessed_in"):
            for raw in (row.get(field) or []):
                try:
                    number = int(raw)
                except (TypeError, ValueError):
                    continue
                claimed.add(number)
                if number not in by_number:
                    findings.append(
                        f"`slo_map` says \"{slo}\" is {field.replace('_', ' ')} "
                        f"lesson {number}, and there is no lesson {number}.")
                    continue
                if key and key not in covered[number]:
                    findings.append(
                        f"`slo_map` says \"{slo}\" is "
                        f"{field.replace('_', ' ')} lesson {number}, but "
                        f"\"{_label(by_number[number], number - 1)}\" does not "
                        f"list it under `slos_covered`. One of the two is "
                        f"wrong, and a scheme of work is built from the map.")

    for number, module in sorted(by_number.items()):
        if number not in claimed:
            findings.append(
                f"Lesson {number} (\"{_label(module, number - 1)}\") appears "
                f"in no row of `slo_map`. Every funded lesson has to carry an "
                f"outcome, or it cannot be justified on the scheme.")

    assessed = {int(n) for row in rows if isinstance(row, dict)
                for n in (row.get("assessed_in") or [])
                if str(n).isdigit()}
    for row in rows:
        if isinstance(row, dict) and not (row.get("assessed_in") or []):
            findings.append(
                f"\"{row.get('slo')}\" is never assessed. The design's rubric "
                f"has a row for it, so a teacher has nothing to fill it from.")
    return findings


def check_learning_experiences(notes: dict[str, Any],
                               design_experiences: list[str]) -> list[str]:
    """Does every cited experience actually come from the design's list?"""
    if not design_experiences:
        return []
    allowed = [_norm(e) for e in design_experiences if str(e).strip()]
    findings: list[str] = []
    seen_bad: set[str] = set()

    for i, module in enumerate(_modules(notes)):
        for used in (module.get("learning_experiences_used") or []):
            key = _norm(used)
            if not key or key in seen_bad:
                continue
            # The guide may shorten one — "use gestures to describe God" for a
            # bullet that runs on into its Swahili gloss — so a genuine prefix
            # or substring of a design bullet is accepted.
            if any(key in bullet or bullet in key for bullet in allowed):
                continue
            seen_bad.add(key)
            findings.append(
                f"\"{_label(module, i)}\" lists \"{used}\" under "
                f"`learning_experiences_used`, and the design does not suggest "
                f"it. The design's experiences are what the learner is guided "
                f"to DO; an outcome or an invented activity in this field "
                f"makes the guide look grounded where it is not.")

    unused = [
        e for e, key in zip(design_experiences, allowed)
        if not any(key in _norm(u) or _norm(u) in key
                   for m in _modules(notes)
                   for u in (m.get("learning_experiences_used") or []))
    ]
    for experience in unused:
        findings.append(
            f"The design suggests \"{experience}\" and no lesson uses it. "
            f"Teach it, or name it in `gaps` — it is the lesson KICD "
            f"published.")
    return findings


def check_required_fields(notes: dict[str, Any]) -> list[str]:
    """Fields the schema asks for that no module supplied."""
    modules = _modules(notes)
    if not modules:
        return []
    missing: dict[str, int] = {}
    for module in modules:
        for field in REQUIRED_MODULE_FIELDS:
            if not module.get(field):
                missing[field] = missing.get(field, 0) + 1

    findings = []
    for field, count in sorted(missing.items(), key=lambda i: -i[1]):
        where = ("every module" if count == len(modules)
                 else f"{count} of {len(modules)} modules")
        findings.append(
            f"`{field}` is empty in {where}. The schema asks for it, and a "
            f"teacher who reaches that lesson finds the part they needed "
            f"missing.")
    return findings


def check(notes: dict[str, Any],
          design_experiences: list[str] | None = None) -> dict[str, Any]:
    """Everything a guide can be caught contradicting about itself."""
    if not isinstance(notes, dict):
        return {"checked": False, "findings": [], "score": 100.0}

    findings = (
        check_slo_map(notes)
        + check_learning_experiences(notes, design_experiences or [])
        + check_required_fields(notes)
    )
    # Each contradiction is a thing a teacher will hit. Ten of them is not ten
    # times worse than one, so the cost tapers rather than running to zero.
    score = round(max(0.0, 100.0 - 12.0 * len(findings)), 1)
    return {
        "checked": True,
        "clean": not findings,
        "score": 100.0 if not findings else score,
        "findings": findings,
    }

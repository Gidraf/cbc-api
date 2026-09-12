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

import difflib
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


# How close two statements of an outcome have to be to count as the same one.
# The model paraphrases — "Practising short prayers" for "practice saying short
# prayers" — and exact matching made the checker and the repair disagree about
# what "the same outcome" means, so the repair created findings the checker
# then reported.
SLO_MATCH = 0.60


def same_outcome(a: str, b: str) -> bool:
    """Whether two statements name the same learning outcome."""
    left, right = _norm(a), _norm(b)
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= SLO_MATCH


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
    covered: dict[int, list[str]] = {
        n: [str(s) for s in (m.get("slos_covered") or [])]
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
                if key and not any(same_outcome(slo, c)
                                   for c in covered[number]):
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


# Words that carry no meaning for matching an experience to a lesson.
_EMPTY_WORDS = frozenset({
    "the", "and", "a", "an", "of", "to", "in", "on", "by", "for", "with",
    "from", "at", "as", "or", "is", "are", "be", "it", "its", "this", "that",
    "their", "them", "they", "will", "can", "using", "use", "used", "all",
    "different", "various", "such", "e", "g", "eg", "involving", "involves",
})


def _stems(text: str) -> set[str]:
    """Content words, crudely stemmed, for comparing prose to prose.

    Crude on purpose: "games" and "game", "performing" and "perform" are the
    same word for this, and anything cleverer needs a stemmer this repository
    does not carry.
    """
    words = re.findall(r"[a-z]+", str(text or "").lower())
    out: set[str] = set()
    for word in words:
        if word in _EMPTY_WORDS or len(word) < 3:
            continue
        for suffix in ("ing", "ies", "ed", "es", "s"):
            if len(word) > len(suffix) + 2 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        out.add(word)
    return out


def _lesson_text(module: dict[str, Any]) -> str:
    """Everything a lesson actually says, for checking what it teaches."""
    parts = [str(module.get(k) or "") for k in
             ("title", "teacher_exposition", "learner_activity", "summary")]
    for segment in (module.get("exposition_segments") or []):
        if isinstance(segment, dict):
            parts += [str(segment.get("topic") or ""), str(segment.get("body") or "")]
    for key in ("resources_needed", "key_inquiry_questions"):
        parts += [str(v) for v in (module.get(key) or [])]
    return " ".join(parts)


# How much of an experience's own vocabulary a lesson must share before it
# counts as teaching it. Two thirds: high enough that a lesson merely about the
# same topic does not qualify, low enough to survive rewording.
_TAUGHT = 0.6

# Below this much of the experience's vocabulary, a lesson that NAMES the
# experience plainly does not do it. Deliberately far under _TAUGHT: the band
# between is "maybe, in other words", and a rewrite on a maybe is churn. A
# lesson that cited "use IT tools ... to carry out operations on integers" and
# made a poster shares 2 of 8 stems; the lesson that used number cards shares 7
# of 10.
_ABSENT = 0.35

# Fewer words than this and the lesson has no text to judge — a stub, or a
# module whose prose the material station has not written yet.
_ENOUGH_TEXT = 40


def _coverage(experience: str, module: dict[str, Any]) -> float | None:
    wanted = _stems(experience)
    if len(wanted) < 2:
        return None
    shared = wanted & _stems(_lesson_text(module))
    return len(shared) / len(wanted)


def _teaches(experience: str, module: dict[str, Any]) -> bool:
    coverage = _coverage(experience, module)
    return coverage is not None and coverage >= _TAUGHT


def _plainly_absent(experience: str, module: dict[str, Any]) -> bool:
    if len(_lesson_text(module).split()) < _ENOUGH_TEXT:
        return False
    coverage = _coverage(experience, module)
    return coverage is not None and coverage < _ABSENT


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
        # Before saying no lesson uses it, read the lessons. This check tests a
        # DECLARED field, and a guide that teaches Integer Bingo and Integer
        # War without declaring the experience was reported as not teaching it
        # at all — which is untrue, and trains an operator to distrust the
        # number rather than act on it.
        taught_in = [_label(m, i) for i, m in enumerate(_modules(notes))
                     if _teaches(experience, m)]
        if taught_in:
            findings.append(
                f"The design suggests \"{experience}\". "
                f"{taught_in[0]} teaches it, but does not name it under "
                f"`learning_experiences_used` — so nothing downstream can tell "
                f"that the design's own activity was covered. Declare it.")
            continue
        findings.append(
            f"The design suggests \"{experience}\" and no lesson uses it. "
            f"Teach it, or name it in `gaps` — it is the lesson KICD "
            f"published.")
    return findings


def check_declared_but_not_taught(
        notes: dict[str, Any],
        design_experiences: list[str]) -> tuple[list[str], list[int]]:
    """Lessons that NAME a design experience their text does not DO.

    The unused-experience check reads the declared field, so the moment a
    lesson wrote `experience 5` under `learning_experiences_used` the finding
    went quiet — and the lesson was poster-making. "use IT tools ... to carry
    out operations on integers" was cited by a lesson containing no IT tool,
    no print resource and no operation. Naming without teaching is the worse
    failure: it makes the guide look grounded exactly where it is not.

    Returns the findings and the module numbers to rewrite.
    """
    if not design_experiences:
        return [], []
    bullets = [(e, _norm(e)) for e in design_experiences if str(e).strip()]
    findings: list[str] = []
    numbers: list[int] = []
    for i, module in enumerate(_modules(notes)):
        for used in (module.get("learning_experiences_used") or []):
            key = _norm(used)
            if not key:
                continue
            bullet = next((e for e, k in bullets if key in k or k in key), None)
            if bullet is None:
                continue
            # Judge the lesson on what it CLAIMED, at the shorter of the two
            # wordings, and without the mother-tongue gloss a design bullet
            # runs on into after a semicolon — English prose cannot share
            # stems with "Mungu ni mkuu na wa ajabu sana", and it should not
            # have to.
            claim = str(used) if len(key) < len(_norm(bullet)) else bullet
            claim = claim.split(";")[0]
            if not _plainly_absent(claim, module):
                continue
            findings.append(
                f"\"{_label(module, i)}\" names \"{bullet}\" under "
                f"`learning_experiences_used`, but nothing in the lesson does "
                f"it — the activities described are not that experience. "
                f"Either make the lesson actually carry it out, in the design's "
                f"own terms, or take the citation off. Naming an experience the "
                f"lesson does not teach is worse than leaving it unnamed.")
            number = _number(module, i)
            if number not in numbers:
                numbers.append(number)
    return findings, numbers


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

    undelivered, undelivered_in = check_declared_but_not_taught(
        notes, design_experiences or [])
    findings = (
        check_slo_map(notes)
        + check_learning_experiences(notes, design_experiences or [])
        + undelivered
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
        "undelivered": undelivered_in,
    }

"""Whether two items are the same task wearing different numbers.

A paper carried "State the directed integer that represents an outstanding
debt of KSh 3,400" as Q2 and the same sentence with KSh 3,500 as Q3; "how do
directed integers keep scoring fair" twice; a diver at −18 m twice; a team
starting on −12 points three times. Every check compared stems exactly, so a
changed number or a changed county was a new question.

The SHAPE of a task is its words with the numbers, the money, the places and
the filler taken out. Two items whose shapes overlap heavily are one task.
"""
from __future__ import annotations

import re
from typing import Any

_STOP = frozenset("""
a an the and or of to in on at for from by with as is are was were be been being this that these those
it its into than then so such which who whom whose what when where how each every all any some no
not only also more most very can could will would should may might must shall do does did done
learner learners student students school class grade junior county town city kenya kenyan use uses
using during while after before given following below above
work out value expression calculate calculates evaluate evaluates find determine state states explain
explains describe describes identify identifies show shows exact without calculator answer question
correct correctly step steps method activity lesson project group club team members records record
""".split())

_MONEY = re.compile(r"(ksh|sh|shillings?|kes)\.?\s*[\d,]+(\.\d+)?|[\d,]+(\.\d+)?\s*(ksh|sh|shillings?|kes)\b", re.I)
_NUMBER = re.compile(r"[−\-+]?\d[\d,]*(\.\d+)?")
_MATH = re.compile(r"\$[^$]*\$|\\[a-z]+")
_UNIT = re.compile(r"\b(m|km|cm|kg|g|l|ml|°c|c|min|mins|minutes?|hours?|points?|marks?|units?)\b", re.I)
# A capitalised word inside a sentence is a name — Nakuru, Kericho, Amina.
_PROPER = re.compile(r"(?<=[a-z,;:] )([A-Z][a-z]+)")


def shape(text: str) -> frozenset[str]:
    """The task's words, without what a rewrite changes."""
    t = str(text or "")
    t = _MATH.sub(" ", t)
    t = _PROPER.sub(" ", t)
    t = _MONEY.sub(" money ", t)
    t = _NUMBER.sub(" ", t)
    t = _UNIT.sub(" ", t)
    words = [w for w in re.findall(r"[a-z]+", t.lower()) if w not in _STOP and len(w) > 2]
    return frozenset(words)


def similarity(a: str, b: str) -> float:
    """How much of the smaller shape the larger one contains, 0–1.

    Containment rather than Jaccard: a clone usually adds a sentence of
    scene-setting ("Learners in Kiambu County design a board game…") that
    the original lacks, and that padding must not hide the copy.
    """
    sa, sb = shape(a), shape(b)
    if len(sa) < 4 or len(sb) < 4:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def shared(a: str, b: str) -> int:
    return len(shape(a) & shape(b))


# Two items are one task when the smaller shape is mostly inside the larger
# AND they share enough words for that to mean something. Set from the paper
# that had the problem: the debt pair 0.57/8, fair scoring 0.61/8, the two
# divers 0.60/9, the two team scores 0.53/8, the two club balances 0.47/8 —
# and two short conceptual items that merely share "why … negative integer"
# 0.50 but only 4 words, two bare expressions 0.17.
SAME_TASK = 0.45
MIN_SHARED = 6


def same_task(a: str, b: str) -> bool:
    return similarity(a, b) >= SAME_TASK and shared(a, b) >= MIN_SHARED


def stem_of(question: dict[str, Any]) -> str:
    return " ".join(str(question.get(k) or "") for k in ("stimulus_context", "question_text")).strip()

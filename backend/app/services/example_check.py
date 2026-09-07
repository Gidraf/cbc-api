"""Whether a worked example's ARITHMETIC actually models what it describes.

A reviewer found three faults in one Grade 9 guide and the maths engine
verified all three as correct:

    "temperature drops from 5°C to -3°C, so 5 + (-3) = 2"      5 + (-3) IS 2
    "a hiker climbs from 200 m to 50 m, so 200 + (-50) = 150"  200 + (-50) IS 150
    "-7 + 3 = -4, so adding a positive moves you closer to 0"  -7 + 3 IS -4

Every sum checks out. The change from 5°C to -3°C is a fall of 8, not 2; a
hiker going from 200 m to 50 m has descended, not climbed; and -2 + 10 = 8 is
further from zero, not closer. The arithmetic was never the problem — the
sentence saying what the arithmetic represents was.

A solver cannot catch this, because there is nothing wrong with the sum. What
CAN catch it is comparing the expression against the words around it:

  * a change "from A to B" is B - A, and an example that writes A + (-B)
    has modelled a different question;
  * "climbs", "rises", "gains" against a pair that falls is the story
    contradicting its own numbers;
  * "always", "results in", "any" is a claim about every case, and a claim
    about every case can be tested against cases.

None of these needs a model. All of them are the difference between a booklet
somebody buys and one they discard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# "from 5°C to -3°C", "from 200 metres to 50 m", "from 10 to -2"
# Up to four words may sit between "from" and its number — "from an elevation
# of 200 metres to 50 metres" is the shape the reviewer found, and a pattern
# demanding the number immediately after "from" walked straight past it.
_FROM_TO = re.compile(
    r"\bfrom\s+(?:\w+\s+){0,4}?(-?\d+(?:\.\d+)?)\s*"
    r"(?:°?\s*[cCfF]\b|m\b|metres?\b|meters?\b|km\b|shillings?\b|KE?S?h?\b)?"
    r"\s*(?:down\s+to|up\s+to|to)\s+(?:\w+\s+){0,3}?(-?\d+(?:\.\d+)?)", re.I)

# The words that say which way it went.
_ROSE = re.compile(r"\b(rise[sn]?|rose|climb(s|ed|ing)?|increase[sd]?|gain(s|ed)?|"
                   r"up|warm(s|ed|er)?|ascend(s|ed|ing)?)\b", re.I)
_FELL = re.compile(r"\b(fall(s|en|ing)?|fell|drop(s|ped|ping)?|decrease[sd]?|"
                   r"lose[sd]?|lost|down|cool(s|ed|er)?|descend(s|ed|ing)?|"
                   r"below)\b", re.I)

# A claim about every case.
_UNIVERSAL = re.compile(
    r"\b(always|never|any\s+\w+|every\s+\w+|all\s+\w+|results?\s+in|"
    r"will\s+(?:be|always)|is\s+always)\b", re.I)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Finding:
    kind: str
    says: str
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "says": self.says, "fix": self.fix}


@dataclass
class Report:
    checked: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def score(self) -> float:
        if not self.checked:
            return 0.0
        bad = len({f.says for f in self.findings})
        return round(max(0.0, 1 - bad / self.checked) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "clean": self.clean,
                "score": self.score,
                "findings": [f.to_dict() for f in self.findings]}


def _text_of(example: dict[str, Any]) -> str:
    parts = [str(example.get("statement") or "")]
    for step in (example.get("steps") or []):
        if isinstance(step, dict):
            parts += [str(step.get("working") or ""), str(step.get("because") or "")]
    parts.append(str(example.get("answer") or ""))
    return " ".join(parts)


def _direction_fault(text: str) -> Finding | None:
    """A story that goes one way and numbers that go the other."""
    pair = _FROM_TO.search(text)
    if not pair:
        return None
    start, end = float(pair.group(1)), float(pair.group(2))
    if start == end:
        return None
    went_up = end > start
    said_up = bool(_ROSE.search(text))
    said_down = bool(_FELL.search(text))
    if went_up and said_down and not said_up:
        return Finding(
            "direction", f"It says the value falls, and goes from {pair.group(1)} "
            f"to {pair.group(2)}, which is a rise.",
            "Fix the wording or the numbers — a learner reading this learns the "
            "wrong sign.")
    if not went_up and said_up and not said_down:
        return Finding(
            "direction", f"It says the value rises, and goes from {pair.group(1)} "
            f"to {pair.group(2)}, which is a fall.",
            "A hiker going from 200 m to 50 m has descended, not climbed.")
    return None


def _change_fault(text: str) -> Finding | None:
    """A change from A to B is B - A, whatever the example writes down."""
    pair = _FROM_TO.search(text)
    if not pair:
        return None
    start, end = float(pair.group(1)), float(pair.group(2))
    change = end - start
    if not re.search(r"\bchange|\bdifference|\bdrop|\bfall|\brise|\bincrease|"
                     r"\bdecrease", text, re.I):
        return None

    # The answer the example actually gives.
    answer = str(_last_number(text) or "")
    if answer == "":
        return None
    try:
        given = float(answer)
    except ValueError:
        return None

    if abs(given - change) < 1e-9 or abs(given - abs(change)) < 1e-9:
        return None
    return Finding(
        "models_the_wrong_thing",
        f"The value goes from {pair.group(1)} to {pair.group(2)}, so the change "
        f"is {change:g}. This example answers {given:g}, which is a different "
        f"question — the arithmetic is right and it is not the arithmetic the "
        f"story asks for.",
        "Write the change as final minus initial and work that out.")


def _last_number(text: str) -> str | None:
    found = _NUMBER.findall(text)
    return found[-1] if found else None


def _too_easy(examples: list[Any], grade: str) -> Finding | None:
    """Arithmetic years below the grade the SET is printed for.

    "7 - 4 = 3" is not wrong, and it is not a Grade 9 revision question either.
    But a guide introducing the sign rule legitimately needs `-4 × 6 = -24` in
    it, so condemning that item on its own would be condemning the example the
    lesson is built around — and a gate that fails honest work gets switched
    off, after which it catches nothing at all.

    What the reviewer actually objected to was never one easy example. It was
    that the hardest thing in a whole Grade 9 booklet was `7 - 4`. So that is
    what is asked here: whether ANYTHING in the set reaches the grade.

    The measurement lives in `task_demand`, which counts what makes an
    expression hard — how many operations, how many KINDS of operation, whether
    anything is bracketed, whether the order of operations decides the answer —
    against the floor for the grade's own level. A set with no arithmetic in it
    is never flagged, which is how a floor written for Mathematics leaves a
    comprehension exercise alone.
    """
    from . import task_demand

    report = task_demand.check_set(examples, grade)
    if not report.below:
        return None
    return Finding("below_the_grade", report.says(), report.fix())


# Claims about every case, and the counterexamples that break them.
_CLAIM_TESTS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"positive.{0,40}negative.{0,40}closer to zero", re.I),
     "-2 + 10 = 8",
     "adding a positive to a negative does not always move towards zero: "
     "-2 + 10 = 8 is further from zero than -2."),
    (re.compile(r"(?:sum|adding|addition).{0,30}two negatives?.{0,30}positive", re.I),
     "-2 + -3 = -5",
     "the sum of two negatives is negative, not positive."),
    (re.compile(r"subtract\w*.{0,40}(?:always|result\w*).{0,20}smaller", re.I),
     "5 - (-3) = 8",
     "subtracting does not always give something smaller: 5 - (-3) = 8."),
)


def _false_generalisation(text: str) -> Finding | None:
    if not _UNIVERSAL.search(text):
        return None
    for pattern, counter, why in _CLAIM_TESTS:
        if pattern.search(text):
            return Finding(
                "false_generalisation",
                f"It states a rule that does not hold: {why}",
                f"State the rule for the case it covers, or drop it. "
                f"Counterexample: {counter}.")
    return None


def check(examples: list[Any], *, grade: str = "") -> Report:
    """Every worked example, against the words around its arithmetic."""
    report = Report()
    for example in (examples or []):
        if not isinstance(example, dict):
            continue
        report.checked += 1
        text = _text_of(example)
        for finding in (_direction_fault(text), _change_fault(text),
                        _false_generalisation(text)):
            if finding:
                report.findings.append(finding)

    # Difficulty is a property of the set, not of any one example in it.
    below = _too_easy(examples, grade)
    if below:
        report.findings.append(below)
    return report


def check_material(material: dict[str, Any], *, grade: str = "") -> Report:
    """Every worked example in a lesson-material artifact."""
    examples: list[Any] = []
    for piece in (material.get("material") or []):
        if isinstance(piece, dict):
            examples += [e for e in (piece.get("worked_examples") or [])
                         if isinstance(e, dict)]
    return check(examples, grade=grade)

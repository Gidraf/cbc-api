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


def _too_easy(examples: list[Any], grade: str, subject: str,
              strand: str = "", sub_strand: str = "") -> Finding | None:
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
    from . import demand_profile

    judgement = demand_profile.judge(examples, grade=grade, subject=subject or "",
                                     strand=strand, sub_strand=sub_strand)

    # Only the ARITHMETIC half applies here. The command-word half asks what a
    # task demands OF THE LEARNER, and a worked example demands nothing of them
    # — it is the teacher showing a method. "Find its temperature after 2
    # hours" is a demonstration, and failing it for not saying "evaluate" would
    # fail every worked example in every guide in the system.
    #
    # That half is measured where it belongs, on the questions, activities and
    # experiments that do ask the learner something.
    if not judgement.numeric.below:
        return None
    return Finding("below_the_grade", judgement.numeric.says(),
                   judgement.numeric.fix())


def _duplicates(examples: list[Any], grade: str, subject: str) -> list[Finding]:
    """The same worked example printed twice in one guide.

    A Grade 9 integers guide taught `3 + 5 × 2` in Lesson 2 and taught it again,
    with the same two steps and the same answer, in Lesson 5. Nothing measured
    it: each copy is a full-length, correct, well-formed example, so a check
    that reads forwards sees two good lessons.

    Matched on the ARITHMETIC rather than the words, because a second copy is
    usually reworded — the tell is that the sums are identical.
    """
    from . import task_demand

    seen: dict[str, int] = {}
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        demand = task_demand.measure_item(example)
        key = re.sub(r"\s+", "", demand.expression)
        if not key or demand.operations == 0:
            continue
        if key in seen:
            findings.append(Finding(
                "repeated_example",
                f"Example {index} works out \"{demand.expression}\", which "
                f"example {seen[key]} has already worked out. A learner "
                f"reaching it has been taught nothing new, and the lesson "
                f"holding it is a lesson the guide did not really write.",
                "Replace it, or move the second copy to where it is revision "
                "and say that is what it is."))
        else:
            seen[key] = index
    return findings


# ── the arithmetic, against the engine, step by step ─────────────────────────
#
# `worked_solutions.check` has existed for the whole of this work and was
# called from nowhere. It solves the EXERCISES a guide sets and never checked
# the guide's own worked examples, which is where two errors reached a page:
#
#   "-(-2) x (-4) = 2 x 4 = 8"      the term is -8; the minus was distributed
#                                   onto one factor and the sign flipped twice
#   "(-15/3 - (-2)(-4) + 6) / (-2(3) + (-4))  =  -7"
#                                   -7 is the NUMERATOR. The denominator was
#                                   worked out, written down, and never used.
#
# The same expression appeared in two lessons of one guide with two different
# answers, and neither was right. Every step is now solved on its own, because
# a fault at step 2 is worth naming at step 2 rather than as a wrong total.

_EQUATION = re.compile(r"^(?P<lhs>[^=]{2,120}?)\s*=\s*(?P<rhs>[^=]{1,60})$")

# Enough to catch a guide, bounded so a 500-item batch cannot spend a minute
# in the solver.
_MAX_CHECKED_EXAMPLES = 40
_MAX_CHECKED_STEPS = 12


def _arithmetic_faults(examples: list[Any]) -> list[Finding]:
    from . import worked_solutions

    findings: list[Finding] = []
    for index, example in enumerate(examples[:_MAX_CHECKED_EXAMPLES] or [],
                                    start=1):
        if not isinstance(example, dict):
            continue

        # Each step's own equation. A wrong step is worth naming where it is.
        steps = [s for s in (example.get("steps") or []) if isinstance(s, dict)]
        for number, step in enumerate(steps[:_MAX_CHECKED_STEPS], start=1):
            match = _EQUATION.match(str(step.get("working") or "").strip())
            if not match:
                continue
            verdict = worked_solutions.check(match.group("lhs"),
                                             match.group("rhs"))
            if verdict["checked"] and verdict["agrees"] is False:
                findings.append(Finding(
                    "step_is_wrong",
                    f"Example {index}, step {number}: "
                    f"\"{match.group('lhs').strip()}\" is "
                    f"{verdict['engine_answer']}, and the step says "
                    f"{match.group('rhs').strip()}.",
                    "Work the step again. Every step after this one inherits "
                    "it, and a learner imitating the guide will make the same "
                    "mistake in the same place."))

        # And the answer, against the WHOLE statement — which is the only thing
        # that catches an answer that solves part of the question.
        statement = str(example.get("statement") or "")
        answer = str(example.get("answer") or "")
        verdict = worked_solutions.check(statement, answer)
        if verdict["checked"] and verdict["agrees"] is False:
            findings.append(Finding(
                "answer_disagrees",
                f"Example {index} answers {answer.strip()}; the engine makes "
                f"it {verdict['engine_answer']}. If the steps are right, the "
                f"answer has stopped short of the whole expression — a "
                f"numerator reported as the value of a fraction is the "
                f"commonest form of this.",
                "Carry the working through to the end of the expression and "
                "state that as the answer."))
    return findings


# The shape every worked example takes, so a learner meets one format.
_SHAPE_RULES: tuple[tuple[str, str], ...] = (
    ("statement", "the task it works, written out"),
    ("steps", "numbered steps"),
    ("answer", "final answer on its own line"),
)


def _shape_faults(examples: list[Any]) -> list[Finding]:
    """Whether every example is laid out the same way.

    A guide whose examples are each formatted differently is a guide a learner
    has to re-learn how to read on every page, and it is the difference between
    a booklet somebody prints and one somebody sells. The rule is deliberately
    plain: a task, numbered steps that each say WHY, and one final answer.
    """
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        # An expression lifted out of teaching prose is not a worked example
        # and has no steps by construction. Reporting all ten of them as
        # badly laid out is the crying-wolf failure this check exists to
        # avoid — its subject is examples somebody actually authored.
        if example.get("from_prose"):
            continue
        missing = [what for key, what in _SHAPE_RULES if not example.get(key)]
        if missing:
            findings.append(Finding(
                "solution_not_uniform",
                f"Example {index} has no " + ", no ".join(missing) + ".",
                "Every worked example takes the same shape: the task, "
                "numbered steps, and one final answer."))
            continue
        steps = [s for s in (example.get("steps") or []) if isinstance(s, dict)]

        # Display maths inside a sentence breaks the sentence. A reason reading
        # "First, adding $$-5$$ and $$8$$ gives $$3$$" prints as prose and
        # centred numbers alternating down the page, one line each — which is
        # what a Grade 9 guide did to every reason in Example 5.1.
        staircase = [n for n, st in enumerate(steps, start=1)
                     if "$$" in str(st.get("because") or "")]
        if staircase:
            findings.append(Finding(
                "solution_not_uniform",
                f"Example {index} puts display maths inside the reason for "
                f"step(s) {', '.join(str(n) for n in staircase[:6])}. Each "
                f"expression takes a centred line of its own, so the sentence "
                f"prints as a staircase of numbers down the page.",
                "Use single dollars inside a sentence. Display maths belongs "
                "on the working line, not in the words explaining it."))

        unreasoned = [n for n, s in enumerate(steps, start=1)
                      if not str(s.get("because") or "").strip()]
        if unreasoned:
            findings.append(Finding(
                "solution_not_uniform",
                f"Example {index} has {len(unreasoned)} step(s) with no reason "
                f"given: {', '.join(str(n) for n in unreasoned[:6])}.",
                "Each step says WHY it is taken, not what it did. \"Make the "
                "denominators the same so the parts are the same size\", never "
                "\"now we rewrite the fractions\"."))
    return findings


# Quantities that CANNOT be negative, and the words that name them.
#
# A reviewer found two of these in one guide: "in a survey, if more people
# prefer tea over coffee, we can represent this as a positive integer for tea
# and a negative for coffee", and "when cooking, if a recipe requires you to
# subtract KES 20 for ingredients you already have".
#
# There is no such thing as -15 people, and a recipe is measured in grams and
# millilitres rather than shillings. Both read as helpful real-life context and
# both teach a learner something false about what a negative number means —
# which is worse than a dry example, because the learner believes it.
#
# What is DELIBERATELY not here: temperature, elevation, altitude, balance,
# account, profit, score. Every one of those is genuinely signed, and they are
# the contexts the sub-strand exists to teach.
_CANNOT_BE_NEGATIVE: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("a count of people or things",
     re.compile(r"\b(surveys?|respondents?|frequenc\w+|tally|how many|"
                r"number of (?:people|learners|students|pupils|items|"
                r"responses|votes))\b", re.I),
     "counts and frequencies start at zero. There is no such thing as -15 "
     "people preferring coffee: a category is not a sign, and a learner told "
     "otherwise will write negative frequencies in a data-handling paper."),
    ("a mass, length or volume",
     re.compile(r"\b(recipes?|ingredients?|cooking|grams?|kilograms?|"
                r"millilitres?|litres?)\b", re.I),
     "a recipe is measured in grams and millilitres, not in shillings, and a "
     "quantity of an ingredient cannot be negative. Use a context that is "
     "genuinely signed — temperature, altitude, or money owed."),
)

_GOES_NEGATIVE = re.compile(
    r"\bnegative\b|\bbelow zero\b|\bminus\b|\bsubtract\w*\b|"
    r"(?<![\d)])-\s?\d", re.I)


def _impossible_negative(examples: list[Any]) -> list[Finding]:
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        text = _text_of(example)
        if not _GOES_NEGATIVE.search(text):
            continue
        for what, pattern, why in _CANNOT_BE_NEGATIVE:
            if pattern.search(text):
                findings.append(Finding(
                    "impossible_negative",
                    f"Example {index} puts a negative value on {what}: {why}",
                    "Move the example to a quantity that really is signed, or "
                    "drop it. A false real-life analogy is worse than a dry "
                    "example, because a learner believes it."))
                break
    return findings


# Notation that will print as it stands, and print as nonsense.
#
# The Grade 9 guide printed "$(6 + ×× 2$" and "$12×12× 2 - 3 + 1$" on the page
# a class reads. Both are what an unbalanced brace or a doubled command leaves
# behind, and the exercise beside them then answered "10 - 22 + 5 = 8", because
# the expression the solver was handed was not the expression on the page.
_MANGLED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[+×÷*/^-]\s*[×÷*/^]"),
     "two operators in a row"),
    (re.compile(r"\d\s*[×÷]\s*\d+\s*[×÷]\s*\d+\s*[×÷]"),
     "a run of operators no expression has"),
    (re.compile(r"[+×÷*/^-]\s*\$"), "an expression that ends on an operator"),
    (re.compile(r"\\[a-zA-Z]+\s*\{[^}]*$"), "an unclosed LaTeX group"),
)


_LATEX_OP = re.compile(r"\\times|\\cdot|\\div|\\pm")


def _as_symbols(text: str) -> str:
    """LaTeX operators as the symbols they print, so one rule catches both."""
    return _LATEX_OP.sub(lambda m: {"\\times": "×", "\\cdot": "×",
                                    "\\div": "÷", "\\pm": "+"}[m.group(0)],
                         text or "")


def _mangled(examples: list[Any]) -> list[Finding]:
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        text = _as_symbols(_text_of(example))
        if text.count("$") % 2:
            findings.append(Finding(
                "mangled_notation",
                f"Example {index} has an odd number of dollar signs, so the "
                f"maths and the words around it run together on the page.",
                "Close every $ … $ pair."))
        for pattern, what in _MANGLED:
            found = pattern.search(text)
            if found:
                findings.append(Finding(
                    "mangled_notation",
                    f"Example {index} contains {what}: "
                    f"\"{found.group(0).strip()}\". This prints exactly as it "
                    f"stands, in front of a class.",
                    "Write the expression again. A learner cannot answer what "
                    "nobody can read, and a solver given it computes something "
                    "else."))
                break
    return findings


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


def check(examples: list[Any], *, grade: str = "", subject: str | None = None,
          strand: str = "", sub_strand: str = "") -> Report:
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
    below = _too_easy(examples, grade, subject, strand, sub_strand)
    if below:
        report.findings.append(below)
    # And so is repetition: a second copy is only visible beside the first.
    report.findings += _duplicates(examples, grade, subject or "")
    report.findings += _mangled(examples)
    report.findings += _impossible_negative(examples)
    report.findings += _shape_faults(examples)
    report.findings += _arithmetic_faults(examples)
    return report


def check_material(material: dict[str, Any], *, grade: str = "",
                   subject: str | None = None, strand: str = "",
                   sub_strand: str = "") -> Report:
    """Every worked example in a lesson-material artifact."""
    examples: list[Any] = []
    for piece in (material.get("material") or []):
        if isinstance(piece, dict):
            examples += [e for e in (piece.get("worked_examples") or [])
                         if isinstance(e, dict)]
    return check(examples, grade=grade, subject=subject, strand=strand,
                 sub_strand=sub_strand)


def check_notes(notes: dict[str, Any], *, grade: str = "",
                subject: str | None = None, strand: str = "",
                sub_strand: str = "") -> Report:
    """The teacher's guide, against the same floor its material is held to.

    The plan station receives the demand block and was never measured against
    it, so a plan could be built entirely from `3 + 5 = 8` and pass — and the
    material station then inherits those examples and writes them out. Checking
    the material and not the plan is checking the copy and not the original.
    """
    texts: list[str] = []
    for module in (notes.get("modules") or notes.get("hour_modules") or []):
        if not isinstance(module, dict):
            continue
        texts.append(str(module.get("teacher_exposition") or ""))
        for segment in (module.get("exposition_segments") or []):
            if isinstance(segment, dict):
                texts.append(str(segment.get("body") or ""))

    from . import task_demand

    items: list[Any] = []
    for text in texts:
        items += task_demand.items_in_prose(text)

    # Worked examples where a plan happens to carry them, judged in full.
    for module in (notes.get("modules") or notes.get("hour_modules") or []):
        if isinstance(module, dict):
            items += [e for e in (module.get("worked_examples") or [])
                      if isinstance(e, dict)]

    return check(items, grade=grade, subject=subject, strand=strand,
                 sub_strand=sub_strand)

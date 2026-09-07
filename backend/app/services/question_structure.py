"""Whether a question has the SHAPE its type promises.

An item can be well written, correctly cited, curriculum-aligned, and still
unusable — because a multiple-choice question came back with two options, a
structured question came back as one undivided paragraph, or a calculation
came back with no working expected and one mark for an answer that takes four
steps to reach. None of that is caught by asking a model whether the question
is good; all of it is caught by counting.

This is deliberately mechanical and deliberately strict. It is the gate that
makes volume safe: a review queue of 250 items a day is only worth having if
a malformed item is stopped before a person spends attention on it.

The rules are KICD's own conventions for assessment items, expressed per
structure. They are not style preferences — each one is a way an item fails in
a printed paper or in a marking room.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..question_models import ALL_QUESTION_TYPES, SELECTED_RESPONSE

# A finding that stops an item, and one that only warns. Anything that would
# make the item unanswerable or unmarkable stops it.
BLOCKS = "blocks"
WARNS = "warns"


@dataclass
class Finding:
    code: str
    severity: str
    says: str
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "severity": self.severity,
                "says": self.says, "fix": self.fix}


@dataclass
class Verdict:
    question_id: str = ""
    question_type: str = ""
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity == BLOCKS for f in self.findings)

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def score(self) -> float:
        """100 for clean; a block costs far more than a warning."""
        if not self.findings:
            return 100.0
        lost = sum(25.0 if f.severity == BLOCKS else 6.0 for f in self.findings)
        return round(max(0.0, 100.0 - lost), 1)

    def to_dict(self) -> dict[str, Any]:
        return {"question_id": self.question_id,
                "question_type": self.question_type,
                "blocked": self.blocked, "score": self.score,
                "findings": [f.to_dict() for f in self.findings]}


# How many options KICD sets for a selected-response item. Four is the
# convention; three is accepted; two is a coin toss and is refused.
MIN_OPTIONS = 3
MAX_OPTIONS = 5
# Below this a stem is a fragment rather than a question.
MIN_STEM = 15
# A structured item that cannot be split into parts is not structured.
MIN_PARTS = 2
# Working is expected above this many marks, whatever the type.
WORKING_EXPECTED_ABOVE = 2.0

_CALCULATION_TYPES = {"quantitative_calculation"}
_STRUCTURED_TYPES = {"structured_inquiry", "structured_scenario"}
_ESSAY_TYPES = {"extended_essay"}

# "All of the above", "None of these" — an option that tests reading rather
# than the curriculum, and that breaks every occlusion and shuffle.
_META_OPTION = re.compile(
    r"^\s*(all|none|both|neither)\s+(of\s+)?(the\s+)?(above|these|those|them)\b", re.I)
_HAS_NUMBER = re.compile(r"\d")
_COMMAND_WORDS = re.compile(
    r"\b(state|name|list|describe|explain|calculate|work out|find|determine|"
    r"identify|outline|discuss|compare|evaluate|justify|show|draw|label|"
    r"complete|solve|derive|prove|suggest|classify|analyse|analyze)\b", re.I)


def _marks_of(question: dict[str, Any]) -> float:
    pedagogy = question.get("pedagogy") or {}
    try:
        total = float(pedagogy.get("max_marks") or 0)
    except (TypeError, ValueError):
        total = 0.0
    if total:
        return total
    return sum(float(p.get("marks") or 0)
               for p in (question.get("structured_parts") or [])
               if isinstance(p, dict))


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def check(question: dict[str, Any]) -> Verdict:
    """One item against the shape its own type promises."""
    question = question if isinstance(question, dict) else {}
    q_type = str(question.get("question_type") or "").strip().lower()
    verdict = Verdict(
        question_id=str(question.get("question_id") or question.get("display_label") or ""),
        question_type=q_type)
    add = lambda *a: verdict.findings.append(Finding(*a))  # noqa: E731

    if q_type not in ALL_QUESTION_TYPES:
        add("unknown_type", BLOCKS,
            f"'{q_type or '(blank)'}' is not a question type this system sets.",
            f"Use one of: {', '.join(sorted(ALL_QUESTION_TYPES))}.")
        return verdict

    stem = _text(question.get("question_text"))
    marks = _marks_of(question)
    parts = [p for p in (question.get("structured_parts") or []) if isinstance(p, dict)]
    options = [o for o in (question.get("options") or []) if isinstance(o, dict)]

    # ── the stem ────────────────────────────────────────────────────────────
    if len(stem) < MIN_STEM:
        add("stem_too_short", BLOCKS,
            f"The stem is {len(stem)} characters. That is a fragment, not a question.",
            "Write the question as a full instruction a learner can act on.")
    elif not _COMMAND_WORDS.search(stem) and not stem.rstrip().endswith("?"):
        add("no_command_word", WARNS,
            "The stem neither asks a question nor gives an instruction.",
            "Begin with what the learner must DO — state, calculate, explain, "
            "compare — or end with a question mark.")

    if not marks:
        add("no_marks", BLOCKS,
            "The item carries no marks, so it cannot be put on a paper.",
            "Set `pedagogy.max_marks`, or give every part its own marks.")

    # ── selected response ───────────────────────────────────────────────────
    if q_type in SELECTED_RESPONSE:
        if q_type == "true_false":
            pass  # its two options are the point
        elif len(options) < MIN_OPTIONS:
            add("too_few_options", BLOCKS,
                f"{len(options)} option(s). Below {MIN_OPTIONS} the item is a "
                f"coin toss rather than an assessment.",
                f"Write {MIN_OPTIONS}–{MAX_OPTIONS} options, the wrong ones "
                f"being mistakes a learner actually makes.")
        elif len(options) > MAX_OPTIONS:
            add("too_many_options", WARNS,
                f"{len(options)} options is more than a paper sets.",
                f"Keep it to {MAX_OPTIONS}.")

        marked = [o for o in options if o.get("is_correct")]
        stated = _text(question.get("correct_answer"))
        if not marked and not stated:
            add("no_key", BLOCKS,
                "No option is marked correct and no answer is stated. The item "
                "cannot be marked.",
                "Mark the correct option, or set `correct_answer`.")
        elif len(marked) > 1:
            add("several_keys", BLOCKS,
                f"{len(marked)} options are marked correct.",
                "Exactly one, unless the stem says how many to choose.")

        for option in options:
            if _META_OPTION.match(_text(option.get("text"))):
                add("meta_option", BLOCKS,
                    f"Option {option.get('id') or ''} is "
                    f"\"{_text(option.get('text'))[:34]}\". It tests reading "
                    f"rather than the curriculum, and it cannot be shuffled or "
                    f"occluded.",
                    "Replace it with a distractor that is a real mistake.")
                break

        blank = [o for o in options if not _text(o.get("text"))]
        if blank:
            add("blank_option", BLOCKS, f"{len(blank)} option(s) have no text.",
                "Every option is printed; an empty one prints as a gap.")

        ids = [str(o.get("id") or "").strip() for o in options]
        if len(set(i for i in ids if i)) != len([i for i in ids if i]):
            add("duplicate_option_ids", BLOCKS,
                "Two options share the same letter.",
                "Letter them A, B, C, D in order.")

        seen = [_text(o.get("text")).lower() for o in options]
        if len(set(s for s in seen if s)) != len([s for s in seen if s]):
            add("duplicate_options", BLOCKS,
                "Two options say the same thing, so one of them cannot be wrong.",
                "Make every distractor a different mistake.")

        if marks > 2:
            add("overweight_selection", WARNS,
                f"{marks:g} marks for choosing one option.",
                "A selected-response item is normally worth 1 mark.")
    elif options:
        add("options_on_written_item", BLOCKS,
            f"A {q_type} item carries {len(options)} options. It will print as "
            f"multiple choice.",
            "Remove the options, or set the type to multiple_choice.")

    # ── structured ──────────────────────────────────────────────────────────
    if q_type in _STRUCTURED_TYPES:
        if len(parts) < MIN_PARTS:
            add("not_structured", BLOCKS,
                f"A structured item with {len(parts)} part(s) is a short-answer "
                f"question wearing the wrong label.",
                f"Break it into at least {MIN_PARTS} lettered parts, or set the "
                f"type to short_answer.")
        else:
            part_marks = sum(float(p.get("marks") or 0) for p in parts)
            if part_marks and marks and abs(part_marks - marks) > 0.01:
                add("parts_do_not_total", BLOCKS,
                    f"The parts add to {part_marks:g} but the item is worth "
                    f"{marks:g}. A marker cannot reconcile that.",
                    "Make the parts total the item's marks.")
            if any(not float(p.get("marks") or 0) for p in parts):
                add("part_without_marks", BLOCKS,
                    "A part carries no marks, so nothing can be awarded for it.",
                    "Give every part its own allocation.")
            if any(not _text(p.get("part_id")) for p in parts):
                add("unlettered_part", WARNS,
                    "A part has no letter, so a script cannot refer to it.",
                    "Letter them (a), (b), (c).")
    elif parts and q_type not in _ESSAY_TYPES:
        if len(parts) > 1:
            add("parts_on_unstructured_item", WARNS,
                f"A {q_type} item has {len(parts)} parts.",
                "Set the type to structured_inquiry or structured_scenario.")

    # ── calculation ─────────────────────────────────────────────────────────
    if q_type in _CALCULATION_TYPES:
        if not _HAS_NUMBER.search(stem) and not any(
                _HAS_NUMBER.search(_text(p.get("sub_question"))) for p in parts):
            add("calculation_without_quantities", BLOCKS,
                "A calculation item states no quantities to work with.",
                "Give the figures the learner is to use.")
        if marks > 1 and not _text(question.get("marking_scheme")):
            add("no_working_expected", BLOCKS,
                f"{marks:g} marks for a calculation with no marking scheme. "
                f"Method marks cannot be awarded.",
                "Write the scheme step by step, with marks against the steps.")

    # ── written response ────────────────────────────────────────────────────
    if q_type in _ESSAY_TYPES:
        if marks < 4:
            add("essay_underweight", WARNS,
                f"{marks:g} marks for an extended response.",
                "An essay a learner plans and writes carries more than this.")
        rubric = question.get("rubric") or {}
        if not _text(question.get("marking_scheme")) and not rubric:
            add("no_rubric", BLOCKS,
                "An extended response with neither a marking scheme nor a "
                "rubric cannot be marked consistently by two people.",
                "Give it a four-level rubric, or a scheme.")

    # ── diagram ─────────────────────────────────────────────────────────────
    if q_type == "diagram_based" and not question.get("diagram"):
        add("no_diagram", BLOCKS,
            "A diagram question with no diagram bound to it cannot be printed.",
            "Bind it to a drawn figure, or set another type.")

    # ── marking, for everything written ─────────────────────────────────────
    if q_type not in SELECTED_RESPONSE:
        if not _text(question.get("model_answer")) and not _text(question.get("marking_scheme")):
            add("unmarkable", BLOCKS,
                "No model answer and no marking scheme.",
                "Write what a full-mark response contains.")
        elif marks > WORKING_EXPECTED_ABOVE and not _text(question.get("marking_scheme")):
            add("no_scheme_for_the_marks", WARNS,
                f"{marks:g} marks with a model answer but no scheme. Part marks "
                f"will be awarded differently by different markers.",
                "Break the answer into steps and put marks against them.")

    return verdict


def check_all(questions: list[Any], *, grade: str = "",
              subject: str | None = None, strand: str = "",
              sub_strand: str = "") -> dict[str, Any]:
    """A batch, and whether it is fit to enter a review queue.

    Volume is the point of this: 500 items a day is only worth generating if
    the malformed ones never reach a person.

    `grade` adds the one judgement that cannot be made item by item: whether
    the batch is pitched at the grade at all. A paper may contain an easy
    opener — every real paper does — but a Grade 9 paper whose hardest item is
    one addition is not a Grade 9 paper, and no per-item rule can see that.

    That judgement has two halves, because two things go wrong independently.
    A set can be arithmetically demanding and ask only for recall, and it can
    ask for an evaluation of nothing harder than 7 - 4. The second half is what
    covers History, CRE, English and every other subject with no arithmetic in
    it at all — there, the command word IS the difficulty.

    `sub_strand` is what lets the sub-strand's own extracted profile be used in
    place of the band floor. Without it the band floor applies, which is
    coarser and still a floor.
    """
    verdicts = [check(q if isinstance(q, dict) else {}) for q in (questions or [])]
    blocked = [v for v in verdicts if v.blocked]
    clean = [v for v in verdicts if v.ok]
    total = len(verdicts) or 1

    counts: dict[str, int] = {}
    for verdict in verdicts:
        for finding in verdict.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1

    # The batch judgement. It is deliberately NOT a verdict in the list: no
    # single question is at fault, so attaching it to one would send a reviewer
    # to an item that is perfectly fine. It counts as a finding and it blocks
    # the batch, and it stays a property of the batch.
    demand: dict[str, Any] = {}
    batch_blocked = False
    if grade:
        from . import demand_profile

        judgement = demand_profile.judge(
            questions or [], grade=grade, subject=subject or "",
            strand=strand, sub_strand=sub_strand)
        demand = judgement.to_dict()
        if judgement.numeric.below:
            batch_blocked = True
            counts["batch_below_the_grade"] = 1
        if judgement.command.below:
            batch_blocked = True
            counts["batch_asks_too_little"] = 1

    return {
        "batch_blocked": batch_blocked,
        "total": len(verdicts),
        "clean": len(clean),
        "blocked": len(blocked),
        "passed": len(verdicts) - len(blocked),
        "score": round(sum(v.score for v in verdicts) / total, 1),
        "by_finding": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "demand": demand,
        "verdicts": [v.to_dict() for v in verdicts],
    }

"""Whether a batch of questions is RIGHT — not whether it is well formed.

The structure gate counts: options, parts, marks, a scheme where marks need
one. Everything it holds is a real fault, and none of it is the fault a
printed paper is remembered for. That one is a key that is wrong, an
answer the marking scheme disagrees with, a distractor that is also
correct, the same sum set three times, or a Grade 9 paper whose hardest
item is `7 − 4`. The teacher's guide has been checked for exactly these
since the notes station was rebuilt; the questions — the product that is
actually sold — were not.

So this does to a batch what `notes_remediation._inspect` does to a guide:

- every answer the engine can solve is solved, and a key it disagrees with
  is named — the option it should have been, where one of the options is
  the engine's answer;
- a distractor the engine agrees with is a second right answer;
- the marking scheme's own equations are checked line by line;
- the batch is read as a set of worked examples, which is what the demand,
  duplicate, story and missing-operation checks already know how to read;
- an item that sets the guide's worked example again, or one already in the
  bank, is a repeat;
- the set has to reach every outcome the design lists, has to ask above
  recall somewhere, and has to use the figures the sub-strand drew.

Each finding names the item it is about, so a rewrite can be aimed at the
item and not at the batch.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-question-check")

# Bounded so a 200-item bank cannot spend a minute in the solver per pass.
MAX_ENGINE_ITEMS = 60

_DIAGRAM_WORDS = re.compile(r"\b(diagram|figure|map|sketch|graph|chart|illustration)\b(?! (?:paper|below is not))", re.I)
_LOW_BLOOM = {"recall", "remember", "understanding", "understand", "knowledge", "comprehension"}
_MATH_SPAN = re.compile(r"\$\$?(.+?)\$\$?", re.S)
_KEY_IN_STEM = re.compile(r"(?:=|\bis\b|\bequals\b|\banswer is\b)\s*(?:\$)?\s*(-?\d+(?:\.\d+)?)")


@dataclass
class Finding:
    kind: str
    says: str
    fix: str = ""
    # Which items, by question_id. Empty for a finding about the set.
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "says": self.says, "fix": self.fix, "items": list(self.items)}


@dataclass
class Report:
    checked: int = 0
    findings: list[Finding] = field(default_factory=list)
    # Deterministic repairs made while checking: a key moved to the option
    # the engine agrees with. Named so the console can show them.
    repaired: list[str] = field(default_factory=list)
    engine_checked: int = 0
    engine_agreed: int = 0

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def faulty_items(self) -> set[str]:
        return {i for f in self.findings for i in f.items}

    @property
    def score(self) -> float:
        """100 for a clean set. Each faulty item costs its share of 80; each
        finding about the set as a whole costs 4 — so ten items with two
        wrong and no outcome coverage stand at 100 − 16 − 4 = 80."""
        if not self.checked:
            return 0.0
        per_item = 80.0 / self.checked
        set_level = sum(1 for f in self.findings if not f.items)
        return round(max(0.0, 100 - per_item * len(self.faulty_items) - 4 * set_level), 1)

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "clean": self.clean, "score": self.score,
                "faulty_items": sorted(self.faulty_items),
                "findings": [f.to_dict() for f in self.findings],
                "repaired": list(self.repaired),
                "engine": {"checked": self.engine_checked, "agreed": self.engine_agreed}}


# ── reading an item ──────────────────────────────────────────────────────────

def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _id(question: dict[str, Any]) -> str:
    return str(question.get("question_id") or question.get("display_label") or "")


def _label(question: dict[str, Any], index: int) -> str:
    return str(question.get("display_label") or f"Q{index}")


def _stem(question: dict[str, Any]) -> str:
    return " ".join(p for p in (_text(question.get("stimulus_context")),
                                _text(question.get("question_text"))) if p)


def _key_option(question: dict[str, Any]) -> dict[str, Any] | None:
    for option in question.get("options") or []:
        if isinstance(option, dict) and option.get("is_correct"):
            return option
    stated = _text(question.get("correct_answer")).upper()
    for option in question.get("options") or []:
        if isinstance(option, dict) and _text(option.get("id")).upper() == stated:
            return option
    return None


def _answer_of(question: dict[str, Any]) -> str:
    key = _key_option(question)
    if key is not None:
        return _text(key.get("text"))
    return _text(question.get("model_answer"))


def _scheme_lines(question: dict[str, Any]) -> list[dict[str, str]]:
    """The marking scheme as steps, where it is written as lines."""
    lines = [ln.strip(" -•*\t") for ln in str(question.get("marking_scheme") or "").splitlines()]
    return [{"working": ln} for ln in lines if ln and "=" in ln][:12]


def _as_examples(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The batch in the shape the worked-example checks read.

    `from_prose` keeps the layout rule off them — a question has no numbered
    steps by design — while the demand, duplicate and story checks still run.
    """
    out = []
    for index, question in enumerate(questions, start=1):
        statement = _stem(question)
        parts = [_text(p.get("sub_question")) for p in (question.get("structured_parts") or [])
                 if isinstance(p, dict)]
        if parts:
            statement = statement + " " + " ".join(parts)
        out.append({"statement": statement, "answer": _answer_of(question),
                    "steps": _scheme_lines(question), "_lesson": index, "from_prose": True})
    return out


# ── the arithmetic ───────────────────────────────────────────────────────────

def _check_key(question: dict[str, Any], label: str, findings: list[Finding],
               report: Report) -> None:
    """The key against the engine; then every distractor against it too."""
    from . import worked_solutions

    stem = _stem(question)
    key = _key_option(question)
    qid = _id(question)

    if key is not None:
        verdict = worked_solutions.check(stem, _text(key.get("text")))
        if not verdict["checked"]:
            return
        report.engine_checked += 1
        engine = verdict["engine_answer"]
        if verdict["agrees"]:
            report.engine_agreed += 1
        else:
            # Which option IS the engine's answer, if any. One match is a key
            # in the wrong place and is moved; none or several is a rewrite.
            matches = [o for o in (question.get("options") or [])
                       if isinstance(o, dict) and o is not key
                       and worked_solutions.check(stem, _text(o.get("text"))).get("agrees")]
            if len(matches) == 1:
                for option in question.get("options") or []:
                    if isinstance(option, dict):
                        option["is_correct"] = option is matches[0]
                question["correct_answer"] = _text(matches[0].get("id"))
                report.repaired.append(
                    f"{label}: the key was {key.get('id')} ({_text(key.get('text'))}); "
                    f"the engine makes it {engine}, which is option {matches[0].get('id')}. Moved.")
                key = matches[0]
            else:
                findings.append(Finding(
                    "wrong_key",
                    f"{label} marks option {key.get('id')} ({_text(key.get('text'))}) correct. "
                    f"The maths engine makes the answer {engine}, and "
                    + ("no option says so." if not matches else "more than one option does."),
                    "Work the item with the engine's answer as the key and one distractor "
                    "per mistake a learner actually makes.",
                    [qid]))
                return
        # A distractor that is also right is a question with two answers.
        for option in question.get("options") or []:
            if not isinstance(option, dict) or option is key:
                continue
            same = worked_solutions.check(stem, _text(option.get("text")))
            if same.get("agrees"):
                findings.append(Finding(
                    "two_right_answers",
                    f"{label}: option {option.get('id')} ({_text(option.get('text'))}) is "
                    f"also {engine}, the same value as the key.",
                    "Every distractor is a different wrong value.",
                    [qid]))
                break
        return

    # Constructed response: the model answer, and each part's.
    answer = _text(question.get("model_answer"))
    checks: list[tuple[str, str, str]] = []
    if answer:
        checks.append(("", stem, answer))
    for part in question.get("structured_parts") or []:
        if isinstance(part, dict) and _text(part.get("model_answer")):
            checks.append((f" part ({_text(part.get('part_id')) or '?'})",
                           stem + " " + _text(part.get("sub_question")),
                           _text(part.get("model_answer"))))
    for where, statement, claimed in checks:
        verdict = worked_solutions.check(statement, claimed)
        if not verdict["checked"]:
            continue
        report.engine_checked += 1
        if verdict["agrees"]:
            report.engine_agreed += 1
            continue
        findings.append(Finding(
            "wrong_answer",
            f"{label}{where} gives the answer \"{claimed[:80]}\". The maths engine makes "
            f"it {verdict['engine_answer']}.",
            "Re-work the item from the statement; the marking scheme must reach the "
            "engine's value.",
            [qid]))
        return


def _check_scheme(question: dict[str, Any], label: str, findings: list[Finding]) -> None:
    """Every `a = b` the marking scheme asserts, checked as an equation."""
    from . import example_check

    scheme = str(question.get("marking_scheme") or "")
    if "=" not in scheme:
        return
    for found in example_check.check_prose_arithmetic([scheme])[:2]:
        findings.append(Finding(
            "scheme_states_a_false_equation",
            f"{label}'s marking scheme: " + found.says.replace("The guide states", "it states"),
            "A marker awards marks against this line. Correct it.",
            [_id(question)]))


# ── repetition ───────────────────────────────────────────────────────────────

def _expression_key(statement: str, answer: str = "") -> str:
    from . import task_demand

    demand = task_demand.measure_item({"statement": statement, "answer": answer})
    if demand.operations == 0:
        return ""
    return re.sub(r"\s+", "", demand.expression)


def _word_key(statement: str) -> str:
    from .notes_remediation import _skeleton

    words = _skeleton(statement)
    return words if len(words.split()) >= 8 else ""


def _against_the_guide(questions: list[dict[str, Any]], notes: Any,
                       findings: list[Finding]) -> None:
    """An item that sets the guide's own worked example is not a new task."""
    from .notes_digest import modules_of

    seen_expr: dict[str, str] = {}
    seen_words: dict[str, str] = {}
    for number, module in enumerate(modules_of(notes), start=1):
        for example in module.get("worked_examples") or []:
            if not isinstance(example, dict):
                continue
            statement = _text(example.get("statement"))
            where = f"lesson {int(module.get('module_number') or number)}"
            key = _expression_key(statement, _text(example.get("answer")))
            if key:
                seen_expr.setdefault(key, where)
            words = _word_key(statement)
            if words:
                seen_words.setdefault(words, where)
    if not seen_expr and not seen_words:
        return
    for index, question in enumerate(questions, start=1):
        stem = _stem(question)
        key = _expression_key(stem)
        hit = seen_expr.get(key) if key else None
        if not hit:
            words = _word_key(stem)
            hit = seen_words.get(words) if words else None
        if hit:
            findings.append(Finding(
                "repeats_the_guide",
                f"{_label(question, index)} sets the worked example the guide already worked "
                f"in {hit}. A learner who read the guide has the answer.",
                "Set a new task at the same demand — new figures, new situation.",
                [_id(question)]))


def _against_the_bank(questions: list[dict[str, Any]], existing: list[dict[str, Any]],
                      findings: list[Finding]) -> None:
    """The same question already filed for this sub-strand."""
    known_text: dict[str, str] = {}
    known_expr: dict[str, str] = {}
    ids = {_id(q) for q in questions}
    for item in existing or []:
        if not isinstance(item, dict) or _id(item) in ids:
            continue
        stem = _stem(item).lower()
        if stem:
            known_text.setdefault(stem, _id(item))
        key = _expression_key(_stem(item))
        if key:
            known_expr.setdefault(key, _id(item))
    if not known_text:
        return
    for index, question in enumerate(questions, start=1):
        stem = _stem(question).lower()
        twin = known_text.get(stem)
        if not twin:
            key = _expression_key(_stem(question))
            twin = known_expr.get(key) if key else None
        if twin:
            findings.append(Finding(
                "already_in_the_bank",
                f"{_label(question, index)} is already in the question bank as {twin}.",
                "Drop it, or set a different task.",
                [_id(question)]))


def _within_the_batch(questions: list[dict[str, Any]], findings: list[Finding]) -> None:
    """Two items with the same stem. The expression-level repeat is found by
    the worked-example reading; this is the plain copy."""
    seen: dict[str, int] = {}
    for index, question in enumerate(questions, start=1):
        stem = _stem(question).lower()
        if not stem:
            continue
        if stem in seen:
            findings.append(Finding(
                "duplicate_in_batch",
                f"{_label(question, index)} is the same question as "
                f"{_label(questions[seen[stem] - 1], seen[stem])}.",
                "One of them goes.",
                [_id(question)]))
        else:
            seen[stem] = index


# ── the set ──────────────────────────────────────────────────────────────────

def _outcomes_uncovered(questions: list[dict[str, Any]], design_row: dict[str, Any] | None,
                        findings: list[Finding]) -> None:
    """Every outcome the design lists has an item against it.

    Judged by what the items RECORD — the design ref in `serves`, or the
    outcome text in `curriculum.slo_text` — never by word overlap between a
    question and an outcome: "perform combined operations on integers in
    different situations" shares no word with "Work out $(-12) + 4 \\times
    (-3)$", and the question assesses it exactly. A batch that records
    nothing is not judged; there is nothing to judge it by.
    """
    from . import design_elements
    from .notes_integrity import same_outcome

    outcomes = design_elements.by_dimension(design_row or {}, "outcomes")
    if not outcomes or len(questions) < len(outcomes):
        # Fewer items than outcomes cannot cover them; the count is the
        # operator's choice and not a fault of the batch.
        return
    served: set[str] = set()
    named: list[str] = []
    for question in questions:
        curriculum = question.get("curriculum") or {}
        served |= {str(r).strip().lower() for r in (curriculum.get("serves") or []) if str(r).strip()}
        if str(curriculum.get("slo_text") or "").strip():
            named.append(str(curriculum["slo_text"]))
    if not served and not named:
        return
    missing = []
    for outcome in outcomes:
        if outcome.ref.lower() in served:
            continue
        if any(same_outcome(outcome.text, text) for text in named):
            continue
        missing.append(outcome.text)
    if missing:
        findings.append(Finding(
            "outcome_not_assessed",
            f"{len(missing)} outcome(s) have no item against them: "
            + "; ".join(f"\"{m[:90]}\"" for m in missing[:3]) + ("…" if len(missing) > 3 else ""),
            "Write one item for each, and record the outcome it serves in `serves` "
            "(the design's ref) and `target_slo_text`."))


def _all_recall(questions: list[dict[str, Any]], findings: list[Finding]) -> None:
    if len(questions) < 4:
        return
    levels = [str((q.get("pedagogy") or {}).get("bloom_level") or "").lower() for q in questions]
    if levels and all(lv in _LOW_BLOOM for lv in levels):
        findings.append(Finding(
            "nothing_above_recall",
            "Every item asks the learner to recall or restate. Nothing asks them to "
            "apply, analyse or evaluate.",
            "Set at least a third of the items at application or above."))


def _figures_unused(questions: list[dict[str, Any]], diagrams: list[Any],
                    findings: list[Finding]) -> None:
    """The sub-strand drew figures and the paper asks about none of them."""
    drawn = [d for d in (diagrams or []) if isinstance(d, dict)
             and (d.get("svg_markup") or d.get("storage_url") or d.get("scene_document"))]
    if not drawn or len(questions) < 5:
        return
    if not any(q.get("question_type") == "diagram_based" or q.get("diagram") for q in questions):
        findings.append(Finding(
            "figures_unused",
            f"The sub-strand has {len(drawn)} drawn figure(s) and no item asks about any of them.",
            "Set at least one diagram question on a drawn figure — name its parts, "
            "read a value off it, or say what it shows."))


def _refers_to_a_figure_it_lacks(questions: list[dict[str, Any]], findings: list[Finding]) -> None:
    for index, question in enumerate(questions, start=1):
        if question.get("diagram"):
            continue
        stem = _stem(question)
        if _DIAGRAM_WORDS.search(stem) and re.search(
                r"\b(the|this|below|above|shown|study|refer|following)\b", stem, re.I):
            findings.append(Finding(
                "figure_not_supplied",
                f"{_label(question, index)} tells the learner to study a figure, and no figure "
                f"is bound to it. It will print as an instruction to look at nothing.",
                "Bind it to a drawn figure, or write it so it stands without one.",
                [_id(question)]))


def _answer_in_the_stem(questions: list[dict[str, Any]], findings: list[Finding]) -> None:
    for index, question in enumerate(questions, start=1):
        answer = _answer_of(question)
        value = re.fullmatch(r"\$?\s*(-?\d+(?:\.\d+)?)\s*\$?", answer)
        if not value:
            continue
        for match in _KEY_IN_STEM.finditer(_text(question.get("question_text"))):
            if match.group(1) == value.group(1):
                findings.append(Finding(
                    "answer_in_the_stem",
                    f"{_label(question, index)} states its own answer ({value.group(1)}) in the "
                    f"question.",
                    "Take the answer out of the stem.",
                    [_id(question)]))
                break


# ── the worked-example reading ───────────────────────────────────────────────

_EXAMPLE_REF = re.compile(r"\b[Ee]xample (\d+)\b")


def _as_worked_examples(questions: list[dict[str, Any]], *, grade: str, subject: str,
                        strand: str, sub_strand: str, findings: list[Finding]) -> None:
    """Demand, repetition, story faults and missing operations, read the way
    the guide's examples are read."""
    from . import example_check

    examples = _as_examples(questions)
    try:
        report = example_check.check(examples, grade=grade, subject=subject,
                                     strand=strand, sub_strand=sub_strand)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Worked-example reading of the batch failed: %s", exc)
        return
    already = {i for f in findings if f.kind in ("wrong_key", "wrong_answer", "two_right_answers",
                                                  "duplicate_in_batch", "already_in_the_bank")
               for i in f.items}
    for found in report.findings:
        if found.kind == "solution_not_uniform":
            continue
        numbers = list(found.lessons) or [int(n) for n in _EXAMPLE_REF.findall(found.says)]
        items = [_id(questions[n - 1]) for n in numbers if 1 <= n <= len(questions)]
        # The engine has already named this item's answer, or the copy is
        # already going: a second finding on it is the same finding twice.
        if found.kind in ("answer_disagrees", "step_is_wrong", "repeated_example") \
                and items and all(i in already for i in items):
            continue
        says = _EXAMPLE_REF.sub(lambda m: _label(questions[int(m.group(1)) - 1], int(m.group(1)))
                                if 1 <= int(m.group(1)) <= len(questions) else m.group(0),
                                found.says)
        findings.append(Finding(found.kind, says, found.fix, sorted(set(items))))


# ── how hard each item is, for the paper as a whole ─────────────────────────
#
# A KJSEA paper whose Section A opened with "identify what the integer −3
# represents" and "state the integer for a debt of KSh 3,400" passed every
# check: each item was well formed, the keys were right, and the set-level
# demand rule only failed a paper where NOTHING reached the grade. A paper
# is judged on its typical item. So each item is placed on a rung, and the
# weak ones beyond a small allowance fail on their own — which is what sends
# them back to be rewritten, and what lets the composer pass over them.

_RECALL_STEM = re.compile(
    r"\b(state|identify|name|write|give)\b.{0,60}\b(integer|sign|directed number)\b"
    r"|\bwhat (does|is) (the )?(integer|sign)\b.{0,40}\brepresent"
    r"|\bwhich (integer|sign) represents\b", re.I)

TRIVIAL, BELOW, AT, UNMEASURED = "trivial", "below", "at", "unmeasured"
_DEGREES = re.compile(r"\^\s*\\?\{?\\circ\}?|°")
_QUANTITY = re.compile(r"(?<![A-Za-z])[-−+]?\d+(?:[.,]\d+)?")


def rung_of(question: dict[str, Any], *, grade: str, subject: str) -> str:
    """Where one item sits against the grade's floor."""
    from . import task_demand

    if not task_demand.has_floor(subject):
        return UNMEASURED
    example = _as_examples([question])[0]
    # A degree sign is not an exponent: `$-3^\\circ$C` measured as "-3 ^".
    example["statement"] = _DEGREES.sub("", example["statement"])
    demand = task_demand.measure_item(example)
    floor = task_demand.floor_for(grade, subject)
    stem = _stem(question)
    # "State the integer that represents…", "identify what −3 represents":
    # reading a sign, whatever situation it is dressed in.
    if _RECALL_STEM.search(stem) and demand.operations <= 1 \
            and len(question.get("structured_parts") or []) < 2:
        return TRIVIAL
    if demand.word_problem or not demand.measurable:
        # A situation is judged by the work it holds, not by the lines of
        # working a question does not carry: "was −3°C, rose 9, fell 14" is
        # three quantities and two operations of real work with no operator
        # in sight, and `−450 + 750 − 320` set as a trader's day is a
        # three-step problem whatever one line of scheme says.
        quantities = len(_QUANTITY.findall(_DEGREES.sub("", stem)))
        operations = max(demand.total_operations, quantities - 1)
        needed = floor.operations if floor else 2
        if quantities >= 3 or operations >= needed:
            return AT
        return BELOW if (demand.measurable or quantities >= 2) else UNMEASURED
    return BELOW if task_demand.check_item(example, grade, subject).below else AT


# The share of a paper that may sit below the grade: an easy opener or two.
WEAK_SHARE = 0.25


def _weak_items(questions: list[dict[str, Any]], *, grade: str, subject: str,
                findings: list[Finding]) -> None:
    rungs = {_id(q): rung_of(q, grade=grade, subject=subject) for q in questions}
    weak = [q for q in questions if rungs[_id(q)] in (TRIVIAL, BELOW)]
    if len(questions) < 4 or not weak:
        return
    allowed = max(1, int(math.ceil(WEAK_SHARE * len(questions))))
    if len(weak) <= allowed:
        return
    # The trivial ones first, then the merely-below, so the allowance is
    # spent on the least bad.
    # The allowance goes to the least bad, so the trivial ones are the
    # ones sent back.
    weak.sort(key=lambda q: 0 if rungs[_id(q)] == BELOW else 1)
    for question in weak[allowed:]:
        label = _label(question, questions.index(question) + 1)
        why = ("asks the learner to read a sign, not to work anything"
               if rungs[_id(question)] == TRIVIAL else
               "is a one-step calculation below what this grade's paper sets")
        findings.append(Finding(
            "below_the_grade_item",
            f"{label} {why}. {len(weak)} of {len(questions)} items sit below the grade; "
            f"a paper may carry {allowed}.",
            "Set it at the grade: a combined operation with a bracket or a sign rule that decides "
            "the answer, or a two-step situation with the figures given.",
            [_id(question)]))


# ── entry ────────────────────────────────────────────────────────────────────

def check(questions: list[dict[str, Any]], *, grade: str = "", subject: str = "",
          strand: str = "", sub_strand: str = "", notes: Any = None,
          design_row: dict[str, Any] | None = None,
          existing: list[dict[str, Any]] | None = None,
          diagrams: list[Any] | None = None) -> Report:
    """Every item, then the set. Repairs a key in place where the engine
    names the option it should have been; everything else is a finding."""
    report = Report()
    items = [q for q in (questions or []) if isinstance(q, dict)]
    report.checked = len(items)
    if not items:
        return report
    findings = report.findings

    for index, question in enumerate(items, start=1):
        label = _label(question, index)
        if index <= MAX_ENGINE_ITEMS:
            try:
                _check_key(question, label, findings, report)
                _check_scheme(question, label, findings)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Engine check of %s failed: %s", label, exc)

    _within_the_batch(items, findings)
    _against_the_guide(items, notes, findings)
    _against_the_bank(items, existing or [], findings)
    _as_worked_examples(items, grade=grade, subject=subject, strand=strand,
                        sub_strand=sub_strand, findings=findings)
    _answer_in_the_stem(items, findings)
    try:
        _weak_items(items, grade=grade, subject=subject, findings=findings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not place the items on the grade's rungs: %s", exc)
    _refers_to_a_figure_it_lacks(items, findings)
    # What the subject's own examiner checks: units and equations in the
    # sciences, passages and the paper's language in the languages.
    from . import subject_checks

    findings += subject_checks.check(items, subject=subject, grade=grade)
    _outcomes_uncovered(items, design_row, findings)
    _all_recall(items, findings)
    _figures_unused(items, diagrams or [], findings)

    # One finding per (kind, item set): the example reading and the engine
    # can name the same repeat twice.
    seen: set[tuple[str, tuple[str, ...]]] = set()
    unique: list[Finding] = []
    for found in findings:
        key = (found.kind, tuple(found.items))
        if key in seen and found.items:
            continue
        seen.add(key)
        unique.append(found)
    report.findings = unique
    return report

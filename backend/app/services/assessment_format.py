"""How a grade's national paper is shaped, so ours is shaped the same way.

The papers a Kenyan school buys look like the ones KNEC sets: a KPSEA paper
at Grade 6 is thirty multiple-choice items answered on a separate sheet,
two columns to a page, a figure or a map beside the questions that use it;
a KJSEA paper at Grade 9 is Section A — thirty multiple choice on the
answer sheet — and Section B, ten structured questions with their marks in
a table on the front. A paper in any other shape is a paper a head teacher
has to explain, and a paper in this shape needs no explaining.

The same profile pitches the items. "Not too easy, not too hard" is not a
number; it is "what a KPSEA item at this grade asks": one skill or fact per
item, a stem a learner reads in one breath, four options of which the
three wrong ones are mistakes learners make, and a spread across recall,
application and reasoning. That is written here once and shown to the
generator, so the fifty items it writes are the fifty a moderator would
keep.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .grade_order import grade_label, grade_ordinal


@dataclass(frozen=True)
class SectionSpec:
    letter: str
    heading: str
    kinds: tuple[str, ...]          # question types this section takes
    count: int                      # items on a full paper
    marks_each: int = 1             # for selected response
    marks_range: tuple[int, int] = (1, 1)   # for written items
    instructions: str = ""
    on_answer_sheet: bool = False


@dataclass(frozen=True)
class Format:
    key: str
    assessment: str                 # the masthead line
    band: str
    sections: tuple[SectionSpec, ...]
    time_allowed: str
    instructions: tuple[str, ...]
    pitch: str                      # what an item at this level is like
    columns: int = 2

    @property
    def total_items(self) -> int:
        return sum(s.count for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "assessment": self.assessment, "band": self.band,
                "time_allowed": self.time_allowed, "columns": self.columns,
                "sections": [{"letter": s.letter, "heading": s.heading, "kinds": list(s.kinds),
                              "count": s.count, "marks_each": s.marks_each,
                              "marks_range": list(s.marks_range),
                              "on_answer_sheet": s.on_answer_sheet} for s in self.sections],
                "instructions": list(self.instructions)}


_SELECTED = ("multiple_choice", "true_false", "matching", "assertion_reason")
_WRITTEN = ("short_answer", "quantitative_calculation", "structured_inquiry", "structured_scenario",
            "diagram_based", "experiment_based", "extended_essay", "practical_performance_task", "cloze")

LOWER_PRIMARY = Format(
    key="lower_primary",
    assessment="SCHOOL BASED ASSESSMENT",
    band="Lower Primary",
    sections=(
        SectionSpec("", "", _SELECTED + ("short_answer", "cloze", "diagram_based"), 20, 1, (1, 2),
                    "Answer ALL the questions."),
    ),
    time_allowed="1 hour",
    instructions=("Write your name and school in the spaces provided.",
                  "Answer ALL the questions in this paper.",
                  "Circle the correct answer, or write it in the space given."),
    pitch=(
        "Items for Grades 1–3: one thing per item, a stem of at most two short sentences in "
        "words the grade reads, a picture where the design uses one, and three or four "
        "options that are all things a young learner might choose. Counting, naming, "
        "matching, ordering and simple 'what happens when' reasoning. Nothing that needs "
        "reading beyond the grade."),
    columns=2,
)

KPSEA = Format(
    key="kpsea",
    assessment="KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT",
    band="Upper Primary",
    sections=(
        SectionSpec("", "", _SELECTED, 30, 1, (1, 1),
                    "Answer ALL the questions on the answer sheet provided.", on_answer_sheet=True),
    ),
    time_allowed="1 hour 40 minutes",
    instructions=("Write your name, school and assessment number in the spaces provided.",
                  "This paper has 30 questions. Answer ALL the questions.",
                  "Each question has four choices, A, B, C and D. Only ONE is correct.",
                  "Mark your answer on the answer sheet provided, not on this paper."),
    pitch=(
        "Items in the KPSEA style (Grades 4–6): every item is multiple choice with four "
        "options A–D and ONE correct answer. One skill or fact per item. A stem a learner "
        "reads in one breath — at most three lines — with the figures, the table or the "
        "picture it needs beside it. The three wrong options are the answers a learner "
        "reaches by a real mistake (adding where they should subtract, misreading a place "
        "value, confusing two terms the lesson contrasted), never nonsense and never 'all of "
        "the above'. Spread the paper: about a third straight recall or one-step work, a "
        "third application in a Kenyan situation (shillings, a farm, a journey, a market), "
        "a third that takes two or three steps or asks the learner to compare, order, "
        "interpret a figure or explain why. Nothing a Grade 3 learner could answer; nothing "
        "that needs what Grade 7 teaches. Where a figure, a map or a table is used, set "
        "three to five consecutive items on it, as the national paper does."),
    columns=2,
)

KJSEA = Format(
    key="kjsea",
    assessment="KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT",
    band="Junior School",
    sections=(
        SectionSpec("A", "Section A", _SELECTED, 30, 1, (1, 1),
                    "Answer ALL the questions in this section on the ANSWER SHEET provided.",
                    on_answer_sheet=True),
        SectionSpec("B", "Section B", _WRITTEN, 10, 0, (3, 6),
                    "Answer ALL the questions in this section in the spaces provided in this "
                    "question paper. Show your working where marks are given for it."),
    ),
    time_allowed="1 hour 40 minutes",
    instructions=("Write your name, school and assessment number in the spaces provided.",
                  "This paper has TWO sections: A and B. Answer ALL the questions.",
                  "Section A: 30 multiple choice questions, answered on the answer sheet.",
                  "Section B: structured questions, answered in this question paper.",
                  "Do NOT remove any page from this paper."),
    pitch=(
        "Items in the KJSEA style (Grades 7–9). SECTION A is thirty multiple-choice items, "
        "four options A–D, one correct, one skill or fact each, the wrong options being "
        "real learner errors. SECTION B is ten structured questions worth 3 to 6 marks "
        "each, with lettered parts (a), (b), (c) whose marks add to the question's, a "
        "Kenyan situation where the outcome allows one, a figure, map, table or data "
        "set where the design uses one, and a marking scheme that awards method marks "
        "(M1) and answer marks (A1) step by step. Pitch: nothing an upper-primary learner "
        "could do, nothing that needs senior-school content; the hardest Section B "
        "question takes three or four connected steps. Spread across recall, application "
        "and analysis, with at least a quarter of the marks above application."),
    columns=2,
)

SENIOR = Format(
    key="senior",
    assessment="KENYA SENIOR SCHOOL EDUCATION ASSESSMENT",
    band="Senior School",
    sections=(
        SectionSpec("A", "Section A", ("short_answer", "quantitative_calculation", "cloze"), 16, 0, (2, 4),
                    "Answer ALL the questions in this section."),
        SectionSpec("B", "Section B", _WRITTEN, 5, 0, (8, 12),
                    "Answer any THREE questions from this section."),
    ),
    time_allowed="2 hours 30 minutes",
    instructions=("Write your name and index number in the spaces provided.",
                  "This paper has TWO sections: A and B.",
                  "Answer ALL the questions in Section A and any THREE from Section B.",
                  "All working must be clearly shown where necessary."),
    pitch=(
        "Items in the senior-school style (Grades 10–12): short structured items of 2–4 "
        "marks in Section A, and extended structured questions of 8–12 marks in Section "
        "B with parts that build on each other. Every question demands the command word "
        "the design assesses at — explain, analyse, evaluate, derive — and the marking "
        "scheme awards each step. Data, figures and case material where the design uses "
        "them."),
    columns=1,
)

_BY_KEY = {f.key: f for f in (LOWER_PRIMARY, KPSEA, KJSEA, SENIOR)}


def for_grade(grade: str) -> Format:
    """The national paper shape for this grade."""
    ordinal = grade_ordinal(grade)
    if ordinal <= 5:      # PP1, PP2, Grades 1–3
        return LOWER_PRIMARY
    if ordinal <= 8:      # Grades 4–6
        return KPSEA
    if ordinal <= 11:     # Grades 7–9
        return KJSEA
    return SENIOR


def by_key(key: str) -> Format | None:
    return _BY_KEY.get((key or "").strip().lower())


# KNEC's own name for the assessment at each grade. The band's format says
# how the paper is shaped; the grade says what it is called on the front —
# a Grade 3 paper is the Kenya Early Years Assessment, a Grade 6 paper the
# Kenya Primary School Education Assessment, a Grade 9 paper the Kenya
# Junior School Education Assessment. A paper headed "Junior Secondary" is
# a paper from a different system, and a head teacher sees it at once.
ASSESSMENT_NAMES: dict[str, str] = {
    "grade-pp1": "SCHOOL BASED ASSESSMENT",
    "grade-pp2": "SCHOOL BASED ASSESSMENT",
    "grade-1": "SCHOOL BASED ASSESSMENT",
    "grade-2": "SCHOOL BASED ASSESSMENT",
    "grade-3": "KENYA EARLY YEARS ASSESSMENT",
    "grade-4": "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT",
    "grade-5": "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT",
    "grade-6": "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT",
    "grade-7": "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT",
    "grade-8": "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT",
    "grade-9": "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT",
    "grade-10": "KENYA SENIOR SCHOOL EDUCATION ASSESSMENT",
    "grade-11": "KENYA SENIOR SCHOOL EDUCATION ASSESSMENT",
    "grade-12": "KENYA SENIOR SCHOOL EDUCATION ASSESSMENT",
}


def assessment_name(grade: str) -> str:
    from .grade_order import normalize_grade

    return ASSESSMENT_NAMES.get(normalize_grade(grade) or "", for_grade(grade).assessment)


def _term_now() -> int:
    import datetime as _dt

    month = _dt.date.today().month
    return 1 if month <= 4 else 2 if month <= 8 else 3


def kind_line(kind: str, scope: str, *, term: int | None = None, year: int | None = None) -> str:
    """What this particular paper is, under the assessment's name: the
    topical test on Integers, the end-of-strand assessment on Numbers, the
    end of Term 2 examination."""
    import datetime as _dt

    year = year or _dt.date.today().year
    scope = (scope or "").strip()
    if kind == "term":
        return f"END OF TERM {term or _term_now()} EXAMINATION {year}"
    if kind == "strand":
        return f"END OF STRAND ASSESSMENT: {scope.upper()}" if scope else "END OF STRAND ASSESSMENT"
    return f"TOPICAL ASSESSMENT: {scope.upper()}" if scope else "TOPICAL ASSESSMENT"


def masthead(grade: str, subject: str, *, year: int | None = None, series: str = "",
             kind: str = "", scope: str = "", term: int | None = None) -> dict[str, str]:
    """The lines at the head of the paper, in the order the samples print
    them: the series, the assessment's own name for this grade, the grade
    and year, the learning area as the design names it, the time."""
    import datetime as _dt

    fmt = for_grade(grade)
    year = year or _dt.date.today().year
    return {
        "series": series,
        "assessment": assessment_name(grade),
        "grade_line": f"{grade_label(grade).upper()} – YEAR {year}",
        "subject": subject.strip().upper(),
        "kind_line": kind_line(kind, scope, term=term, year=year) if kind else "",
        "time": f"Time: {fmt.time_allowed}",
    }


def prompt_block(grade: str, count: int | None = None) -> str:
    """What the generator is told about the paper its items will sit on."""
    fmt = for_grade(grade)
    lines = [f"=== THE PAPER THESE ITEMS ARE FOR: {fmt.assessment} ({fmt.band}) ==="]
    lines.append(fmt.pitch)
    if fmt.sections and len(fmt.sections) > 1:
        share = ", ".join(f"{s.heading}: {s.count} × {'/'.join(k.replace('_', ' ') for k in s.kinds[:3])}"
                          for s in fmt.sections)
        lines.append(f"A full paper is {share}. Write items in that proportion.")
    if count:
        lines.append(f"This batch is {count} items; keep the proportion above within it.")
    lines.append("Every item records `bloom_level` honestly and `difficulty_index` between 0.35 "
                 "and 0.80 — an item outside that band is either below the grade or above it.")
    return "\n".join(lines)

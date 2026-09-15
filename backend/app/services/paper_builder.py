"""A paper composed from the bank: topical, strand, or term.

The bank is a pile of items. What a school buys is a PAPER — a topical
test at the end of Integers, an end-of-strand assessment over Numbers, an
end-of-term examination over everything taught since January — with
sections, a marks total that adds up, a time allowance, instructions, and a
marking scheme at the back. Composing that by hand from a list of four
hundred items is the work nobody does, which is why the exam builder held
zero exams.

This composes one deterministically from what the bank holds:

- **topical**: one sub-strand. **strand**: every sub-strand under a strand.
  **term**: every strand with content, weighted by how much of it there is.
- Three sections, by what the item asks for: A is selected response, one
  mark each; B is short written work and calculations; C is structured,
  scenario, diagram and extended work. A paper with nothing for a section
  simply has no such section.
- Spread first, then difficulty: items are dealt round the sub-strands
  and outcomes so no topic is a whole paper, and within a section run
  easy to hard. The same task set twice — in the bank under two ids — is
  set once.
- The same request composes the same paper; a different `seed` deals a
  different one from the same bank, which is how Paper 1 and Paper 2 for
  two streams come out of one pool.

Approved items are preferred. Drafts are admitted when asked, and a paper
carrying any is stamped as such on the page, because a paper printed from
unsigned items is a proof, not a product.
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Any

from ..question_models import SELECTED_RESPONSE

KINDS = ("topical", "strand", "term")

# Where an item goes on the paper, by the type of work it asks for.
_SECTION_C = {"structured_inquiry", "structured_scenario", "diagram_based",
              "experiment_based", "extended_essay", "practical_performance_task"}

SECTIONS = {
    "A": ("Section A", "Answer ALL the questions in this section. "
                       "For each question, choose the correct answer."),
    "B": ("Section B", "Answer ALL the questions in this section. "
                       "Show all your working in the spaces provided."),
    "C": ("Section C", "Answer ALL the questions in this section. "
                       "Answer each part fully; the marks for each part are shown."),
}

# The marks each section takes of the total, where the bank can supply it.
_SHARE = {"A": 0.30, "B": 0.35, "C": 0.35}


@dataclass
class Section:
    letter: str
    heading: str
    instructions: str
    items: list[dict[str, Any]] = field(default_factory=list)

    @property
    def marks(self) -> float:
        return sum(_marks_of(q) for q in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {"letter": self.letter, "heading": self.heading,
                "instructions": self.instructions, "marks": self.marks,
                "question_ids": [str(q.get("question_id") or "") for q in self.items],
                "count": len(self.items)}


@dataclass
class Paper:
    kind: str
    title: str
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str = ""
    sections: list[Section] = field(default_factory=list)
    time_allowed: str = ""
    instructions: list[str] = field(default_factory=list)
    has_drafts: bool = False
    covers: dict[str, int] = field(default_factory=dict)
    seed: str = ""
    asked_for: int = 0
    shortfall: str = ""
    # The national shape this paper follows (KPSEA, KJSEA, …), and the lines
    # at its head. Empty for the generic A/B/C school paper.
    format: dict[str, Any] = field(default_factory=dict)
    masthead: dict[str, str] = field(default_factory=dict)
    exam_id: str = ""
    scheme_url: str = ""

    @property
    def items(self) -> list[dict[str, Any]]:
        return [q for s in self.sections for q in s.items]

    @property
    def total_marks(self) -> float:
        return sum(s.marks for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "title": self.title, "grade": self.grade,
            "subject": self.subject, "strand": self.strand, "sub_strand": self.sub_strand,
            "total_marks": self.total_marks, "asked_for": self.asked_for,
            "time_allowed": self.time_allowed, "instructions": list(self.instructions),
            "has_drafts": self.has_drafts, "covers": dict(self.covers), "seed": self.seed,
            "shortfall": self.shortfall,
            "sections": [s.to_dict() for s in self.sections],
            "question_ids": [str(q.get("question_id") or "") for q in self.items],
            "question_count": len(self.items),
            "format": dict(self.format), "masthead": dict(self.masthead),
            "exam_id": self.exam_id, "scheme_url": self.scheme_url,
        }


def _marks_of(question: dict[str, Any]) -> float:
    pedagogy = question.get("pedagogy") or {}
    try:
        total = float(pedagogy.get("max_marks") or 0)
    except (TypeError, ValueError):
        total = 0.0
    if total:
        return total
    return sum(float(p.get("marks") or 0) for p in (question.get("structured_parts") or [])
               if isinstance(p, dict))


def _difficulty(question: dict[str, Any]) -> float:
    try:
        return float((question.get("pedagogy") or {}).get("difficulty_index") or 0.5)
    except (TypeError, ValueError):
        return 0.5


def section_of(question: dict[str, Any]) -> str:
    q_type = str(question.get("question_type") or "").lower()
    if q_type in SELECTED_RESPONSE:
        return "A"
    if q_type in _SECTION_C or len(question.get("structured_parts") or []) >= 2:
        return "C"
    if _marks_of(question) >= 5:
        return "C"
    return "B"


def _stem(question: dict[str, Any]) -> str:
    return " ".join(str(question.get(k) or "") for k in ("stimulus_context", "question_text")).strip()


def _task_key(question: dict[str, Any]) -> str:
    """One key per task, so the same sum under two ids is set once."""
    from .question_check import _expression_key

    text = _stem(question)
    key = _expression_key(text)
    if key:
        return "expr:" + key
    return "text:" + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _topic(question: dict[str, Any]) -> tuple[str, str]:
    curriculum = question.get("curriculum") or {}
    return (str(curriculum.get("sub_strand") or "").strip().lower(),
            str(curriculum.get("slo_id") or curriculum.get("slo_text") or "").strip().lower())


def time_for(marks: float, grade: str = "") -> str:
    """A time allowance from the marks: about a minute and a half a mark,
    rounded to a quarter hour, never under half an hour or over two and a
    half."""
    minutes = int(round(marks * 1.5 / 15.0)) * 15
    minutes = max(30, min(150, minutes))
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} hour{'s' if hours > 1 else ''} {rest} minutes"
    if hours:
        return f"{hours} hour{'s' if hours > 1 else ''}"
    return f"{rest} minutes"


def _deal(candidates: list[dict[str, Any]], budget: float, rng: random.Random,
          seen_tasks: set[str], used_topics: dict[tuple[str, str], int]) -> list[dict[str, Any]]:
    """Items up to the marks budget, dealt round the topics.

    The candidates are first put in DEALING order — one from each topic in
    turn, the least-used topic first — and then taken in that order while
    they fit the budget. A sub-strand with forty items and one with four
    both appear before either appears twice.
    """
    by_topic: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for question in candidates:
        by_topic.setdefault(_topic(question), []).append(question)
    for pile in by_topic.values():
        rng.shuffle(pile)
        # Approved first, then the rest — within the shuffle, so the deal
        # is still different for a different seed. `pop()` takes the end.
        # And within that, items AT the grade before items below it: a bank
        # with seventy items dealt a Section A that opened with "identify
        # what −3 represents" while harder items sat unused.
        pile.sort(key=lambda q: (1 if str(q.get("status") or "") == "approved" else 0,
                                 0 if q.get("_weak") else 1))

    taken: dict[tuple[str, str], int] = {}
    ordered: list[tuple[tuple[str, str], dict[str, Any]]] = []
    while by_topic:
        topic = min(by_topic, key=lambda t: (used_topics.get(t, 0) + taken.get(t, 0), rng.random()))
        pile = by_topic[topic]
        ordered.append((topic, pile.pop()))
        taken[topic] = taken.get(topic, 0) + 1
        if not pile:
            del by_topic[topic]

    chosen: list[dict[str, Any]] = []
    spent = 0.0
    for topic, question in ordered:
        key = _task_key(question)
        if key in seen_tasks:
            continue
        marks = _marks_of(question)
        if not marks or spent + marks > budget + 0.5:
            continue
        seen_tasks.add(key)
        used_topics[topic] = used_topics.get(topic, 0) + 1
        chosen.append(question)
        spent += marks
        if spent >= budget:
            break
    chosen.sort(key=_difficulty)
    return chosen


def _figure_of(question: dict[str, Any]) -> str:
    binding = question.get("diagram")
    if isinstance(binding, dict):
        return str(binding.get("diagram_id") or binding.get("diagram_title") or "")
    return ""


def group_by_figure(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items on the same figure made consecutive, in the order the first of
    them appears — so the paper can say "study the map below and answer
    questions 6 to 10" and print the map once."""
    out: list[dict[str, Any]] = []
    placed: set[int] = set()
    for i, question in enumerate(items):
        if i in placed:
            continue
        out.append(question)
        placed.add(i)
        figure = _figure_of(question)
        if not figure:
            continue
        for j in range(i + 1, len(items)):
            if j not in placed and _figure_of(items[j]) == figure:
                out.append(items[j])
                placed.add(j)
    return out


def _compose_to_format(pool: list[dict[str, Any]], paper: Paper, fmt: Any, count: int | None,
                       rng: random.Random) -> None:
    """The national shape: each section takes the types it takes, in the
    count the format sets (scaled when fewer items are asked for)."""
    from .assessment_format import Format  # noqa: F401  (typing only)

    total = fmt.total_items
    scale = (count / total) if (count and total) else 1.0
    seen_tasks: set[str] = set()
    used_topics: dict[tuple[str, str], int] = {}
    for spec in fmt.sections:
        wanted = max(1, int(round(spec.count * scale)))
        candidates = [q for q in pool if str(q.get("question_type") or "").lower() in spec.kinds
                      and _task_key(q) not in seen_tasks]
        if spec.marks_each:
            # A selected-response section counts items, not marks: budget in
            # items by making every item one mark for the deal.
            for q in candidates:
                (q.setdefault("pedagogy", {}))["max_marks"] = spec.marks_each
            chosen = _deal(candidates, float(wanted), rng, seen_tasks, used_topics)
        else:
            low, high = spec.marks_range
            fitting = [q for q in candidates if low <= _marks_of(q) <= high] or candidates
            budget = wanted * (low + high) / 2.0
            chosen = _deal(fitting, budget, rng, seen_tasks, used_topics)[:wanted]
        if chosen:
            paper.sections.append(Section(spec.letter, spec.heading, spec.instructions,
                                          group_by_figure(chosen)))
    paper.format = fmt.to_dict()


def compose(items: list[dict[str, Any]], *, kind: str, grade: str, subject: str,
            strand: str = "", sub_strand: str = "", marks: int = 50,
            seed: str = "", title: str = "", allow_drafts: bool = False,
            format_key: str = "", count: int | None = None, year: int | None = None,
            series: str = "", term: int | None = None) -> Paper:
    """One paper from the bank's items for its scope.

    `format_key` picks the shape: "auto" (the default) follows the national
    paper for the grade — KPSEA, KJSEA, senior — and "school" is the generic
    three-section paper by marks. `count` is the number of items on a
    formatted paper; `marks` is the budget of a school paper.
    """
    from . import assessment_format

    kind = kind if kind in KINDS else "topical"
    pool = [q for q in (items or []) if isinstance(q, dict) and _stem(q)]
    # Which items sit below the grade, so the deal reaches for them last.
    try:
        from . import question_check

        for q in pool:
            q["_weak"] = question_check.rung_of(q, grade=grade, subject=subject) in (
                question_check.TRIVIAL, question_check.BELOW)
    except Exception:  # noqa: BLE001
        pass
    # Only the scope's own items, whatever the caller handed over.
    if kind == "topical" and sub_strand:
        pool = [q for q in pool
                if str((q.get("curriculum") or {}).get("sub_strand") or "").strip().lower()
                == sub_strand.strip().lower()]
    elif kind == "strand" and strand:
        pool = [q for q in pool
                if str((q.get("curriculum") or {}).get("strand") or "").strip().lower()
                == strand.strip().lower()]
    if not allow_drafts:
        pool = [q for q in pool if str(q.get("status") or "") == "approved"]
    seed = seed or hashlib.sha1(f"{grade}|{subject}|{kind}|{strand}|{sub_strand}|{marks}".encode()).hexdigest()[:8]
    rng = random.Random(seed)

    scope = sub_strand if kind == "topical" else strand if kind == "strand" else subject
    paper = Paper(kind=kind, grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
                  seed=seed, asked_for=marks,
                  title=title or {"topical": f"Topical Test: {scope}",
                                  "strand": f"End of Strand Assessment: {scope}",
                                  "term": f"End of Term Examination: {scope}"}[kind])

    fmt = None if (format_key or "auto") == "school" else (
        assessment_format.by_key(format_key) or assessment_format.for_grade(grade))
    paper.masthead = assessment_format.masthead(grade, subject, year=year, series=series,
                                                kind=kind, scope=scope, term=term)
    if not pool:
        paper.shortfall = "the bank holds no usable items for this scope"
        return paper
    if fmt is not None:
        _compose_to_format(pool, paper, fmt, count, rng)
        _finish(paper, kind, sub_strand, grade, fmt.time_allowed, _instructions_for(paper, fmt),
                asked_items=count or fmt.total_items)
        return paper

    by_section: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for question in pool:
        by_section[section_of(question)].append(question)

    # A section the bank cannot fill gives its share to the others.
    present = [s for s in ("A", "B", "C") if by_section[s]]
    if not present:
        paper.shortfall = "the bank holds no usable items for this scope"
        return paper
    share_total = sum(_SHARE[s] for s in present)
    budgets = {s: marks * _SHARE[s] / share_total for s in present}

    seen_tasks: set[str] = set()
    used_topics: dict[tuple[str, str], int] = {}
    for letter in present:
        heading, instructions = SECTIONS[letter]
        chosen = _deal(by_section[letter], budgets[letter], rng, seen_tasks, used_topics)
        if chosen:
            paper.sections.append(Section(letter, heading, instructions, chosen))

    # Whatever the sections left unspent, spend on any section that still has
    # items — a paper short of its marks is a paper the school pads by hand.
    remaining = marks - paper.total_marks
    if remaining >= 1:
        for section in paper.sections:
            left = [q for q in by_section[section.letter] if _task_key(q) not in seen_tasks]
            more = _deal(left, remaining, rng, seen_tasks, used_topics)
            if more:
                section.items = sorted(section.items + more, key=_difficulty)
                remaining = marks - paper.total_marks
            if remaining < 1:
                break

    # Only one section: the letter is noise on a five-question quiz.
    if len(paper.sections) == 1:
        paper.sections[0].heading = ""
    for section in paper.sections:
        section.items = group_by_figure(section.items)

    _finish(paper, kind, sub_strand, grade, time_for(paper.total_marks, grade), [
        "Write your name, class and admission number in the spaces provided.",
        f"This paper has {len(paper.items)} questions in "
        f"{len(paper.sections)} section{'s' if len(paper.sections) != 1 else ''}. Answer ALL questions.",
        "Show all your working clearly. Marks may be awarded for correct method.",
        "Do not write in the margins or on the marking column.",
    ])
    if paper.total_marks < marks - 0.5:
        paper.shortfall = (f"the bank supplied {paper.total_marks:g} of the {marks} marks asked for; "
                           f"generate more items for this scope to fill the paper")
    return paper


def _instructions_for(paper: Paper, fmt: Any) -> list[str]:
    """The format's instructions, with THIS paper's counts in them. The
    format says a full KJSEA paper has thirty in Section A; a paper with
    twenty-two must not tell the candidate to answer thirty."""
    by_letter = {s.letter: s for s in paper.sections}
    lines: list[str] = ["Write your name, school and assessment number in the spaces provided."]
    if len(paper.sections) > 1:
        words = {2: "TWO", 3: "THREE", 4: "FOUR"}.get(len(paper.sections), str(len(paper.sections)))
        lines.append(f"This paper has {words} sections: "
                     + " and ".join(s.letter for s in paper.sections) + ". Answer ALL the questions.")
    else:
        lines.append(f"This paper has {len(paper.items)} questions. Answer ALL the questions.")
    for spec in fmt.sections:
        section = by_letter.get(spec.letter)
        if section is None:
            continue
        n = len(section.items)
        if spec.marks_each:
            where = "on the answer sheet provided" if spec.on_answer_sheet else "on this paper"
            lines.append((f"{spec.heading}: " if spec.heading else "")
                         + f"{n} multiple choice question{'s' if n != 1 else ''}, answered {where}. "
                         f"Each has four choices, A, B, C and D; only ONE is correct.")
        else:
            lines.append((f"{spec.heading}: " if spec.heading else "")
                         + f"{n} structured question{'s' if n != 1 else ''} ({section.marks:g} marks), answered "
                         f"in the spaces provided in this paper. Show your working where marks are given for it.")
    lines.append("Do NOT remove any page from this paper.")
    return lines


def _finish(paper: Paper, kind: str, sub_strand: str, grade: str, time_allowed: str,
            instructions: list[str], asked_items: int | None = None) -> None:
    paper.has_drafts = any(str(q.get("status") or "") != "approved" for q in paper.items)
    for question in paper.items:
        name = (question.get("curriculum") or {}).get("sub_strand") or sub_strand or "—"
        paper.covers[name] = paper.covers.get(name, 0) + 1
    paper.time_allowed = time_allowed
    paper.instructions = instructions
    if asked_items and len(paper.items) < asked_items:
        paper.shortfall = (f"the bank supplied {len(paper.items)} of the {asked_items} items the "
                           f"paper takes; generate more items for this scope to fill it")


def thaw(snapshot: dict[str, Any], questions: list[dict[str, Any]]) -> Paper:
    """A frozen paper, rebuilt from its snapshot and the items it froze.

    The snapshot records the composition — the sections and the ids in each,
    the format, the masthead, the seed — and the items come from the bank by
    id; the paper reprints next term exactly as it printed today.
    """
    by_id = {str(q.get("question_id") or ""): q for q in questions}
    paper = Paper(kind=str(snapshot.get("kind") or "topical"), title=str(snapshot.get("title") or ""),
                  grade=str(snapshot.get("grade") or ""), subject=str(snapshot.get("subject") or ""),
                  strand=str(snapshot.get("strand") or ""), sub_strand=str(snapshot.get("sub_strand") or ""),
                  seed=str(snapshot.get("seed") or ""), asked_for=int(snapshot.get("asked_for") or 0),
                  format=dict(snapshot.get("format") or {}), masthead=dict(snapshot.get("masthead") or {}),
                  exam_id=str(snapshot.get("exam_id") or ""), scheme_url=str(snapshot.get("scheme_url") or ""),
                  time_allowed=str(snapshot.get("time_allowed") or ""),
                  instructions=list(snapshot.get("instructions") or []),
                  has_drafts=bool(snapshot.get("has_drafts")), covers=dict(snapshot.get("covers") or {}))
    for section in snapshot.get("sections") or []:
        if not isinstance(section, dict):
            continue
        items = [by_id[i] for i in (section.get("question_ids") or []) if i in by_id]
        paper.sections.append(Section(str(section.get("letter") or ""), str(section.get("heading") or ""),
                                      str(section.get("instructions") or ""), items))
    return paper

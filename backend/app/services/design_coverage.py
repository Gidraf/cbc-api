"""Which parts of a KICD design the generated content actually covers.

`production_coverage` answers "how much has been produced" — hours planned,
diagrams drawn, questions written. It is a count, and a count cannot say WHICH
outcome has no question against it. A sub-strand can read 100% produced with
three of its five learning outcomes never assessed, because ten questions on
outcome one look exactly like ten questions spread across five.

This answers the other question, the one somebody selling the content has to be
able to answer: what in this design is still not covered, named.

Every dimension is a LIST OF ELEMENTS taken from the design itself — the
outcomes it states, the inquiry questions it poses, the competencies and values
it names, the experiences it suggests, the diagrams and experiments it requires,
and the demand its rubric is written at. Each element is either covered by
something generated, or it is not, and when it is not it is named with what
would cover it.

WHAT IS DELIBERATELY NOT HERE. No score is invented for a dimension the design
is silent about. A sub-strand whose design names no core competencies is not
0% covered on competencies — it has none to cover, and reporting it as a gap
would send somebody to write content the curriculum never asked for. A
dimension with no elements is reported as `not_stated`, and it is left out of
the total rather than counted as complete.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-design-coverage")

# What a dimension is worth in the roll-up. Outcomes dominate because an
# outcome with no question is a promise the content does not keep; a suggested
# learning experience not used is a missed opportunity, not a broken promise.
WEIGHTS: dict[str, float] = {
    "outcomes": 0.30,
    "inquiry_questions": 0.12,
    "demand": 0.18,
    "learning_experiences": 0.12,
    "core_competencies": 0.10,
    "values": 0.08,
    "required_diagrams": 0.05,
    "experiments": 0.05,
}

NOT_STATED = "not_stated"


@dataclass
class Element:
    """One thing the design asks for, and what covers it."""

    kind: str
    ref: str
    text: str
    covered_by: list[str] = field(default_factory=list)
    how: str = ""

    @property
    def covered(self) -> bool:
        return bool(self.covered_by)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "text": self.text[:400],
                "covered": self.covered, "covered_by": self.covered_by[:12],
                "count": len(self.covered_by), "how": self.how}


@dataclass
class Dimension:
    name: str
    elements: list[Element] = field(default_factory=list)
    note: str = ""

    @property
    def stated(self) -> bool:
        return bool(self.elements)

    @property
    def covered(self) -> int:
        return sum(1 for e in self.elements if e.covered)

    @property
    def percent(self) -> float:
        if not self.elements:
            return 0.0
        return round(self.covered / len(self.elements) * 100, 1)

    @property
    def gaps(self) -> list[Element]:
        return [e for e in self.elements if not e.covered]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "stated": self.stated,
            "status": "covered" if self.stated and not self.gaps
            else ("partial" if self.stated else NOT_STATED),
            "total": len(self.elements), "covered": self.covered,
            "percent": self.percent, "weight": WEIGHTS.get(self.name, 0.0),
            "note": self.note,
            "gaps": [e.to_dict() for e in self.gaps],
            "elements": [e.to_dict() for e in self.elements],
        }


@dataclass
class SubStrandCoverage:
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    lesson_hours: str = ""
    questions: int = 0
    dimensions: list[Dimension] = field(default_factory=list)

    @property
    def stated(self) -> list[Dimension]:
        """Only the dimensions this design actually asks for."""
        return [d for d in self.dimensions if d.stated]

    @property
    def percent(self) -> float:
        """Weighted over the dimensions the design STATES.

        Averaging over all eight would score a sub-strand down for having no
        experiments when its design asks for none, and the way to raise that
        score would be to invent an experiment.
        """
        stated = self.stated
        if not stated:
            return 0.0
        total = sum(WEIGHTS.get(d.name, 0.0) for d in stated) or 1.0
        return round(
            sum(d.percent * WEIGHTS.get(d.name, 0.0) for d in stated) / total, 1)

    @property
    def gap_count(self) -> int:
        return sum(len(d.gaps) for d in self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade, "subject": self.subject, "strand": self.strand,
            "sub_strand": self.sub_strand, "lesson_hours": self.lesson_hours,
            "questions": self.questions, "percent": self.percent,
            "gap_count": self.gap_count,
            "dimensions": [d.to_dict() for d in self.dimensions],
        }


@dataclass
class Report:
    grade: str = ""
    subject: str = ""
    sub_strands: list[SubStrandCoverage] = field(default_factory=list)

    @property
    def percent(self) -> float:
        if not self.sub_strands:
            return 0.0
        return round(sum(s.percent for s in self.sub_strands)
                     / len(self.sub_strands), 1)

    def by_dimension(self) -> list[dict[str, Any]]:
        """The same picture across the whole scope, dimension by dimension.

        This is the view that answers "what aspect are we weakest on" — the
        one a person uses to decide what to generate next.
        """
        out = []
        for name in WEIGHTS:
            total = covered = stated_in = 0
            for sub in self.sub_strands:
                for dim in sub.dimensions:
                    if dim.name != name or not dim.stated:
                        continue
                    stated_in += 1
                    total += len(dim.elements)
                    covered += dim.covered
            out.append({
                "name": name, "weight": WEIGHTS[name],
                "sub_strands_stating_it": stated_in,
                "total": total, "covered": covered,
                "percent": round(covered / total * 100, 1) if total else 0.0,
                "status": NOT_STATED if not stated_in else
                          ("covered" if covered == total else "partial"),
            })
        return sorted(out, key=lambda d: (d["status"] == NOT_STATED, d["percent"]))

    def worst(self, limit: int = 20) -> list[dict[str, Any]]:
        """Where to go next: the sub-strands with the most uncovered elements."""
        ranked = sorted(self.sub_strands, key=lambda s: (-s.gap_count, s.percent))
        return [{"sub_strand": s.sub_strand, "strand": s.strand,
                 "percent": s.percent, "gaps": s.gap_count,
                 "questions": s.questions,
                 "worst_dimension": next(
                     (d.name for d in sorted(
                         s.stated, key=lambda x: x.percent) if d.gaps), "")}
                for s in ranked[:limit] if s.gap_count]

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade, "subject": self.subject,
            "percent": self.percent,
            "sub_strands": len(self.sub_strands),
            "gap_count": sum(s.gap_count for s in self.sub_strands),
            "by_dimension": self.by_dimension(),
            "worst": self.worst(),
            "detail": [s.to_dict() for s in self.sub_strands],
        }


# ── matching a design element to what covers it ──────────────────────────────

_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset((
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by",
    "learner", "learners", "should", "be", "able", "is", "are", "as", "at",
    "their", "they", "it", "its", "that", "this", "from", "which", "will",
    "different", "various", "given", "using", "use", "identify", "state",
))


def _terms(text: str) -> set[str]:
    """The words that carry the meaning, for matching one text against another."""
    return {w for w in _WORD.findall((text or "").lower())
            if len(w) > 3 and w not in _STOP}


def _mentions(haystack: str, element_text: str, *, need: float = 0.5) -> bool:
    """Whether a piece of content addresses this element.

    Deliberately generous. The alternative to fuzzy matching here is not exact
    matching, it is NO matching — nothing in the pipeline records "this
    question serves suggested learning experience 3". So a low bar that
    over-reports coverage would be the wrong error, and the bar is set at half
    the element's content words appearing.
    """
    wanted = _terms(element_text)
    if not wanted:
        return False
    found = _terms(haystack)
    hits = len(wanted & found)
    return hits / len(wanted) >= need


def _question_text(question: dict[str, Any]) -> str:
    parts = [str(question.get(k) or "") for k in
             ("stem", "question_text", "answer", "model_answer", "explanation")]
    for part in (question.get("parts") or []):
        if isinstance(part, dict):
            parts += [str(part.get("text") or ""), str(part.get("answer") or "")]
    for row in (question.get("marking_scheme") or []):
        if isinstance(row, dict):
            parts.append(str(row.get("step") or row.get("point") or ""))
    return " ".join(parts)


def _ref(question: dict[str, Any]) -> str:
    return str(question.get("question_id") or question.get("id") or "question")


def _listed(row: dict[str, Any], key: str) -> list[Any]:
    value = row.get(key)
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except ValueError:
            return [value] if value.strip() else []
    return value if isinstance(value, list) else []


def _text_of(item: Any, *keys: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return " ".join(str(v) for v in item.values() if isinstance(v, str))
    return str(item)


def _outcomes(row: dict[str, Any], questions: list[dict[str, Any]]) -> Dimension:
    """Each specific learning outcome, and the questions that assess it.

    Matched on the recorded `slo_id` FIRST, because the question schema carries
    one and a recorded link is worth more than any amount of word overlap. The
    text match is the fallback for questions generated before that field was
    filled, and for outcomes whose id nothing used.
    """
    dim = Dimension("outcomes")
    for i, slo in enumerate(_listed(row, "slos"), start=1):
        text = _text_of(slo, "slo", "outcome", "text", "description")
        ref = str(slo.get("slo_id") or slo.get("id") or f"SLO {i}") \
            if isinstance(slo, dict) else f"SLO {i}"
        element = Element("outcome", ref, text)
        for question in questions:
            link = question.get("curriculum_link") or question.get("curriculum") or {}
            recorded = str(link.get("slo_id") or question.get("slo_id") or "")
            if (recorded and recorded.strip().lower() == ref.strip().lower()) \
                    or _mentions(_question_text(question), text):
                element.covered_by.append(_ref(question))
        element.how = "a question that assesses it"
        dim.elements.append(element)
    return dim


def _named(row: dict[str, Any], key: str, name: str, kind: str,
           questions: list[dict[str, Any]], field_name: str = "") -> Dimension:
    """A dimension whose elements are named strings in the design."""
    dim = Dimension(name)
    for i, item in enumerate(_listed(row, key), start=1):
        text = _text_of(item, "text", "name", "title", "description", "question",
                        "experience", "value", "competency")
        element = Element(kind, f"{kind} {i}", text)
        for question in questions:
            link = question.get("curriculum_link") or question.get("curriculum") or {}
            recorded = str(link.get(field_name) or question.get(field_name) or "") \
                if field_name else ""
            if (recorded and _mentions(recorded, text, need=0.4)) \
                    or _mentions(_question_text(question), text):
                element.covered_by.append(_ref(question))
        dim.elements.append(element)
    return dim


def _demand(row: dict[str, Any], questions: list[dict[str, Any]],
            grade: str, subject: str, strand: str, sub_strand: str) -> Dimension:
    """Whether the questions reach the demand this sub-strand is assessed at.

    This is the dimension the rest of this work built. An outcome can be
    covered by a question that asks the learner to name something, and the
    rubric it is marked against asks them to compare — so "covered" on outcomes
    and "not reached" on demand is a real and common combination.
    """
    from . import command_words, demand_profile

    dim = Dimension("demand")
    profile = None
    try:
        profile = demand_profile.load(grade, subject, strand, sub_strand)
    except Exception as exc:  # noqa: BLE001
        logger.debug("No profile for %s (%s)", sub_strand, exc)

    floor = command_words.floor_for(grade)
    if profile and profile.top:
        wanted = list(range(max(1, profile.top - profile.distinct + 1),
                            profile.top + 1))
        dim.note = "from this sub-strand's own extracted demand profile"
    elif floor:
        wanted = list(range(max(1, floor.top - floor.distinct + 1), floor.top + 1))
        dim.note = "from the band floor — no profile has been extracted yet"
    else:
        dim.note = "no demand floor applies at this level"
        return dim

    spread = command_words.spread(
        [{"stem": str(q.get("stem") or q.get("question_text") or "")}
         for q in questions])
    for rank in wanted:
        name = next((r.name for r in command_words.LADDER if r.rank == rank), str(rank))
        element = Element("rung", f"rung {rank}", f"{name} — a task at this level")
        element.how = f"a question whose command word is a {name} verb"
        if spread.by_rank.get(rank):
            element.covered_by = [f"{spread.by_rank[rank]} question(s)"]
        dim.elements.append(element)
    return dim


def for_sub_strand(row: dict[str, Any], questions: list[dict[str, Any]],
                   grade: str, subject: str) -> SubStrandCoverage:
    """One sub-strand's design, element by element, against what exists."""
    strand = str(row.get("strand_name") or "")
    sub_strand = str(row.get("sub_strand_name") or "")
    cover = SubStrandCoverage(
        grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
        lesson_hours=str(row.get("allocated_hours") or ""),
        questions=len(questions))
    cover.dimensions = [
        _outcomes(row, questions),
        _named(row, "key_inquiry_questions", "inquiry_questions", "inquiry",
               questions),
        _demand(row, questions, grade, subject, strand, sub_strand),
        _named(row, "learning_experiences", "learning_experiences", "experience",
               questions),
        _named(row, "core_competencies", "core_competencies", "competency",
               questions, field_name="core_competency"),
        _named(row, "values", "values", "value", questions,
               field_name="constitutional_value"),
        _named(row, "required_diagrams", "required_diagrams", "diagram", questions),
        _named(row, "experiments", "experiments", "experiment", questions),
    ]
    for dim in cover.dimensions:
        if not dim.note and not dim.stated:
            dim.note = "this design names none, so there is nothing to cover"
    return cover


# ── reading a whole scope ────────────────────────────────────────────────────


def _rows(grade: str, subject: str, strand: str = "",
          sub_strand: str = "") -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    from .grade_sql import clause

    where = [clause("grade"), "LOWER(subject) = LOWER(:subject)"]
    params: dict[str, Any] = {"grade": grade, "subject": subject}
    if strand:
        where.append("LOWER(strand_name) = LOWER(:strand)")
        params["strand"] = strand
    if sub_strand:
        where.append("LOWER(sub_strand_name) = LOWER(:sub_strand)")
        params["sub_strand"] = sub_strand
    try:
        return fetch_all(
            f"""
            SELECT strand_name, sub_strand_name, allocated_hours, slos,
                   learning_experiences, key_inquiry_questions,
                   core_competencies, values, assessment_rubrics,
                   required_diagrams, experiments
            FROM curriculum_substrands
            WHERE {' AND '.join(where)}
            ORDER BY strand_name, sub_strand_name
            """, params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the design for %s %s: %s",
                       grade, subject, exc)
        return []


def for_scope(grade: str, subject: str, strand: str = "", sub_strand: str = "",
              status: str = "", question_limit: int = 2_000) -> Report:
    """Every sub-strand in this scope, against everything filed for it.

    `status` filters the questions counted — pass "approved" to see what a
    buyer would actually receive, and leave it empty to include drafts. The
    difference between those two numbers is worth looking at: a scope that is
    complete in drafts and empty in approvals is a review queue, not a product.
    """
    from .question_dna import question_dna_service

    report = Report(grade=grade, subject=subject)
    for row in _rows(grade, subject, strand, sub_strand):
        name = str(row.get("sub_strand_name") or "")
        try:
            questions = question_dna_service.list_questions(
                grade=grade, subject=subject,
                strand=str(row.get("strand_name") or "") or None,
                sub_strand=name or None, status=status or None,
                limit=question_limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read questions for %s: %s", name, exc)
            questions = []
        report.sub_strands.append(
            for_sub_strand(row, questions, grade, subject))
    return report

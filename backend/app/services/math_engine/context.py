from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ...infra.db import fetch_one
from ..grade_sql import clause as grade_clause

logger = logging.getLogger("cbc-math-context")


@dataclass(slots=True)
class CurriculumContext:
    grade: str
    subject: str
    strand_id: str = ""
    strand_name: str = ""
    sub_strand_id: str = ""
    sub_strand_name: str = ""
    slo_id: str = ""
    slo_text: str = ""
    hour_number: int = 1
    notes_summary: str = ""
    raw_notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "subject": self.subject,
            "strand_id": self.strand_id,
            "strand_name": self.strand_name,
            "sub_strand_id": self.sub_strand_id,
            "sub_strand_name": self.sub_strand_name,
            "slo_id": self.slo_id,
            "slo_text": self.slo_text,
            "hour_number": self.hour_number,
            "notes_summary": self.notes_summary[:500] if self.notes_summary else "",
        }


def load_context_from_db(
    grade: str,
    subject: str,
    sub_strand: str,
    hour_number: int = 1,
) -> CurriculumContext:
    """Load curriculum context from substrand_resources or curriculum_designs."""
    clean_grade = grade.strip()
    clean_subj = subject.strip()
    clean_ss = sub_strand.strip()

    # The grade belongs in the WHERE clause. Without it this query happily
    # returned a Grade 9 sub-strand for a Grade 6 request whenever the names
    # matched — and sub-strand names repeat across grades by design, because
    # the curriculum spirals. `grade_sql.clause` normalises both sides so it
    # does not matter whether the caller holds "Grade 6", "grade-6" or "PP1".
    row = fetch_one(
        f"""
        SELECT curriculum, notes FROM substrand_resources
        WHERE {grade_clause("curriculum->>'grade'", "grade")}
          AND (LOWER(curriculum->>'subject') = LOWER(:subject)
               OR LOWER(curriculum->>'subject') LIKE :subj_like)
          AND (LOWER(curriculum->>'sub_strand') = LOWER(:sub_strand)
               OR LOWER(curriculum->>'sub_strand') LIKE :ss_like)
        ORDER BY updated_at DESC LIMIT 1
        """,
        {
            "grade": clean_grade,
            "subject": clean_subj,
            "subj_like": f"%{clean_subj.lower()}%",
            "sub_strand": clean_ss,
            "ss_like": f"%{clean_ss.lower()}%",
        },
    )

    curr: dict[str, Any] = {}
    notes_dict: dict[str, Any] = {}
    if row:
        curr = row.get("curriculum") or {}
        notes_dict = row.get("notes") or {}

    strand_name = curr.get("strand") or ""
    sub_strand_name = curr.get("sub_strand") or clean_ss
    resolved_grade = curr.get("grade") or clean_grade
    resolved_subj = curr.get("subject") or clean_subj

    # Extract notes text for specified hour if available
    notes_summary = ""
    if notes_dict and isinstance(notes_dict, dict):
        h_mods = notes_dict.get("hour_modules") or notes_dict.get("key_concepts") or []
        for idx, hm in enumerate(h_mods):
            h_num = hm.get("hour_number", idx + 1)
            if h_num == hour_number or hour_number == 0:
                h_title = hm.get("hour_title") or hm.get("heading") or f"Hour {h_num}"
                h_notes = hm.get("full_lecture_notes") or hm.get("content") or hm.get("detailed_exposition") or ""
                notes_summary += f"[{h_title}]: {h_notes}\n"
        if not notes_summary:
            notes_summary = str(notes_dict.get("overview") or notes_dict.get("summary") or "")

    # The SLO comes from the design or it does not exist. This used to build an
    # identifier out of string slices and a sentence out of a template, then
    # print both on the teacher's copy under the heading "SLO:" — where they
    # read as a KICD reference that nothing in the curriculum had ever said.
    slos = curr.get("slos") or curr.get("learning_outcomes") or []
    first_slo = ""
    if isinstance(slos, list) and slos:
        head = slos[0]
        first_slo = head.get("text", "") if isinstance(head, dict) else str(head)
    slo_id = str(curr.get("slo_id") or "")
    slo_text = first_slo

    return CurriculumContext(
        grade=resolved_grade,
        subject=resolved_subj,
        strand_id="",
        strand_name=strand_name,
        sub_strand_id="",
        sub_strand_name=sub_strand_name,
        slo_id=slo_id,
        slo_text=slo_text,
        hour_number=hour_number,
        notes_summary=notes_summary[:4000],
        raw_notes=notes_dict,
    )


def extract_math_concepts(notes_text_or_dict: str | dict[str, Any]) -> list[dict[str, Any]]:
    """Scan notes text or JSON to identify key mathematical operations and topics."""
    text = ""
    if isinstance(notes_text_or_dict, dict):
        for v in notes_text_or_dict.values():
            if isinstance(v, str):
                text += " " + v
            elif isinstance(v, list):
                text += " " + " ".join(str(item) for item in v)
    else:
        text = str(notes_text_or_dict)

    concepts: list[dict[str, Any]] = []
    text_lower = text.lower()

    # Pattern matchers for CBC topics
    patterns = [
        ("fraction_addition", r"\b(add|addition|sum)\b.*\bfraction", "fractions", "addition"),
        ("fraction_multiplication", r"\b(multiply|product)\b.*\bfraction", "fractions", "multiplication"),
        ("linear_equation", r"\b(linear equation|solve for [a-z]|unknown)\b", "algebra", "linear_equation"),
        ("percentage", r"\b(percent|percentage|discount|interest)\b", "number", "percentage"),
        ("ratio_proportion", r"\b(ratio|proportion|share in the ratio)\b", "number", "ratio"),
        ("triangle_area", r"\b(area of.*triangle|half.*base.*height)\b", "geometry", "area"),
        ("pythagoras", r"\b(pythagor|hypotenuse|right-angled)\b", "geometry", "pythagoras"),
        ("circle_area", r"\b(area of.*circle|circumference|radius|diameter)\b", "geometry", "circle"),
        ("mean_median_mode", r"\b(mean|median|mode|average|central tendency)\b", "statistics", "central_tendency"),
    ]

    for cid, pattern, domain, operation in patterns:
        if re.search(pattern, text_lower):
            concepts.append({
                "concept_id": cid,
                "domain": domain,
                "operation": operation,
            })

    return concepts

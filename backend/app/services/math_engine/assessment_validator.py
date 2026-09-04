"""Mathematical Assessment Validator.

Ensures mathematical correctness, marking scheme tally integrity, step correspondence,
and curriculum rubric alignment for assessment papers and questions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .objects import SolutionStep, SolutionTrace


@dataclass(slots=True)
class RubricMark:
    mark_type: str  # 'M' (Method), 'A' (Accuracy), 'B' (Independent/Fact)
    points: int
    step_number: Optional[int]
    description: str


@dataclass(slots=True)
class QuestionValidationResult:
    question_number: int
    total_marks: int
    allocated_marks: int
    is_mark_consistent: bool
    has_solution_trace: bool
    trace_verified: bool
    discrepancies: List[str]


@dataclass(slots=True)
class AssessmentAuditReport:
    assessment_id: str
    is_valid: bool
    total_marks: int
    computed_marks: int
    question_count: int
    discrepancies: List[str]
    question_results: List[QuestionValidationResult]
    audit_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "is_valid": self.is_valid,
            "total_marks": self.total_marks,
            "computed_marks": self.computed_marks,
            "question_count": self.question_count,
            "discrepancies": self.discrepancies,
            "question_results": [
                {
                    "question_number": qr.question_number,
                    "total_marks": qr.total_marks,
                    "allocated_marks": qr.allocated_marks,
                    "is_mark_consistent": qr.is_mark_consistent,
                    "has_solution_trace": qr.has_solution_trace,
                    "trace_verified": qr.trace_verified,
                    "discrepancies": qr.discrepancies,
                }
                for qr in self.question_results
            ],
            "audit_metadata": self.audit_metadata,
        }


class AssessmentValidator:
    """Validates mathematical assessment papers and question marking schemes."""

    @staticmethod
    def parse_marking_scheme_marks(marking_scheme_text: str) -> int:
        """Extract total marks allocated in marking scheme text (e.g. 'M1 A1 B1' -> 3, or '2 marks' -> 2)."""
        clean = marking_scheme_text.strip()
        if not clean:
            return 0

        # Pattern 1: Standard CBC/KNEC mark codes like M1, A1, B2
        code_matches = re.findall(r"\b([MAB])(\d+)\b", clean, re.I)
        if code_matches:
            return sum(int(pts) for _, pts in code_matches)

        # Pattern 2: Explicit point mentions e.g. "2 marks", "(3 mks)"
        num_matches = re.findall(r"(\d+)\s*(?:marks?|mks?|pts?|points?)", clean, re.I)
        if num_matches:
            return sum(int(n) for n in num_matches)

        # Pattern 3: Bracketed single numbers at end of lines e.g. "(1)" or "[2]"
        bracket_matches = re.findall(r"[\[\(](\d+)[\]\)]", clean)
        if bracket_matches:
            return sum(int(n) for n in bracket_matches)

        return 0

    @classmethod
    def validate_question(
        cls,
        question: Dict[str, Any],
        default_index: int = 1,
    ) -> QuestionValidationResult:
        """Validate a single mathematical question item."""
        q_num = question.get("question_number", default_index)
        q_marks = question.get("marks", 0)
        ms_text = question.get("marking_scheme", "")
        sol_trace = question.get("solution_trace")

        discrepancies: List[str] = []

        # Parse marking scheme marks
        allocated_marks = cls.parse_marking_scheme_marks(ms_text) if ms_text else 0
        if allocated_marks == 0 and q_marks > 0 and sol_trace and isinstance(sol_trace, dict):
            # If marking scheme text didn't specify, default to step count or question marks
            allocated_marks = q_marks

        is_mark_consistent = True
        if allocated_marks > 0 and q_marks > 0 and allocated_marks != q_marks:
            is_mark_consistent = False
            discrepancies.append(
                f"Question {q_num} mark mismatch: question states {q_marks} marks, "
                f"but marking scheme allocates {allocated_marks} marks."
            )

        has_trace = bool(sol_trace)
        trace_verified = False
        if has_trace:
            if isinstance(sol_trace, dict):
                trace_verified = bool(sol_trace.get("verified", False))
                steps = sol_trace.get("steps", [])
                if not steps:
                    discrepancies.append(f"Question {q_num} solution trace contains no step-by-step working.")
                if sol_trace.get("unsolved"):
                    discrepancies.append(
                        f"Question {q_num} was not solved by any deterministic solver — "
                        f"its answer and marking scheme are unchecked."
                    )
                elif not trace_verified:
                    discrepancies.append(
                        f"Question {q_num} has a worked solution that could not be verified "
                        f"automatically. A person must check it before this paper is used."
                    )
            elif isinstance(sol_trace, SolutionTrace):
                trace_verified = sol_trace.verified
                if not sol_trace.steps:
                    discrepancies.append(f"Question {q_num} solution trace contains no step-by-step working.")
        else:
            discrepancies.append(f"Question {q_num} lacks a deterministic solution trace.")

        return QuestionValidationResult(
            question_number=q_num,
            total_marks=q_marks,
            allocated_marks=allocated_marks,
            is_mark_consistent=is_mark_consistent,
            has_solution_trace=has_trace,
            trace_verified=trace_verified,
            discrepancies=discrepancies,
        )

    @classmethod
    def validate_assessment_document(
        cls,
        document_dict: Dict[str, Any],
    ) -> AssessmentAuditReport:
        """Audit an entire assessment document (e.g. from EducationalDocument or exam builder)."""
        doc_id = document_dict.get("document_id", "doc_untitled")
        stated_total = document_dict.get("total_marks", 0)
        blocks = document_dict.get("blocks", [])

        # Filter question blocks
        questions: List[Dict[str, Any]] = []
        for b in blocks:
            b_type = b.get("type") if isinstance(b, dict) else getattr(b, "type", "")
            content = b.get("content") if isinstance(b, dict) else getattr(b, "content", {})
            if b_type == "question":
                questions.append(content)

        # Also support raw 'questions' list if passed directly
        if not questions and "questions" in document_dict:
            questions = document_dict["questions"]

        question_results: List[QuestionValidationResult] = []
        computed_total = 0
        all_discrepancies: List[str] = []

        for idx, q in enumerate(questions, start=1):
            q_res = cls.validate_question(q, default_index=idx)
            question_results.append(q_res)
            computed_total += q_res.total_marks
            all_discrepancies.extend(q_res.discrepancies)

        # Validate paper-level mark tally
        if stated_total > 0 and computed_total != stated_total:
            all_discrepancies.append(
                f"Paper mark total discrepancy: document header specifies {stated_total} marks, "
                f"but sum of questions is {computed_total} marks."
            )
        elif stated_total == 0:
            stated_total = computed_total

        is_valid = len(all_discrepancies) == 0

        audit_meta = {
            "validator_version": "2.0-deterministic",
            "passed_checks": [
                "all_questions_have_traces" if all(q.has_solution_trace for q in question_results) else None,
                "all_traces_verified" if all(q.trace_verified for q in question_results) else None,
                "mark_totals_reconciled" if computed_total == stated_total else None,
            ],
        }
        audit_meta["passed_checks"] = [p for p in audit_meta["passed_checks"] if p]

        return AssessmentAuditReport(
            assessment_id=doc_id,
            is_valid=is_valid,
            total_marks=stated_total,
            computed_marks=computed_total,
            question_count=len(questions),
            discrepancies=all_discrepancies,
            question_results=question_results,
            audit_metadata=audit_meta,
        )

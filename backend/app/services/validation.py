from __future__ import annotations

from ..errors import raise_api_error
from .grade_order import GRADE_SEQUENCE, normalize_grade


WRITTEN_RESPONSE_TYPES = {
    "short_answer",
    "structured_inquiry",
    "practical_performance_task",
    "cloze",
    "matching",
}


VALID_GRADE_SLUGS = frozenset(slug for slug, _label, _level in GRADE_SEQUENCE)


def validate_grade_dataset(grade: str) -> str:
    """Normalise a grade to its canonical slug, rejecting anything off the ladder.

    This used to normalise without checking, so "grade-15" or a typo became a
    dataset slug of its own and quietly produced an empty grade that nothing
    would ever fill.
    """
    if not grade:
        return "grade-7"

    slug = normalize_grade(grade)
    if slug not in VALID_GRADE_SLUGS:
        raise_api_error(
            "INVALID_GRADE_DATASET",
            f"'{grade}' is not a CBC grade. Expected one of: "
            f"{', '.join(sorted(VALID_GRADE_SLUGS))}.",
        )
    return slug


def validate_question_batch(questions: list[dict]) -> None:
    if not questions:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "Question batch is empty")

    mcq_count = 0
    written_count = 0

    for item in questions:
        question_type, answers, kicd_evidence = _extract_question_fields(item)
        _validate_answers(question_type, answers)
        _validate_kicd_evidence(kicd_evidence)

        if question_type == "multiple_choice":
            mcq_count += 1
        if question_type in WRITTEN_RESPONSE_TYPES:
            written_count += 1

    total = len(questions)
    if mcq_count / total < 0.3 or written_count / total < 0.4:
        raise_api_error(
            "INSUFFICIENT_WRITTEN_RESPONSE_ITEMS",
            "Question mix policy failed: requires MCQ >= 30% and written-response >= 40%",
        )


def _extract_question_fields(item: dict) -> tuple[str | None, dict, list]:
    content = item.get("content", {})
    question_type = content.get("question_type")
    answers = content.get("answers", {})
    kicd_evidence = content.get("kicd_guideline_evidence", [])
    return question_type, answers, kicd_evidence


def _validate_answers(question_type: str | None, answers: dict) -> None:
    if question_type == "multiple_choice" and not answers.get("correct_option_ids"):
        raise_api_error("SCHEMA_VALIDATION_FAILED", "MCQ question missing answers.correct_option_ids")

    if question_type in WRITTEN_RESPONSE_TYPES:
        if not answers.get("expected_response") or not answers.get("scoring_points"):
            raise_api_error("SCHEMA_VALIDATION_FAILED", "Written-response question missing required answers fields")


def _validate_kicd_evidence(kicd_evidence: list) -> None:
    if not kicd_evidence:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "Question missing kicd_guideline_evidence")

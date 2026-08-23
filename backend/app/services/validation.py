from __future__ import annotations

from ..errors import raise_api_error


WRITTEN_RESPONSE_TYPES = {
    "short_answer",
    "structured_inquiry",
    "practical_performance_task",
    "cloze",
    "matching",
}


def validate_grade_dataset(grade: str) -> str:
    if not grade:
        return "grade-7"
    grade_norm = grade.strip().lower()
    if grade_norm.startswith("grade-"):
        return grade_norm
    if grade_norm.startswith("grade"):
        suffix = grade_norm[5:].lstrip("-").strip()
        return f"grade-{suffix}" if suffix else "grade-7"
    if grade_norm in {"dte", "diploma", "teacher-education"}:
        return "grade-dte"
    if grade_norm in {"pp1", "pp2"}:
        return f"grade-{grade_norm}"
    if grade_norm.isdigit():
        return f"grade-{grade_norm}"
    return f"grade-{grade_norm}"


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

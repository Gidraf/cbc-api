from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services.validation import validate_grade_dataset, validate_question_batch


def test_validate_grade_dataset_valid():
    assert validate_grade_dataset("7") == "grade-7"
    assert validate_grade_dataset("grade 7") == "grade-7"
    assert validate_grade_dataset("grade-7") == "grade-7"
    assert validate_grade_dataset("pp1") == "grade-pp1"
    assert validate_grade_dataset("pp2") == "grade-pp2"
    assert validate_grade_dataset("grade-12") == "grade-12"


def test_validate_grade_dataset_invalid():
    with pytest.raises(ApiError) as exc_info:
        validate_grade_dataset("15")
    assert exc_info.value.code == "INVALID_GRADE_DATASET"

    with pytest.raises(ApiError) as exc_info:
        validate_grade_dataset("invalid_text")
    assert exc_info.value.code == "INVALID_GRADE_DATASET"


def test_validate_question_batch_valid():
    batch = [
        {
            "content": {
                "question_type": "multiple_choice",
                "answers": {"correct_option_ids": ["A"]},
                "kicd_guideline_evidence": [{"quote": "evidence"}],
            }
        },
        {
            "content": {
                "question_type": "structured_inquiry",
                "answers": {"expected_response": "resp", "scoring_points": ["pt1"]},
                "kicd_guideline_evidence": [{"quote": "evidence"}],
            }
        },
    ]
    # 50% MCQ (>=30%), 50% Written (>=40%) -> should pass
    validate_question_batch(batch)


def test_validate_question_batch_insufficient_written():
    batch = [
        {
            "content": {
                "question_type": "multiple_choice",
                "answers": {"correct_option_ids": ["A"]},
                "kicd_guideline_evidence": [{"quote": "evidence"}],
            }
        },
        {
            "content": {
                "question_type": "multiple_choice",
                "answers": {"correct_option_ids": ["B"]},
                "kicd_guideline_evidence": [{"quote": "evidence"}],
            }
        },
        {
            "content": {
                "question_type": "multiple_choice",
                "answers": {"correct_option_ids": ["C"]},
                "kicd_guideline_evidence": [{"quote": "evidence"}],
            }
        },
    ]
    # 0% Written (<40%) -> should fail
    with pytest.raises(ApiError) as exc_info:
        validate_question_batch(batch)
    assert exc_info.value.code == "INSUFFICIENT_WRITTEN_RESPONSE_ITEMS"

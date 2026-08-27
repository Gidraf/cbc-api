"""The sub-strand generator must send the design once, and in pieces if it is large.

A 296-page KICD design compiled into one prompt reached 170k tokens against a
128k window. The provider rejects the whole request rather than truncating it,
so the failure mode is not a worse answer — it is no answer at all. Two things
kept it there: the document was interpolated into the prompt template and then
appended a second time as a separate message, and nothing split it when it was
genuinely too big for one call.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

from app.services.document_chunking import Chunk
from app.services.document_index import Line, Page
from app.services.langfuse_context import context_safe_package
from app.services.map_reduce import reconcile


def _chunk(index: int, first: int, last: int) -> Chunk:
    pages = [Page(number=n, lines=[Line(page=n, line=1, text="x")]) for n in range(first, last + 1)]
    return Chunk(index=index, pages=pages, text="x")


def test_the_design_is_not_injected_into_the_prompt_twice() -> None:
    """No message may re-append the source document the template already carries."""
    from app.routes import curriculum

    source = textwrap.dedent(inspect.getsource(curriculum.factory_generate_substrands))
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # context.messages.append(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "append"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "messages"
        ):
            segment = ast.get_source_segment(source, node) or ""
            if "source_material" in segment:
                offenders.append(segment[:160])

    assert not offenders, (
        "The sub-strand prompt re-appends the design document as an extra message. "
        "The substrand-generator template already interpolates it, so this sends the "
        f"whole design twice and blows the context window. Found: {offenders}"
    )


def test_downstream_agent_prompts_are_stripped_from_curriculum_context() -> None:
    """Curriculum facts survive; other agents' instruction templates do not."""
    stored = {
        "slos": ["identify three qualities of God"],
        "allocated_hours": "4 hours",
        "strand_dna_id": "dna_strand_grade-pp1_1_0",
        "notes_prompt": "You are an elite Senior Curriculum Specialist..." * 200,
        "diagram_prompt": "You are the DiagramAgent..." * 200,
        "question_prompt": "You are the QuestionGeneratorAgent..." * 200,
        "reviewer_prompt": "You are the StrictSafetyAndQualityReviewerAgent..." * 200,
        "approver_agent1_prompt": "You are Primary Approver Agent..." * 200,
        "approver_agent2_prompt": "You are Senior Quality Approver Agent..." * 200,
        "experiment_activity_prompt": "You are the ExperimentActivityAgent..." * 200,
    }

    safe = context_safe_package(stored)

    assert safe["slos"] == ["identify three qualities of God"]
    assert safe["allocated_hours"] == "4 hours"
    assert safe["strand_dna_id"] == "dna_strand_grade-pp1_1_0"
    assert not [k for k in safe if k.endswith("_prompt")]
    # The templates are the bulk of it: this is the difference between a
    # subject context that fits and one that does not.
    assert len(str(safe)) < len(str(stored)) / 10


def test_context_safe_package_tolerates_a_missing_or_malformed_package() -> None:
    assert context_safe_package(None) == {}
    assert context_safe_package("not a dict") == {}
    assert context_safe_package({}) == {}


def test_a_substrand_spanning_two_chunks_is_reported_once() -> None:
    """The same sub-strand seen on pages 16 and 44 is one sub-strand, not two."""
    partials = [
        (_chunk(0, 1, 40), [{"sub_strand_name": "1.1.1 Greetings and Farewell", "allocated_hours": "3 lessons"}]),
        (_chunk(1, 41, 80), [{"sub_strand_name": "Greetings and farewell", "slos": ["use greetings in social interactions"]}]),
    ]

    items, summary = reconcile(partials, identity_fields=("sub_strand_name", "sub_strand_id", "name"))

    assert len(items) == 1, "Numbering and casing drift between chunks; it is still one sub-strand."
    assert summary["duplicates_merged"] == 1
    merged = items[0]
    # Each chunk contributed a different field, and both survive.
    assert merged["allocated_hours"] == "3 lessons"
    assert merged["slos"] == ["use greetings in social interactions"]
    # A reviewer must be able to find where it came from.
    assert merged["source_pages"] == ["1-40", "41-80"]


def test_distinct_substrands_are_not_collapsed_together() -> None:
    partials = [
        (_chunk(0, 1, 40), [
            {"sub_strand_name": "1.1.1 Greetings and Farewell"},
            {"sub_strand_name": "1.2.1 Reading Readiness"},
        ]),
    ]

    items, summary = reconcile(partials, identity_fields=("sub_strand_name", "sub_strand_id", "name"))

    assert len(items) == 2
    assert summary["duplicates_merged"] == 0


def test_the_catalogue_lists_pre_primary_as_seven_learning_areas() -> None:
    """"Pre-Primary 1" is a level, not a subject. Filing all seven areas under it
    made each overwrite the last."""
    from app.services.curriculum_catalogue import (
        expected_design_count, expected_subjects, has_combined_design,
    )

    for grade in ("grade-pp1", "grade-pp2"):
        subjects = expected_subjects(grade)
        assert len(subjects) == 7, f"{grade} should list seven learning areas, got {subjects}"
        assert "Language Activities" in subjects
        assert "Christian Religious Education" in subjects
        assert not any(s.startswith("Pre-Primary") for s in subjects), (
            "the level must not be listed as a learning area"
        )
        # One published PDF, seven areas inside it.
        assert expected_design_count(grade) == 1
        assert has_combined_design(grade) is True

    # Grades that publish one document per learning area are unaffected.
    assert has_combined_design("grade-7") is False
    assert has_combined_design("grade-4") is False

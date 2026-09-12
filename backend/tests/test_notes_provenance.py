"""The notes station was never asked to cite, and nothing checked whether it had.

Six teacher's guides in a row printed "this lesson names no design element"
under every lesson. The design row was loaded, the resolver could read it, the
block on the page was honest — and the model had done nothing wrong, because
the `serves` instruction was written for the QUESTIONS station and the notes
prompt never carried it, and `check_provenance` lived in the MATERIAL station
and the notes route never called it. The only part of the chain that reached
the teacher's guide was the sentence saying it was empty.
"""
from __future__ import annotations

import inspect

from app.services import design_elements, notes_remediation
from app.services.langfuse_seed import SEED_AGENT_PROMPTS, SEED_PROMPT_BLOCKS

_ROW = {
    "slos": ["perform basic operations on Integers in different situations",
             "work out combined operations of integers in the correct order"],
    "key_inquiry_questions": [],
    "learning_experiences": ["Learners use number cards to work combined operations"],
    "core_competencies": [], "values": [], "required_diagrams": [], "experiments": [],
}


# ── the prompt asks ─────────────────────────────────────────────────────────

def test_the_lesson_block_speaks_to_lessons_not_questions() -> None:
    block = design_elements.block_for(_ROW, unit="lesson")

    assert "Every lesson you write must record" in block
    assert "[outcome 1]" in block and "[experience 1]" in block
    assert "question" not in block.lower().split("rules for")[0], \
        "the questions wording must not leak into the lessons block"


def test_the_questions_block_is_unchanged() -> None:
    assert "Every question you write must record" in design_elements.block_for(_ROW)


def test_the_notes_prompt_carries_the_slot_and_the_route_fills_it() -> None:
    from app.routes import curriculum

    assert "{{ design_elements }}" in SEED_PROMPT_BLOCKS["note-plan-rules"]
    source = inspect.getsource(curriculum.factory_generate_notes)
    assert 'design_elements.block_for(' in source
    assert 'unit="lesson"' in source


def test_an_unextracted_design_asks_for_no_citation() -> None:
    """Better no request than an invited invention."""
    assert design_elements.block_for({}, unit="lesson") == ""


# ── and the check acts ──────────────────────────────────────────────────────

def test_an_uncited_lesson_is_a_finding_and_a_rewrite_target() -> None:
    notes = {"modules": [
        {"module_number": 1, "title": "Intro", "serves": ["outcome 1"]},
        {"module_number": 2, "title": "Real life"},
    ]}
    score, findings, targets = notes_remediation._inspect(notes, [], _ROW)

    assert 2 in targets, "a finding nothing can act on is a comment"
    assert any('Lesson 2 "Real life" names no design element' in f
               for f in findings)
    assert any("[outcome 1]" in f for f in findings), \
        "the rewrite is told what to choose from"


def test_an_invented_ref_is_removed_before_it_can_print() -> None:
    notes = {"modules": [{"module_number": 1, "title": "L1",
                          "serves": ["outcome 9", "g9-mat-77"]}]}
    report = notes_remediation.check_provenance(notes, _ROW)

    assert notes["modules"][0]["serves"] == []
    assert report["uncited"] == [1]
    assert "outcome 9" in report["findings"][0]
    assert "g9-mat-77" in report["findings"][0]
    assert "discarded" in report["findings"][0]


def test_provenance_counts_toward_the_score_only_when_checkable() -> None:
    notes = {"modules": [{"module_number": 1, "title": "L1"}]}

    unchecked = notes_remediation.check_provenance(notes, None)
    assert not unchecked["checked"] and unchecked["findings"] == []

    checked = notes_remediation.check_provenance(notes, _ROW)
    assert checked["checked"] and checked["score"] == 0.0


def test_a_fully_cited_guide_is_clean() -> None:
    notes = {"modules": [
        {"module_number": 1, "title": "A", "serves": ["outcome 1"]},
        {"module_number": 2, "title": "B", "serves": ["outcome 2", "experience 1"]},
    ]}
    report = notes_remediation.check_provenance(notes, _ROW)

    assert report["score"] == 100.0 and report["uncited"] == []


def test_the_route_hands_the_design_row_to_remediation() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert "design_row=substrand_row" in source


# ── the model cited in the wrong field, and it still counts ──────────────────
#
# The module skeleton's placeholder read `"slos_covered": ["<the SLO(s) this
# lesson SERVES>"]`. Asked to "record which of these it serves", the model put
# every ref there — bracketed, exactly as asked, every one valid — and the page
# said the lesson named nothing. A lesson that cites correctly in the wrong
# field has cited.

_DESIGN = {
    "slos": [{"id": "grade-9-Mat-1.1-1", "text": "perform basic operations on Integers"},
             {"id": "grade-9-Mat-1.1-2", "text": "work out combined operations of integers"}],
    "key_inquiry_questions": ["How are integers used in real life?"],
    "learning_experiences": ["use number cards", "play integer games"],
    "core_competencies": [], "values": [], "required_diagrams": [], "experiments": [],
}


def _as_the_model_wrote_it() -> dict:
    return {"module_number": 1, "title": "Introduction",
            "slos_covered": ["[grade-9-Mat-1.1-1]", "[inquiry 1]", "[experience 2]",
                             "perform basic operations on Integers"]}


def test_refs_filed_in_slos_covered_are_harvested_into_serves() -> None:
    module = _as_the_model_wrote_it()
    kept = design_elements.harvest_serves(module, _DESIGN)

    assert kept == ["grade-9-Mat-1.1-1", "inquiry 1", "experience 2"]
    assert module["serves"] == kept


def test_the_objectives_line_is_left_reading_as_objectives() -> None:
    """"[grade-9-Mat-1.1-1] · [inquiry 1] · perform basic…" is not a header."""
    module = _as_the_model_wrote_it()
    design_elements.harvest_serves(module, _DESIGN)

    assert module["slos_covered"] == ["perform basic operations on Integers"]


def test_a_bracketed_phrase_that_is_not_a_ref_stays_put() -> None:
    module = {"slos_covered": ["[see page 12]", "perform basic operations"]}
    kept = design_elements.harvest_serves(module, _DESIGN)

    assert kept == []
    assert module["slos_covered"] == ["[see page 12]", "perform basic operations"]


def test_the_harvested_lesson_is_not_a_rewrite_target() -> None:
    notes = {"modules": [_as_the_model_wrote_it()]}
    report = notes_remediation.check_provenance(notes, _DESIGN)

    assert report["uncited"] == []
    assert report["score"] == 100.0


def test_an_invented_bracketed_ref_in_slos_covered_is_named() -> None:
    notes = {"modules": [{"module_number": 1, "title": "L1",
                          "slos_covered": ["[grade-9-Mat-9.9-9]"]}]}
    report = notes_remediation.check_provenance(notes, _DESIGN)

    assert report["uncited"] == [1]
    assert "grade-9-Mat-9.9-9" in report["findings"][0]


def test_the_skeleton_now_shows_where_serves_goes() -> None:
    # The module skeleton lives in the system prompt, `note-generator`, which
    # the notes route assembles; the rules block carries the element list.
    skeleton = SEED_AGENT_PROMPTS["note-generator"]

    assert '"serves":' in skeleton
    assert "this lesson serves" not in skeleton, \
        "the slos_covered placeholder must stop using the word that names the other field"

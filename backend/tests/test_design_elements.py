"""Every element a KICD design asks for, numbered once.

`design_coverage` needs a stable name for each thing a design asks for so it
can say "outcome g9-mat-02 has no question against it". The question generator
needs the SAME names so it can record which ones each question serves. Two
lists built in two places drift, and the drift is silent.
"""
from __future__ import annotations

from app.services import design_elements as de

DESIGN = {
    "slos": [{"slo_id": "g9-mat-01", "slo": "perform combined operations"},
             {"slo": "an outcome the design gave no id"}],
    "key_inquiry_questions": ["How do we use negative numbers?"],
    "learning_experiences": ["Learners work in groups", "Learners use a number line"],
    "core_competencies": ["Critical thinking"],
    "values": ["Responsibility"],
    "required_diagrams": ["A number line"],
    "experiments": [],
}


def test_an_outcome_keeps_the_design_s_own_id() -> None:
    """It is written in the design and already carried on every question, so
    using it means questions filed before any of this still match."""
    elements = de.enumerate_for(DESIGN)

    assert elements[0].ref == "g9-mat-01"


def test_an_element_with_no_id_is_numbered_by_position() -> None:
    """Nothing but an outcome has an id, so position is the only stable name
    available — which is why the numbering lives in one place."""
    refs = de.refs(DESIGN)

    assert {"outcome 2", "inquiry 1", "experience 1", "experience 2",
            "competency 1", "value 1", "diagram 1"} <= refs


def test_a_dimension_the_design_is_silent_about_contributes_nothing() -> None:
    assert de.by_dimension(DESIGN, "experiments") == []


def test_elements_come_back_in_the_design_s_own_order() -> None:
    kinds = [e.kind for e in de.enumerate_for(DESIGN)]

    assert kinds.index("outcome") < kinds.index("inquiry") < kinds.index("experience")


def test_an_empty_or_blank_entry_is_not_an_element() -> None:
    """A blank line in a design is not something to cover."""
    assert de.refs({"values": ["", "   ", "Responsibility"]}) == {"value 3"}


def test_a_design_field_stored_as_json_text_is_read() -> None:
    """These columns come back as JSONB or as text depending on the driver."""
    assert de.refs({"values": '["Responsibility"]'}) == {"value 1"}


# ── what a question may claim ───────────────────────────────────────────────


def test_an_invented_ref_is_discarded_rather_than_kept() -> None:
    """One element reading covered because a question claimed a ref that does
    not exist is the most expensive mistake a coverage report can make, and it
    would be invisible — a fabricated ref looks exactly like a real one."""
    keep, invented = de.valid_serves(
        ["g9-mat-01", "experience 9", "the one about groups"], DESIGN)

    assert keep == ["g9-mat-01"]
    assert invented == ["experience 9", "the one about groups"]


def test_a_ref_claimed_twice_is_kept_once() -> None:
    keep, _ = de.valid_serves(["inquiry 1", "inquiry 1"], DESIGN)

    assert keep == ["inquiry 1"]


def test_claiming_nothing_is_a_real_answer() -> None:
    assert de.valid_serves([], DESIGN) == ([], [])
    assert de.valid_serves(None, DESIGN) == ([], [])


# ── what the generator is shown ─────────────────────────────────────────────


def test_the_block_lists_every_ref_the_gate_will_match() -> None:
    block = de.block_for(DESIGN)

    for ref in de.refs(DESIGN):
        assert f"[{ref}]" in block


def test_the_block_says_what_a_wrongly_tagged_question_costs() -> None:
    """A question tagged with six refs to look thorough makes six elements read
    as covered when one was assessed — worse than an untagged question, which
    is at least visibly missing."""
    block = de.block_for(DESIGN)

    assert "discarded" in block
    assert "invisibly wrong" in block
    assert "empty list" in block


def test_a_design_that_states_nothing_asks_for_no_citation() -> None:
    """Rather than inviting an invented one."""
    assert de.block_for({}) == ""


def test_the_block_is_editable_without_a_deploy() -> None:
    from app.services.prompt_sync import _all_prompts

    assert "design-elements" in _all_prompts()


def test_the_question_generator_is_shown_the_list() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    assert "{{ design_elements }}" in SEED_AGENT_PROMPTS["question-generator"]


# ── and the generator records against it ────────────────────────────────────


def _normalized(raw: dict, design_row: dict | None):
    from app.services.question_normalizer import question_normalizer

    return question_normalizer.normalize_batch(
        [raw], grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", design_row=design_row)


def _item(**over):
    return {"question_id": "Q1", "question_type": "short_answer",
            "question_text": "Compare the two expressions and say which is larger.",
            "model_answer": "the second", "marking_scheme": "1 mark each",
            **over}


def test_the_refs_a_question_records_are_filed() -> None:
    batch = _normalized(_item(serves=["g9-mat-01", "inquiry 1"]), DESIGN)

    assert batch.items[0].curriculum.serves == ["g9-mat-01", "inquiry 1"]


def test_an_invented_ref_never_reaches_the_file() -> None:
    batch = _normalized(_item(serves=["g9-mat-01", "experience 9"]), DESIGN)

    assert batch.items[0].curriculum.serves == ["g9-mat-01"]


def test_with_no_design_to_check_against_nothing_is_kept() -> None:
    """A claim nobody can check is not evidence."""
    batch = _normalized(_item(serves=["anything at all"]), None)

    assert batch.items[0].curriculum.serves == []


def test_the_outcome_a_question_names_counts_as_a_ref_it_serves() -> None:
    """It was already recorded separately, so folding it in means a question
    filed before `serves` existed still reports what it serves."""
    batch = _normalized(_item(target_slo="g9-mat-01"), DESIGN)

    assert batch.items[0].curriculum.serves == ["g9-mat-01"]


def test_the_question_route_hands_the_normaliser_the_design() -> None:
    """Otherwise every ref is discarded as unverifiable and the whole thing is
    a no-op that looks like it works."""
    import inspect

    from app.routes import questions

    source = inspect.getsource(questions)
    assert "design_elements.block_for(design_row)" in source
    assert "design_row=design_row," in source


def test_every_question_call_site_is_shown_the_list() -> None:
    """A slot bound at two of three call sites renders as the literal text
    "{{ design_elements }}" at the third, which reaches the model."""
    import inspect

    from app.routes import curriculum, questions
    from app.services import pipeline

    for module in (questions, curriculum, pipeline):
        source = inspect.getsource(module)
        assert '"design_elements": design_elements.block_for(' in source, \
            module.__name__


def test_the_prompt_and_the_call_sites_still_agree() -> None:
    from app.services import prompt_bindings

    report = prompt_bindings.alignment_report()

    assert report["aligned"], report["says"]

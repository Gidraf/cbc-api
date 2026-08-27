"""Each stage sees only its own layers, and every artefact traces to the design."""
from __future__ import annotations

import pytest

from app.services import content_lineage as cl


class Skill:
    persona = "An early childhood specialist who writes for pre-literate learners."


@pytest.fixture
def chain():
    """design -> strand -> substrand -> hour notes -> diagram -> question."""
    strand = cl.Artifact(
        kind=cl.STRAND, id="s1", title="1.0 Listening and Speaking",
        content={"description": "Oral language development"},
        citations=[cl.Citation("PP1-LANG", 12, 1, "STRAND 1.0 LISTENING AND SPEAKING")],
    )
    substrand = cl.descend(
        cl.SUBSTRAND, "ss1", [strand], title="1.1 Greetings",
        content={"description": "Greetings and farewells", "allocated_hours": "4 hours"},
        own_citations=[cl.Citation("PP1-LANG", 12, 2, "1.1 Greetings and Farewell")],
    )
    hour1 = cl.descend(cl.HOUR_NOTE, "h1", [substrand], title="Hour 1", hour=1,
                       content={"summary": "Morning greetings"})
    hour2 = cl.descend(cl.HOUR_NOTE, "h2", [substrand], title="Hour 2", hour=2,
                       content={"summary": "Farewells"})
    diagram = cl.descend(cl.DIAGRAM, "d1", [hour1], title="Greeting picture cards", hour=1,
                         content={"description": "Picture cards"})
    return {"strand": strand, "substrand": substrand, "hour1": hour1, "hour2": hour2, "diagram": diagram}


# ── The layer counts the pipeline is built around ───────────────────────────

def test_notes_have_three_layers_and_never_the_design(chain):
    ctx = cl.build_context(
        cl.HOUR_NOTE, strand=chain["strand"], substrand=chain["substrand"],
        skill=Skill(), design_pages="1-76",
    )
    assert ctx["manifest"]["layers_used"] == ["strand", "substrand", "skill"]
    assert "CURRICULUM DESIGN" not in ctx["context"], "notes must not resend the design"


def test_diagrams_have_four_layers_including_exactly_one_hour(chain):
    ctx = cl.build_context(
        cl.DIAGRAM, strand=chain["strand"], substrand=chain["substrand"],
        hour_note=chain["hour1"], skill=Skill(),
    )
    assert ctx["manifest"]["layers_used"] == ["strand", "substrand", "hour_note", "skill"]
    assert "Morning greetings" in ctx["context"]
    assert "Farewells" not in ctx["context"], "a diagram belongs to its hour, not the whole sub-strand"


def test_questions_have_five_layers_and_the_combined_context(chain):
    ctx = cl.build_context(
        cl.QUESTION, strand=chain["strand"], substrand=chain["substrand"],
        notes=[chain["hour1"], chain["hour2"]], assets=[chain["diagram"]], skill=Skill(),
    )
    assert ctx["manifest"]["layers_used"] == ["strand", "substrand", "notes", "assets", "skill"]
    assert "Morning greetings" in ctx["context"] and "Farewells" in ctx["context"]
    assert "Greeting picture cards" in ctx["context"]


def test_substrands_are_the_only_stage_that_still_reads_the_design(chain):
    ctx = cl.build_context(cl.SUBSTRAND, strand=chain["strand"], design_pages="12-18")
    assert "design_pages" in ctx["manifest"]["layers_used"]
    assert "pages 12-18" in ctx["context"]


def test_prompts_narrow_as_the_chain_descends(chain):
    """The point of the design: notes cost less than sub-strands, not more."""
    substrand_ctx = cl.build_context(cl.SUBSTRAND, strand=chain["strand"], design_pages="1-76")
    notes_ctx = cl.build_context(
        cl.HOUR_NOTE, strand=chain["strand"], substrand=chain["substrand"], skill=Skill()
    )
    diagram_ctx = cl.build_context(
        cl.DIAGRAM, strand=chain["strand"], substrand=chain["substrand"],
        hour_note=chain["hour1"], skill=Skill(),
    )
    question_ctx = cl.build_context(
        cl.QUESTION, strand=chain["strand"], substrand=chain["substrand"],
        notes=[chain["hour1"], chain["hour2"]], assets=[chain["diagram"]], skill=Skill(),
    )
    assert diagram_ctx["manifest"]["chars"] < question_ctx["manifest"]["chars"]
    assert notes_ctx["manifest"]["chars"] > 0 and substrand_ctx["manifest"]["chars"] > 0


def test_a_missing_required_layer_stops_the_run(chain):
    """Superseded the earlier behaviour, which reported the gap and carried on."""
    with pytest.raises(cl.MissingParentContext):
        cl.build_context(cl.DIAGRAM, strand=chain["strand"], substrand=chain["substrand"])


def test_an_unknown_stage_is_refused():
    with pytest.raises(ValueError, match="unknown generation stage"):
        cl.build_context("vibes")


# ── Provenance ──────────────────────────────────────────────────────────────

def test_a_descendant_inherits_the_design_pages_it_rests_on(chain):
    refs = {c.ref for c in chain["diagram"].citations}
    assert "PP1-LANG 12:1" in refs, "the strand's page must survive to the diagram"
    assert "PP1-LANG 12:2" in refs, "and the sub-strand's"


def test_citations_are_not_duplicated_when_parents_share_them(chain):
    question = cl.descend(cl.QUESTION, "q1", [chain["substrand"], chain["hour1"], chain["diagram"]])
    refs = [c.ref for c in question.citations]
    assert len(refs) == len(set(refs))


def test_a_questions_context_reports_the_design_pages_behind_it(chain):
    ctx = cl.build_context(
        cl.QUESTION, strand=chain["strand"], substrand=chain["substrand"],
        notes=[chain["hour1"]], assets=[chain["diagram"]], skill=Skill(),
    )
    assert {c["ref"] for c in ctx["citations"]} >= {"PP1-LANG 12:1", "PP1-LANG 12:2"}


def test_the_chain_back_to_the_design_can_be_walked(chain):
    by_id = {a.id: a for a in chain.values()}
    walk = cl.trace_to_design(chain["diagram"], by_id)
    assert [step["kind"] for step in walk] == ["diagram", "hour_note", "substrand", "strand"]
    assert walk[-1]["citations"] == ["PP1-LANG 12:1"]


def test_an_artefact_with_no_cited_ancestry_is_created_but_carries_nothing():
    orphan = cl.descend(cl.HOUR_NOTE, "h9", [])
    assert orphan.citations == []


# ── Nothing generates without its parents ───────────────────────────────────
# Generating with a hole in the context means inventing whatever the missing
# ancestor would have said. That reads fine and rests on nothing, which is the
# failure this pipeline exists to prevent.

def test_notes_refuse_without_a_substrand(chain):
    with pytest.raises(cl.MissingParentContext) as exc:
        cl.build_context(cl.HOUR_NOTE, strand=chain["strand"], skill=Skill())
    assert exc.value.missing == ["substrand"]


def test_a_diagram_refuses_without_the_hour_it_belongs_to(chain):
    with pytest.raises(cl.MissingParentContext) as exc:
        cl.build_context(cl.DIAGRAM, strand=chain["strand"], substrand=chain["substrand"], skill=Skill())
    assert exc.value.missing == ["hour_note"]


def test_questions_refuse_without_notes_or_assets(chain):
    with pytest.raises(cl.MissingParentContext) as exc:
        cl.build_context(
            cl.QUESTION, strand=chain["strand"], substrand=chain["substrand"], skill=Skill()
        )
    assert exc.value.missing == ["notes", "assets"]


def test_substrands_refuse_without_the_design(chain):
    with pytest.raises(cl.MissingParentContext) as exc:
        cl.build_context(cl.SUBSTRAND, strand=chain["strand"])
    assert exc.value.missing == ["design_pages"]


def test_the_refusal_says_what_to_do_about_it(chain):
    with pytest.raises(cl.MissingParentContext) as exc:
        cl.build_context(cl.DIAGRAM, strand=chain["strand"], substrand=chain["substrand"])
    message = str(exc.value)
    assert "hour_note" in message
    assert "Generate the lesson notes" in message, "an error should name the remedy"


def test_a_missing_skill_does_not_block_generation(chain):
    """A skill changes how content is written, not what it can be about."""
    ctx = cl.build_context(cl.HOUR_NOTE, strand=chain["strand"], substrand=chain["substrand"])
    assert ctx["manifest"]["layers_missing_optional"] == ["skill"]
    assert ctx["context"], "generation continues, unskilled but grounded"


def test_the_check_can_be_relaxed_for_inspection(chain):
    """Previewing a prompt should show the gap, not raise on it."""
    ctx = cl.build_context(cl.DIAGRAM, strand=chain["strand"], substrand=chain["substrand"], strict=False)
    assert ctx["manifest"]["layers_missing"] == ["hour_note", "skill"]


def test_required_layers_exclude_the_skill():
    assert cl.required_layers(cl.QUESTION) == ("strand", "substrand", "notes", "assets")
    assert cl.required_layers(cl.DIAGRAM) == ("strand", "substrand", "hour_note")

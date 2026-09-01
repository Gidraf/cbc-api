"""How a subject writes the things it cannot write in words.

A fraction typed as "3/4", an angle as "45 degrees" and an equation as "x
squared plus 2x minus 3 equals 0" all survive the trip through JSON and all
arrive at a Kenyan learner as something they have never seen in a textbook.
Worse, they cannot be marked: "3/4", "0.75" and "three quarters" are the same
answer written three ways, and a scheme expecting one fails the other two.
"""
from __future__ import annotations

import pathlib

from app.services import notation


# ── which subjects get which rules ──────────────────────────────────────────


def test_a_design_that_calls_it_activities_still_gets_the_notation():
    """The design says "Mathematical Activities" at PP1 and "Mathematics" at
    Grade 9. A pattern anchored on the whole word matches neither."""
    assert notation.uses_notation("Mathematical Activities")
    assert notation.uses_notation("Mathematics")


def test_a_subject_with_no_mathematics_gets_no_block():
    """A CRE guide carrying two pages about balancing equations spends a page
    of prompt on something it never uses, and every irrelevant instruction
    makes the relevant ones harder to find."""
    assert notation.block_for("Christian Religious Education") == ""
    assert notation.block_for("Creative Activities") == ""


def test_home_science_is_cookery_not_stoichiometry():
    """Matching it on "science" gave it two pages about balancing equations."""
    assert notation.block_for("Home Science") == ""
    assert notation.block_for("Integrated Science") != ""


def test_chemistry_gets_formulae_and_physics_gets_units():
    assert "SO_4^{2-}" in notation.block_for("Chemistry")
    assert "\\text{m/s}" in notation.block_for("Physics")


def test_only_the_subjects_that_draw_figures_get_the_construction_spec():
    assert notation.geometry_block("Mathematics")
    assert notation.geometry_block("Physics")
    assert notation.geometry_block("Christian Religious Education") == ""


# ── the notation itself has to be usable ────────────────────────────────────


def test_the_latex_is_latex_and_not_double_escaped():
    """`$\\\\frac{3}{4}$` reaches the model as an escape sequence, not as a
    fraction, and it will copy what it is shown."""
    block = notation.block_for("Mathematics")

    assert "$\\frac{3}{4}$" in block
    assert "$\\\\frac" not in block
    assert "$45^\\circ$" in block


def test_it_says_what_the_wrong_form_looks_like_beside_the_right_one():
    """A rule with no counter-example is a rule that gets read past."""
    block = notation.block_for("Mathematics")

    assert "not 3/4" in block
    assert 'not "45 degrees"' in block


def test_prose_is_told_to_stay_prose():
    """"Cut the orange into $4$ equal parts" is worse than the sentence it
    replaced."""
    assert "PROSE STAYS PROSE" in notation.block_for("Mathematics")


def test_the_notation_is_held_back_from_a_learner_who_has_not_met_it():
    """A child counting to ten has not met a fraction bar, and writing one
    teaches them nothing."""
    assert "USE ONLY WHAT THE LEARNER HAS MET" in notation.block_for("Mathematics")


# ── a figure that can be drawn twice the same way ───────────────────────────


def test_a_figure_is_asked_for_as_a_construction_not_a_description():
    """"A triangle with a right angle at B" leaves every length, every position
    and every label to whoever draws it — and the question asked about it then
    does not match the picture printed beside it."""
    block = notation.geometry_block("Mathematics")

    assert '"points":' in block and '"segments":' in block and '"angles":' in block
    assert "constructible" in block


def test_a_measurement_is_stated_once():
    """A length on the segment and again in the prose is two places to be
    wrong."""
    assert "State a measurement ONCE" in notation.geometry_block("Mathematics")


def test_a_diagram_is_told_not_to_label_its_own_answer():
    assert "labels the answer has asked nothing" in \
        notation.geometry_block("Mathematics")


def test_not_to_scale_is_declared_rather_than_drawn():
    assert "`not_to_scale`" in notation.geometry_block("Mathematics")


# ── checking what came back ─────────────────────────────────────────────────


def test_mathematics_written_as_speech_is_caught():
    found = {f["kind"] for f in notation.unmarked_in(
        "Cut it into 3/4. Then x squared. The angle is 45 degrees. "
        "Take the square root of 16.")}

    assert {"fraction", "power", "degrees", "root"} <= found


def test_properly_written_mathematics_is_not_flagged():
    assert notation.unmarked_in(
        "Each part is $\\frac{3}{4}$ and the angle is $45^\\circ$.") == []


def test_a_subject_without_notation_is_not_scored_on_it():
    report = notation.check({"title": "Our God"}, "Christian Religious Education")

    assert not report["checked"]


def test_content_with_no_latex_at_all_scores_worst():
    poor = notation.check({"body": "Cut it into 3/4 and turn 45 degrees."},
                          "Mathematics")
    good = notation.check({"body": "Cut it into $\\frac{3}{4}$ and turn $45^\\circ$."},
                          "Mathematics")

    assert poor["score"] < good["score"]
    assert good["clean"] and not poor["clean"]


def test_findings_are_reported_not_corrected():
    """"3/4" inside a date, a ratio a teacher reads aloud, and a genuine
    fraction all look alike from here, and rewriting a guide's prose on a
    regular expression is how a lesson acquires a fraction it never had."""
    source = pathlib.Path(notation.__file__).read_text()

    assert "Reported, not corrected" in source


# ── wiring ──────────────────────────────────────────────────────────────────


def test_every_station_that_says_who_it_writes_for_also_says_how_to_write_it():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/routes/curriculum.py").read_text()

    assert source.count('"language_register": language_block(') == \
        source.count('"notation": notation.block_for(')


def test_the_question_station_gets_the_same_notation_as_the_lesson():
    """A question whose answer is "3/4" and a scheme expecting
    $\\frac{3}{4}$ are the same answer written two ways, and one is marked
    wrong."""
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/routes/questions.py").read_text()

    assert '"notation": notation.block_for(' in source


def test_the_reviewers_hold_the_same_rule_they_are_judging_against():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/services/pipeline.py").read_text()

    assert '"notation": notation.block_for(' in source


def test_the_geometry_spec_reaches_the_station_that_draws_figures():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_plan_visuals)
    assert "notation.geometry_block(payload.subject)" in source
    assert "{geometry_spec}" in source


def test_every_seeded_prompt_that_states_the_register_has_a_slot_for_notation():
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/services/langfuse_seed.py").read_text()

    assert source.count("{{ level_register }}") == source.count("{{ notation }}")


# ── prompts in folders ──────────────────────────────────────────────────────


def test_prompts_are_written_under_a_folder_as_well_as_their_flat_name():
    """Langfuse has no folders: a prompt's NAME is its path, and a slash is
    what the console renders as one. Nineteen prompts in a flat list is a list
    nobody edits."""
    from app.services.prompt_sync import _all_prompts

    names = set(_all_prompts())

    assert "generate/lesson-plan" in names
    assert "note-generator" in names, "the flat name must survive"
    assert "review/approver-1" in names


def test_the_flat_name_survives_so_edits_already_made_are_not_orphaned():
    """Renaming outright would throw away every edit made against the old name
    — which is the work this is supposed to make easier."""
    from app.services.langfuse_context import langfuse_context_service as svc
    import inspect

    source = inspect.getsource(svc.get_agent_prompt)
    assert "self.get_prompt(agent_name)" in source, "no fallback to the flat name"


def test_the_foldered_prompt_wins_where_both_exist():
    """Falling back the other way would silently serve a stale prompt to
    whoever migrated first."""
    from app.services.langfuse_context import langfuse_context_service as svc

    assert svc.folder_name("note-generator") == "generate/lesson-plan"
    assert svc.folder_name("something-new") == "something-new"


def test_every_generating_station_has_a_folder():
    from app.services.langfuse_context import langfuse_context_service as svc

    for agent in ("note-generator", "diagram-generator",
                  "media-prompt-generator", "activity-generator",
                  "simulation-generator", "question-generator"):
        assert svc.FOLDERS[agent].startswith("generate/"), agent

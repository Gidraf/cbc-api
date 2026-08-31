"""Nobody was writing the words.

Everything the pipeline produced was a DIRECTION. "Choose a simple song about
God." "Tell a simple story that illustrates God's love." A teacher reading that
still has to find the song and write the story — which is the whole of the
work, and none of it was here.
"""
from __future__ import annotations

import pathlib

from app.services import lesson_material as lm

PLAN = {
    "modules": [
        {"module_number": 1, "title": "Lesson 1: Introducing God",
         "exposition_segments": [
             {"topic": "Singing Songs About God", "minutes": 10,
              "body": "Choose a simple song about God, such as 'He's Got the "
                      "Whole World in His Hands.' Teach them the lyrics line "
                      "by line."},
             {"topic": "Saying the Name of God", "minutes": 10,
              "body": "Begin by asking the children, 'What is God's name in "
                      "your language?' Encourage them to respond."},
         ]},
        {"module_number": 2, "title": "Lesson 2: God's Love",
         "exposition_segments": [
             {"topic": "A Story", "minutes": 10,
              "body": "Tell a simple story that illustrates God's love."},
         ]},
    ]
}


# ── reading the plan ────────────────────────────────────────────────────────


def test_every_instruction_becomes_its_own_directive():
    """One model call per instruction, not one per guide: the failure this
    layer prevents — something general where something specific was needed — is
    exactly what a long prompt produces."""
    plan = lm.directives_of(PLAN)

    assert plan.modules == 2
    assert len(plan.directives) == 3
    assert [d.topic for d in plan.directives][:1] == ["Singing Songs About God"]


def test_the_instructions_that_leave_the_work_undone_are_marked():
    """"Choose a song" and "tell a story" are exactly the places a guide leaves
    the teacher to do the writing."""
    plan = lm.directives_of(PLAN)
    unfulfilled = {d.topic for d in plan.unfulfilled}

    assert "Singing Songs About God" in unfulfilled
    assert "A Story" in unfulfilled
    assert "Saying the Name of God" not in unfulfilled


def test_a_plan_with_no_segments_falls_back_to_its_exposition():
    plan = lm.directives_of({"modules": [
        {"module_number": 1, "title": "L1", "duration_minutes": 30,
         "teacher_exposition": "Introduce the concept of God."}]})

    assert len(plan.directives) == 1
    assert plan.directives[0].minutes == 30


def test_a_plan_with_nothing_in_it_yields_nothing():
    assert lm.directives_of({}).directives == []
    assert lm.directives_of("not a plan").directives == []


# ── what is asked for ───────────────────────────────────────────────────────


def _prompt(index: int = 0) -> str:
    plan = lm.directives_of(PLAN)
    return lm.prompt_for(plan.directives[index], register="PP1, 4-5 years old.",
                         faith="Christian Religious Education.",
                         sub_strand="Our God",
                         slos=["identify three qualities of God"])


def test_the_prompt_carries_the_instruction_it_is_fulfilling():
    assert "Choose a simple song about God" in _prompt()


def test_it_asks_for_the_thing_rather_than_a_description_of_it():
    prompt = _prompt()

    assert "WRITE THE VERSE OUT" in prompt
    assert "Do not repeat the instruction back" in prompt
    assert "Produce it." in prompt


def test_it_carries_the_register_and_the_faith_scope():
    prompt = _prompt()

    assert "PP1, 4-5 years old." in prompt
    assert "Christian Religious Education." in prompt


def test_it_asks_where_the_words_came_from():
    """A teacher introducing a song to a class should know whether it is one
    the children may already know."""
    assert '"attribution"' in _prompt()


def test_it_forbids_invention_of_sources():
    assert "Invent no scripture reference" in _prompt()


# ── checking what came back ─────────────────────────────────────────────────


def _material(*pieces) -> dict:
    return {"material": list(pieces)}


def test_material_that_fulfils_every_instruction_is_clean():
    plan = lm.directives_of(PLAN)
    report = lm.check(_material(
        {"module_number": 1, "index": 1, "say": "He has got the whole world. " * 8},
        {"module_number": 1, "index": 2, "say": "Good morning. Today we will " * 8},
        {"module_number": 2, "index": 1, "say": "Once there was a boy who " * 8},
    ), plan)

    assert report.clean
    assert report.score == 100.0


def test_an_instruction_handed_back_as_material_is_caught():
    """Asked to write the song, a model returns "a simple song about God's
    love, sung with actions" — the instruction again, one adjective longer, and
    the teacher is exactly where they started."""
    plan = lm.directives_of(PLAN)
    echo = ("Choose a simple song about God, such as He's Got the Whole World "
            "in His Hands, and teach them the lyrics line by line to the "
            "children in the class.")
    report = lm.check(_material(
        {"module_number": 1, "index": 1, "say": echo}), plan)

    assert report.echoed
    assert report.echoed[0]["topic"] == "Singing Songs About God"


def test_a_heading_where_material_was_asked_for_is_caught():
    plan = lm.directives_of(PLAN)
    report = lm.check(_material(
        {"module_number": 1, "index": 1, "say": "A song about God."}), plan)

    assert report.thin
    assert report.thin[0]["chars"] < lm.MIN_MATERIAL_CHARS


def test_an_instruction_with_no_material_at_all_lowers_the_score():
    plan = lm.directives_of(PLAN)
    report = lm.check(_material(
        {"module_number": 1, "index": 1, "say": "He has got the whole world. " * 8}),
        plan)

    assert report.written == 1
    assert report.total == 3
    assert not report.clean


def test_nothing_returned_is_not_a_crash():
    assert lm.check({}, lm.directives_of(PLAN)).written == 0
    assert lm.check({"material": "wrong shape"}, lm.directives_of(PLAN)).written == 0


# ── where it sits in the pipeline ───────────────────────────────────────────


def test_the_material_follows_the_plan_it_is_written_from():
    """The words cannot be produced until there is an instruction telling them
    what to be."""
    from app.routes import curriculum

    steps = list(curriculum.PIPELINE_STEPS)
    assert steps.index("material") == steps.index("notes") + 1
    assert curriculum._STEP_SCOPE["material"] == "sub_strand"


def test_it_is_queueable_like_every_other_station():
    """One call per instruction makes it the slowest station here, which is the
    reason the queue exists."""
    from app.routes import curriculum

    endpoint, model = curriculum._QUEUEABLE["material"]
    assert endpoint == "factory_generate_material"
    assert model.model_fields


def test_it_has_its_own_stage_so_it_can_have_its_own_model():
    """The only stage whose product a child hears verbatim."""
    from app.services import stages

    names = [s.name for s in stages.STAGES]
    stage = next(s for s in stages.STAGES if s.name == "material_generation")

    assert "material_generation" in names
    assert stage.falls_back_to == "notes_generation"
    assert "instruction reworded" in stage.guidance


def test_it_is_its_own_artifact_kind_with_its_own_review_scope():
    from app.services import artifact_registry, review_layers

    assert "material" in artifact_registry.KINDS
    scope = review_layers.KIND_SCOPE["material"]

    assert "the song written out" in scope["is"]
    # And the reviewer is told not to re-judge the plan.
    assert "Judge whether the words fulfil the instruction" in scope["elsewhere"]


def test_the_plan_is_described_as_a_plan():
    """It says "choose a simple song about God". Calling that "the teaching
    notes" is why nobody noticed the words were missing."""
    from app.services import review_layers

    assert "LESSON PLAN" in review_layers.KIND_SCOPE["notes"]["is"]
    assert "the song's words belong in the `material` artifact" \
        in review_layers.KIND_SCOPE["notes"]["is"]


def test_one_instruction_failing_does_not_lose_the_sub_strand():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert 'piece = {"say": "", "error": str(exc)[:200]}' in source


def test_the_material_records_which_plan_it_came_from():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert '"from_plan": {"artifact_id": plan_id' in source
    assert "parent=plan_id" in source


# ── throwing a draft away ───────────────────────────────────────────────────


def test_a_draft_can_be_discarded_from_the_console():
    """A draft nobody can throw away accumulates until the version list is a
    haystack."""
    panel = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/views/VersionReview.tsx").read_text()

    assert "function DiscardVersion(" in panel
    assert "Delete version {version} and its reviews?" in panel


def test_a_version_holding_a_label_says_why_it_cannot_be_discarded():
    panel = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/views/VersionReview.tsx").read_text()

    assert "held by {held.join" in panel
    assert "silently loses its approved copy" in panel


# ── the words have to sound right for the age KICD states ───────────────────


def test_the_language_band_comes_from_the_age_the_design_states():
    from app.services.level_register import language_block

    pp1 = language_block("grade-pp1")

    assert "4-5 years old" in pp1
    assert "Pre-literate" in pp1


def test_each_band_gets_its_own_vocabulary_and_sentence_rule():
    from app.services.level_register import language_block

    pp1, g3, g9 = (language_block(g) for g in ("grade-pp1", "grade-3", "grade-9"))

    assert "Words a four-year-old already uses at home" in pp1
    assert "one at a time and used again immediately" in g3
    assert "Do not simplify a technical term" in g9


def test_the_length_target_is_the_one_the_check_measures_against():
    """A prompt asking for one register while the check grades against another
    is how content comes back "correct" and unusable, and neither number is
    wrong on its own."""
    from app.services.dna_scoring import _reading_target
    from app.services.grade_order import grade_ordinal
    from app.services.level_register import language_block

    for grade in ("grade-pp1", "grade-3", "grade-6", "grade-9"):
        target = _reading_target(grade_ordinal(grade))
        assert f"aim near {target:.0f} words a sentence" in language_block(grade)


def test_the_target_is_stated_as_a_mean_not_a_rule():
    """Every sentence the same length is not the register; it is a metronome."""
    from app.services.level_register import language_block

    assert "it is a MEAN" in language_block("grade-pp1")


def test_pre_primary_is_told_to_speak_to_the_child():
    from app.services.level_register import language_block

    assert "'Look at your hands' rather than 'learners observe their hands'" \
        in language_block("grade-pp1")


def test_an_unknown_grade_produces_no_band_rather_than_a_wrong_one():
    from app.services.level_register import language_block

    assert language_block("") == "" or "HOW THE WORDS MUST SOUND" in language_block("")


def test_the_material_prompt_carries_the_band():
    plan = lm.directives_of(PLAN)
    prompt = lm.prompt_for(plan.directives[0], register="", faith="",
                           sub_strand="Our God", slos=[],
                           language="=== HOW THE WORDS MUST SOUND ===")

    assert "=== HOW THE WORDS MUST SOUND ===" in prompt


def test_the_station_passes_the_band_for_the_grade_it_is_writing_for():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert "language = language_block(payload.grade)" in source
    assert "language=language," in source


def test_every_station_that_states_who_it_writes_for_also_states_how():
    """The register governs what the learner may be ASKED to do; the band
    governs the sentences they hear while being asked. Only the first half was
    ever sent."""
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/routes/curriculum.py").read_text()

    assert source.count('"level_register": register_block(') == \
        source.count('"language_register": language_block(')


# ── a song the instruction names is not an echo of the instruction ──────────


def test_material_is_not_called_an_echo_for_using_the_words_it_was_named_by():
    """An instruction that names the song — "such as 'He's Got the Whole World
    in His Hands'" — shares almost every word with the song's actual verse."""
    plan = lm.directives_of(PLAN)
    verse = ("He's got the whole world in His hands. " * 6
             + "He's got you and me, brother, in His hands. " * 4)
    report = lm.check({"material": [
        {"module_number": 1, "index": 1, "say": verse}]}, plan)

    assert not report.echoed, report.echoed


def test_a_restatement_is_still_caught():
    """What a restatement cannot do is be much longer than the thing it
    restates."""
    plan = lm.directives_of(PLAN)
    report = lm.check({"material": [
        {"module_number": 1, "index": 1,
         "say": "Choose a simple song about God, such as the one named, and "
                "teach the children the lyrics of that song line by line."}]},
        plan)

    assert report.thin or report.echoed, "a restatement got past"


def test_a_restatement_padded_out_to_length_is_left_to_the_reviewer():
    """Stated rather than hidden. The mechanical rule is narrow on purpose — an
    echo is material no longer than its instruction that shares its vocabulary,
    and that claim has almost no false positives. A restatement padded with
    connectives until it is twice the length is a judgement, and dressing a
    judgement up as a measurement is how this pipeline came to trust numbers it
    should not have."""
    plan = lm.directives_of(PLAN)
    padded = ("Choose a simple song about God, such as the one named in the "
              "lesson, and teach the children the lyrics of that song line by "
              "line, about God, until they can sing the song about God line by "
              "line.")
    report = lm.check({"material": [
        {"module_number": 1, "index": 1, "say": padded}]}, plan)

    assert not report.echoed
    assert report.written == 1

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


# ── the station has to report its gate the way every other station does ─────


def test_the_material_station_reports_a_gate() -> None:
    """It returned its findings under `coverage` and no `quality_gate` at all.

    The review loop reads `quality_gate`, so it saw no score, no pass and
    nothing to act on — and filed a run that had fulfilled 21 of 21
    instructions at 95.2/100 as "0/100, not passed, the gate failed but named
    nothing to fix". The number the operator saw had no relation to the work.
    """
    import inspect as _inspect

    from app.routes import curriculum
    from app.services.lesson_material import MaterialReport, gate_of

    source = _inspect.getsource(curriculum.factory_generate_material)
    assert '"quality_gate": lesson_material.gate_of(report)' in source

    gate = gate_of(MaterialReport(total=21, written=21, echoed=[
        {"title": "Introducing God's Name", "chars": 168}]))

    assert gate["overall_score"] == 95
    assert gate["passed"] is True
    assert "95.2/100" in gate["summary_message"]


def test_the_loop_is_given_something_to_act_on() -> None:
    """Without `next_actions` the loop has a failure it cannot regenerate
    against, which is the same call again at the same price."""
    from app.services.lesson_material import MaterialReport, gate_of
    from app.services.review_cycle import _directives_from

    report = MaterialReport(
        total=4, written=3,
        thin=[{"title": "Singing Together", "chars": 40}],
        echoed=[{"title": "A song about God", "chars": 120}],
    )
    gate = gate_of(report)

    assert gate["passed"] is False
    directives = _directives_from(gate)
    assert directives, "the loop must have something to regenerate against"
    # Named per piece, not as an average.
    assert any("A song about God" in d for d in directives)
    assert any("Singing Together" in d for d in directives)
    assert any("got no material at all" in d for d in directives)


def test_a_clean_run_passes() -> None:
    from app.services.lesson_material import MaterialReport, gate_of

    gate = gate_of(MaterialReport(total=21, written=21))
    assert gate["passed"] is True and gate["overall_score"] == 100
    assert gate["next_actions"] == []


def test_the_result_can_be_read_rather_than_only_copied() -> None:
    """A station could finish 21 pieces of material and the operator had no way
    to read one of them."""
    from pathlib import Path

    factory = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/ContentFactory.tsx")
        .read_text().split()
    )
    assert "Read it as a book" in factory
    assert '["notes", "material"].includes(station.id)' in factory


# ── one classroom voice for every grade ─────────────────────────────────────


def _pieces():
    return [
        {"title": "Introduction to Arabic Sounds", "module_number": 1, "topic": "a",
         "say": ("Hello, everyone! Let's start with the letter baa. Can you repeat after "
                 "me? Great! Wonderful! Now the letter taa. Excellent! Fantastic! "
                 "Great job, everyone! " * 3),
         "learner_does": "The children repeat each sound after the teacher."},
        {"title": "Collaborative Articulation", "module_number": 1, "topic": "b",
         "say": ("Pair up. One of you says the sound for fatha; the other repeats it, "
                 "then you swap. If your partner's vowel is short where it should be "
                 "long, say so and try again. " * 4),
         "learner_does": "Learners pair up and take turns articulating the sounds."},
    ]


def _plan():
    from app.services.lesson_material import Directive, Plan
    return Plan(modules=1, directives=[
        Directive(index=1, module_number=1, module_title="L1", topic="a",
                  instruction="write it", minutes=10),
        Directive(index=2, module_number=1, module_title="L1", topic="b",
                  instruction="write it", minutes=15),
    ])


def test_an_older_learner_written_to_as_an_infant_is_caught() -> None:
    """A Grade 6 Arabic lesson came back saying "Wonderful! Fantastic! Great
    job, everyone!" after every turn, and telling the teacher what "the
    children" do. An eleven-year-old reads that as being talked down to.
    """
    from app.services.lesson_material import check

    report = check({"material": _pieces()}, _plan(), grade="grade-6")

    assert len(report.infantilised) == 1
    found = report.infantilised[0]
    assert found["title"] == "Introduction to Arabic Sounds"
    assert "the children" in found["phrases"]
    assert "wonderful!" in found["phrases"]
    # The piece written properly for this age is not flagged.
    assert report.score == 50.0
    assert report.clean is False


def test_the_same_words_are_right_at_pre_primary() -> None:
    """Below lower primary that register is correct rather than wrong, and a
    check that fires everywhere is a check that gets turned off."""
    from app.services.lesson_material import check

    for grade in ("grade-pp1", "grade-pp2", "grade-1", "grade-3"):
        report = check({"material": _pieces()}, _plan(), grade=grade)
        assert report.infantilised == [], grade
        assert report.score == 100.0, grade


def test_the_loop_is_told_what_to_change() -> None:
    """Without a named directive the regeneration is the same call again."""
    from app.services.lesson_material import check, gate_of

    gate = gate_of(check({"material": _pieces()}, _plan(), grade="grade-6"))

    assert gate["passed"] is False
    assert any(f["aspect"] == "register" and f["status"] == "fail"
               for f in gate["reviewer"]["feedback"])
    directive = next(a for a in gate["next_actions"] if "infant" in a)
    assert "This learner is not four" in directive
    assert "'learners', not 'children'" in directive


def test_the_prompt_says_the_register_is_the_voice() -> None:
    """The schema field itself said "what the children do while this happens" —
    the model's cue to write for children, whatever the grade."""
    from app.services.lesson_material import Directive, prompt_for

    directive = Directive(index=1, module_number=1, module_title="L1",
                          topic="a", instruction="write it", minutes=10)
    prompt = prompt_for(directive, register="AUDIENCE: Upper-primary learners",
                        faith="", sub_strand="Pronunciation", slos=[])

    assert '"what the learners do while this happens"' in prompt
    assert "what the children do" not in prompt
    assert "THE REGISTER ABOVE IS THE VOICE, NOT A NOTE" in prompt
    assert "nursery warmth poured over an upper-primary lesson" in prompt
    # And the opposite failure is named too, or the fix trades one for the other.
    assert "a four-year-old cannot follow a subordinate clause" in prompt


def test_the_printed_page_does_not_call_them_children() -> None:
    from pathlib import Path

    renderer = (Path(__file__).resolve().parents[1]
                / "app/services/notes_renderer.py").read_text()
    assert '("learner_does", "The learners")' in renderer
    # The comment quotes the old label to explain it; match the code.
    assert '("learner_does", "The children")' not in renderer

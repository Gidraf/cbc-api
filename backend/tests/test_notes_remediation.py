"""A validator whose finding changes nothing is a comment.

Every mechanical check in this pipeline worked and none of them changed
anything. A PP1 guide came back with three lessons built to one template, an
`slo_map` naming a lesson that taught something else, and a learning experience
that was really an outcome. All three were found, scored, reported — and the
operator's only move was to press the button again and hope.
"""
from __future__ import annotations

from app.services import notes_remediation, run_log

DESIGN = [
    "say the name of God in their mother tongue or language of catchment area",
    "use gestures to describe God; Mungu ni mkuu na wa ajabu sana",
    "sing songs about God in groups",
    "in turns, say what they know about God (loving, creator, and provider)",
    "listen to a recorded clip of a short prayer",
    "say a short prayer to God in groups",
    "sing songs in groups",
]
QUALITIES = "identify three qualities of God"
PRAYERS = "practice saying short prayers"
LOVE = "appreciate God as a loving heavenly father"
SLOS = [QUALITIES, PRAYERS, LOVE]

FULL = {
    "duration_minutes": 30, "learning_intent": "…", "formative_check": "…",
    "differentiation": {"struggling": "…", "confident": "…", "sne": "…"},
    "key_questions": ["…"], "resources_needed": ["…"],
    "common_misconceptions": [{"misconception": "…"}],
}


def _module(n: int, title: str, slo: str, used: list[str], ref: str,
            topics: list[str]) -> dict:
    return {**FULL, "module_number": n, "title": f"Lesson {n}: {title}",
            "slos_covered": [slo], "learning_experiences_used": used,
            "citations": [{"ref": ref, "claim": "c", "quote": "q"}],
            "exposition_segments": [
                {"topic": t, "minutes": 10,
                 "body": f"Teaching for {t}. " + "Detail. " * 20}
                for t in topics]}


def _guide() -> dict:
    return {
        "slo_map": [
            {"slo": QUALITIES, "taught_in": [1], "assessed_in": [1]},
            # Says prayer is taught in lesson 3. Lesson 3 teaches love.
            {"slo": PRAYERS, "taught_in": [2, 3], "assessed_in": [3]},
        ],
        "modules": [
            _module(1, "Introducing God", QUALITIES, [DESIGN[0]], "203:26",
                    ["Saying the Name of God", "Using Gestures", "Singing"]),
            _module(2, "Practicing Prayer", PRAYERS, [DESIGN[4], DESIGN[5]],
                    "203:36", ["What is Prayer?", "Listening to a Prayer",
                               "Saying Short Prayers"]),
            # An OUTCOME in learning_experiences_used, and the same three beats
            # as lesson 4 below.
            _module(3, "Appreciating God's Love", LOVE, [LOVE], "203:22",
                    ["Understanding God's Love",
                     "Expressing Appreciation through Prayer",
                     "Singing about God's Love"]),
            _module(4, "God's Love in Our Lives", LOVE, [LOVE], "203:22",
                    ["Recognizing God's Love",
                     "Expressing Feelings through Prayer",
                     "Celebrating God's Love through Song"]),
        ],
    }


# ── the repairs that need no model ──────────────────────────────────────────


def test_the_map_is_derived_from_the_modules_rather_than_authored():
    """It said prayer was taught in lesson 3; lesson 3 taught love and had no
    prayer in it. Writing the map separately from the modules is what let the
    two disagree, so it is derived and cannot."""
    guide = _guide()
    note = notes_remediation.rebuild_slo_map(guide, SLOS)

    rows = {r["slo"]: r for r in guide["slo_map"]}
    assert rows[PRAYERS]["taught_in"] == [2]
    assert rows[LOVE]["taught_in"] == [3, 4]
    assert "Rebuilt `slo_map`" in note


def test_the_derived_map_assesses_where_the_outcome_was_taught_last():
    guide = _guide()
    notes_remediation.rebuild_slo_map(guide, SLOS)
    love = next(r for r in guide["slo_map"] if r["slo"] == LOVE)

    assert love["assessed_in"] == [4]


def test_an_outcome_no_lesson_claims_is_left_out_rather_than_invented():
    guide = _guide()
    for module in guide["modules"]:
        module["slos_covered"] = [QUALITIES]
    notes_remediation.rebuild_slo_map(guide, SLOS)

    assert [r["slo"] for r in guide["slo_map"]] == [QUALITIES]


def test_a_map_that_already_matches_is_left_alone():
    guide = _guide()
    notes_remediation.rebuild_slo_map(guide, SLOS)
    before = [dict(r) for r in guide["slo_map"]]

    assert notes_remediation.rebuild_slo_map(guide, SLOS) == ""
    assert guide["slo_map"] == before


def test_an_outcome_listed_as_a_learning_experience_is_removed():
    """The field is what the learner is guided to DO, and the design's bullets
    are the whole of what may appear in it."""
    guide = _guide()
    note = notes_remediation.strip_invented_experiences(guide, DESIGN)

    assert guide["modules"][2]["learning_experiences_used"] == []
    assert LOVE in note


def test_a_genuine_experience_survives_the_strip():
    guide = _guide()
    notes_remediation.strip_invented_experiences(guide, DESIGN)

    assert guide["modules"][1]["learning_experiences_used"] == [DESIGN[4], DESIGN[5]]


def test_with_no_design_nothing_is_stripped():
    guide = _guide()

    assert notes_remediation.strip_invented_experiences(guide, []) == ""
    assert guide["modules"][2]["learning_experiences_used"] == [LOVE]


# ── the loop ────────────────────────────────────────────────────────────────


def test_the_free_repairs_run_even_with_no_generator():
    guide, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS)

    assert report.attempted
    assert report.score_after > report.score_before
    assert report.stopped_because == "no_generator"
    assert any("Rebuilt `slo_map`" in d
               for p in report.passes for d in p.deterministic)


def test_a_clean_guide_is_not_touched():
    guide = {
        "slo_map": [
            {"slo": QUALITIES, "taught_in": [1], "assessed_in": [1]},
            {"slo": PRAYERS, "taught_in": [2], "assessed_in": [2]},
        ],
        "modules": [
            _module(1, "Introducing God", QUALITIES, DESIGN[:4], "203:26",
                    ["Saying the Name of God", "Using Gestures", "Singing"]),
            _module(2, "Practicing Prayer", PRAYERS, DESIGN[4:], "203:36",
                    ["What is Prayer?", "Listening to a Recorded Clip",
                     "Praying Together in Twos"]),
        ],
    }

    _, report = notes_remediation.run(
        guide, design_experiences=DESIGN, slos=SLOS)

    assert report.clean, report.outstanding
    assert not report.attempted
    assert report.stopped_because == "clean"


def _rewriter(calls: list) -> object:
    """A generator that actually fixes the lesson it is asked about."""
    def generate(model_config, messages, **kw):
        calls.append(messages[-1]["content"])
        return type("R", (), {"content": {"modules": [{
            "module_number": 4,
            "title": "Lesson 4: Songs About God",
            "slos_covered": [LOVE],
            "learning_experiences_used": [DESIGN[2], DESIGN[6]],
            "citations": [{"ref": "203:32", "claim": "c", "quote": "q"}],
            "exposition_segments": [
                {"topic": "Learning a New Song", "minutes": 10,
                 "body": "Teach the class one verse at a time. " + "Detail. " * 20},
                {"topic": "Singing It in Two Groups", "minutes": 10,
                 "body": "Split the class and let each half answer. " + "Detail. " * 20},
                {"topic": "Adding Our Own Actions", "minutes": 10,
                 "body": "Ask each child for one movement to add. " + "Detail. " * 20},
            ]}]}})()
    return generate


def test_a_templated_lesson_is_sent_back_and_the_rewrite_lands():
    calls: list = []
    guide, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=_rewriter(calls), model_config=object(),
        base_messages=[{"role": "system", "content": "…"}],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert calls, "the generator was never asked"
    assert "Rewrite ONLY lesson(s) 4" in calls[0]
    assert guide["modules"][3]["title"] == "Lesson 4: Songs About God"
    assert report.score_after > report.score_before


def test_the_rewrite_instruction_carries_the_actual_findings():
    calls: list = []
    notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=_rewriter(calls), model_config=object(),
        base_messages=[], sub_strand="Our God", allocation_phrase="7 lessons")

    assert "same template" in calls[0]
    assert "must not be the earlier lesson in new words" in calls[0]


def test_the_earlier_lesson_of_a_pair_is_never_the_one_rewritten():
    """It is the real lesson; the copy is the padding."""
    calls: list = []
    notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=_rewriter(calls), model_config=object(),
        base_messages=[], sub_strand="Our God", allocation_phrase="7 lessons")

    assert "lesson(s) 3" not in calls[0]


def test_a_rewrite_that_omits_a_field_does_not_delete_it():
    def thin(model_config, messages, **kw):
        return type("R", (), {"content": {"modules": [
            {"module_number": 4, "title": "Lesson 4: Songs"}]}})()

    guide, _ = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=thin, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert guide["modules"][3]["duration_minutes"] == 30
    assert guide["modules"][3]["differentiation"]


def test_a_pass_that_does_not_help_stops_the_loop():
    """A model that has not fixed this in one attempt will not fix it in five,
    and each attempt is paid for."""
    calls: list = []

    def useless(model_config, messages, **kw):
        calls.append(1)
        return type("R", (), {"content": {}})()

    _, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=useless, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert len(calls) == 1
    assert report.stopped_because == "no_improvement"


def test_a_generator_that_raises_does_not_lose_the_guide():
    def broken(model_config, messages, **kw):
        raise RuntimeError("provider timed out")

    guide, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=broken, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert report.stopped_because == "rewrite_failed"
    assert len(guide["modules"]) == 4
    # The free repairs still stand.
    assert guide["modules"][2]["learning_experiences_used"] == []


def test_what_still_stands_is_reported_rather_than_hidden():
    _, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS)

    assert not report.clean
    assert report.outstanding


# ── the narration ───────────────────────────────────────────────────────────


def test_the_run_says_what_it_is_doing_as_it_does_it():
    log = run_log.start()
    try:
        notes_remediation.run(_guide(), design_experiences=DESIGN, slos=SLOS)
    finally:
        run_log.stop()

    names = [s.step for s in log.steps]
    assert "Self-check" in names
    assert any(n.startswith("Repair") for n in names)
    assert "Self-check complete" in names


def test_narration_outside_a_run_is_harmless():
    """A station has to be able to narrate itself unconditionally, or every
    call site grows a check that the one that matters will be missing."""
    run_log.stop()
    run_log.step("no listener", "should not raise")


def test_the_station_narrates_its_own_steps():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert '"Drafted",' in source
    assert '"Checking for invention"' in source
    assert "notes_remediation.run(" in source


# ── a finding nothing could act on ──────────────────────────────────────────


def test_an_unused_experience_nominates_a_lesson_to_take_it_up():
    """The loop reported "the design suggests 'listen to a recorded clip of a
    short prayer' and no lesson uses it", found no pair to rewrite, and
    stopped. A finding that can never be acted on is the failure this whole
    module exists to end."""
    guide = _guide()
    guide["modules"][1]["learning_experiences_used"] = [DESIGN[5]]

    _, _, targets = notes_remediation._inspect(guide, DESIGN)

    assert targets, "nothing was nominated to teach the unused experience"


def test_the_lesson_that_already_talks_about_it_is_the_one_chosen():
    """'listen to a recorded clip of a short prayer' belongs in the prayer
    lesson, not in whichever happens to be shortest."""
    guide = _guide()
    home = notes_remediation._best_home(guide["modules"], DESIGN[4])

    assert home == 2, "the prayer lesson should take up the prayer experience"


def test_with_no_obvious_home_the_shortest_lesson_gets_the_work():
    """It has the most room and the least to lose."""
    modules = [
        {**FULL, "module_number": 1, "title": "Lesson 1",
         "exposition_segments": [{"topic": "t", "body": "x " * 400}]},
        {**FULL, "module_number": 2, "title": "Lesson 2",
         "exposition_segments": [{"topic": "t", "body": "x " * 20}]},
    ]

    assert notes_remediation._best_home(modules, "colour a drawn picture") == 2


def test_the_rewrite_is_told_to_name_the_experience_as_well_as_teach_it():
    """Teaching it without naming it leaves the guide looking ungrounded;
    naming it without teaching it is worse."""
    calls: list = []
    guide = _guide()
    guide["modules"][1]["learning_experiences_used"] = [DESIGN[5]]

    notes_remediation.run(
        guide, design_experiences=DESIGN, slos=SLOS,
        generate=_rewriter(calls), model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert calls
    assert "`learning_experiences_used`" in calls[0]
    assert "worded as the design words it" in calls[0]


def test_a_guide_with_no_slo_map_at_all_gets_one():
    """The model returned none. Nothing said which lesson carried which
    outcome, and the map is derivable from the modules."""
    guide = _guide()
    del guide["slo_map"]

    repaired, report = notes_remediation.run(
        repaired_guide := guide, design_experiences=DESIGN, slos=SLOS)

    assert repaired["slo_map"], "no map was derived"
    assert not any("has no `slo_map`" in f for f in report.outstanding)


# ── the run has to be watchable while it runs ───────────────────────────────


def test_a_run_publishes_its_steps_under_an_id_a_browser_can_poll():
    """A station called from the factory blocks until its guide is finished, so
    the console showed a spinner for two minutes and then a result — with no
    way to tell a slow run from a wedged one."""
    log = run_log.start(run_id="test-run-1")
    try:
        run_log.step("Started", "Our God")
        mid = run_log.read("test-run-1")
    finally:
        run_log.stop()

    if mid.get("error"):
        import pytest
        pytest.skip(f"no Redis in this environment: {mid['error']}")

    assert [s["step"] for s in mid["steps"]] == ["Started"]
    assert mid["finished"] is False
    assert run_log.read("test-run-1")["finished"] is True


def test_an_unknown_run_is_not_an_error():
    """Not started yet, or expired. Reporting an error would make a run that is
    simply slow to start look broken."""
    body = run_log.read("no-such-run")

    assert body["steps"] == []
    assert body["finished"] is False


def test_the_station_accepts_a_run_id_and_publishes_under_it():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert "_run_log.start(run_id=payload.run_id)" in source
    assert hasattr(curriculum, "factory_progress")

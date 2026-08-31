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


def test_an_outcome_no_lesson_claims_is_placed_rather_than_dropped():
    """Dropping it produced a map missing a funded outcome — and when every
    lesson paraphrased, an EMPTY map, which the checker then reported as "the
    guide has no slo_map": a finding the repair had itself caused."""
    guide = _guide()
    for module in guide["modules"]:
        module["slos_covered"] = [QUALITIES]
    notes_remediation.rebuild_slo_map(guide, SLOS)

    assert {r["slo"] for r in guide["slo_map"]} == set(SLOS)


def test_a_paraphrased_outcome_still_matches_its_design_slo():
    """The model writes "Practising short prayers" for "practice saying short
    prayers". Exact matching dropped that lesson out of the map."""
    guide = _guide()
    guide["modules"][1]["slos_covered"] = ["Practising short prayers"]
    notes_remediation.rebuild_slo_map(guide, SLOS)
    row = next(r for r in guide["slo_map"] if r["slo"] == PRAYERS)

    assert row["taught_in"] == [2]


def test_the_checker_and_the_repair_agree_on_what_the_same_outcome_means():
    """Two definitions is how a repair comes to create findings the checker
    then reports."""
    from app.services import notes_integrity

    guide = _guide()
    guide["modules"][1]["slos_covered"] = ["Practising short prayers"]
    notes_remediation.rebuild_slo_map(guide, SLOS)

    assert notes_integrity.check_slo_map(guide) == []


def test_a_placed_outcome_is_written_onto_the_lesson_too():
    """Otherwise the map says lesson 3 carries it and lesson 3 does not."""
    guide = _guide()
    for module in guide["modules"]:
        module["slos_covered"] = [QUALITIES]
    notes_remediation.rebuild_slo_map(guide, SLOS)

    everything = [s for m in guide["modules"] for s in m["slos_covered"]]
    assert PRAYERS in everything and LOVE in everything


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
    # The free repairs survive the stop — they are the whole point of running
    # them before anything is asked of a model.
    assert guide["slo_map"]
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


def test_a_targeted_rewrite_that_does_not_help_escalates_rather_than_stopping():
    """"2 findings still stand" leaves an operator nothing to do but press the
    button again, which costs a whole generation to learn what the pipeline
    already knew. A rewrite that cannot fix a lesson is evidence about the
    rewrite, not about the guide."""
    calls: list = []

    def useless(model_config, messages, **kw):
        calls.append(messages[-1]["content"])
        return type("R", (), {"content": {}})()

    _, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=useless, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert any("WRITE THIS GUIDE AGAIN" in c for c in calls), "never escalated"
    assert report.regenerations >= 1
    assert report.stopped_because == "no_improvement"


def test_the_ladder_is_bounded():
    """"Even if generation is expensive" is not "without limit"."""
    calls: list = []

    def useless(model_config, messages, **kw):
        calls.append(1)
        return type("R", (), {"content": {}})()

    notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=useless, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    assert len(calls) <= notes_remediation.MAX_PASSES


def test_the_best_version_is_kept_not_the_last():
    """A pass that made the guide worse used to be the version that got
    saved."""
    def worse(model_config, messages, **kw):
        return type("R", (), {"content": {"modules": [
            {"module_number": n, "title": f"Lesson {n}: The Same Lesson",
             "slos_covered": [LOVE], "learning_experiences_used": [],
             "exposition_segments": [
                 {"topic": "Understanding God's Love", "minutes": 10,
                  "body": "Identical body. " * 30}]}
            for n in range(1, 5)]}})()

    guide, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=worse, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    titles = [m["title"] for m in guide["modules"]]
    assert "Lesson 1: Introducing God" in titles, "the worse version was kept"
    assert report.score_after >= report.score_before


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


def test_a_short_regeneration_is_refused():
    """The design funds a fixed number of lessons, and losing four of them to
    fix a repeated one is not a repair."""
    guide = _guide()
    landed = notes_remediation._replace(
        guide, {"modules": [{"module_number": 1, "title": "Only one"}]})

    assert landed == []
    assert len(guide["modules"]) == 4


def test_a_full_regeneration_replaces_rather_than_merges():
    """The point of escalating is that the previous PLAN was the defect, so
    merging the old lessons back would carry it forward."""
    guide = _guide()
    fresh = [{"module_number": n, "title": f"Lesson {n}: Fresh",
              "slos_covered": [QUALITIES]} for n in range(1, 5)]
    landed = notes_remediation._replace(guide, {"modules": fresh, "gaps": ["…"]})

    assert landed == [1, 2, 3, 4]
    assert all("Fresh" in m["title"] for m in guide["modules"])
    assert guide["gaps"] == ["…"]


# ── what the run cost, and how many attempts it took ────────────────────────


def test_the_report_says_how_many_attempts_and_of_what_kind():
    calls: list = []

    def useless(model_config, messages, **kw):
        calls.append(1)
        return type("R", (), {"content": {}})()

    _, report = notes_remediation.run(
        _guide(), design_experiences=DESIGN, slos=SLOS,
        generate=useless, model_config=object(), base_messages=[],
        sub_strand="Our God", allocation_phrase="7 lessons")

    body = report.to_dict()
    assert body["passes_run"] >= 2
    assert body["rewrites"] >= 1
    assert body["regenerations"] >= 1
    assert "repair_cost_usd" in body and "repair_calls" in body


def test_each_pass_records_its_own_cost():
    from app.services import run_meter

    class Usage:
        prompt_tokens, completion_tokens, total_tokens = 1000, 500, 1500

    def spending(model_config, messages, **kw):
        run_meter.add(Usage(), "gpt-4o-mini", "openai")
        return type("R", (), {"content": {}})()

    run_meter.start("test-job")
    try:
        _, report = notes_remediation.run(
            _guide(), design_experiences=DESIGN, slos=SLOS,
            generate=spending, model_config=object(), base_messages=[],
            sub_strand="Our God", allocation_phrase="7 lessons")
    finally:
        run_meter.stop()

    model_passes = [p for p in report.passes if p.rung != "repair"]
    assert model_passes and all(p.calls >= 1 for p in model_passes)
    assert report.calls == sum(p.calls for p in report.passes)


# ── the console has to show the work that was filed ─────────────────────────


def _factory() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/ContentFactory.tsx").read_text()


def test_a_finished_job_refreshes_the_version_list():
    """The station files a version every time it generates, and the list was
    fetched before the run — so it held the empty result from before and the
    panel said "nothing filed yet" about work that had just been filed. There
    was then no way to review or approve it without a full reload."""
    source = _factory()
    effect = source[source.index("A finished job's result is read back"):]
    effect = effect[: effect.index("}, [job.data")]

    assert 'invalidateQueries({ queryKey: ["artifacts"] })' in effect
    assert 'invalidateQueries({ queryKey: ["artifact-versions"] })' in effect


def test_the_empty_state_is_not_shown_over_a_list_that_is_refreshing():
    source = _factory()

    assert "artifacts.isFetching && !rows.length" in source


def test_the_run_log_is_shown_as_a_timeline_not_a_numbered_list():
    """Every line opened with an index nobody needs, and the elapsed time — the
    one number that says whether a run is moving — sat behind it."""
    source = _factory()

    assert "function RunTimeline(" in source
    assert "<RunTimeline steps={liveSteps}" in source, "not used while running"
    assert "<RunTimeline steps={steps}" in source, "not used once finished"


# ── citations whose quote is real and whose address has drifted ─────────────

DRIFTED = """[PAGE 203]
203:14  The learner is guided to:
203:15  • say the name of God in their mother tongue or
203:16  language of catchment area,
203:40  • sing songs in groups.
"""


def test_a_drifted_citation_address_is_corrected_not_reported():
    """The reviewer and the generator do not read the same rendering of the
    design, so addresses drift. Every review since has spent a finding saying
    "the quote is real but the address is wrong" — which nothing acted on."""
    notes = {"modules": [{"citations": [{
        "ref": "203:26", "claim": "c",
        "quote": "say the name of God in their mother tongue or language of "
                 "catchment area"}]}]}

    note = notes_remediation.repair_citation_addresses(notes, DRIFTED)

    assert notes["modules"][0]["citations"][0]["ref"] == "203:14"
    assert "203:26 → 203:14" in note


def test_a_corrected_address_then_verifies():
    from app.services import citation_evidence

    notes = {"modules": [{"citations": [{
        "ref": "203:26", "claim": "c",
        "quote": "say the name of God in their mother tongue or language of "
                 "catchment area"}]}]}
    notes_remediation.repair_citation_addresses(notes, DRIFTED)

    assert citation_evidence.resolve(notes, DRIFTED)["citations"][0]["status"] \
        == "VERIFIED"


def test_a_citation_that_already_resolves_is_left_alone():
    notes = {"modules": [{"citations": [{
        "ref": "203:15", "claim": "c",
        "quote": "say the name of God in their mother tongue or language of "
                 "catchment area"}]}]}

    assert notes_remediation.repair_citation_addresses(notes, DRIFTED) == ""
    assert notes["modules"][0]["citations"][0]["ref"] == "203:15"


def test_an_invented_quote_is_not_given_an_address():
    notes = {"modules": [{"citations": [{
        "ref": "203:26", "claim": "c",
        "quote": "the learner shall recite the Nicene Creed from memory"}]}]}

    assert notes_remediation.repair_citation_addresses(notes, DRIFTED) == ""
    assert notes["modules"][0]["citations"][0]["ref"] == "203:26"


def test_with_no_design_no_address_is_touched():
    notes = {"modules": [{"citations": [{"ref": "203:26", "claim": "c",
                                         "quote": "anything at all here"}]}]}

    assert notes_remediation.repair_citation_addresses(notes, "") == ""


def test_the_station_hands_the_repair_the_page_addressed_design():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert "design_text=source_text or \"\"" in source


def test_there_is_somewhere_to_read_the_guide_as_a_document():
    """The console could produce notes, score them, review them and approve
    them, and never once show them as prose — which is how a lesson taught
    three times under three titles survived several reviews."""
    import pathlib

    views = pathlib.Path(__file__).resolve().parents[2] / "frontend-web/src/views"
    reader = (views / "NotesReader.tsx").read_text()
    factory = (views / "ContentFactory.tsx").read_text()

    assert "export function NotesReader" in reader
    assert "<NotesReader notes={notes}" in factory
    # The handover between topics is what makes it a lesson rather than four
    # paragraphs, so it has to be visible.
    assert "segment.bridge" in reader

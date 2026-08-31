"""A diagram may only depict what the lesson actually teaches.

An asset planner given a sub-strand's title and outcomes will happily return a
soil-profile schematic for a lesson that never mentions soil. The diagram is
then drawn, reviewed on its own terms, approved, and printed beside a lesson it
illustrates nothing in — because every check downstream asks whether the
DIAGRAM is good, and none asks whether the lesson contains it.
"""
from __future__ import annotations

from app.services import topic_linkage as tl

PLAN = {
    "modules": [
        {"title": "Lesson 1: Introducing God",
         "slos_covered": ["identify three qualities of God"],
         "learning_intent": "Say the name of God in their mother tongue.",
         "exposition_segments": [
             {"topic": "Saying the Name of God"},
             {"topic": "Using Gestures to Describe God"},
             {"topic": "Singing Songs About God"},
         ]},
        {"title": "Lesson 2: Praying to God",
         "slos_covered": ["practice saying short prayers"],
         "exposition_segments": [{"topic": "Listening to a Recorded Prayer"}]},
    ]
}


def _assets(*rows) -> dict:
    return {"visuals": list(rows)}


# ── what the plan teaches ───────────────────────────────────────────────────


def test_the_plans_own_topics_are_the_vocabulary():
    topics = tl.topics_of(PLAN)

    assert "Saying the Name of God" in topics
    assert "identify three qualities of God" in topics
    assert "Lesson 2: Praying to God" in topics


def test_topics_are_titles_and_segments_not_the_whole_prose():
    """An asset that shares three words with a paragraph is not thereby
    illustrating it, and matching against the whole plan makes everything look
    linked."""
    plan = {"modules": [{"title": "L1", "exposition_segments": [
        {"topic": "Gestures", "body": "A long paragraph about volcanoes and "
                                      "sedimentary rock and titration."}]}]}
    topics = " ".join(tl.topics_of(plan)).lower()

    assert "volcano" not in topics and "titration" not in topics


def test_a_plan_with_no_topics_is_not_checked_rather_than_failing_everything():
    report = tl.check(_assets({"title": "Anything"}), {})

    assert not report.checked
    assert report.clean is False or report.total == 0


# ── what the asset depicts ──────────────────────────────────────────────────


def test_an_asset_about_something_the_lesson_teaches_is_linked():
    report = tl.check(_assets(
        {"asset_id": "vis_01", "title": "Children singing songs about God",
         "micro_concept": "singing in groups"}), PLAN)

    assert report.clean
    assert report.linked[0]["closest_topic"] == "Singing Songs About God"


def test_an_asset_about_something_else_entirely_is_named():
    report = tl.check(_assets(
        {"asset_id": "vis_02", "title": "Soil profile horizon strata O-A-B-C",
         "micro_concept": "soil layers"}), PLAN)

    assert not report.clean
    assert report.unlinked[0]["asset"] == "vis_02"
    assert report.score == 0.0


def test_generic_words_do_not_make_an_asset_look_linked():
    """Matching on "lesson", "children" and "diagram" links everything to
    everything."""
    report = tl.check(_assets(
        {"asset_id": "vis_03",
         "title": "A diagram showing the children in the lesson"}), PLAN)

    assert report.unlinked, "matched on words that carry no subject"


def test_the_score_is_the_proportion_that_illustrate_the_lesson():
    report = tl.check(_assets(
        {"asset_id": "a", "title": "Children singing songs about God"},
        {"asset_id": "b", "title": "Saying the name of God aloud"},
        {"asset_id": "c", "title": "Titration apparatus and burette"},
    ), PLAN)

    assert report.score == round(2 / 3 * 100, 1)


def test_assets_are_found_whatever_the_station_called_the_list():
    for key in ("visuals", "assets", "diagrams", "media", "simulations"):
        report = tl.check({key: [{"title": "Singing songs about God"}]}, PLAN)
        assert report.total == 1, key


def test_a_bare_list_of_assets_is_read_too():
    assert tl.check([{"title": "Singing songs about God"}], PLAN).total == 1


def test_what_the_plan_teaches_and_nothing_illustrates_is_reported_separately():
    """Not a defect on its own — not everything needs a picture."""
    report = tl.check(_assets({"title": "Singing songs about God"}), PLAN)

    assert "Listening to a Recorded Prayer" in report.uncovered


# ── what the reviewer is told ───────────────────────────────────────────────


def _rendered() -> str:
    return tl.render(tl.check(_assets(
        {"asset_id": "vis_02", "title": "Soil profile horizon strata"}), PLAN))


def test_the_block_names_the_asset_and_what_the_plan_actually_says():
    rendered = _rendered()

    assert "NOT IN THE PLAN" in rendered
    assert "vis_02" in rendered
    assert "Saying the Name of God" in rendered


def test_a_visual_metaphor_is_explicitly_not_the_defect():
    """A picture of a mother giving food illustrates "God provides" and shares
    no words with it. Flagging that would push the pipeline towards literal
    illustration, which is worse teaching."""
    rendered = _rendered()

    assert "A visual METAPHOR" in rendered
    assert "Say so and move on" in rendered


def test_the_block_says_what_the_real_defect_costs():
    assert "printed beside a lesson it illustrates nothing in" in _rendered()


def test_a_clean_set_of_assets_produces_no_block():
    report = tl.check(_assets({"title": "Singing songs about God"}), PLAN)

    assert tl.render(report) == ""


# ── wiring ──────────────────────────────────────────────────────────────────


def test_only_the_kinds_drawn_from_the_plan_are_checked():
    from app.services import review_layers

    assert "diagram" in review_layers.DRAWN_FROM_PLAN
    assert "simulation" in review_layers.DRAWN_FROM_PLAN
    assert "notes" not in review_layers.DRAWN_FROM_PLAN


def test_the_reviewer_receives_the_linkage():
    from app.services import review_layers

    artifact = type("A", (), {
        "kind": "diagram", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "Creation", "sub_strand_name": "Our God", "version": 1,
        "content": _assets({"asset_id": "vis_02",
                            "title": "Soil profile horizon strata"}),
    })()
    user = review_layers.build_messages(artifact, 2, plan_content=PLAN)[1]["content"]

    assert "=== WHAT THE LESSON PLAN ACTUALLY TEACHES ===" in user
    assert "vis_02" in user


def test_the_plan_is_not_checked_against_itself():
    from app.services import review_layers

    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "", "sub_strand_name": "Our God", "version": 1,
        "content": PLAN,
    })()
    user = review_layers.build_messages(artifact, 2, plan_content=PLAN)[1]["content"]

    assert "WHAT THE LESSON PLAN ACTUALLY TEACHES" not in user


def test_the_review_route_loads_the_plan_behind_an_asset():
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.review_artifact)
    assert "review_layers.DRAWN_FROM_PLAN" in source
    assert "plan_content=plan_content" in source

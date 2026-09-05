"""The diagram station reporting a score, so the review loop can read one.

    1 review cycle — best 0/100, not passed
    Stopped because the gate failed but named nothing to fix.

It returned its visuals and no `quality_gate`. The loop reads `quality_gate`,
found none, scored the run 0 and had nothing to name — so a run that planned
three perfectly good diagrams looked identical to one that produced nothing.
The material station had the same hole.
"""
from __future__ import annotations

import inspect

import pytest

from app.services.diagram_gate import check, gate_of

COMPLETE = {"visuals": [{
    "diagram_title": "Number line from -10 to 10",
    "vivid_prompt": "A horizontal number line marked at every integer from -10 "
                    "to 10, with arrows at both ends.",
    "accessibility": {"alt_text": "A number line from minus ten to ten, marked "
                                  "at every integer."},
    "scene": {"parts": [{"label": "Number Line",
                         "function": "represents the set of integers from -10 to 10",
                         "assessable": True, "occludable": False}]},
}]}


def test_a_complete_plan_passes() -> None:
    gate = gate_of(check(COMPLETE))

    assert gate["passed"]
    assert gate["overall_score"] == 100
    assert all(f["status"] == "pass" for f in gate["reviewer"]["feedback"])


def test_a_thin_plan_fails_and_says_why() -> None:
    gate = gate_of(check({"visuals": [{"diagram_title": "Number line"}]}))

    assert not gate["passed"]
    failed = {f["aspect"] for f in gate["reviewer"]["feedback"] if f["status"] == "fail"}
    assert failed == {"drawable", "accessible", "addressable"}
    assert gate["next_actions"], "a failing gate must name something to fix"


def test_nothing_planned_is_named_rather_than_silent() -> None:
    """This is the case that produced "the gate failed but named nothing"."""
    gate = gate_of(check({"visuals": []}))

    assert gate["overall_score"] == 0
    assert not gate["passed"]
    assert gate["next_actions"], "0/100 with no action is the bug"
    assert "No visual was planned" in gate["next_actions"][0]


def test_a_diagram_with_no_addressable_parts_is_caught() -> None:
    """This station exists to make diagrams a question can point into. A scene
    with no parts is a picture the question station cannot use."""
    thin = {"visuals": [{**COMPLETE["visuals"][0], "scene": {"parts": []}}]}
    report = check(thin)

    assert report.unaddressable
    assert "no question can point into them" in " ".join(
        f["comment"] for f in gate_of(report)["reviewer"]["feedback"])


def test_a_label_with_no_function_is_caught() -> None:
    """A label with no meaning cannot be asked about."""
    nameless = {"visuals": [{**COMPLETE["visuals"][0],
                             "scene": {"parts": [{"label": "A", "function": ""}]}}]}

    assert check(nameless).unexplained


def test_alt_text_is_required() -> None:
    """Without it a learner using a screen reader gets an unlabelled box."""
    blind = {"visuals": [{**COMPLETE["visuals"][0], "accessibility": {}}]}

    assert check(blind).inaccessible


def test_one_fault_does_not_lose_the_whole_visual() -> None:
    """Five checks per visual, so a plan that is right about most things scores
    as a plan that is right about most things."""
    missing_alt = {"visuals": [{**COMPLETE["visuals"][0], "accessibility": {}}]}
    gate = gate_of(check(missing_alt))

    assert 70 <= gate["overall_score"] < 100, gate["overall_score"]


def test_both_keys_are_read() -> None:
    """The planner files `visuals`; a single render files `diagrams`."""
    as_diagrams = {"diagrams": COMPLETE["visuals"]}
    assert check(as_diagrams).total == 1


def test_the_station_reports_it() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_plan_visuals)
    assert "diagram_gate.gate_of" in source
    assert '"quality_gate": gate' in source
    assert "measured_from=" in source, "so a regeneration can act on it"


# ── material can now be acted on ────────────────────────────────────────────

def test_material_can_be_regenerated_from_its_review() -> None:
    """It was reviewable and not regenerable, so a review of it had nowhere to
    go: eight pieces handed the instruction back, the gate said so, and
    "Review and refine" refused the kind."""
    from app.routes.artifacts import _REGENERATORS

    assert "material" in _REGENERATORS
    assert _REGENERATORS["material"]["endpoint"] == "factory_generate_material"


def test_material_is_judged_against_the_plan_it_fulfils() -> None:
    """One piece per instruction, written to fulfil it. Without the plan the
    reviewer judged the words with no sight of what they were asked to be."""
    from app.services.review_layers import DRAWN_FROM_PLAN

    assert "material" in DRAWN_FROM_PLAN


def test_it_is_judged_against_the_plan_it_was_written_from() -> None:
    """Not the newest one for the sub-strand: judging version 2 of the words
    against version 3 of the plan reports them for missing instructions they
    were never given."""
    from app.routes import artifacts

    source = inspect.getsource(artifacts.review_artifact)
    assert "parent_artifact_id" in source
    assert "from_plan" in source


def test_the_material_gate_findings_reach_a_regeneration() -> None:
    """The chain that has to work for "Review and refine" to fix a 50/100."""
    from app.services import measured_findings
    from app.services.lesson_material import MaterialReport, gate_of as material_gate
    from app.services.revision_directives import build

    report = MaterialReport(total=18, written=18)
    report.echoed = [{"lesson": 1, "topic": "Part", "overlap": 82}] * 8
    report.unexercised = [{"lesson": n, "numbered_questions": 0} for n in range(1, 7)]

    found = measured_findings.collect({"quality_gate": material_gate(report)})
    directives = build([], [], measured=found)["directives"]

    assert found, "the gate's findings are filed with the version"
    assert "handed the instruction back" in directives
    assert "nothing to work" in directives


# ── a title that names the kind of picture rather than its subject ───────────


def test_a_visual_titled_charts_is_not_a_planned_visual() -> None:
    """The book prints the title verbatim as the figure's caption, and it is
    all the drawing step is handed. A plan whose visual was called "charts"
    put the word "charts" under the figure and produced four identical
    circles captioned as four different operations."""
    from app.services import diagram_gate

    report = diagram_gate.check({"visuals": [{
        "diagram_title": "charts",
        "vivid_prompt": "x" * 60,
        "accessibility": {"alt_text": "something long enough to pass"},
        "scene": {"parts": [{"label": "A", "function": "does a thing"}]},
    }]})

    assert [w["title"] for w in report.uncaptioned] == ["charts"]
    assert not report.clean
    gate = diagram_gate.gate_of(report)
    assert any("names a KIND of picture" in a for a in gate["next_actions"])
    assert any("Adding integers on a number line" in a for a in gate["next_actions"])


def test_a_title_that_names_its_subject_passes() -> None:
    """Narrow on purpose. "Bar chart of Grade 9 attendance" contains a category
    word and is a perfectly good caption; a check that rejected it would be
    turned off within a week."""
    from app.services import diagram_gate

    for title in ("Digestive system", "Bar chart of Grade 9 attendance",
                  "The water cycle", "Number line from -5 to 5"):
        report = diagram_gate.check({"visuals": [{
            "diagram_title": title,
            "vivid_prompt": "x" * 60,
            "accessibility": {"alt_text": "something long enough to pass"},
            "scene": {"parts": [{"label": "A", "function": "does a thing"}]},
        }]})
        assert report.uncaptioned == [], title
        assert report.clean, title

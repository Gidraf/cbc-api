"""Did what came back have the same shape as what went out?

Copying an artifact out, improving it in another model and pasting it back is
often the fastest way to a good artifact. What makes it dangerous is silent
drift: a model asked to improve a guide returns the RIGHT guide, with
`exposition_segments` renamed to `segments`, `citations` dropped from three
modules and `duration_minutes` turned into "30 minutes".

Each reads as fine to a person scanning the prose. Each breaks something
downstream — because everything downstream reads with `.get()` and a default,
and a missing key is indistinguishable from an empty one by the time it is read.
"""
from __future__ import annotations

import pathlib

from app.services import content_shape as cs

GUIDE = {
    "title": "Teacher's Guide: Our God",
    "module_count": 7,
    "gaps": ["No recorded prayer clip was supplied."],
    "modules": [
        {"title": "Lesson 1", "duration_minutes": 30,
         "citations": [{"ref": "203:26", "quote": "…"}],
         "exposition_segments": [{"topic": "A", "body": "x", "minutes": 10}]},
        {"title": "Lesson 2", "duration_minutes": 30,
         "citations": [{"ref": "203:33", "quote": "…"}],
         "exposition_segments": [{"topic": "B", "body": "y", "minutes": 10}]},
    ],
}


def _paste(**changes) -> dict:
    import copy

    out = copy.deepcopy(GUIDE)
    out.update(changes)
    return out


# ── the drifts that break something ─────────────────────────────────────────


def test_an_identical_paste_is_clean():
    report = cs.compare(GUIDE, _paste())

    assert report.clean and report.safe
    assert cs.summarise(report) == "Same shape as the version it came from."


def test_a_renamed_key_is_caught_as_a_loss_and_an_addition():
    """The commonest drift, and the one that reads as fine: the guide is right,
    and coverage counts no modules."""
    pasted = _paste()
    for module in pasted["modules"]:
        module["segments"] = module.pop("exposition_segments")
    report = cs.compare(GUIDE, pasted)

    assert not report.safe
    assert any("exposition_segments" in f.path for f in report.missing)
    assert any("segments" in f.path for f in report.added)


def test_a_dropped_key_is_named_with_what_it_was():
    pasted = _paste()
    for module in pasted["modules"]:
        module.pop("citations")
    report = cs.compare(GUIDE, pasted)

    finding = next(f for f in report.missing if "citations" in f.path)
    assert finding.was == "list"


def test_a_number_turned_into_text_is_caught():
    """"30 minutes" renders as a blank duration and sorts wrongly, and nothing
    downstream complains."""
    pasted = _paste()
    pasted["modules"][0]["duration_minutes"] = "30 minutes"
    report = cs.compare(GUIDE, pasted)

    finding = report.type_changed[0]
    assert finding.was == "number" and finding.now == "text"


def test_a_list_that_was_full_and_is_now_empty_is_its_own_kind_of_loss():
    report = cs.compare(GUIDE, _paste(gaps=[]))

    assert report.emptied
    assert "had 1 entr" in report.emptied[0].detail


def test_text_blanked_out_is_caught():
    pasted = _paste()
    pasted["modules"][0]["title"] = "   "
    report = cs.compare(GUIDE, pasted)

    assert any(f.path.endswith("title") for f in report.emptied)


def test_a_field_set_to_null_is_reported_as_emptied_not_retyped():
    pasted = _paste()
    pasted["modules"][0]["citations"] = None
    report = cs.compare(GUIDE, pasted)

    assert report.emptied and not report.type_changed


# ── the ones that are the operator's business ───────────────────────────────


def test_an_added_field_is_reported_but_breaks_nothing():
    """Adding a field on purpose is reasonable, and a tool that refuses it
    teaches people to stop using the tool."""
    report = cs.compare(GUIDE, _paste(teacher_note="Read this first."))

    assert report.added
    assert report.safe, "an addition is not a break"
    assert not report.clean


def test_a_null_in_the_original_constrains_nothing():
    """It tells us nothing about what the field should be."""
    report = cs.compare({"maybe": None}, {"maybe": "now a string"})

    assert report.clean


# ── the report has to be readable ───────────────────────────────────────────


def test_one_finding_per_path_however_long_the_list():
    """Seven identically-shaped modules do not need seven identical reports."""
    pasted = _paste()
    for module in pasted["modules"]:
        module.pop("citations")
    report = cs.compare(GUIDE, pasted)

    assert len([f for f in report.missing if "citations" in f.path]) == 1


def test_the_summary_says_how_many_of_each():
    pasted = _paste(gaps=[], extra="x")
    pasted["modules"][0].pop("citations")
    summary = cs.summarise(cs.compare(GUIDE, pasted))

    assert "missing" in summary and "emptied" in summary and "added" in summary


def test_deep_nesting_stops_rather_than_reporting_paths_nobody_can_act_on():
    deep = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": 1}}}}}}}}
    shallow = {"a": {"b": {"c": {"d": {"e": {"f": {"g": {}}}}}}}}

    cs.compare(deep, shallow)  # must not raise


def test_it_renders_for_a_log_as_well_as_a_screen():
    pasted = _paste()
    pasted["modules"][0].pop("citations")
    rendered = cs.render(cs.compare(GUIDE, pasted))

    assert "MISSING" in rendered and "citations" in rendered


# ── wiring ──────────────────────────────────────────────────────────────────


def test_the_paste_can_be_checked_before_it_is_filed():
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.check_edit_shape)
    assert "content_shape.compare" in source


def test_a_drifted_edit_is_recorded_on_the_version_it_became():
    """Reported, not refused — but a version that quietly lost `citations`
    should say so on its own record, where the next person to open it sees it."""
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.edit_artifact)
    assert "if not shape.clean:" in source
    assert "registry.add_comment(" in source


def _panel() -> str:
    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/VersionReview.tsx").read_text()


def test_the_editor_offers_the_check_before_the_save():
    panel = _panel()

    assert "Check the shape" in panel
    assert "function ShapeNotice(" in panel


def test_saving_over_a_drift_says_that_is_what_it_is_doing():
    """The button changes its own words rather than silently doing the same
    thing."""
    assert "Save anyway as the next version" in _panel()


def test_a_stale_report_is_dropped_when_the_text_changes():
    """A report about text that has since changed is worse than none."""
    assert "if (shape) setShape(null);" in _panel()


def test_the_editor_says_to_keep_the_keys():
    assert "keep the keys as they are" in _panel()

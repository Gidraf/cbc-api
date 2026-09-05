"""Regenerating from what a review found — which did not work.

Three separate faults, each enough on its own to make the button do nothing:

*   The route for reading the findings was bound to a Pydantic CLASS, because
    a decorator had drifted onto the model declared under it. The real handler
    was never registered, and the accidental route had no auth on it.
*   The findings an operator was looking at — "contradicts itself", "learner
    language fit at 0.31" — lived only in the generation's HTTP response and
    were never filed with the version.
*   So regeneration, which reads reviews and comments, correctly reported that
    nothing was wrong.
"""
from __future__ import annotations

import re

from app.services.measured_findings import collect, provenance_for, stored


# ── the routes are bound to the right things ────────────────────────────────

def test_the_findings_route_is_bound_to_its_handler_and_not_to_a_model() -> None:
    from app.routes.artifacts import router

    routes = {(tuple(sorted(r.methods)), r.path): r for r in router.routes}
    key = (("GET",), "/api/v1/artifacts/{artifact_id}/revision-directives")

    assert key in routes, "the findings route must exist"
    endpoint = routes[key].endpoint
    assert endpoint.__name__ == "read_revision_directives"
    assert not isinstance(endpoint, type), "a Pydantic model is not an endpoint"


def test_every_artifact_route_requires_authentication() -> None:
    """The misbound route had no dependency on it at all — the handler's
    `require_roles` went with the handler."""
    from app.routes.artifacts import router

    for route in router.routes:
        if not getattr(route, "dependant", None):
            continue
        assert route.dependant.dependencies, f"{route.path} has no auth"


# ── what a machine found is filed with the version ──────────────────────────

GENERATION = {
    "quality_gate": {
        "passed": True, "overall_score": 90,
        "reviewer": {"feedback": [
            {"aspect": "learner_language_fit", "status": "fail",
             "comment": "Language sits above this grade band."},
            {"aspect": "grounding", "status": "pass", "comment": "fine"},
        ]},
        "next_actions": ["Teach the IT-tools outcome or name it in `gaps`."],
    },
    "integrity": {"checked": True, "clean": False, "findings": [
        'The design suggests "use IT tools ... to carry out operations on '
        'integers" and no lesson uses it.']},
    "repetition": {"checked": True, "clean": True, "findings": []},
    "lesson_coverage": {"complete": False, "modules_required": 6,
                        "modules_found": 5, "thin_modules": [{"title": "Lesson 5"}]},
}


def test_a_gate_that_passed_still_yields_its_failing_criteria() -> None:
    """The case that prompted this: 90/100, gate passed, one measure at 0.31,
    and a contradiction printed on screen — none of it actionable."""
    found = collect(GENERATION)
    blob = " ".join(found).lower()

    assert any("learner language fit" in f.lower() for f in found)
    assert "contradicts itself" in blob
    assert "it tools" in blob
    assert "6 lesson" in blob and "5" in blob
    assert "too thin" in blob


def test_a_clean_generation_yields_nothing() -> None:
    assert collect({"quality_gate": {"passed": True, "reviewer": {"feedback": [
        {"aspect": "grounding", "status": "pass", "comment": "fine"}]}},
        "integrity": {"checked": True, "clean": True, "findings": []},
        "repetition": {"checked": True, "clean": True, "findings": []}}) == []
    assert collect({}) == []
    assert collect(None) == []


def test_the_findings_ride_along_in_provenance() -> None:
    provenance = provenance_for(GENERATION, {"source": "factory_generate_notes"})

    assert provenance["source"] == "factory_generate_notes", "the base survives"
    assert provenance["gate_score"] == 90
    assert provenance["gate_passed"] is True
    assert len(provenance["measured"]) >= 4


def test_they_are_read_back_off_the_artifact() -> None:
    class Artifact:
        provenance = provenance_for(GENERATION)

    assert len(stored(Artifact())) >= 4

    class Bare:
        provenance = {}

    assert stored(Bare()) == []
    assert stored(object()) == []


def test_the_notes_station_files_what_it_measured() -> None:
    """Without this the whole chain is decorative: the checks run, the console
    draws them, and the artifact carries none of it."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert "measured_from=" in source
    assert "integrity" in source and "quality_gate" in source


def test_regeneration_reads_them_alongside_the_reviewers() -> None:
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts._measured_defects)
    assert "measured_findings.stored" in source
    assert "redundancy_check" in source, "and still compares the lessons"


def test_an_unreviewed_version_with_measured_defects_can_be_regenerated() -> None:
    """The guard demanded a review. The station's own checks are findings too,
    and they are what the operator is looking at when they press the button."""
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.regenerate_artifact)
    assert "if not reviews and not measured:" in source


# ── preview before saving ───────────────────────────────────────────────────

def test_regeneration_can_be_previewed_without_filing_a_version() -> None:
    import inspect

    from app.routes import artifacts

    assert "preview" in artifacts.RegenerateRequest.model_fields
    assert artifacts.RegenerateRequest.model_fields["preview"].default is False

    source = inspect.getsource(artifacts.regenerate_artifact)
    assert "if payload.preview:" in source
    assert "delete_version" in source, "a preview must not leave a version behind"
    assert "kept_because" in source, "and must say so if it could not withdraw it"


def test_the_preview_returns_the_content_the_station_produced() -> None:
    from app.routes.artifacts import _regenerated_content

    assert _regenerated_content({"notes": {"a": 1}}, "notes") == {"a": 1}
    assert _regenerated_content({"material": {"b": 2}}, "material") == {"b": 2}
    assert _regenerated_content({"strands": [1]}, "strand") == [1]
    # Unknown shapes come back whole rather than empty.
    assert _regenerated_content({"other": 1}, "notes") == {"other": 1}


# ── rendering a document, whichever kind it is ──────────────────────────────

class _Artifact:
    """The bits of an artifact the document routes actually read."""

    def __init__(self, kind: str, content: dict) -> None:
        self.kind = kind
        self.content = content
        self.grade = "grade-9"
        self.subject = "Mathematics"
        self.strand_name = "Numbers"
        self.sub_strand_name = "Integers"
        self.version = 1
        self.artifact_id = f"art_{kind}_test"
        self.provenance = {}


def test_both_kinds_render_without_a_type_error(monkeypatch) -> None:
    """Every material page 500'd with

        render_material_html() got an unexpected keyword argument 'assets'

    because the routes chose a renderer and then passed one renderer's
    arguments to both. The choice is made in one place now.
    """
    from app.routes import curriculum
    from app.services import lesson_assets

    monkeypatch.setattr(lesson_assets, "for_notes", lambda *a, **k: {})

    material = _Artifact("material", {"material": [
        {"module_number": 1, "module_title": "Lesson 1", "topic": "Integers",
         "say": "An integer is a whole number."}]})
    notes = _Artifact("notes", {"modules": [
        {"title": "Lesson 1", "teacher_exposition": "An integer is a whole number."}]})

    for artifact in (material, notes):
        html = curriculum._render_document(artifact)
        assert html.startswith("<!doctype html>"), artifact.kind
        assert "integer" in html.lower(), artifact.kind


def test_a_lesson_plan_is_given_the_pictures_and_the_material_is_not() -> None:
    """Not a style choice: the plan keeps space for figures, the material is
    the words said aloud. Passing material an asset map is a parameter it
    ignores — and passing it as a keyword is what broke the page."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum._render_document)
    material_branch = source.split('if artifact.kind == "material":')[1].split("return")[1]
    assert "assets" not in material_branch.split("\n")[0]
    assert "assets=" in source, "the plan still gets them"


def test_material_typesets_its_mathematics() -> None:
    """The words a teacher reads aloud carry LaTeX in a mathematics lesson, and
    escaping it printed the dollars and backslashes on the page."""
    from app.services.notes_renderer import render_material_html

    html = render_material_html(
        {"material": [{"module_number": 1, "module_title": "Lesson 1",
                       "topic": "Integers",
                       "say": r"We get $3 \times (-4) = -12$.",
                       "learner_does": r"Work out $5 \times (-2)$."}]},
        grade="grade-9", subject="Mathematics", sub_strand="Integers",
    )

    assert "$" not in html, "no raw delimiters reach the page"
    assert html.count("class='math'") >= 2
    assert "katex.min.js" in html

    # The LaTeX itself stays — inside the span KaTeX typesets, never loose in
    # the prose around it.
    spans = re.findall(r"<span class='math'[^>]*>(.*?)</span>", html)
    assert any(r"\times" in span for span in spans), spans
    outside = re.sub(r"<span class='math'[^>]*>.*?</span>", "", html)
    assert r"\times" not in outside, "no command escaped its span"

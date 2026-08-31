"""A guide that only exists on a screen is not much use to a teacher whose
classroom has no screen in it.

The console's Print button hands the job to whatever browser the operator
happens to have, so no two copies match and none can be sent to somebody who is
not sitting at the console.
"""
from __future__ import annotations

import pathlib

from app.services import notes_renderer

GUIDE = {
    "title": "Teacher's Guide: Our God",
    "intro": "This sub-strand teaches pre-primary learners about God.",
    "allocated_time": "7 lessons",
    "gaps": ["No recorded prayer clip was supplied with the design."],
    "modules": [
        {
            "title": "Lesson 1: Introducing God",
            "duration_minutes": 30,
            "slos_covered": ["identify three qualities of God"],
            "learning_intent": "Say the name of God in their mother tongue.",
            "exposition_segments": [
                {"topic": "Saying the Name of God", "minutes": 10,
                 "body": "Begin by asking the learners to say the name of God.",
                 "bridge": "Now that we have said it, let us describe Him."},
            ],
            "key_questions": ["How do you say God's name at home?"],
            "resources_needed": ["a simple song about God"],
            "common_misconceptions": [
                {"misconception": "God can be seen like a person.",
                 "why_it_happens": "Children relate to what they can see.",
                 "how_to_correct_it": "Use gestures to show greatness."},
            ],
            "differentiation": {"struggling": "Model it.", "confident": "Lead the song.",
                                "sne": "Use picture cards."},
            "formative_check": "Observe if they can say the name.",
            "homework_or_follow_up": "",
        },
        {"title": "Lesson 2: Describing God", "duration_minutes": 30,
         "exposition_segments": [{"topic": "Gestures", "minutes": 10,
                                  "body": "Introduce the Swahili phrase."}]},
    ],
}


def _html(**kw) -> str:
    return notes_renderer.render_html(GUIDE, grade="grade-pp1", subject="CRE",
                                      sub_strand="Our God", version=3, **kw)


# ── the document ────────────────────────────────────────────────────────────


def test_it_is_a_complete_document_not_a_fragment():
    html = _html()

    assert html.startswith("<!doctype html>")
    assert "@page { size: A4" in html
    assert html.rstrip().endswith("</html>")


def test_each_lesson_starts_on_its_own_page():
    """A teacher carries the page for the lesson they are about to teach, not a
    stapled block they have to hunt through."""
    assert ".lesson { page-break-before: always;" in _html()
    assert ".lesson:first-of-type { page-break-before: avoid; }" in _html()


def test_a_topic_is_never_split_across_a_page_break():
    assert ".seg { margin-bottom: 14px; page-break-inside: avoid; }" in _html()


def test_the_teachers_own_words_and_the_handover_both_survive():
    html = _html()

    assert "Begin by asking the learners to say the name of God." in html
    assert "Now that we have said it, let us describe Him." in html


def test_what_the_design_did_not_supply_is_on_the_first_page():
    """It is what the teacher has to supply themselves."""
    html = _html()
    gaps = html.index("What the design did not supply")

    assert gaps < html.index("class='lesson'")


def test_every_part_of_a_lesson_reaches_the_page():
    html = _html()

    for expected in ("Ask, in this order", "Have ready", "What goes wrong",
                     "If a learner is stuck", "How you know it worked"):
        assert expected in html, expected


def test_an_empty_field_does_not_leave_an_empty_heading():
    """`homework_or_follow_up` is "" here, and a bare "After the lesson" with
    nothing under it reads as a lost field."""
    assert "After the lesson" not in _html()


def test_content_is_escaped():
    html = notes_renderer.render_html(
        {"title": "<script>alert(1)</script>", "modules": []})

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_a_guide_with_no_lessons_says_so_rather_than_rendering_blank():
    assert "This guide holds no lessons." in notes_renderer.render_html({})


def test_the_page_carries_the_scope_it_was_written_for():
    html = _html()

    for part in ("grade-pp1", "CRE", "Our God", "7 lessons", "version 3"):
        assert part in html, part


# ── the route ───────────────────────────────────────────────────────────────


def test_only_a_plan_or_its_material_renders_to_pdf():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_notes_pdf)
    assert 'artifact.kind not in ("notes", "material")' in source
    assert "does not render to PDF" in source


def test_the_download_is_named_for_what_it_holds():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_notes_pdf)
    assert "attachment; filename=" in source
    assert "{stem}-v{artifact.version}.pdf" in source


def test_a_browser_that_cannot_render_says_what_to_do_instead():
    """Losing the file is survivable; losing the reason is not."""
    from app.services import pdf

    source = pathlib.Path(pdf.__file__).read_text()

    assert "class PdfUnavailable" in source
    assert "playwright` container is running" in source
    assert "saved as PDF from the print" in source


def test_the_document_owns_its_own_page_size():
    """Overriding the margins in the PDF call would fight the @page rule."""
    from app.services import pdf

    assert "prefer_css_page_size=True" in pathlib.Path(pdf.__file__).read_text()


def test_the_console_fetches_it_with_the_auth_header():
    """A plain <a href> carries no token and would download the sign-in page."""
    queries = (pathlib.Path(__file__).resolve().parents[2]
               / "frontend-web/src/lib/queries.ts").read_text()

    assert "export function useNotesPdf()" in queries
    assert "bearerToken: token" in queries


def test_the_button_is_offered_only_where_there_is_a_filed_version():
    reader = (pathlib.Path(__file__).resolve().parents[2]
              / "frontend-web/src/views/NotesReader.tsx").read_text()

    assert "artifactId && (" in reader
    assert "Download PDF" in reader


# ── the material: the words themselves ──────────────────────────────────────

MATERIAL = {
    "sub_strand": "Our God",
    "from_plan": {"artifact_id": "art_notes_x", "version": 1},
    "material": [
        {"module_number": 1, "module_title": "Lesson 1: Introducing God",
         "index": 1, "topic": "Singing Songs About God", "minutes": 10,
         "form": "song",
         "instruction": "Choose a simple song about God and teach the lyrics.",
         "title": "He's Got the Whole World in His Hands",
         "say": "He's got the whole world in His hands,\nHe's got the whole "
                "world in His hands.",
         "learner_does": "Sing and sway.",
         "attribution": "Traditional; widely known in Kenyan schools.",
         "notes_for_the_teacher": "Pause after each line."},
        {"module_number": 1, "module_title": "Lesson 1: Introducing God",
         "index": 2, "topic": "Saying the Name of God", "minutes": 10,
         "instruction": "Ask what God is called at home.", "say": ""},
    ],
}


def _material_html() -> str:
    return notes_renderer.render_material_html(
        MATERIAL, grade="grade-pp1", subject="CRE", sub_strand="Our God",
        version=2)


def test_the_words_are_what_the_page_is_for():
    """This is read DURING a lesson, off a page held in one hand. The spoken
    words are set large; the instruction that produced them is small and grey,
    there for reference and never competing with them."""
    html = _material_html()

    # Apostrophes are escaped, as everything on the page is.
    assert "whole world in His hands" in html
    assert ".say { font-size: 12.5pt" in html
    assert ".directive { font-size: 8.5pt; color: #777" in html


def test_a_verse_keeps_its_line_breaks():
    """A verse is a verse. Collapsing it into a paragraph makes it unsingable."""
    html = _material_html()

    assert html.count("<p>He&#x27;s got the whole world in His hands,</p>") == 1


def test_an_instruction_nobody_fulfilled_is_marked_rather_than_left_blank():
    """A silent gap reads as "nothing needed here", which is the opposite of
    the truth."""
    html = _material_html()

    assert "No words were written for this part" in html
    assert "The teacher must supply them." in html


def test_where_the_words_came_from_is_on_the_page():
    """A teacher introducing a song should know whether it is one the children
    may already know."""
    assert "Where these words come from" in _material_html()
    assert "Traditional; widely known" in _material_html()


def test_a_piece_is_never_split_across_a_page_break():
    assert ".piece { margin-bottom: 18px; page-break-inside: avoid; }" in _material_html()


def test_the_material_pdf_is_named_apart_from_the_plans():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_notes_pdf)
    assert '"material" if artifact.kind == "material" else "plan"' in source

"""The guide printed a KICD footer and not one reference to the design.

`_citation` existed and was wired into the MATERIAL page only. The teacher's
guide — the document that gets printed and taught from — closed with
"Generated from the KICD curriculum design. Check it before you teach from it."
and carried no citation anywhere in six lessons.

Separately, `check_provenance` returned an empty list both when every piece
cited the design and when this system had never read the design at all, so the
gate scored a guide with no provenance 1.0 and called it "every piece names the
design element it serves".
"""
from __future__ import annotations

import re

from app.services import lesson_material
from app.services.notes_renderer import _provenance, render_html

_ROW = {
    "slos": ["perform basic operations on Integers in different situations",
             "work out combined operations of integers in the correct order",
             "apply Integers to real-life situations"],
    "key_inquiry_questions": ["How do we use integers in daily life?"],
    "learning_experiences": ["Learners work out combined operations using cards"],
    "core_competencies": ["Critical thinking"],
    "values": [], "required_diagrams": [], "experiments": [],
}


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_a_ref_prints_as_the_design_s_own_words() -> None:
    """`outcome 2` is an address. The sentence is what can be looked up."""
    html = _provenance({"serves": ["outcome 2"]}, grade_label="grade-9",
                       subject="Mathematics", sub_strand="Integers",
                       design_row=_ROW)

    assert "work out combined operations of integers in the correct order" in html
    assert "outcome 2" in html


def test_the_page_and_line_are_printed_where_given() -> None:
    html = _provenance({"serves": ["outcome 1"],
                        "citation": {"ref": "47:12",
                                     "quote": "combined operations in order"}},
                       design_row=_ROW)

    assert "page 47" in html and "line 12" in html
    assert "combined operations in order" in html


def test_an_invented_ref_is_not_printed_as_provenance() -> None:
    """An invented reference survives inspection precisely because it looks real."""
    html = _provenance({"serves": ["outcome 9", "g9-mat-77"]}, design_row=_ROW)

    assert "outcome 9" not in html
    assert "g9-mat-77" not in html
    assert "names no design element" in _text(html)


def test_a_lesson_with_no_provenance_says_so_on_the_page() -> None:
    html = _provenance({"module_number": 1}, design_row=_ROW)

    assert html, "the block must print rather than vanish"
    assert "names no design element" in _text(html)
    assert "BECF" in html


def test_every_lesson_of_the_guide_carries_the_block() -> None:
    notes = {"title": "Integers", "modules": [
        {"module_number": 1, "title": "Introduction", "serves": ["outcome 1"],
         "teacher_exposition": "An integer is a whole number."},
        {"module_number": 2, "title": "Combined operations",
         "teacher_exposition": "BODMAS decides the order."},
    ]}
    html = render_html(notes, grade="grade-9", subject="Mathematics",
                       strand="Numbers", sub_strand="Integers")

    assert html.count("Where this comes from") == 2, \
        "the footer claims KICD provenance for every lesson"


def test_an_unread_design_is_not_scored_as_clean() -> None:
    """"Could not check" and "every piece cites the design" are not the same."""
    report = lesson_material.MaterialReport()
    report.provenance_blocked = "no row in curriculum_substrands for grade-9"

    assert not report.unsourced, "the list is empty in both cases; that was the bug"


def test_check_provenance_refuses_rather_than_passing_silently() -> None:
    material = {"material": [{"module_number": 1, "title": "A lesson"}]}

    try:
        lesson_material.check_provenance(
            material, "grade-9", "Mathematics", "a sub-strand nobody loaded")
    except lesson_material.UncheckableProvenance as exc:
        assert "curriculum_substrands" in str(exc) or "no learning outcomes" in str(exc)
    else:  # pragma: no cover - only if a design row appears for this name
        pass


def test_an_unloaded_design_reads_differently_from_an_uncited_lesson() -> None:
    """Two faults, two fixes. One sentence was covering both.

    Twelve lessons across two guides printed "this lesson names no design
    element" when the design row was in fact present — `_design_row` matched the
    sub-strand name exactly while the notes route matched exact-OR-LIKE, so the
    route had the outcomes and the resolver had nothing.
    """
    missing = _provenance({}, grade_label="grade-9", subject="Mathematics",
                          design_row={})
    uncited = _provenance({}, grade_label="grade-9", subject="Mathematics",
                          design_row=_ROW)

    assert "design for this sub-strand is not loaded" in _text(missing)
    assert "missing design, not a missing citation" in _text(missing)
    assert "names no design element" in _text(uncited)
    assert "not loaded" not in _text(uncited)


def test_the_resolver_looks_the_design_up_the_way_the_route_does() -> None:
    """An exact-only match left the guide uncitable for a row the route found."""
    import inspect

    sql = inspect.getsource(lesson_material._design_row)

    assert "sub_strand_pattern" in sql, \
        "the notes route matches exact OR LIKE; this has to agree or the " \
        "guide cannot cite a design the route is already reading"

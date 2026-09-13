"""The notes reach the stations after them as lessons, not as a JSON prefix.

The questions station received `json.dumps(notes)[:2000]` — the title, the
intro and half of lesson one's citations — or, on the batch route, read
`full_lecture_notes` off modules that carry `teacher_exposition`, so every
lesson came through as a heading with nothing under it.
"""
from __future__ import annotations

from app.services import notes_digest


def _guide(lessons: int = 4) -> dict:
    modules = []
    for n in range(1, lessons + 1):
        modules.append({
            "module_number": n,
            "title": f"Lesson {n}: Working with integers {n}",
            "learning_intent": f"By the end of lesson {n} the learner can combine operations.",
            "teacher_exposition": (f"In lesson {n} the teacher shows that a temperature falling "
                                   f"from 3°C by 8°C reaches −5°C. " * 30),
            "worked_examples": [
                {"statement": f"Work out $(-{n}) \\times 4 + 6$.", "answer": f"${6 - 4 * n}$",
                 "steps": [{"working": "...", "because": "..."}]},
                {"statement": f"A trader loses {n} shillings on each of 5 days. Find the change.",
                 "answer": f"$-{5 * n}$"},
            ],
            "lesson_flow": [
                {"phase": "Introduction", "minutes": 5,
                 "what_the_teacher_does": "Asks about last night's temperature.",
                 "what_learners_do": f"Learners in lesson {n} place cards on a number line."},
            ],
            "key_questions": [f"Why does the sign change in lesson {n}?"],
            "common_misconceptions": [{"misconception": f"Two negatives make a positive sum ({n})",
                                       "why_it_happens": "...", "how_to_correct_it": "..."}],
            "resources_needed": ["Number line chart", "Integer cards"],
            "learning_experiences_used": ["experience 2"],
            "citations": [{"claim": "x", "ref": "p.12:3", "quote": "y"}] * 20,
        })
    return {"title": "Teacher's Guide: Integers", "intro": "Integers extend the number line.",
            "modules": modules}


def test_every_lesson_reaches_the_questions_station() -> None:
    digest = notes_digest.for_questions(_guide(4))

    assert len(digest.lessons) == 4
    for n in range(1, 5):
        assert f"--- Lesson {n}: Working with integers {n} ---" in digest.text
        assert f"In lesson {n} the teacher shows" in digest.text, f"lesson {n}'s content is missing"
        assert f"Why does the sign change in lesson {n}?" in digest.text
        assert f"Two negatives make a positive sum ({n})" in digest.text


def test_the_worked_examples_are_marked_as_already_used() -> None:
    digest = notes_digest.for_questions(_guide(2))

    assert digest.examples == 4
    assert "do not set these again" in digest.text
    assert "A trader loses 2 shillings on each of 5 days" in digest.text
    assert "→ $-10$" in digest.text


def test_the_citations_do_not_crowd_out_the_teaching() -> None:
    """The JSON prefix was mostly citation objects; the digest is not."""
    digest = notes_digest.for_questions(_guide(4))

    assert "p.12:3" not in digest.text
    assert len(digest.text) > 4_000


def test_a_long_guide_is_cut_evenly_not_from_the_end() -> None:
    digest = notes_digest.for_questions(_guide(12), budget=9_000)

    assert len(digest.text) <= 9_010
    assert "--- Lesson 12:" in digest.text, "the budget must be shared across lessons"


def test_the_older_module_shape_is_still_read() -> None:
    notes = {"title": "Old", "hour_modules": [
        {"hour_title": "Hour 1: Fractions", "full_lecture_notes": "Halves and quarters."},
    ]}
    digest = notes_digest.for_questions(notes)

    assert "Hour 1: Fractions" in digest.text
    assert "Halves and quarters." in digest.text


def test_nothing_in_gives_nothing_out() -> None:
    assert notes_digest.for_questions(None).text == ""
    assert notes_digest.for_questions({"modules": []}).text == ""
    assert notes_digest.index("") == ""
    assert notes_digest.for_activities({}) == ""
    assert notes_digest.for_diagrams({}) == ""


def test_the_index_is_one_line_per_lesson() -> None:
    lines = notes_digest.index(_guide(3)).splitlines()

    assert len(lines) == 3
    assert lines[0].startswith("1. Lesson 1: Working with integers 1 — By the end of lesson 1")


def test_activities_see_what_learners_already_did() -> None:
    text = notes_digest.for_activities(_guide(2))

    assert "Learners in lesson 2 place cards on a number line." in text
    assert "Resources the teacher has: Number line chart, Integer cards" in text
    assert "Experiences used: experience 2" in text


def test_diagrams_see_the_figures_each_lesson_asked_for() -> None:
    guide = _guide(1)
    guide["modules"][0]["resources_needed"] = [
        "Chart: a horizontal number line from −10 to 10 with zero marked",
    ]
    text = notes_digest.for_diagrams(guide)

    assert "--- Lesson 1:" in text
    assert "horizontal number line" in text

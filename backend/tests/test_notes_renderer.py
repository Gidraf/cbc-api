

# ── an exercise list must not be split by its own brackets ──────────────────


def test_a_closing_bracket_is_not_read_as_a_question_number() -> None:
    r"""`(6 + 4) \times 2` ends a bracket with `4)`, and reading that as
    question 4 split the expression in half. The page printed "$(6 +" and
    "\times 2$", the engine was handed the fragment "10-2" left by the item
    before it, solved it correctly to 8, and printed 8 beside a green
    `checked` badge under a question that actually reads 10 - 22 + 5.

    Nothing about that was visible downstream: the maths was right, the badge
    was honest, and the expression it applied to no longer existed.
    """
    from app.services.notes_renderer import _numbered_items

    items = _numbered_items(
        r"1. $4+3 \times 2$  2. $10-22+5$  3. $(6 + 4) \times 2$  "
        r"4. $8 - (3 + 5) \times 2$  5. $12 \times 2 - 3 + 1$")

    assert items == [r"$4+3 \times 2$", r"$10-22+5$", r"$(6 + 4) \times 2$",
                     r"$8 - (3 + 5) \times 2$", r"$12 \times 2 - 3 + 1$"]


def test_a_real_bracketed_list_still_splits() -> None:
    """The fix must not stop `1)` `2)` `3)` being a list."""
    from app.services.notes_renderer import _numbered_items

    items = _numbered_items(
        "1) Work out -5 + 3.  2) Work out 7 - 12.  3) Work out -4 × 6.")

    assert len(items) == 3 and items[0] == "Work out -5 + 3."


def test_the_engine_disagreeing_is_said_out_loud() -> None:
    """The badge read `checked` whether the engine agreed or not, so a wrong
    answer carried the same green mark as a right one."""
    import pathlib

    body = pathlib.Path("app/services/notes_renderer.py").read_text()

    assert "not verified" in body
    assert body.count("<span class='ok'>checked</span>\" if solution.verified") \
        or "if solution.verified" in body


def test_the_engine_catches_the_answer_that_reached_the_page() -> None:
    from app.services.worked_solutions import check

    verdict = check("10 - 22 + 5", "8")

    assert verdict["checked"] and verdict["agrees"] is False
    assert verdict["engine_answer"] == "-7"


# ── a quiz written one question per line still gets a key ───────────────────


def test_a_quiz_written_one_question_per_line_is_found() -> None:
    """Asking each LINE for a run of three questions is a question a
    one-question line can never answer, so a quiz written the way every quiz is
    written — one per line, fifteen of them — produced no answers at all, and
    said nothing about it."""
    from app.services.notes_renderer import _numbered_items

    quiz = "\n".join([
        "1. Evaluate: 5+(-3).",
        "2. Calculate: -7+4-(-2).",
        "3. Solve the expression: (-3)*(-2)+5-8.",
        "4. What is the result of -12*3+15*(-2)?",
    ])

    assert [_numbered_items(line) for line in quiz.splitlines()] == [[], [], [], []]
    assert len(_numbered_items(quiz)) == 4


def test_the_key_prefers_the_answers_the_guide_itself_gives() -> None:
    """The engine can work `-7 + 4 - (-2)` and cannot work "a hiker descends
    300 m"; a set that is half word problems gets half a key from the solver
    alone, and half a key sends a learner hunting for a page that does not
    exist."""
    from app.services.notes_renderer import _practice

    piece = {
        "say": "1. Evaluate 5+(-3).\n2. A hiker descends 300 m. What changed?",
        "exercises": [
            {"question": "5+(-3)", "answer": "2", "working": "5 - 3 = 2"},
            {"question": "A hiker descends 300 m. What changed?",
             "answer": "-300 m"},
        ],
    }
    html = _practice(piece["say"], piece)

    assert "checked" in html
    assert "not checked by the engine" in html, "a word problem is still answered"


def test_an_answer_the_engine_disagrees_with_says_so_in_the_key() -> None:
    from app.services.notes_renderer import _practice

    html = _practice("1. Calculate -7+4-(-2).", {
        "exercises": [{"question": "-7+4-(-2)", "answer": "5"}]})

    assert "the engine makes it -1" in html


def test_questions_the_engine_cannot_work_are_listed_as_unworked() -> None:
    """A numbered gap in an answer key is what sends a learner hunting."""
    from app.services.notes_renderer import _practice

    html = _practice("\n".join([
        "1. Evaluate 5+(-3).",
        "2. Evaluate -7+4-(-2).",
        "3. A hiker descends 300 metres and then ascends 150 metres.",
    ]), {})

    assert "could not be worked by the maths engine" in html

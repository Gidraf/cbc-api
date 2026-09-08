

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
    """It says so AND prints the right one — the guide's wrong answer would
    otherwise become the marking key of a paper somebody sits."""
    from app.services.notes_renderer import _practice

    html = _practice("1. Calculate -7+4-(-2).", {
        "exercises": [{"question": "-7+4-(-2)", "answer": "5"}]})

    assert "corrected" in html
    assert "The guide gave" in html
    assert "-1" in html


def test_questions_the_engine_cannot_work_are_listed_as_unworked() -> None:
    """A numbered gap in an answer key is what sends a learner hunting."""
    from app.services.notes_renderer import _practice

    html = _practice("\n".join([
        "1. Evaluate 5+(-3).",
        "2. Evaluate -7+4-(-2).",
        "3. A hiker descends 300 metres and then ascends 150 metres.",
    ]), {})

    assert "could not be worked by the maths engine" in html


# ── the key must not mark its own right answers wrong ───────────────────────


def test_the_dollars_the_schema_asks_for_are_not_a_disagreement() -> None:
    """The material prompt says `"answer": "<the answer, in $…$>"`, so the
    generator writes `$1$` — and comparing that against the engine's `1`
    reported EVERY correct answer as wrong. A key whose right answers are
    marked wrong is worse than no key: the reader stops believing the badge."""
    from app.services.worked_solutions import check

    assert check(r"\frac{-8+4+6}{2}", "$1$")["agrees"] is True
    assert check(r"\frac{-8+4+6}{2}", "1")["agrees"] is True
    assert check(r"\frac{5+(-3)-4}{-2}", "$-1$")["agrees"] is False


def test_a_unit_on_an_answer_is_not_a_disagreement() -> None:
    from app.services.worked_solutions import check

    assert check("20 + (-8)", "$12$ points")["agrees"] is True
    assert check("12/3", r"$4\text{ metres}$")["agrees"] is True


def test_implicit_multiplication_is_read_as_multiplication() -> None:
    """`(-2)(-4)` is how a textbook writes a product and is not how a parser
    reads one. The engine returned 1/10 for an expression whose value is 7/10
    and reported no error — a wrong answer with a confident face, printed as
    the authority a teacher's own answer was marked against."""
    from app.services.worked_solutions import check

    got = check(r"\frac{-15 \div 3 - (-2)(-4) + 6}{-2 \times 3 + (-4)}", "7/10")

    assert got["agrees"] is True
    assert "7" in got["engine_answer"] and "10" in got["engine_answer"]

    from app.services.math_engine.latex_input import to_plain

    assert "3*(" in to_plain("3(4+2)")


def test_a_wrong_answer_is_corrected_rather_than_printed() -> None:
    """This key is read by machine to build question papers, so the guide's
    wrong answer would become the marking key of a paper somebody sits."""
    from app.services.notes_renderer import _practice

    html = _practice("1. x", {"exercises": [
        {"question": r"\frac{5+(-3)-4}{-2}", "answer": "$-1$"}]})

    assert "corrected" in html
    assert "The guide gave" in html, "a silent correction hides a systematic fault"


def test_a_question_the_engine_cannot_work_keeps_the_guide_s_answer() -> None:
    from app.services.notes_renderer import _practice

    html = _practice("1. x", {"exercises": [
        {"question": "A hiker descends 300 m then ascends 150 m.",
         "answer": "-150 m"}]})

    assert "not checked by the engine" in html
    assert "-150" in html

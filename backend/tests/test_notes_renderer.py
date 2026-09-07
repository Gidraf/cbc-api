

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

"""A material piece is checked as soon as it is written, and mended.

Found in one Grade 9 Integers guide: a piece with no words; a key whose
working ended at 40 and whose answer said 46; a sentence answering a
question about signs "corrected" to −3 by an engine that solved the
expression; `(−6)times7` where the backslash was lost; 1,200 read as 200
and a correct balance of 875 replaced by −125 under "arithmetic checked";
and the order of operations explained in nine pieces of twenty-one.
"""
from __future__ import annotations

from app.services import lesson_material as lm
from app.services import notes_renderer, worked_solutions


def test_the_engine_reads_a_thousands_separator() -> None:
    verdict = worked_solutions.check("Determine the final balance: $1,200+(-475)+300+(-150)$.", "875")
    assert verdict["checked"] and verdict["agrees"]
    assert worked_solutions.check("$2,000+(-450)+[300\\div(-3)]-(-125)$", "1,575")["agrees"]


def test_a_working_whose_last_link_is_false_is_named() -> None:
    piece = {"say": "x" * 200, "exercises": [
        {"question": "A club gains 16, then 24, loses 6, gains 6.", "working": "$16+24-6+6=40-6+6=46$", "answer": "46 shillings"}]}
    findings = lm.inspect_piece(piece)
    assert len(findings) == 1 and "40-6+6 = 46" in findings[0] and "comes to 40" in findings[0]


def test_an_answer_that_disagrees_with_its_own_working_is_named() -> None:
    piece = {"say": "x" * 200, "exercises": [
        {"question": "Find the balance.", "working": "$700+(-260)+30-30=440+30-30=470-30=440$", "answer": "667 shillings"}]}
    findings = lm.inspect_piece(piece)
    assert findings and "ends at 440" in findings[0] and "says 667" in findings[0]


def test_a_sentence_answer_is_not_judged_by_the_engine() -> None:
    piece = {"say": "x" * 200, "exercises": [
        {"question": "In $-8+5$, name the operation sign and the signs attached to the integers.",
         "working": "", "answer": "The operation sign is +. The signs attached are − on 8 and + on 5."}]}
    assert lm.inspect_piece(piece) == []


def test_a_value_answer_the_engine_disagrees_with_is_named() -> None:
    piece = {"say": "x" * 200, "exercises": [
        {"question": "Work out $-14-[5+(-8)]+6$.", "working": "", "answer": "$-32$"}]}
    findings = lm.inspect_piece(piece)
    assert findings and "engine makes it -5" in findings[0]


def test_an_empty_piece_and_a_thin_piece_are_findings() -> None:
    assert lm.inspect_piece({"say": ""}) == ["no words were written: `say` is empty"]
    assert any("too thin" in f for f in lm.inspect_piece({"say": "Short."}))


def test_lost_backslashes_and_doubled_ones_are_mended_in_place() -> None:
    piece = {"title": "Estimating", "say": "Estimating\nEvaluate $(−6)times7+12−(−5)$ and $(-240)div6$; $(-6)\\\\times 7 approx -42$. It was 20^C.",
             "exercises": [{"question": "$(−9)times2$", "answer": "$-18$", "working": "$(−9)times2=-18$"}]}
    mended = lm.tidy_piece(piece)

    assert "\\times 7" in piece["say"] and "\\div 6" in piece["say"]
    assert "\\\\times" not in piece["say"] and "\\times 7" in piece["say"]
    assert "\\approx" in piece["say"] and "20^\\circ C" in piece["say"]
    assert piece["say"].startswith("Evaluate"), "the title is not the first line of the prose"
    assert "\\times 2" in piece["exercises"][0]["question"]
    assert mended


def test_the_renderer_prints_the_questions_and_does_not_correct_a_sentence() -> None:
    html = notes_renderer._authored_key([
        {"question": "In $-8+5$, name the operation sign.", "answer": "The operation sign is +.", "working": ""},
        {"question": "Work out $-14-[5+(-8)]+6$.", "answer": "$-32$", "working": ""},
        {"question": "Find the balance.", "working": "$700-260+30-30=440$", "answer": "667"},
    ])
    assert "exercise-set" in html and "name the operation sign" in html
    assert "not checked by the engine" in html.split("class='solution'")[1]
    assert "corrected" in html.split("class='solution'")[2] and "-5" in html.split("class='solution'")[2]
    assert "class='steps'" in html.split("class='solution'")[2], "the engine's working replaces the wrong one"
    assert "answer disagrees with its working" in html.split("class='solution'")[3]


def test_a_doubled_latex_command_typesets_as_one() -> None:
    assert "\\\\times" not in notes_renderer._math("$(-6)\\\\times 7$")
    assert "\\times" in notes_renderer._math("$(-6)\\\\times 7$")


def test_a_rule_explained_in_three_pieces_is_a_repeat_and_later_pieces_are_told() -> None:
    bodmas = ("Brackets are evaluated first, then multiplication and division from left to right, "
              "and finally addition and subtraction from left to right.")
    material = {"material": [
        {"module_number": n, "title": f"Piece {n}", "say": bodmas + " x" * 100, "exercises": []} for n in (1, 2, 4)]}
    found = lm.retaught_rules(material)
    assert found and found[0]["rule"].startswith("the order of operations") and found[0]["times"] == 3

    told = lm.already_taught(material["material"][:1])
    assert "RULES ALREADY EXPLAINED IN FULL" in told and "order of operations (BODMAS) — explained in Lesson 1" in told


def test_wrong_answers_and_repeats_lower_the_score() -> None:
    report = lm.MaterialReport(total=10, written=10)
    assert report.score == 100.0 and report.clean
    report.wrong_answers.append({"number": 1})
    report.repeated.append({"kind": "rule"})
    assert not report.clean and report.score == 90.0


def test_the_station_mends_each_piece_as_it_is_written() -> None:
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert "_mend_piece(piece, messages, resolved, llm_client, directive, i, len(plan.directives))" in source
    mend = inspect.getsource(curriculum._mend_piece)
    assert "lesson_material.tidy_piece(piece)" in mend and "lesson_material.inspect_piece(piece)" in mend
    assert "lesson_material.rewrite_prompt(piece, findings)" in mend
    assert "len(left) < len(findings)" in mend, "a rewrite that does not improve the piece is not kept"

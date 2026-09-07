"""How demanding a task is, measured, against what the grade requires.

The complaint this answers, in the reviewer's own words: a Grade 9 integers
guide that is "Grade 3/4 Math, Not Grade 9". Nothing in it was arithmetically
wrong. Its hardest line was `7 - 4 = 3`.

What Grade 9 is actually assessed on looks like this:

    Evaluate without using a calculator:
        (-15 ÷ 3 - (-2) × (-4) + 6) / (-2 × 3 + (-4))

That is not harder because the numbers are bigger. It is harder because of its
SHAPE — four operations, brackets, two negatives multiplied together, and a
fraction bar that is a pair of brackets the learner has to supply — and shape
is countable.
"""
from __future__ import annotations

import pytest

from app.services import prompt_fragments as pf
from app.services import task_demand as td

EXEMPLAR = r"$\dfrac{-15 \div 3 - (-2) \times (-4) + 6}{-2 \times 3 + (-4)}$"


# ── what makes an expression hard ───────────────────────────────────────────


def test_the_shape_of_a_real_grade_nine_item_is_measured() -> None:
    demand = td.measure(EXEMPLAR)

    assert demand.operations >= 4
    assert demand.kinds == frozenset({"+", "-", "×", "÷"})
    assert demand.depth >= 1
    assert demand.fraction_bar
    assert demand.order_matters


def test_one_addition_is_one_operation_of_one_kind() -> None:
    demand = td.measure("$5 + (-3) = 2$")

    assert demand.operations == 1
    assert not demand.order_matters


def test_a_leading_minus_is_a_sign_and_not_an_operation() -> None:
    """`-5 - 8 + 6` is two operations on three terms, not three operations."""
    demand = td.measure("-5 - 8 + 6 = -7")

    assert demand.operations == 2
    assert demand.negatives == 1


def test_a_thousands_space_is_not_a_multiplication() -> None:
    r"""`1\,250` is one number. Reading the gap as a product inflated the
    demand of every figure with four digits in it."""
    demand = td.measure(r"$1\,250 - 3 \times 240$")

    assert demand.operations == 2
    assert demand.kinds == frozenset({"-", "×"})


def test_prose_is_not_read_as_algebra() -> None:
    """"Work out 7 - 4" was once measured as seven variables multiplied
    together, because a word was matched one letter at a time."""
    demand = td.measure("Work out 7 - 4")

    assert demand.operations == 1
    assert demand.expression == "7 - 4"


def test_a_bracket_next_to_a_bracket_is_a_product() -> None:
    demand = td.measure("$(-3)(4) + 15$")

    assert "×" in demand.kinds


def test_indices_and_roots_count_as_their_own_kinds() -> None:
    demand = td.measure(r"$2^{3} - \sqrt{49}$")

    assert {"^", "√"} <= demand.kinds


def test_text_with_no_arithmetic_in_it_is_not_measurable() -> None:
    """A floor written for Mathematics must leave a comprehension exercise
    alone, and it does so by having nothing to compare."""
    assert not td.measure("Explain why Kenya lies across the equator").measurable


# ── the floor ───────────────────────────────────────────────────────────────


def test_the_youngest_have_no_floor_at_all() -> None:
    """A six-year-old adding two single-digit numbers is doing the thing the
    design asks for. A check that demands brackets of them is simply wrong."""
    for grade in ("grade-pp1", "grade-1", "grade-3"):
        assert td.floor_for(grade) is None


@pytest.mark.parametrize("grade,level", [
    ("grade-5", "Upper Primary"), ("grade-9", "Junior School"),
    ("grade-12", "Senior School"),
])
def test_each_level_above_that_has_one(grade: str, level: str) -> None:
    floor = td.floor_for(grade)

    assert floor and floor.level == level


def test_an_unknown_grade_gets_no_floor_rather_than_the_hardest_one() -> None:
    assert td.floor_for("") is None and td.floor_for("banana") is None


# ── the set, which is the unit that matters ─────────────────────────────────


def test_a_set_whose_hardest_item_is_one_addition_is_below_the_grade() -> None:
    report = td.check_set([
        {"statement": "Work out 5 + (-3)", "steps": [{"working": "5 + (-3) = 2"}]},
        {"statement": "Work out -7 + 3", "steps": [{"working": "-7 + 3 = -4"}]},
    ], "grade-9")

    assert report.below
    assert "Junior School" in report.says()
    assert r"\dfrac" in report.fix()


def test_one_item_at_the_grade_carries_the_set() -> None:
    """A lesson introducing the sign rule NEEDS `-4 × 6 = -24` in it. Failing
    that item on its own is how a gate gets switched off."""
    report = td.check_set([
        {"statement": "Work out the product of -4 and 6",
         "steps": [{"working": "-4 × 6 = -24"}]},
        {"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
         "steps": [{"working": "-5 - 8 + 6 = -7"}]},
    ], "grade-9")

    assert not report.below
    assert report.at_grade == 1 and report.measured == 2


def test_a_multi_step_word_problem_is_not_failed_for_its_easiest_line() -> None:
    """Its hardest single line is one multiplication and it is still three
    steps of real work. Failing it would fail the item the grade wants most."""
    short = td.check_item({
        "statement": "A trader buys 3 crates at KSh 450 each and sells each at "
                     "KSh 620. Find the profit.",
        "steps": [{"working": r"$3 \times 450 = 1350$"},
                  {"working": r"$3 \times 620 = 1860$"},
                  {"working": r"$1860 - 1350 = 510$"}],
        "answer": "KSh 510"}, "grade-9")

    assert not short.below


def test_a_set_with_no_arithmetic_in_it_is_never_below_the_grade() -> None:
    report = td.check_set([
        {"statement": "Explain how the Rift Valley was formed",
         "steps": [{"working": "Tectonic plates moved apart."}]},
    ], "grade-9")

    assert not report.below and report.measured == 0


def test_the_same_easy_set_is_fine_lower_down() -> None:
    assert not td.check_set([
        {"statement": "Work out 5 + 3", "steps": [{"working": "5 + 3 = 8"}]},
    ], "grade-2").below


def test_the_shortfall_names_what_is_missing_and_what_would_fix_it() -> None:
    short = td.check_item(
        {"statement": "Work out 7 - 4", "steps": [{"working": "7 - 4 = 3"}]},
        "grade-9")

    assert short.below
    said = short.says()
    assert "1 operation" in said and "at least 2" in said
    assert "BODMAS" in said
    assert "Junior School" in short.fix()


# ── the prompt and the gate must not drift apart ────────────────────────────


@pytest.mark.parametrize("fragment_name,grade", [
    ("maths-demand-upper", "grade-5"),
    ("maths-demand-junior", "grade-9"),
    ("maths-demand-senior", "grade-11"),
])
def test_the_shape_a_prompt_asks_for_clears_the_floor_it_is_judged_by(
        fragment_name: str, grade: str) -> None:
    """A prompt that asks for one thing and a gate that demands another is how
    a generator gets held for producing exactly what it was told to produce."""
    floor = td.floor_for(grade)
    assert floor
    fragment = next(f for f in pf.FRAGMENTS if f.name == fragment_name)

    assert floor.exemplar.strip("$") in fragment.body, (
        f"{fragment_name} does not show the shape {floor.level} is measured by")
    assert not td.shortfall(td.measure(floor.exemplar), floor).below


def test_the_maths_floor_reaches_maths_and_nothing_else() -> None:
    assert pf.compose("Mathematics", "questions", "grade-9")
    assert not pf.compose("Christian Religious Education", "notes", "grade-9")
    assert not pf.compose("Mathematics", "questions", "grade-2")


def test_the_junior_fragment_stops_at_junior_school() -> None:
    """A Grade 9 floor reaching Grade 11 would cap a pathway paper at the
    demand of a junior one."""
    junior = pf.compose("Mathematics", "questions", "grade-9")
    senior = pf.compose("Mathematics", "questions", "grade-11")

    assert "Junior School" in junior and "Junior School" not in senior


# ── the gates it actually feeds ─────────────────────────────────────────────


def test_a_batch_of_well_formed_but_easy_questions_is_held() -> None:
    """Every item can be well formed and the whole paper still be four years
    too easy. That is what the reviewer found, and no per-item rule sees it."""
    from app.services import question_structure

    easy = [{"question_id": f"q{i}", "question_type": "quantitative_calculation",
             "stem": f"Work out {i} + 3 and write down the answer.",
             "marks": 1, "marking_scheme": [{"step": "add", "marks": 1}],
             "answer": f"{i + 3}",
             "steps": [{"working": f"{i} + 3 = {i + 3}"}]}
            for i in range(1, 5)]

    report = question_structure.check_all(easy, grade="grade-9")

    assert report["batch_blocked"]
    assert report["by_finding"].get("batch_below_the_grade") == 1
    assert "Junior School" in report["demand"]["says"]


def test_the_same_batch_is_not_held_when_one_item_reaches_the_grade() -> None:
    from app.services import question_structure

    items = [{"question_id": "q1", "question_type": "quantitative_calculation",
              "stem": "Work out 4 + 3 and write down the answer.", "marks": 1,
              "marking_scheme": [{"step": "add", "marks": 1}], "answer": "7",
              "steps": [{"working": "4 + 3 = 7"}]},
             {"question_id": "q2", "question_type": "quantitative_calculation",
              "stem": r"Evaluate $-15 \div 3 - (-2) \times (-4) + 6$ without a "
                      r"calculator.",
              "marks": 3,
              "marking_scheme": [{"step": "divide first", "marks": 1},
                                 {"step": "multiply", "marks": 1},
                                 {"step": "combine", "marks": 1}],
              "answer": "-7", "steps": [{"working": "-5 - 8 + 6 = -7"}]}]

    assert not question_structure.check_all(items, grade="grade-9")["batch_blocked"]


def test_a_batch_with_no_grade_is_not_judged_on_demand() -> None:
    """Guessing the grade here would hold a batch for missing a floor that was
    never established."""
    from app.services import question_structure

    report = question_structure.check_all(
        [{"question_id": "q1", "question_type": "short_answer",
          "stem": "Name two uses of integers in daily life.", "marks": 2,
          "answer": "temperature, altitude"}])

    assert not report["batch_blocked"] and report["demand"] == {}


def test_the_material_gate_fails_on_a_set_below_the_grade() -> None:
    from app.services import example_check

    report = example_check.check_material({"material": [{"worked_examples": [
        {"statement": "Work out 5 + (-3)", "steps": [{"working": "5 + (-3) = 2"}]},
        {"statement": "Work out -7 + 3", "steps": [{"working": "-7 + 3 = -4"}]},
    ]}]}, grade="grade-9")

    assert [f.kind for f in report.findings] == ["below_the_grade"]


def test_the_batch_verdict_does_not_discard_the_items() -> None:
    """Every item was generated and paid for, an easy opener is legitimate, and
    a set that is merely thin needs MORE items rather than fewer."""
    import inspect

    from app.routes import questions

    block = inspect.getsource(questions).split('structure.get("batch_blocked")')[1][:900]
    assert '"stage": "demand"' in block
    assert "normalized_questions = [" not in block, \
        "the batch verdict must not filter the items"


# ── what the floor applies TO ───────────────────────────────────────────────


def test_a_subject_the_generator_was_never_told_the_rule_is_not_held_to_it() -> None:
    """Gating a station that did exactly as it was told is how a gate loses its
    credibility. A subject is gated on arithmetic only where its generator has
    been given an arithmetic floor to work to."""
    numbers = [{"statement": "How many disciples did Jesus call?",
                "steps": [{"working": "10 + 2 = 12"}], "answer": "12"}]

    assert td.check_set(numbers, "grade-9", "Christian Religious Education").below \
        is False
    assert td.check_set(numbers, "grade-9", "Mathematics").below is True


def test_the_sciences_are_gated_because_their_calculations_are_marked() -> None:
    """Their designs award the formula, the substitution and the unit
    separately, so a one-line calculation cannot be marked on the rubric."""
    thin = [{"statement": "Find the density.", "steps": [{"working": "240 ÷ 30 = 8"}],
             "answer": "8 g/cm3"}]

    for subject in ("Physics", "Chemistry", "Integrated Science"):
        assert td.check_set(thin, "grade-9", subject).below, subject


def test_the_gate_and_the_prompt_cover_the_same_subjects() -> None:
    """One list, read by both sides. A subject gated but not instructed cries
    wolf; a subject instructed but not gated is a rule nothing enforces."""
    instructed = {stem for f in pf.FRAGMENTS
                  if f.name.endswith("-demand") or "-demand-" in f.name
                  for stem in f.subjects}

    assert instructed == set(td.QUANTITATIVE)


def test_an_unstated_subject_still_gets_the_level_floor() -> None:
    """"Do not ask" is not "any subject": a caller that never knew the subject
    must not silently lose the check."""
    easy = [{"statement": "Work out 7 - 4", "steps": [{"working": "7 - 4 = 3"}]}]

    assert td.check_set(easy, "grade-9").below


def test_the_reason_given_is_about_the_level_not_about_integers() -> None:
    """Integers were the sub-strand under review. The message printed on every
    other Grade 9 sub-strand too, and on Pythagoras it was simply wrong."""
    for floor in td._FLOORS.values():
        assert "integer" not in floor.because.lower(), floor.level

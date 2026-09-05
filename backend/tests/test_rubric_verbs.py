"""Reading KICD's rubric tables in every subject, not just the ones on a list.

`_CELL_VERBS` was written from the pre-primary and CRE designs — sings,
retells, dramatises, colours, cares, desires, respects — and never extended
when the system reached the rest of the curriculum. Mathematics parsed to
nothing and `rubric_filler` wrote a generated replacement for every sub-strand.

Extending the list for Mathematics fixed Mathematics and nothing else.
Measured across the fifty learning areas this system carries, it still read
22 of 48 realistic cells: Creative Arts 1 of 6, Physical Education 1 of 4,
Agriculture 1 of 6, teacher education 0 of 4.

A list of verbs is the wrong shape for the problem — every subject has its own
and the next one added will have more. So a cell is now recognised by its
GRAMMAR, which KICD writes identically in every subject: a capitalised
third-person singular verb with an object after it. The list survives as the
fast, precise path; the grammar is what makes it general.
"""
from __future__ import annotations

import pytest

from app.services.rubric_tables import _CELL_START, _CELL_VERBS, RubricRow


MATHS = [
    "Calculates the sum of two integers accurately.",
    "Works out combined operations in the correct order.",
    "Solves problems involving integers correctly.",
    "Adds and subtracts integers accurately.",
    "Evaluates expressions using the order of operations.",
    "Multiplies and divides integers correctly.",
    "Orders integers on a number line accurately.",
    "Simplifies the expression correctly.",
    "Rounds off to the nearest ten correctly.",
    "Converts metres to centimetres accurately.",
]

ORIGINAL = [
    "Identifies three qualities of God correctly.",
    "Names two ways of caring for others.",
    "Retells the story with all the events.",
    "Sings the song with actions.",
    "Measures the mass to the nearest gram.",
]

PRACTICAL = [
    "Investigates the effect of heat on the metal.",
    "Constructs the circuit correctly.",
    "Analyses the data and draws a conclusion.",
    "Prepares the seedbed to the correct depth.",
]


@pytest.mark.parametrize("cell", MATHS)
def test_a_mathematics_rubric_cell_is_recognised(cell: str) -> None:
    assert _CELL_START.match(cell), cell


@pytest.mark.parametrize("cell", ORIGINAL)
def test_the_cells_that_always_worked_still_do(cell: str) -> None:
    """Widening the list must not be a rewrite of it."""
    assert _CELL_START.match(cell), cell


@pytest.mark.parametrize("cell", PRACTICAL)
def test_the_practical_subjects_were_waiting_for_the_same_failure(cell: str) -> None:
    assert _CELL_START.match(cell), cell


def test_no_arithmetic_verb_was_present_before() -> None:
    """The finding itself, kept as a test: this is what was missing."""
    for verb in ("calculates", "solves", "evaluates", "works", "multiplies",
                 "divides", "simplifies", "rounds"):
        assert verb in _CELL_VERBS, verb


# ── the guard the verb list is NOT responsible for ──────────────────────────

def test_a_wrapped_continuation_is_still_not_a_rubric_level() -> None:
    """The PDF wraps cells across lines, and a fragment reads like a level and
    measures nothing. Capitalisation is what rejects those — not the narrowness
    of the verb list — so extending the list costs nothing here."""
    row = RubricRow(
        indicator="Ability to identify qualities of God",
        exceeding="Identifies three qualities of God correctly.",
        meeting="shows His love to them.",
        approaching="David and Goliath.",
        below="birth of Jesus Christ.",
    )

    assert not row.complete


def test_a_lower_case_mathematics_fragment_is_rejected_too() -> None:
    row = RubricRow(
        indicator="Ability to work out operations",
        exceeding="Calculates the sum accurately.",
        meeting="calculates the sum with help.",
        approaching="Adds with errors.",
        below="Attempts to add.",
    )

    assert not row.complete


def test_prose_that_is_not_an_assessment_cell_is_rejected() -> None:
    row = RubricRow(
        indicator="Ability to work out operations",
        exceeding="The learner is able to do this well.",
        meeting="Works it out.",
        approaching="Adds.",
        below="Attempts.",
    )

    assert not row.complete


def test_a_whole_mathematics_row_is_accepted() -> None:
    row = RubricRow(
        indicator="Ability to perform basic operations on integers",
        exceeding="Calculates the sum of two integers accurately.",
        meeting="Works out combined operations in the correct order.",
        approaching="Adds integers with some errors.",
        below="Attempts to add integers.",
    )

    assert row.complete
    assert row.to_dict()["rubric_source"] == "design", "KICD's, not generated"


# ── every subject, not just the ones somebody remembered ────────────────────

BY_FAMILY = {
    "languages": ["Pronounces the words clearly and correctly.",
                  "Spells the words accurately.",
                  "Listens attentively and responds correctly.",
                  "Recites the poem with expression."],
    "social studies": ["Locates the county on the map accurately.",
                       "Sequences the historical events correctly."],
    "creative arts": ["Paints the picture using appropriate colours.",
                      "Weaves the basket neatly.",
                      "Improvises a melody creatively.",
                      "Decorates the article attractively."],
    "physical education": ["Throws the ball accurately to the target.",
                           "Dribbles the ball while running.",
                           "Executes the skill with control."],
    "agriculture / home science": ["Plants the seedlings at correct spacing.",
                                   "Harvests the crop at the right stage.",
                                   "Mixes the ingredients in correct proportions.",
                                   "Cuts the fabric along the marked line."],
    "ict / pre-technical": ["Types the document using correct formatting.",
                            "Saves the file in the correct folder."],
    "teacher education": ["Plans the lesson using the correct format.",
                          "Facilitates the discussion effectively.",
                          "Assesses the learners using appropriate tools.",
                          "Reflects critically on the practice."],
}


@pytest.mark.parametrize(
    "cell",
    [c for cells in BY_FAMILY.values() for c in cells],
    ids=[f"{family}-{i}" for family, cells in BY_FAMILY.items()
         for i, _ in enumerate(cells)],
)
def test_a_rubric_cell_is_read_in_every_subject_family(cell: str) -> None:
    assert _CELL_START.match(cell), cell


def test_a_verb_nobody_listed_is_still_read() -> None:
    """The point of the grammatical rule: the next subject does not need an
    edit here. None of these verbs is in `_CELL_VERBS`."""
    invented = [
        "Calibrates the instrument to the required accuracy.",
        "Germinates the seeds under the correct conditions.",
        "Choreographs the sequence with clear transitions.",
        "Titrates the solution to the correct end point.",
    ]
    for cell in invented:
        assert not any(cell.lower().startswith(v) for v in _CELL_VERBS), cell
        assert _CELL_START.match(cell), cell


# ── and the fragments it exists to reject ───────────────────────────────────

@pytest.mark.parametrize("fragment", [
    "shows His love to them.",              # a wrap continuation, lower case
    "David and Goliath.",                   # proper noun
    "birth of Jesus Christ.",               # lower case
    "Jesus Christ.",                        # ends in -s, but two words
    "Numbers and operations.",              # a plural noun heading
    "Integers and their properties.",       # a plural noun heading
    "the correct order.",
    "God's love for the world.",
    "Kenya's counties and their capitals.",
    "Learners.",
])
def test_a_wrapped_fragment_is_never_a_rubric_level(fragment: str) -> None:
    """Widening recall must not cost precision: a fragment that reads as a
    level measures nothing, and a teacher cannot act on it."""
    assert not _CELL_START.match(fragment), fragment


def test_a_row_whose_verbs_are_all_unlisted_still_parses() -> None:
    """Teacher education scored 0 of 4 after the Mathematics fix — every one of
    its verbs was unlisted, so every row was discarded."""
    row = RubricRow(
        indicator="Ability to plan a lesson",
        exceeding="Plans the lesson using the correct format.",
        meeting="Facilitates the discussion effectively.",
        approaching="Assesses the learners with some support.",
        below="Attempts to plan the lesson.",
    )

    assert row.complete
    assert row.to_dict()["rubric_source"] == "design"

"""Read KICD's own assessment rubric tables out of the design.

The rubrics were being missed and generated instead. Two reasons, and both are
structural rather than particular to any one subject.

First, the extractor looked for a heading that does not exist. It searched for
"Suggested Formative Assessment Rubrics"; the designs say "Suggested Assessment
Rubric", sometimes "Rubrics", sometimes with a stray space — "Rubric s" — from
the PDF's own letter spacing. "Formative" appears nowhere.

Second, and more fundamental: a rubric table is on its OWN page, between
sub-strand sections. Every extractor here works over one sub-strand's body
text, and the rubric for sub-strands 1.1, 1.2 and 1.3 sits after all three of
them. It is in nobody's body, so nobody found it — and `rubric_filler` did what
it was built to do and wrote a replacement, honestly labelled and not KICD's.

So this reads rubric pages as pages, parses the indicator rows, and matches
each row back to the sub-strand whose outcome it measures. Matching by outcome
rather than by position matters: the tables are ragged, rows are dropped by the
PDF extraction, and counting rows against sub-strands in order is how a rubric
for the Holy Bible ends up under the birth of Jesus.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from . import document_index

logger = logging.getLogger("cbc-rubric-tables")

# Every spelling of the heading seen in a KICD design. The stray space in
# "Rubric s" is the PDF's letter spacing, not a typo we should be tolerant of
# by accident.
_HEADING = re.compile(
    r"suggested\s+(?:formative\s+)?assessment\s+rubric\s*s?\b",
    re.IGNORECASE,
)

# A row opens with "Ability to ..." in every design examined. Some open with
# the bare outcome, so the fallback is a line that reads like an indicator.
_INDICATOR = re.compile(r"^\s*(Ability to\s+.+|Identify\s+the\s+.+)$", re.IGNORECASE)

# How a rubric cell opens. A cell is recognised by its verb because KICD's
# columns arrive as an unlabelled stream once the PDF is flattened.
#
# This list was written from the pre-primary and CRE designs — sings, retells,
# dramatises, colours, cares, desires, respects — and never extended when the
# system reached the rest of the curriculum. It held 53 verbs and not one of
# them was arithmetic, so a Mathematics rubric table parsed to nothing:
#
#     Calculates the sum of two integers accurately.     not a cell
#     Works out combined operations in the correct order. not a cell
#     Solves problems involving integers correctly.       not a cell
#
# A row needs all four levels to be whole cells, so one unrecognised verb
# discarded the row, and a sub-strand with no rows fell through to
# `rubric_filler` — which wrote an honest replacement and labelled it
# generated. Mathematics therefore had no KICD rubrics anywhere in the system,
# and the measure that reports it read "no sub-strands in this result".
#
# The capitalisation check in `complete` is what rejects continuation
# fragments, not the narrowness of this list, so extending it costs nothing.
_CELL_VERBS = (
    # Naming, telling, describing — the original set.
    "identifies", "names", "demonstrates", "tells", "mentions", "practices",
    "practise", "practises", "retells", "narrates", "describes", "shows",
    "lists", "explains", "colours", "colors", "draws", "performs",
    "dramatizes", "dramatises", "sings", "observes", "selects", "matches",
    "sorts", "counts", "writes", "reads", "answers", "applies", "uses",
    "makes", "builds", "creates", "records", "measures", "classifies",
    "compares", "arranges", "follows", "participates", "shares", "cares",
    "appreciates", "desires", "respects", "states", "expresses", "recognises",
    "recognizes", "partly", "attempts", "does",
    # Mathematics. "works" carries "works out", which is how the designs
    # phrase almost every computational outcome.
    "calculates", "computes", "solves", "evaluates", "works", "adds",
    "subtracts", "multiplies", "divides", "orders", "simplifies", "converts",
    "rounds", "estimates", "substitutes", "expands", "factorises",
    "factorizes", "plots", "graphs", "tabulates", "represents", "derives",
    "interprets", "determines", "finds", "obtains",
    # Science, agriculture and pre-technical: the same failure was waiting for
    # every practical subject.
    "investigates", "experiments", "predicts", "tests", "assembles",
    "connects", "operates", "maintains", "designs", "sketches", "models",
    "analyses", "analyzes", "justifies", "concludes", "infers", "constructs",
    "collects", "prepares", "handles", "sets",
    # General assessment language across the ladder.
    "discusses", "explores", "distinguishes", "differentiates", "relates",
    "summarises", "summarizes", "outlines", "defines", "illustrates",
    "labels", "completes", "organises", "organizes",
    # Named by measuring the fifty learning areas rather than guessed at:
    # languages, creative arts, physical education, agriculture, home science,
    # ICT and teacher education each had their own and none were here.
    "pronounces", "spells", "listens", "recites", "articulates", "narrates",
    "locates", "sequences", "maps", "traces",
    "paints", "weaves", "moulds", "molds", "improvises", "decorates",
    "sculpts", "prints", "dances", "acts", "plays",
    "throws", "catches", "kicks", "dribbles", "executes", "jumps", "runs",
    "swims", "balances",
    "plants", "harvests", "mixes", "cuts", "joins", "stitches", "sews",
    "cooks", "serves", "waters", "prunes", "feeds",
    "types", "saves", "opens", "inserts", "formats", "installs",
    "plans", "facilitates", "assesses", "reflects", "mentors", "evaluates",
    "adapts", "differentiates",
)
# The PDF loses the space after the verb — "Identifiestwo", "Namesthree",
# "Demonstratestwo" all appear in a single design — so the number is allowed to
# be glued on.
_KNOWN_VERB = re.compile(
    r"^(?:" + "|".join(_CELL_VERBS) + r")"
    r"(?:\s|one|two|three|four|five|not\b|$)",
    re.IGNORECASE,
)

# The list above will never be finished. Measured across the fifty learning
# areas this system carries, a list built for CRE and then extended for
# Mathematics still recognised 22 of 48 realistic cells: Creative Arts 1 of 6,
# Physical Education 1 of 4, Agriculture 1 of 6, teacher education 0 of 4.
# Weaves, dribbles, harvests, improvises, facilitates — every subject has its
# own verbs and the next one added will have more.
#
# So recognise the GRAMMAR instead. KICD writes every rubric cell in the same
# form, in every subject: a capitalised third-person singular present verb.
#
#     Identifies three qualities of God correctly.
#     Weaves the basket neatly.
#     Facilitates the discussion effectively.
#
# What must still be rejected is the PDF's wrapped continuations, and those
# fail on other grounds: they open lower-case ("shows His love to them."), or
# they are short noun phrases ("David and Goliath.", "Jesus Christ."). So the
# structural rule asks for a capitalised word ending in -s AND enough words
# after it to be a cell rather than a fragment.
_THIRD_PERSON = re.compile(r"^[A-Z][a-z]+(?:es|s)\b")

# Below this a capitalised phrase is a heading or a wrapped fragment, not a
# rubric level. "Jesus Christ." and "David and Goliath." both die here.
_MIN_CELL_WORDS = 4


def _looks_like_a_cell(text: str) -> bool:
    """Whether this reads as a rubric level in any subject.

    The known verbs are the fast, precise path. The grammatical form is the
    general one, and is what stops this from needing a new list every time the
    curriculum reaches a subject nobody wrote verbs for.
    """
    stripped = (text or "").strip()
    if not stripped or not stripped[:1].isupper():
        # A cell opens capitalised in every design. `_KNOWN_VERB` is
        # case-insensitive, so without this "shows His love to them." — a wrap
        # continuation — matched on its own.
        return False
    if _KNOWN_VERB.match(stripped):
        return True

    words = stripped.split()
    if len(words) < _MIN_CELL_WORDS or not _THIRD_PERSON.match(stripped):
        return False
    # "Integers and their properties." is a plural noun heading, not a level.
    # A cell is a verb and its object; a heading is a noun joined to a noun.
    # Only the structural path needs this — a KNOWN verb followed by "and"
    # ("Adds and subtracts integers accurately.") took the fast path above.
    return words[1].lower() not in {"and", "or", "&"}


class _CellStart:
    """Kept callable as `_CELL_START.match(...)` for the existing call sites."""

    @staticmethod
    def match(text: str) -> bool:
        return _looks_like_a_cell(text)


_CELL_START = _CellStart()
_GLUED = re.compile(
    r"\b(" + "|".join(_CELL_VERBS) + r")(one|two|three|four|five)\b",
    re.IGNORECASE,
)
_TERMINAL = re.compile(r"[.!?]\s*$")

# The four levels, in the order KICD prints them. The names vary between
# "Exceeds"/"Exceeding" and "Meets"/"Meeting" within a single document.
_LEVELS = (
    ("exceeding", re.compile(r"^exceed(?:s|ing)?\b", re.IGNORECASE)),
    ("meeting", re.compile(r"^meet(?:s|ing)?\b", re.IGNORECASE)),
    ("approaching", re.compile(r"^approach(?:es|ing)?\b", re.IGNORECASE)),
    ("below", re.compile(r"^below\b", re.IGNORECASE)),
)

_LEVEL_ORDER = ("exceeding", "meeting", "approaching", "below")

# Lines that are page furniture rather than rubric content.
_NOISE = re.compile(
    r"^\s*(?:page\s*$|/\s*$|\d{1,4}\s*$|level\s*$|indicator\s*$|"
    r"page\s+\d+\s+of\s+\d+\s*$)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class RubricRow:
    indicator: str = ""
    exceeding: str = ""
    meeting: str = ""
    approaching: str = ""
    below: str = ""
    page: int = 0
    matched_sub_strand: str = ""
    match_score: float = 0.0
    # Levels finished from the indicator's own words, named so a reviewer can
    # see that the join happened rather than discovering it.
    completed_levels: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """All four levels present AND each of them a whole cell.

        The PDF drops cells and wraps others across three lines, so a level can
        come back as a continuation fragment — "shows His love to them.",
        "David and Goliath." — which reads as a rubric level and measures
        nothing. Better an honest generated rubric than a level a teacher
        cannot act on.
        """
        levels = (self.exceeding, self.meeting, self.approaching, self.below)
        if not self.indicator or not all(levels):
            return False
        # A cell opens with a capitalised assessment verb. A continuation line
        # opens lower-case — "shows His love to them.", "birth of Jesus Christ."
        # — which is exactly how a fragment came through as a rubric level.
        return all(
            level[:1].isupper() and _CELL_START.match(level) for level in levels
        )

    @property
    def truncated_levels(self) -> list[str]:
        """Levels the PDF cut off mid-phrase.

        "Identifies three", "Names one thing", "Tells three" — the words are
        KICD's and the sentence is not finished. Keeping them beats replacing a
        real rubric with a generated one, but a teacher reading "Meeting:
        Identifies three" should know the design is what stopped there, not us.
        """
        return [
            level for level in _LEVEL_ORDER
            if getattr(self, level) and not _TERMINAL.search(getattr(self, level))
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator": self.indicator,
            "exceeding": self.exceeding,
            "meeting": self.meeting,
            "approaching": self.approaching,
            "below": self.below,
            "source_page": self.page,
            "rubric_source": "design",
            "truncated_levels": self.truncated_levels,
            "completed_levels": self.completed_levels,
        }


@dataclass(slots=True)
class RubricHarvest:
    rows: list[RubricRow] = field(default_factory=list)
    pages_read: list[int] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    def for_sub_strand(self, name: str) -> list[dict[str, Any]]:
        key = name.strip().lower()
        return [r.to_dict() for r in self.rows
                if r.matched_sub_strand.strip().lower() == key and r.complete]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": len(self.rows),
            "complete_rows": sum(1 for r in self.rows if r.complete),
            "pages_read": self.pages_read,
            "unmatched_indicators": self.unmatched,
        }


def _clean(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _is_noise(line: str) -> bool:
    return not line.strip() or bool(_NOISE.match(line))


def rubric_pages(pages: list[document_index.Page]) -> list[document_index.Page]:
    """The pages that hold a rubric table.

    A rubric page is one whose heading says so. Scanning every page for
    "Exceeds Expectations" instead would also catch the prose that mentions the
    four levels in an essence statement.
    """
    found = []
    for page in pages:
        head = " ".join(_clean(l.text) for l in page.lines[:8])
        if _HEADING.search(head):
            found.append(page)
    return found


def _split_rows(page: document_index.Page) -> list[RubricRow]:
    """Turn one rubric page into rows.

    KICD's table survives PDF extraction as a column-major stream: every
    indicator, then the cells, wrapped across lines and frequently missing one.
    So an indicator opens a row and everything up to the next indicator belongs
    to it, assigned to a level by its own leading word where it has one and by
    position where it does not.
    """
    rows: list[RubricRow] = []
    current: RubricRow | None = None
    buffer: list[str] = []
    # An indicator wraps too — "Ability to identify three / qualities of God." —
    # and treating its second line as the first cell shifts every level by one,
    # which put "more than three" under Meeting and lost Below entirely.
    building_indicator = False

    def flush() -> None:
        nonlocal current, buffer
        if current is None:
            return
        cells = [c for c in buffer if c]
        # Cells that name their own level win; the rest fill the remaining
        # levels in KICD's printed order.
        remaining = list(_LEVEL_ORDER)
        leftovers: list[str] = []
        for cell in cells:
            for level, pattern in _LEVELS:
                if pattern.match(cell) and level in remaining:
                    setattr(current, level, _strip_level(cell, pattern))
                    remaining.remove(level)
                    break
            else:
                leftovers.append(cell)
        for level, cell in zip(remaining, leftovers):
            setattr(current, level, cell)
        for level in _LEVEL_ORDER:
            value = getattr(current, level)
            if value:
                setattr(current, level, _GLUED.sub(r"\1 \2", value))
        current.indicator = _GLUED.sub(r"\1 \2", current.indicator)

        # Finish what the column cut off. Half of KICD's cells arrive
        # truncated — "Identifies three", "Tells three" — and a teacher cannot
        # mark against those. Only ever a join from the indicator's own words;
        # where they cannot be located the cell is left as it is.
        for level in _LEVEL_ORDER:
            value = getattr(current, level)
            if not value:
                continue
            finished = complete_cell(value, current.indicator)
            if finished != value:
                setattr(current, level, finished)
                current.completed_levels.append(level)
        rows.append(current)
        current, buffer = None, []

    for line in page.lines:
        text = _clean(line.text)
        if _is_noise(text):
            continue
        if _HEADING.search(text):
            continue
        if _INDICATOR.match(text):
            flush()
            current = RubricRow(indicator=text, page=page.number)
            building_indicator = not _TERMINAL.search(text)
            continue
        if current is None:
            continue

        if building_indicator:
            # Still the indicator, until it closes with a full stop or a cell
            # verb starts the first level.
            if _CELL_START.match(text):
                building_indicator = False
            else:
                current.indicator = f"{current.indicator} {text}"
                if _TERMINAL.search(text):
                    building_indicator = False
                continue

        # A new cell starts where a cell verb opens the line, or where the cell
        # before it closed with a full stop. Otherwise it is a wrapped
        # continuation: KICD breaks a single cell across three lines routinely.
        starts_cell = bool(_CELL_START.match(text)) or bool(
            buffer and _TERMINAL.search(buffer[-1])
        )
        if buffer and not starts_cell:
            buffer[-1] = f"{buffer[-1]} {text}"
        else:
            buffer.append(text)
    flush()
    return rows


def _strip_level(cell: str, pattern: re.Pattern[str]) -> str:
    without = pattern.sub("", cell, count=1)
    return re.sub(r"^\s*(expectations?)?\s*[:\-]?\s*", "", without, flags=re.IGNORECASE).strip()


# Words every rubric indicator in every subject contains. Matching on these
# matches everything: "Ability to identify three qualities of God" scored 0.5
# against "A Holy Book" purely on "identify" and "three", which is how one
# strand's rubric reached four other sub-strands at once.
_GENERIC = {
    "ability", "identify", "identifies", "name", "names", "tell", "tells",
    "mention", "mentions", "demonstrate", "demonstrates", "state", "states",
    "list", "lists", "describe", "describes", "explain", "explains", "show",
    "shows", "narrate", "narrates", "observe", "observes", "practice",
    "practise", "express", "expresses", "appreciate", "appreciates", "desire",
    "respect", "retell", "retells", "dramatize", "dramatise",
    "one", "two", "three", "four", "five", "more", "than", "ways", "way",
    "thing", "things", "learner", "learners", "them", "their", "his", "her",
    "the", "and", "for", "from", "with", "about", "they", "that", "this",
}

# How much of the indicator's DISTINCTIVE vocabulary must be present, and how
# many distinctive words there must be at all. One shared word is a coincidence
# — "God" appears in nine of twelve CRE sub-strands.
_MATCH_FLOOR = 0.6
_MIN_DISTINCTIVE = 2


def _distinctive(text: str) -> set[str]:
    from .dna_scoring import tokens

    return {t for t in tokens(text) if t not in _GENERIC and len(t) > 2}


def _match_to_sub_strand(
    row: RubricRow, sub_strands: list[dict[str, Any]]
) -> tuple[str, float]:
    """Which sub-strand's outcome this row measures.

    By the topic words the indicator and the outcome share, never by position
    and never by the assessment verbs they all share. The tables are ragged and
    rows are dropped in extraction, so walking rows and sub-strands in step is
    exactly how a rubric for the Holy Bible was filed under the birth of Jesus.
    """
    indicator = re.sub(r"^\s*ability to\s+", "", row.indicator, flags=re.IGNORECASE)
    wanted = _distinctive(indicator)
    if len(wanted) < _MIN_DISTINCTIVE:
        # Nothing topical to match on. "Ability to name three things" belongs
        # to whichever sub-strand the page says, and this cannot tell.
        return "", 0.0

    scored: list[tuple[float, str]] = []
    for sub in sub_strands:
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        if not name:
            continue
        outcomes = [str(s) for s in (sub.get("slos") or []) if str(s).strip()]
        have = _distinctive(" ".join(outcomes + [name]))
        shared = wanted & have
        scored.append((len(shared) / len(wanted), name))

    if not scored:
        return "", 0.0
    scored.sort(reverse=True)
    best_score, best = scored[0]

    if best_score < _MATCH_FLOOR:
        return "", best_score

    # An indicator that fits two sub-strands equally well fits neither well
    # enough to file against one of them.
    if len(scored) > 1 and scored[1][0] >= best_score:
        logger.info(
            "Rubric row %r matches %r and %r equally; leaving it unfiled.",
            row.indicator[:60], best, scored[1][1],
        )
        return "", best_score

    return best, best_score


def harvest(design_text: str, sub_strands: list[dict[str, Any]]) -> RubricHarvest:
    """Every rubric row KICD published for these sub-strands."""
    result = RubricHarvest()
    if not design_text.strip():
        return result

    pages = document_index.parse_pages(design_text)
    for page in rubric_pages(pages):
        result.pages_read.append(page.number)
        for row in _split_rows(page):
            name, score = _match_to_sub_strand(row, sub_strands)
            row.matched_sub_strand, row.match_score = name, round(score, 3)
            if name:
                result.rows.append(row)
            else:
                result.unmatched.append(f"p{page.number}: {row.indicator[:120]}")

    logger.info(
        "Read %d rubric row(s) from page(s) %s; %d could not be matched to a sub-strand.",
        len(result.rows), result.pages_read, len(result.unmatched),
    )
    return result


# ── completing what the PDF cut off ─────────────────────────────────────────

def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text or "")


def _same(a: str, b: str) -> bool:
    """Loose word equality, so "thing" matches "things"."""
    a, b = a.lower(), b.lower()
    return a == b or a.rstrip("s") == b.rstrip("s")


# Words a truncated cell can end on that carry no meaning to anchor against.
# "Demonstrates one way of" ends on "of"; the word to look for is "way".
_FUNCTION_TAIL = {"of", "the", "a", "an", "to", "in", "for", "with", "and",
                  "on", "at", "by", "from", "their", "his", "her", "its"}

# A level opens by stating how many. "one", "two", "one to two", "more than
# three" — after the quantity comes the same object the indicator names.
_QUANTITY = {"one", "two", "three", "four", "five", "six", "seven", "eight",
             "nine", "ten", "more", "than", "fewer", "less", "least"}


def _indicator_tail(indicator: str) -> list[str]:
    """The indicator's object phrase — what the level is measuring.

    "Ability to identify three qualities of God." -> three qualities of God
    """
    stripped = re.sub(r"^\s*ability\s+to\s+", "", indicator or "", flags=re.IGNORECASE)
    words = _words(stripped)
    # Drop the leading verb; the levels supply their own.
    return words[1:] if words else []


def complete_cell(cell: str, indicator: str) -> str:
    """Finish a cell the PDF cut off, using the indicator's own words.

    Half of KICD's rubric cells arrive truncated — "Identifies three",
    "Names one thing", "Tells three" — because the table column ran out. A
    teacher cannot mark against "Meeting: Identifies three".

    This is a JOIN, not a guess: the cell's trailing words are located inside
    the indicator's object phrase, and only the remainder of that phrase is
    appended. Where they cannot be located, the cell is returned untouched
    rather than completed on a hunch.
    """
    if not cell or _TERMINAL.search(cell):
        return cell

    cell_words = _words(cell)
    tail = _indicator_tail(indicator)
    if not cell_words or not tail:
        return cell

    # Longest suffix of the cell that appears as a run inside the tail. Longest
    # first, so "qualities of" is preferred over the bare "of".
    #
    # Trailing function words are stripped before anchoring: "Demonstrates one
    # way of" ends on "of", which appears everywhere and anchors nowhere, while
    # the word that actually locates it is "way".
    anchorable = list(cell_words)
    while anchorable and anchorable[-1].lower() in _FUNCTION_TAIL:
        anchorable.pop()

    for length in range(min(len(anchorable), len(tail)), 0, -1):
        suffix = anchorable[-length:]
        for start in range(len(tail) - length + 1):
            if all(_same(a, b) for a, b in zip(suffix, tail[start:start + length])):
                remainder = tail[start + length:]
                # The function words stripped above may already be in the cell
                # AND at the head of the remainder — "handling the" then "the
                # holy Bible" — in which case saying them twice is wrong. Skip
                # only the ones that genuinely match: "way of" followed by
                # "loving God" shares nothing, and dropping a word there would
                # cost the sentence its verb.
                stripped_tail = cell_words[len(anchorable):]
                skip = 0
                while (skip < len(stripped_tail) and skip < len(remainder)
                       and _same(stripped_tail[skip], remainder[skip])):
                    skip += 1
                remainder = remainder[skip:]
                if not remainder:
                    return cell.rstrip() + "."
                return f"{cell.rstrip()} {' '.join(remainder)}."

    # No anchor, but the cell ends on a quantity and the indicator's object
    # opens with one: "Identifies one to two" against "four activities they do
    # in church" is stating a different count of the same thing.
    if cell_words[-1].lower() in _QUANTITY:
        after_quantity = list(tail)
        while after_quantity and after_quantity[0].lower() in _QUANTITY:
            after_quantity.pop(0)
        if after_quantity and len(after_quantity) < len(tail):
            return f"{cell.rstrip()} {' '.join(after_quantity)}."
    return cell

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

# How a rubric cell opens. These are assessment verbs, not subject vocabulary —
# the same set works for "Identifies three qualities of God" and "Measures the
# mass to the nearest gram". A cell is recognised by its verb because KICD's
# columns arrive as an unlabelled stream once the PDF is flattened.
_CELL_VERBS = (
    "identifies", "names", "demonstrates", "tells", "mentions", "practices",
    "practise", "practises", "retells", "narrates", "describes", "shows",
    "lists", "explains", "colours", "colors", "draws", "performs",
    "dramatizes", "dramatises", "sings", "observes", "selects", "matches",
    "sorts", "counts", "writes", "reads", "answers", "applies", "uses",
    "makes", "builds", "creates", "records", "measures", "classifies",
    "compares", "arranges", "follows", "participates", "shares", "cares",
    "appreciates", "desires", "respects", "states", "expresses", "recognises",
    "recognizes", "partly", "attempts", "does",
)
# The PDF loses the space after the verb — "Identifiestwo", "Namesthree",
# "Demonstratestwo" all appear in a single design — so the number is allowed to
# be glued on.
_CELL_START = re.compile(
    r"^(?:" + "|".join(_CELL_VERBS) + r")"
    r"(?:\s|one|two|three|four|five|not\b|$)",
    re.IGNORECASE,
)
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

    @property
    def complete(self) -> bool:
        return bool(self.indicator and self.exceeding and self.meeting
                    and self.approaching and self.below)

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator": self.indicator,
            "exceeding": self.exceeding,
            "meeting": self.meeting,
            "approaching": self.approaching,
            "below": self.below,
            "source_page": self.page,
            "rubric_source": "design",
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


def _match_to_sub_strand(
    row: RubricRow, sub_strands: list[dict[str, Any]]
) -> tuple[str, float]:
    """Which sub-strand's outcome this row measures.

    By outcome text, never by position. The tables are ragged and rows are
    dropped in extraction, so walking rows and sub-strands in step is exactly
    how a rubric for the Holy Bible was filed under the birth of Jesus.
    """
    from .dna_scoring import containment

    indicator = re.sub(r"^\s*ability to\s+", "", row.indicator, flags=re.IGNORECASE)
    best, best_score = "", 0.0

    for sub in sub_strands:
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        outcomes = [str(s) for s in (sub.get("slos") or []) if str(s).strip()]
        if not name:
            continue
        # The indicator restates an outcome, so ask how much of the indicator
        # is present in this sub-strand's outcomes — plus its own name, which
        # carries the topic when the outcome wording diverges.
        haystack = " ".join(outcomes + [name])
        score = containment(indicator, haystack)
        if score > best_score:
            best, best_score = name, score

    # Below this the row is about something else on the page. Filing it anyway
    # is the contamination this function exists to prevent.
    return (best, best_score) if best_score >= 0.5 else ("", best_score)


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

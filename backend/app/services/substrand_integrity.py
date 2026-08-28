"""Refuse to author from a sub-strand record that was never parsed.

Hindu Religious Education PP1 ingested as ONE strand containing ONE sub-strand,
both named "1.0 CREATION", carrying 54 shredded outcome fragments — "say the
first", "appreciate the", "for", ",", "249:19  ● Library" — scraped from all
six strands at once, with no lesson count. The design's own summary page says
six strands, sixteen sub-strands, ninety lessons.

The pipeline generated from it anyway, and reported "Lesson Coverage: complete,
100%" — because one module was asked for and one module arrived. Every measure
downstream agreed: SLO coverage 96%, structural completeness 100%. They were
all measuring the wrong thing correctly.

A record this broken is not a quality problem to be scored; it is an input that
cannot produce anything true, and the only honest response is to stop and say
which part of the extraction failed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-substrand-integrity")

# "241:48  • Picking litterfrom" — a page address that reached a content field
# means the extractor was scraping lines, not reading a table.
_LINE_ADDRESS = re.compile(r"\b\d{1,4}:\d{1,5}\s\s")

# A learning outcome is a clause. These are the shapes a shredded column leaves.
_TRAILING_FRAGMENT = re.compile(
    r"\b(?:the|a|an|of|in|to|for|and|with|their|from|at|as|by|into)\s*[,.]?\s*$",
    re.IGNORECASE,
)

MIN_SLO_CHARS = 12

# A learning outcome names a verb AND what it applies to: "identify three
# qualities of God" is four words at minimum. "say the first" is a column that
# was cut mid-clause, and it clears a character threshold comfortably.
MIN_SLO_WORDS = 4

# No KICD sub-strand has more outcomes than this. Fifty-four means the record
# holds a whole learning area, not a sub-strand.
MAX_PLAUSIBLE_SLOS = 12


@dataclass(slots=True)
class IntegrityReport:
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    problems: list[dict[str, str]] = field(default_factory=list)
    slo_count: int = 0
    fragment_count: int = 0

    @property
    def usable(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "grade": self.grade, "subject": self.subject,
            "strand": self.strand, "sub_strand": self.sub_strand,
            "slo_count": self.slo_count,
            "fragment_count": self.fragment_count,
            "problems": self.problems,
        }

    def message(self) -> str:
        return (
            f"'{self.sub_strand}' was not parsed into a usable sub-strand, so "
            f"nothing generated from it can be true: "
            + "; ".join(p["what"] for p in self.problems)
            + f". Re-ingest {self.subject} ({self.grade}) — "
            f"POST /factory/ingest-learning-area — and check "
            f"GET /factory/structure-report?grade={self.grade} before generating."
        )


def _is_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if len(stripped) < MIN_SLO_CHARS:
        return True
    if _LINE_ADDRESS.search(stripped):
        return True
    if len(stripped.split()) < MIN_SLO_WORDS:
        return True
    return bool(_TRAILING_FRAGMENT.search(stripped))


def check(
    grade: str, subject: str, strand: str, sub_strand: str,
    slos: list[Any] | None = None, allocated: str = "",
) -> IntegrityReport:
    """Is this record a sub-strand, or the wreckage of a failed parse?"""
    report = IntegrityReport(
        grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
    )

    texts = [
        (s.get("text") if isinstance(s, dict) else str(s)) or ""
        for s in (slos or [])
    ]
    report.slo_count = len(texts)
    report.fragment_count = sum(1 for t in texts if _is_fragment(t))

    def problem(kind: str, what: str) -> None:
        report.problems.append({"check": kind, "what": what})

    # A sub-strand named after its own strand is the block the parser could not
    # read, recorded whole.
    if strand and sub_strand and strand.strip().lower() == sub_strand.strip().lower():
        problem(
            "strand_is_substrand",
            f"the sub-strand and its strand are both '{strand}', so the whole "
            f"strand was stored as a single sub-strand",
        )

    if report.slo_count > MAX_PLAUSIBLE_SLOS:
        problem(
            "too_many_outcomes",
            f"{report.slo_count} learning outcomes on one sub-strand — no KICD "
            f"sub-strand has more than about {MAX_PLAUSIBLE_SLOS}, so this record "
            f"holds a whole learning area",
        )

    if texts and report.fragment_count >= max(2, len(texts) // 3):
        examples = [t for t in texts if _is_fragment(t)][:3]
        problem(
            "shredded_outcomes",
            f"{report.fragment_count} of {report.slo_count} outcomes are broken "
            f"fragments rather than clauses (e.g. "
            + ", ".join(f"{e!r}" for e in examples) + ")",
        )

    debris = [t for t in texts if _LINE_ADDRESS.search(t)]
    if debris:
        problem(
            "page_debris",
            f"{len(debris)} outcome(s) carry raw page addresses (e.g. "
            f"{debris[0][:60]!r}), so the extractor was scraping lines rather "
            f"than reading the table",
        )

    if not str(allocated or "").strip():
        problem(
            "no_lesson_count",
            "the design's lesson allocation was not captured, so the guide has "
            "no idea how many lessons to plan",
        )

    if report.problems:
        logger.error(
            "Sub-strand '%s' (%s, %s) is unusable: %s",
            sub_strand, subject, grade,
            "; ".join(p["check"] for p in report.problems),
        )
    return report


def require(
    grade: str, subject: str, strand: str, sub_strand: str,
    slos: list[Any] | None = None, allocated: str = "",
) -> IntegrityReport:
    """Stop before spending tokens on a record that cannot produce anything true."""
    from ..errors import raise_api_error

    report = check(grade, subject, strand, sub_strand, slos, allocated)
    if not report.usable:
        raise_api_error("MISSING_PARENT_CONTEXT", report.message(),
                        detail=report.to_dict())
    return report

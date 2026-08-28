"""Resolve the citations in generated content against the design it cites.

Content that cites its source is checkable; content whose citations are never
resolved is content that merely looks checkable, which is worse. A manufactured
`202:14` survives every inspection short of opening page 202 — and nobody opens
page 202 when the field is already filled in.

So every citation is resolved against the actual document: the address must
exist, and the quote must be at it. A citation that fails is reported rather
than dropped, because the claim it was attached to is now unsupported and the
reviewer needs to know which claim that is.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-citations")

# How much of a quote must appear at the cited lines. Extraction inserts and
# drops whitespace, and a design's own text wraps mid-phrase across columns, so
# an exact match would fail on citations that are perfectly good.
MIN_OVERLAP = 0.6

# What starts a new entry in a KICD table cell: a bullet, or a lettered or
# numbered outcome. The lines between two of these are one wrapped entry.
_ENTRY_START = re.compile(r"^\s*(?:[•\-*●]|\(?[a-h]\)|\d{1,2}[.)])\s")

# How far past the cited line to look for the rest of a wrapped quote.
#
# KICD prints in narrow columns, so one bullet routinely spans two or three
# lines: 203:26 holds "say the name of God in their mother tongue or" and
# 203:27 holds "language of catchment area". Checking only the cited line
# failed six of fourteen otherwise-correct citations and told the operator the
# claims were unsupported — which was wrong, and worse than saying nothing.
WRAP_LOOKAHEAD = 3


@dataclass(slots=True)
class Citation:
    claim: str = ""
    ref: str = ""
    quote: str = ""
    verified: bool = False
    reason: str = ""
    found_at: str = ""
    lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim, "ref": self.ref, "quote": self.quote,
            "verified": self.verified, "reason": self.reason,
            "found_at": self.found_at, "lines": self.lines,
        }


@dataclass(slots=True)
class CitationReport:
    citations: list[Citation] = field(default_factory=list)
    document_available: bool = True

    @property
    def verified(self) -> int:
        return sum(1 for c in self.citations if c.verified)

    @property
    def percentage(self) -> int:
        if not self.citations:
            return 0
        return round(self.verified / len(self.citations) * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_available": self.document_available,
            "total": len(self.citations),
            "verified": self.verified,
            "unverified": len(self.citations) - self.verified,
            "percentage": self.percentage,
            "citations": [c.to_dict() for c in self.citations],
        }


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3}


def collect(content: Any, path: str = "") -> list[Citation]:
    """Every citation anywhere in a generated payload.

    Walked rather than read from a known key: notes cite per module, questions
    cite per item, and a sub-strand cites at the top level.
    """
    found: list[Citation] = []

    if isinstance(content, dict):
        raw_list = content.get("citations")
        if isinstance(raw_list, list):
            for raw in raw_list:
                if isinstance(raw, dict) and (raw.get("ref") or raw.get("quote")):
                    found.append(Citation(
                        claim=str(raw.get("claim") or "")[:400],
                        ref=str(raw.get("ref") or "").strip(),
                        quote=str(raw.get("quote") or "")[:600],
                    ))
        # A question's citation lives on its own curriculum block.
        reference = content.get("guideline_reference")
        if isinstance(reference, dict) and reference.get("ref"):
            found.append(Citation(
                claim=str(content.get("kicd_alignment") or path)[:400],
                ref=str(reference.get("ref") or "").strip(),
                quote=str(content.get("guideline_quote") or "")[:600],
            ))
        for key, value in content.items():
            if key not in ("citations", "guideline_reference"):
                found += collect(value, f"{path}.{key}" if path else str(key))

    elif isinstance(content, list):
        for index, item in enumerate(content):
            found += collect(item, f"{path}[{index}]")

    return found


def _with_wrapped_continuation(pages: Any, ref: str) -> tuple[list[str], str]:
    """The whole wrapped ENTRY the cited line belongs to.

    KICD prints in narrow columns, so one outcome is routinely split across
    three printed lines: "a) identify three" / "qualities of" / "God,". A model
    quoting the outcome may anchor on any of them — the run that cites
    "practice saying short prayers" at the line holding "short prayers," is
    correct about the claim and merely pointing at the second half of it.

    Looking only forward failed those: two of three correct citations in one run
    were reported as unsupported. So the entry is resolved in BOTH directions —
    back to the bullet or lettered marker that starts it, forward to the next
    one — because that span is exactly the text the quote was taken from.
    """
    from .document_index import parse_reference, resolve_reference

    parsed = parse_reference(ref)
    if not parsed:
        return [], ""

    _doc, page_number, start, end = parsed
    page = next((p for p in pages if p.number == page_number), None)
    if page is None:
        return [], ""

    by_number = {line.line: line for line in page.lines}

    # Back to the line that starts this entry.
    first = start
    for candidate in range(start, max(0, start - WRAP_LOOKAHEAD) - 1, -1):
        line = by_number.get(candidate)
        if line is None:
            break
        first = candidate
        if _ENTRY_START.match(line.text):
            break

    # Forward to the line before the next entry starts.
    last = end
    for candidate in range(end + 1, end + WRAP_LOOKAHEAD + 1):
        line = by_number.get(candidate)
        if line is None or not line.text.strip():
            break
        if _ENTRY_START.match(line.text):
            break
        last = candidate

    if first == start and last == end:
        return [line.text for line in resolve_reference(pages, ref)], ""

    span = f"{page_number}:{first}-{last}"
    return [by_number[n].text for n in range(first, last + 1) if n in by_number], span


def _deduplicate(citations: list[Citation]) -> list[Citation]:
    """One entry per distinct claim.

    Notes carry `modules` and a mirrored `hour_modules` for the older readers,
    so the walk found every citation twice and reported fourteen where there
    are seven — which makes the verified fraction look like a measurement of
    something other than what it is.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Citation] = []
    for citation in citations:
        key = (citation.ref, citation.quote.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(citation)
    return unique


def verify(content: Any, design_text: str) -> CitationReport:
    """Resolve each citation against the design, and say which ones fail."""
    from .document_index import parse_pages, parse_reference, resolve_reference

    report = CitationReport(citations=_deduplicate(collect(content)))
    if not design_text or not design_text.strip():
        report.document_available = False
        for citation in report.citations:
            citation.reason = "The design document was not available to check against."
        return report

    pages = parse_pages(design_text)

    for citation in report.citations:
        if not citation.ref:
            citation.reason = "No page:line address, so it cannot be resolved."
            continue
        if not parse_reference(citation.ref):
            citation.reason = f"'{citation.ref}' is not a page:line address."
            continue

        lines = resolve_reference(pages, citation.ref)
        if not lines:
            citation.reason = (
                f"'{citation.ref}' does not exist in this document — the page or "
                "the line is beyond it."
            )
            continue

        citation.found_at = citation.ref
        citation.lines = [line.text for line in lines]

        if not citation.quote.strip():
            citation.verified = True
            citation.reason = "Address resolves; no quote was given to check."
            continue

        quoted = _terms(citation.quote)
        if not quoted:
            citation.verified = True
            continue

        overlap = len(quoted & _terms(" ".join(citation.lines))) / len(quoted)

        # The quote may continue onto the next line or two. Reading only the
        # cited line reports a wrapped bullet as unsupported.
        if overlap < MIN_OVERLAP:
            wrapped, span = _with_wrapped_continuation(pages, citation.ref)
            if span:
                combined = len(quoted & _terms(" ".join(wrapped))) / len(quoted)
                if combined > overlap:
                    overlap = combined
                    citation.lines = wrapped
                    citation.found_at = span

        if overlap >= MIN_OVERLAP:
            citation.verified = True
            citation.reason = (
                f"{round(overlap * 100)}% of the quote is at "
                f"{citation.found_at}"
                + (" (the line wraps)." if citation.found_at != citation.ref else ".")
            )
        else:
            citation.reason = (
                f"The quote is not at {citation.ref} — only {round(overlap * 100)}% "
                "of it appears there, or on the lines it wraps onto. The claim it "
                "supports is unsupported."
            )

    if report.citations and report.verified < len(report.citations):
        logger.warning(
            "%d of %d citation(s) did not resolve.",
            len(report.citations) - report.verified, len(report.citations),
        )
    return report



# ── Page reconciliation ─────────────────────────────────────────────────────

@dataclass(slots=True)
class PageReconciliation:
    """Whether a strand's pages and its sub-strands' pages agree.

    A strand occupies a span of the design — say pages 202 to 211 — and its
    sub-strands divide that span between them: three pages for the first, four
    for the second, and so on. When a sub-strand cites a page outside its
    strand's span, or two sub-strands claim the same page, or a page in the
    span is claimed by nobody, the citations are pointing somewhere other than
    where the content came from. Each of those is checkable arithmetic, and
    each is invisible one citation at a time.
    """

    strand: str = ""
    strand_pages: list[int] = field(default_factory=list)
    covered: list[int] = field(default_factory=list)
    uncovered: list[int] = field(default_factory=list)
    outside: list[dict[str, Any]] = field(default_factory=list)
    overlapping: list[dict[str, Any]] = field(default_factory=list)
    per_sub_strand: dict[str, list[int]] = field(default_factory=dict)

    @property
    def reconciles(self) -> bool:
        return not (self.uncovered or self.outside or self.overlapping)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strand": self.strand,
            "reconciles": self.reconciles,
            "strand_pages": self.strand_pages,
            "covered": self.covered,
            "uncovered": self.uncovered,
            "outside": self.outside,
            "overlapping": self.overlapping,
            "per_sub_strand": self.per_sub_strand,
        }


def _page_span(pages: list[int]) -> list[int]:
    if not pages:
        return []
    return list(range(min(pages), max(pages) + 1))


def reconcile_pages(
    strand: str,
    strand_pages: list[int],
    sub_strand_pages: dict[str, list[int]],
) -> PageReconciliation:
    """Check a strand's page span against how its sub-strands divide it."""
    report = PageReconciliation(
        strand=strand,
        strand_pages=sorted(set(int(p) for p in strand_pages if isinstance(p, int))),
        per_sub_strand={
            name: sorted(set(int(p) for p in pages if isinstance(p, int)))
            for name, pages in sub_strand_pages.items()
        },
    )

    span = set(_page_span(report.strand_pages))
    claimed: dict[int, list[str]] = {}
    for name, pages in report.per_sub_strand.items():
        for page in pages:
            claimed.setdefault(page, []).append(name)

    report.covered = sorted(claimed)

    for page, owners in sorted(claimed.items()):
        if span and page not in span:
            report.outside.append({
                "page": page, "sub_strands": owners,
                "why": f"outside the strand's span "
                       f"{min(span)}–{max(span)}" if span else "no strand span known",
            })
        if len(owners) > 1:
            report.overlapping.append({"page": page, "sub_strands": owners})

    # A page inside the strand that no sub-strand claims is content nothing
    # cites — either a sub-strand is missing, or one is citing the wrong pages.
    report.uncovered = sorted(span - set(claimed)) if span else []
    return report


def reconcile_from_db(grade: str, subject: str, strand: str) -> PageReconciliation:
    """Reconcile one strand's stored sub-strands against its own page span."""
    from ..infra.db import fetch_all

    rows = fetch_all(
        """
        SELECT sub_strand_name, source_pages FROM curriculum_substrands
        WHERE (grade = :grade OR grade = :alt_grade)
          AND LOWER(subject) = LOWER(:subject)
          AND LOWER(strand_name) = LOWER(:strand)
        ORDER BY sub_strand_id
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""),
         "subject": subject, "strand": strand},
    ) or []

    per_sub: dict[str, list[int]] = {}
    everything: list[int] = []
    for row in rows:
        pages = [p for p in (row.get("source_pages") or []) if isinstance(p, int)]
        per_sub[str(row.get("sub_strand_name") or "")] = pages
        everything += pages

    # Without a stored strand span, the sub-strands' own range is the best
    # available statement of where the strand sits — which still catches a
    # sub-strand citing a page far outside its siblings.
    return reconcile_pages(strand, everything, per_sub)

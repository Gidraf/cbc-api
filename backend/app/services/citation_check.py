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
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-citations")

# How much of a quote must appear at the cited lines. Extraction inserts and
# drops whitespace, and a design's own text wraps mid-phrase across columns, so
# an exact match would fail on citations that are perfectly good.
MIN_OVERLAP = 0.6


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
    import re

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


def verify(content: Any, design_text: str) -> CitationReport:
    """Resolve each citation against the design, and say which ones fail."""
    from .document_index import parse_pages, parse_reference, resolve_reference

    report = CitationReport(citations=collect(content))
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

        source = _terms(" ".join(citation.lines))
        quoted = _terms(citation.quote)
        if not quoted:
            citation.verified = True
            continue

        overlap = len(quoted & source) / len(quoted)
        if overlap >= MIN_OVERLAP:
            citation.verified = True
            citation.reason = f"{round(overlap * 100)}% of the quote is at those lines."
        else:
            citation.reason = (
                f"The quote is not at {citation.ref} — only {round(overlap * 100)}% "
                "of it appears there. The claim it supports is unsupported."
            )

    if report.citations and report.verified < len(report.citations):
        logger.warning(
            "%d of %d citation(s) did not resolve.",
            len(report.citations) - report.verified, len(report.citations),
        )
    return report

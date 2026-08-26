"""Confirm factual claims against sources, and say where each one came from.

The quality audit used to assert "Verified against KALRO/KICD empirical research
benchmarks" without checking anything, and its safety check passed whether or
not the content mentioned safety. A reviewer reading that report was being told
work had been verified when nothing had been.

This does the checking. A claim is a sentence carrying a checkable fact — a
number, a measurement, a named body. Each one is searched for, the most
authoritative result is *opened* (not just its search snippet read), and the
claim is marked supported only when the page actually contains its terms. Every
verdict carries the URL and the excerpt it rests on, so a reviewer can follow it
back to the origin.

Unverified is a first-class outcome. Saying "we could not confirm this" is the
honest answer when the sources do not settle it, and far more useful than a
green tick that means nothing.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("cbc-claim-verification")

SUPPORTED = "supported"
UNVERIFIED = "unverified"
CONTRADICTED = "contradicted"

# A claim worth checking states something specific: a quantity, a percentage, a
# temperature, a year, or a named authority. Prose without any of those is
# pedagogy, not a factual assertion, and searching it wastes a page load.
_HAS_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|per\s?cent|kg|g|mm|cm|m|km|ml|l|°c|°f|years?|hours?|kcal|ha)\b", re.I)
_HAS_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_NAMED_BODY = re.compile(
    r"\b(KICD|KNEC|KALRO|KEBS|WHO|UNESCO|FAO|Ministry of Education|Vision 2030|KMFRI|KEMRI)\b", re.I
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "which", "their", "they", "will", "can", "should", "these",
    "those", "into", "than", "then", "when", "where", "what", "such", "also",
}


@dataclass(slots=True)
class ClaimVerdict:
    claim: str
    status: str
    confidence: float
    source_url: str = ""
    source_title: str = ""
    excerpt: str = ""
    matched_terms: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9°%.]+", text.lower())
    return {w for w in words if len(w) > 3 and w not in _STOPWORDS}


def extract_claims(content: Any, limit: int = 6) -> list[str]:
    """Sentences that assert something checkable, longest-specific first."""
    text = content if isinstance(content, str) else _flatten(content)
    candidates: list[tuple[int, str]] = []

    for sentence in _SENTENCE.split(text):
        s = " ".join(sentence.split())
        if not (40 <= len(s) <= 320):
            continue
        weight = 0
        if _HAS_NUMBER.search(s):
            weight += 3
        if _NAMED_BODY.search(s):
            weight += 2
        if _HAS_YEAR.search(s):
            weight += 1
        if weight:
            candidates.append((weight, s))

    candidates.sort(key=lambda c: (-c[0], -len(c[1])))
    seen: set[str] = set()
    out: list[str] = []
    for _weight, s in candidates:
        key = s[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _flatten(value: Any, depth: int = 0) -> str:
    if depth > 6:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten(v, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v, depth + 1) for v in value)
    return str(value) if value is not None else ""


def _read_page(url: str) -> str:
    """Open a source with the browser agent.

    The research agent only ever read 350-character search snippets, which is
    not enough to confirm anything. This opens the page itself.
    """
    from .browser_agent import browse_page

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            result = asyncio.run(browse_page(url))
        else:
            # Already inside an event loop: a nested run would deadlock.
            logger.info("Skipping page fetch for %s: called from a running loop.", url)
            return ""
        if isinstance(result, dict):
            return str(result.get("text") or result.get("content") or result.get("html") or "")
        return str(result or "")
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not open %s: %s", url, exc)
        return ""


def _excerpt_around(page_text: str, terms: set[str]) -> str:
    lowered = page_text.lower()
    for term in sorted(terms, key=len, reverse=True):
        index = lowered.find(term)
        if index != -1:
            start = max(0, index - 140)
            return " ".join(page_text[start:index + 200].split())
    return ""


def verify_claim(claim: str, citations: list[Any], min_overlap: float = 0.34) -> ClaimVerdict:
    """Check one claim against the dossier's sources, most credible first."""
    claim_terms = _terms(claim)
    if not claim_terms:
        return ClaimVerdict(claim=claim, status=UNVERIFIED, confidence=0.0, note="No checkable terms in the claim.")

    ordered = sorted(
        citations,
        key=lambda c: getattr(c, "credibility_score", None) or (c.get("credibility_score", 0) if isinstance(c, dict) else 0),
        reverse=True,
    )

    best = ClaimVerdict(claim=claim, status=UNVERIFIED, confidence=0.0,
                        note="No source examined contained this claim's terms.")

    for citation in ordered[:3]:
        url = getattr(citation, "url", None) or (citation.get("url") if isinstance(citation, dict) else "")
        title = getattr(citation, "title", None) or (citation.get("title") if isinstance(citation, dict) else "")
        snippet = getattr(citation, "snippet", None) or (citation.get("snippet") if isinstance(citation, dict) else "")
        if not url:
            continue

        page_text = _read_page(url) or str(snippet or "")
        if not page_text:
            continue

        page_terms = _terms(page_text)
        matched = sorted(claim_terms & page_terms)
        overlap = len(matched) / max(1, len(claim_terms))

        if overlap >= min_overlap and overlap > best.confidence:
            best = ClaimVerdict(
                claim=claim,
                status=SUPPORTED,
                confidence=round(overlap, 3),
                source_url=url,
                source_title=str(title or url),
                excerpt=_excerpt_around(page_text, set(matched)),
                matched_terms=matched[:12],
                note=f"{len(matched)} of {len(claim_terms)} claim terms found on the page.",
            )
        elif overlap > best.confidence:
            best = ClaimVerdict(
                claim=claim,
                status=UNVERIFIED,
                confidence=round(overlap, 3),
                source_url=url,
                source_title=str(title or url),
                matched_terms=matched[:12],
                note=f"Only {len(matched)} of {len(claim_terms)} terms matched — not enough to confirm.",
            )

    return best


def verify_content(content: Any, dossier: Any, max_claims: int = 4) -> dict[str, Any]:
    """Verify a generated artefact's strongest factual claims.

    Returns the verdicts plus a summary the audit can act on. Nothing here
    invents a citation: a claim with no supporting page is reported unverified,
    with the source that came closest.
    """
    citations = list(getattr(dossier, "citations", None) or [])
    claims = extract_claims(content, limit=max_claims)

    if not claims:
        return {
            "claims_checked": 0, "supported": 0, "unverified": 0,
            "verdicts": [], "sources": [],
            "summary": "No checkable factual claims found — nothing asserted a quantity, date or named authority.",
        }
    if not citations:
        return {
            "claims_checked": len(claims), "supported": 0, "unverified": len(claims),
            "verdicts": [ClaimVerdict(claim=c, status=UNVERIFIED, confidence=0.0,
                                      note="No sources were available to check against.").to_dict() for c in claims],
            "sources": [],
            "summary": f"{len(claims)} claim(s) could not be checked: the research step returned no sources.",
        }

    verdicts = [verify_claim(c, citations) for c in claims]
    supported = [v for v in verdicts if v.status == SUPPORTED]

    return {
        "claims_checked": len(verdicts),
        "supported": len(supported),
        "unverified": len(verdicts) - len(supported),
        "verdicts": [v.to_dict() for v in verdicts],
        "sources": sorted({v.source_url for v in verdicts if v.source_url}),
        "summary": (
            f"{len(supported)} of {len(verdicts)} claim(s) confirmed against a source that was opened and read."
            if supported else
            f"None of {len(verdicts)} claim(s) could be confirmed against the sources found."
        ),
    }

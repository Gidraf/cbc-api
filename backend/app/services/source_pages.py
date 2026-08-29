"""Find the pages a sub-strand is actually on, instead of guessing them.

The model was returning `source_pages` alongside everything else, and what it
returned was a pattern rather than a fact: the page the sub-strand appears on,
plus the next one. Checked against a PP1 CRE design, three of twelve were
wrong — 1.2 claimed page 206, which is 1.3; 3.1 claimed 212, which is 3.2; 5.1
claimed 219, which is 5.2 — and most omitted the rubric page entirely.

That matters more here than it would elsewhere. Page addresses are this
system's citation substrate: `citation_check` resolves `page:line` against the
design, notes cite by address, and a reviewer clicks the address to read the
original. A citation that resolves to the wrong page is worse than an absent
one, because it survives inspection.

The document knows the answer. This asks it.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import document_index

logger = logging.getLogger("cbc-source-pages")

# "1.1 Our God", "2.2 Bible Story: David and Goliath", "4.3 Sharing with Others"
def _heading_pattern(sub_id: str, name: str) -> re.Pattern[str]:
    parts = []
    if sub_id.strip():
        parts.append(re.escape(sub_id.strip()))
    if name.strip():
        # The PDF breaks names across lines, so match the first few words
        # rather than the whole title.
        words = [w for w in re.findall(r"[A-Za-z']+", name) if len(w) > 2][:3]
        if words:
            parts.append(r"\s+".join(re.escape(w) for w in words))
    if not parts:
        return re.compile(r"(?!x)x")
    return re.compile(r"|".join(parts), re.IGNORECASE)


def _summary_page(pages: list[document_index.Page]) -> int:
    """The 'Summary of Strands and Sub-Strands' table, which lists them all.

    Every sub-strand appears there, so it is a true source page for all of
    them — but on its own it says nothing about where the detail is.
    """
    for page in pages:
        head = " ".join(l.text for l in page.lines[:10]).lower()
        if "summary of strands" in head:
            return page.number
    return 0


def resolve(
    design_text: str,
    sub_strands: list[dict[str, Any]],
) -> dict[str, list[int]]:
    """The pages each sub-strand's detail and rubric actually occupy.

    A sub-strand's detail page is the one whose table row opens it; its content
    runs to the next sub-strand's opening. Its rubric page is the next rubric
    table after that, since KICD prints one rubric table per strand covering
    the sub-strands before it.
    """
    from .rubric_tables import rubric_pages

    if not design_text.strip() or not sub_strands:
        return {}

    pages = document_index.parse_pages(design_text)
    if not pages:
        return {}

    summary = _summary_page(pages)
    rubric_page_numbers = [p.number for p in rubric_pages(pages)]

    # Where each sub-strand opens. A heading match in the FIRST few lines of a
    # page is an opening; the same words later on the page are a cross
    # reference, and treating those as openings is how a sub-strand acquires
    # four source pages.
    openings: dict[str, int] = {}
    for sub in sub_strands:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        sub_id = str(sub.get("sub_strand_id") or "")
        if not name:
            continue
        pattern = _heading_pattern(sub_id, name)
        best_page, best_hits = 0, 0
        for page in pages:
            if page.number == summary:
                continue
            head = "\n".join(l.text for l in page.lines[:30])
            hits = len(pattern.findall(head))
            if hits > best_hits:
                best_page, best_hits = page.number, hits
        if best_page:
            openings[name] = best_page

    resolved: dict[str, list[int]] = {}
    ordered = sorted(openings.items(), key=lambda kv: kv[1])

    for index, (name, opening) in enumerate(ordered):
        # Runs until the next sub-strand opens, so a sub-strand whose block
        # spills onto a continuation page keeps that page.
        next_opening = ordered[index + 1][1] if index + 1 < len(ordered) else 10_000
        span = [
            p.number for p in pages
            if opening <= p.number < next_opening
            and p.number not in rubric_page_numbers
        ]
        # The rubric that measures it: the first rubric table printed after it.
        rubric = next((n for n in rubric_page_numbers if n >= opening), 0)

        found = sorted({*span, *( [rubric] if rubric else [] ), *([summary] if summary else [])})
        resolved[name] = found

    missing = [
        str(s.get("sub_strand_name") or s.get("name") or "")
        for s in sub_strands
        if isinstance(s, dict) and str(s.get("sub_strand_name") or s.get("name") or "") not in resolved
    ]
    if missing:
        logger.warning("Could not locate page(s) for: %s", ", ".join(m for m in missing if m))

    return resolved


def apply(design_text: str, sub_strands: list[dict[str, Any]]) -> int:
    """Overwrite guessed page numbers with resolved ones. Returns how many."""
    resolved = resolve(design_text, sub_strands)
    changed = 0
    for sub in sub_strands or []:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        pages = resolved.get(name)
        if not pages:
            # Leave whatever was there rather than blanking it: an unresolved
            # sub-strand is a gap in this resolver, not proof the model's guess
            # was wrong.
            continue
        if sub.get("source_pages") != pages:
            sub["source_pages"] = pages
            changed += 1
    return changed

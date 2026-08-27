"""Split a curriculum design that holds several learning areas into its parts.

KICD publishes Pre-Primary as ONE document containing seven learning areas —
Language, Mathematical, Creative and Environmental Activities, plus Christian,
Hindu and Islamic Religious Education. Ingesting it as a single design filed all
seven under the cover title "Pre-Primary 1", so a request to break down a strand
of Language Activities was answered with the strands of Christian Religious
Education, and every learning area's sub-strands overwrote the last.

A learning area announces itself the same way in every KICD design: a banner
page carrying its name and almost nothing else, listed in the document's own
table of contents. That is what this reads. Front matter announces itself
differently — "NATIONAL GOALS OF EDUCATION" is a heading with its text directly
beneath it, never a page of its own — which is what separates the two without a
hard-coded list of titles per grade.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .document_index import Page, parse_pages

logger = logging.getLogger("cbc-design-sections")

# Front and back matter that can look like a learning area in a contents list.
_NOT_A_LEARNING_AREA = (
    "foreword", "preface", "acknowledgement", "acknowledgment",
    "table of contents", "contents", "national goals of education",
    "lesson allocation", "level learning outcomes", "learning outcomes for",
    "suggested assessment methods", "assessment methods", "appendix",
    "glossary", "bibliography", "references", "introduction", "rationale",
    "csl at", "community service learning", "general introduction",
    "time allocation", "subject list",
)

# A banner page is short by definition — the title, maybe a page number.
_MAX_BANNER_CHARS = 120
_MIN_TITLE_CHARS = 6
_MIN_SECTIONS = 2

_TOC_ENTRY = re.compile(r"^(?P<title>[A-Z][A-Z&'()/,.\- ]{4,}?)\s*[.\s]{2,}\s*(?P<page>\d{1,4})\s*$")
_PAGE_ECHO = re.compile(r"^\W*page\s*\d*\s*(?:/|of)?\s*\d*\W*$", re.IGNORECASE)


@dataclass(slots=True)
class DesignSection:
    """One learning area's slice of a combined design document."""

    learning_area: str
    start_page: int
    end_page: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "learning_area": self.learning_area,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "chars": len(self.text),
        }


def _normalise(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _is_front_matter(title: str) -> bool:
    flat = _normalise(title)
    return any(flat.startswith(_normalise(bad)) or _normalise(bad) in flat for bad in _NOT_A_LEARNING_AREA)


def _page_body(page: Page) -> list[str]:
    """The page's real content, with page-number echoes dropped."""
    return [
        line.text.strip()
        for line in page.lines
        if line.text.strip() and not _PAGE_ECHO.match(line.text.strip())
    ]


def _banner_title(page: Page) -> str:
    """The learning area this page announces, or '' if it announces nothing.

    A banner page carries a title and essentially nothing else. That is the
    signal; a heading followed by its own body text is not one.
    """
    body = _page_body(page)
    if not body:
        return ""
    joined = " ".join(body)
    if len(joined) > _MAX_BANNER_CHARS:
        return ""

    # Titles wrap across lines on some covers; take the upper-case run.
    parts = [b for b in body if b.upper() == b and len(b) >= _MIN_TITLE_CHARS]
    if not parts:
        return ""
    title = " ".join(parts).strip()
    if len(title) < _MIN_TITLE_CHARS or _is_front_matter(title):
        return ""
    if not re.search(r"[A-Z]{3,}", title):
        return ""
    return re.sub(r"\s+", " ", title)


def _contents_titles(pages: list[Page]) -> list[str]:
    """Learning-area names as the document's own contents page lists them."""
    titles: list[str] = []
    for page in pages[:12]:
        body = _page_body(page)
        if not any("table of contents" in b.lower() or b.strip().lower() == "contents" for b in body):
            continue
        for line in body:
            match = _TOC_ENTRY.match(line)
            if not match:
                continue
            title = re.sub(r"\s+", " ", match.group("title")).strip(" .")
            if len(title) >= _MIN_TITLE_CHARS and not _is_front_matter(title):
                titles.append(title)
        break
    return titles



def _squash(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _matches_any(flat: str, listed: set[str]) -> bool:
    """Whether a banner title is one of the titles the contents page lists."""
    squashed = _squash(flat)
    for entry in listed:
        if flat == entry or flat in entry or entry in flat:
            return True
        other = _squash(entry)
        if squashed == other or squashed in other or other in squashed:
            return True
    return False


def canonical_area_name(title: str, published: list[str] | None = None) -> str:
    """Map a detected section title onto the grade's published learning-area name.

    Banner pages and contents pages disagree: the CRE banner reads "CHRISTIAN
    RELIGIOUS EDUCATION ACTIVITIES" while the catalogue and every other part of
    the system say "Christian Religious Education". Filing it under the banner's
    wording made a correctly-split learning area read as "not ingested", because
    nothing downstream recognised the name.
    """
    cleaned = re.sub(r"\s+", " ", str(title or "")).strip()
    if not cleaned or not published:
        return cleaned.title() if cleaned else cleaned

    flat = _squash(_normalise(cleaned))
    for name in published:
        if _squash(_normalise(name)) == flat:
            return name
    # "…Education Activities" vs "…Education": prefer the published wording.
    for name in published:
        other = _squash(_normalise(name))
        if flat.startswith(other) or other.startswith(flat):
            return name
    return cleaned.title()


def split_learning_areas(text: str, published: list[str] | None = None) -> list[DesignSection]:
    """The learning areas a combined design contains, in document order.

    Returns [] when the document holds a single learning area — the ordinary
    case — so callers can treat "not combined" as the default.
    """
    pages = parse_pages(text)
    if len(pages) < 4:
        return []

    listed = {_normalise(t) for t in _contents_titles(pages)}

    banners: list[tuple[int, str, int]] = []  # (page number, title, page index)
    for index, page in enumerate(pages):
        title = _banner_title(page)
        if not title:
            continue
        flat = _normalise(title)
        # When the document lists its contents, trust that list: it is the
        # document's own statement of what it contains.
        #
        # Compare with spaces removed as well. The PP1 contents page prints
        # "MATHEMATICALACTIVITIES" and "CREATIVEACTIVITIES" with no space, while
        # the banner pages print them with one — so a space-sensitive match
        # silently dropped two of the seven learning areas.
        if listed and not _matches_any(flat, listed):
            continue
        if banners and _normalise(banners[-1][1]) == flat:
            continue  # the same banner repeated on a facing page
        banners.append((page.number, title, index))

    if len(banners) < _MIN_SECTIONS:
        return []

    # Back matter follows the last learning area — CSL notes, assessment
    # appendices. Without a terminator the final area absorbs all of it and its
    # sub-strands are extracted from an appendix that belongs to no subject.
    end_of_areas = len(pages)
    for index in range(banners[-1][2] + 1, len(pages)):
        body = _page_body(pages[index])
        if body and _is_front_matter(body[0]):
            end_of_areas = index
            break

    lines_by_index = [
        "\n".join(f"{p.number}:{line.line}  {line.text}" for line in p.lines) for p in pages
    ]

    sections: list[DesignSection] = []
    for position, (page_number, title, index) in enumerate(banners):
        stop = banners[position + 1][2] if position + 1 < len(banners) else end_of_areas
        body = "\n".join(
            f"[PAGE {pages[i].number}]\n{lines_by_index[i]}" for i in range(index, stop)
        )
        sections.append(
            DesignSection(
                learning_area=canonical_area_name(title, published),
                start_page=page_number,
                end_page=pages[stop - 1].number,
                text=body,
            )
        )

    logger.info(
        "Design splits into %d learning areas: %s",
        len(sections), ", ".join(s.learning_area for s in sections),
    )
    return sections


def is_combined_design(text: str, published: list[str] | None = None) -> bool:
    return len(split_learning_areas(text, published)) >= _MIN_SECTIONS

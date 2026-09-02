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


# Spelled out on the cover, abbreviated in the catalogue. Only where the two
# genuinely name one thing — this is a dictionary, not a similarity test.
_ABBREVIATED: dict[str, str] = {
    "christianreligiouseducation": "cre",
    "christianreligiousactivities": "cre",
    "hindureligiouseducation": "hre",
    "hindureligiousactivities": "hre",
    "islamicreligiouseducation": "ire",
    "islamicreligiousactivities": "ire",
    "kenyasignlanguage": "ksl",
    "physicalandhealtheducation": "phe",
}


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

    # The catalogue publishes the religious-education areas as abbreviations
    # and the covers spell them out, so nothing above can connect the two: a
    # Grade 6 HRE design's cover reads "HINDU RELIGIOUS EDUCATION" and the
    # published name is "HRE". They share no prefix and are not equal, so the
    # document could not be recognised as its own learning area.
    expanded = _ABBREVIATED.get(flat, "")
    if expanded:
        for name in published:
            if _squash(_normalise(name)) == expanded:
                return name
    return cleaned.title()



def _heading_like(line: str, squashed_name: str) -> bool:
    """Whether a line is this learning area's heading rather than a mention of it.

    "MATHEMATICAL ACTIVITIES" alone on a line is a heading. The same words
    inside "...relate to shapes in Mathematical Activities." is a cross-reference,
    and slicing the document there would put half of one area inside another.
    """
    stripped = line.strip().strip(".:-")
    if not stripped or len(stripped) > 60:
        return False
    return _squash(_normalise(stripped)) == squashed_name


def _recover_missing_areas(
    pages: list[Page],
    banners: list[tuple[int, str, int]],
    published: list[str],
) -> list[tuple[int, str, int]]:
    """Locate any published learning area the banner scan did not find."""
    found = {_squash(_normalise(canonical_area_name(t, published))) for _n, t, _i in banners}
    claimed = {index for _n, _t, index in banners}
    recovered: list[tuple[int, str, int]] = []

    for name in published:
        squashed = _squash(_normalise(name))
        if squashed in found:
            continue

        for index, page in enumerate(pages):
            if index in claimed:
                continue
            body = _page_body(page)
            if not body or _is_front_matter(body[0]):
                continue
            if any(_heading_like(line, squashed) for line in body):
                recovered.append((page.number, name, index))
                claimed.add(index)
                logger.info(
                    "Learning area '%s' had no banner page; recovered from its "
                    "heading on page %d.", name, page.number,
                )
                break
        else:
            logger.warning(
                "Learning area '%s' is published for this grade but appears "
                "nowhere in the document as a heading. It will be missing.", name,
            )

    if not recovered:
        return banners
    return sorted(banners + recovered, key=lambda entry: entry[2])


def missing_learning_areas(sections: list[DesignSection], published: list[str]) -> list[str]:
    """Published areas the split did not produce. Empty is the correct answer."""
    got = {_squash(_normalise(s.learning_area)) for s in sections}
    return [n for n in published if _squash(_normalise(n)) not in got]


def _cover_area(pages: list[Page], published: list[str]) -> str:
    """The learning area this document's own cover declares, if any.

    The cover is the document stating what it is. Everything else — a banner
    heuristic, a search for published names — is inference about it.
    """
    if not pages or not published:
        return ""
    lines = [l for l in _page_body(pages[0]) if l.strip()][:20]
    for line in lines:
        name = canonical_area_name(line, published)
        if name and _squash(_normalise(name)) in {
            _squash(_normalise(p)) for p in published
        }:
            return name
    return ""


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

    # A banner page is how a learning area USUALLY announces itself, but not
    # always: extraction merges page fragments, so a banner can arrive carrying
    # a running header, a stray page number, or its title split across lines in
    # a way the heuristic misses. When the catalogue says seven areas exist and
    # only four were found, the other three are in the document somewhere — they
    # simply did not look like banners. Go and find them by name.
    if published:
        banners = _recover_missing_areas(pages, banners, published)

    if len(banners) < _MIN_SECTIONS:
        return []

    # A document whose cover says ARABIC is an Arabic document.
    #
    # `_recover_missing_areas` searches the pages for every published name, and
    # a single-subject design names other areas all over itself: "Link to other
    # Learning Areas: Kiswahili", the lesson-allocation table listing all nine.
    # A Grade 6 ARABIC design was split into Kiswahili and Social Studies, and
    # Arabic — the subject on its own cover — was reported as "not found in the
    # document". The whole design was then filed under two learning areas it is
    # not, which is worse than not splitting at all.
    #
    # So the cover has the final say: if it declares an area and the split does
    # not contain it, the split is reading cross-references, not sections.
    declared = _cover_area(pages, published or [])
    if declared:
        squashed = _squash(_normalise(declared))
        if not any(
            _squash(_normalise(canonical_area_name(title, published))) == squashed
            for _n, title, _i in banners
        ):
            logger.info(
                "Cover declares '%s' and the split found %s instead; treating it "
                "as a single-area design.",
                declared, ", ".join(t for _n, t, _i in banners)[:120],
            )
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

def diagnose(text: str, published: list[str] | None = None) -> dict[str, Any]:
    """Explain what the splitter saw, and why it rejected what it rejected.

    Built because three learning areas kept coming back "(not ingested)" with
    no way to tell whether the splitter never saw them, saw them and rejected
    them, or found them and the ingest failed afterwards. Guessing at that from
    a dropdown took several rounds; this answers it in one call.
    """
    pages = parse_pages(text)
    listed = _contents_titles(pages)
    listed_norm = {_normalise(t) for t in listed}

    rejected: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    for index, page in enumerate(pages):
        body = _page_body(page)
        if not body:
            continue
        joined = " ".join(body)
        title = _banner_title(page)

        if title:
            flat = _normalise(title)
            if listed_norm and not _matches_any(flat, listed_norm):
                rejected.append({
                    "page": page.number, "text": joined[:100],
                    "reason": "title is not in the document's table of contents",
                })
            else:
                accepted.append({"page": page.number, "title": title})
            continue

        # Why was this page not a banner? Only report pages that look like they
        # were trying to be one, or the list is every page in the document.
        upper_runs = [b for b in body if b.upper() == b and len(b) >= _MIN_TITLE_CHARS]
        if not upper_runs:
            continue
        candidate = " ".join(upper_runs)
        if _is_front_matter(candidate):
            reason = "recognised as front or back matter"
        elif len(joined) > _MAX_BANNER_CHARS:
            reason = f"page carries {len(joined)} characters; a banner page must be under {_MAX_BANNER_CHARS}"
        else:
            reason = "no upper-case title of sufficient length"
        rejected.append({"page": page.number, "text": joined[:100], "reason": reason})

    sections = split_learning_areas(text, published)
    absent = missing_learning_areas(sections, published) if published else []

    # For anything still missing, say where its name does appear.
    traces: dict[str, list[int]] = {}
    for name in absent:
        squashed = _squash(_normalise(name))
        hits = [
            page.number for page in pages
            if any(_heading_like(line, squashed) for line in _page_body(page))
        ]
        traces[name] = hits[:5]

    return {
        "page_count": len(pages),
        "contents_page_titles": listed,
        "banner_pages_accepted": accepted,
        "banner_pages_rejected": rejected[:40],
        "sections": [s.to_dict() for s in sections],
        "expected": list(published or []),
        "missing": absent,
        "missing_appears_as_heading_on_pages": traces,
    }

"""Address a curriculum design by page and line, the way a verse is cited.

Generated content can say what it claims but not where the claim came from. If
every line of the source has a stable address — `GRADE-4-MATH 12:7` for page 12,
line 7 — then a sub-strand, a learning outcome or a question can cite the exact
lines it was drawn from, and a reviewer can open that page and read them.

The extractor already writes page markers into the text it captures from Drive
("PAGE 12 OF 76"), so pages are real rather than an arbitrary chunking. A
document without markers is still addressable: it becomes one page, and lines
are numbered from the top.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

# "📄 PAGE 12 OF 76", "PAGE 12 OF 76", "Page 12 of 76"
_PAGE_MARKER = re.compile(r"^\W*page\s+(\d{1,4})\s+of\s+(\d{1,4})\W*$", re.IGNORECASE)

# "[PAGE 12]" — what this module's own renderers emit when they write a page
# back out. A slice of a design (one learning area, one chunk) is re-read by
# the next stage, so rendering and parsing have to be inverses: without this a
# 90-page section re-parses as a single page numbered 1, which both destroys
# its citations and defeats chunking, since one page is never split.
# Deliberately strict — only the bracketed form, which prose never contains.
_RENDERED_PAGE = re.compile(r"^\[PAGE\s+(\d{1,4})\]$")

# "12:7  " — the line address those renderers prefix to each line. Stripped on
# re-parse so a second render does not stack a second address on top. Only when
# the page it names is the page being read, so a scripture reference at the
# start of a line ("3:16  For God so loved…") is left alone.
_RENDERED_ADDRESS = re.compile(r"^(\d{1,4}):\d{1,5}\s\s")

_RULE = re.compile(r"^[=\-_]{8,}$")
_REFERENCE = re.compile(r"^\s*(?:(?P<doc>[A-Z0-9][A-Z0-9\-]*)\s+)?(?P<page>\d{1,4}):(?P<line>\d{1,4})(?:\s*-\s*(?P<end>\d{1,4}))?\s*$")

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
    "have", "has", "which", "their", "they", "will", "can", "should", "these",
}


@dataclass(slots=True)
class Line:
    page: int
    line: int
    text: str

    @property
    def ref(self) -> str:
        return f"{self.page}:{self.line}"

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "line": self.line, "ref": self.ref, "text": self.text}


@dataclass(slots=True)
class Page:
    number: int
    lines: list[Line] = field(default_factory=list)

    @property
    def heading(self) -> str:
        """The first substantial line, used as the page's topic in a listing."""
        for line in self.lines:
            stripped = line.text.strip()
            if len(stripped) >= 12 and not _PAGE_MARKER.match(stripped):
                return stripped[:90]
        return f"Page {self.number}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.number,
            "heading": self.heading,
            "line_count": len(self.lines),
            "lines": [l.to_dict() for l in self.lines],
        }


def document_code(grade: str, subject: str) -> str:
    """A short, stable prefix so a reference names its document."""
    def clean(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", (value or "").strip()).strip("-").upper()

    parts = [p for p in (clean(grade), clean(subject)) if p]
    return "-".join(parts)[:40] or "DOC"


def parse_pages(text: str) -> list[Page]:
    """Split a captured document into pages of numbered lines.

    Page markers and the rules around them are structural, not content, so they
    are not given line numbers — otherwise every reference would drift by the
    number of separators above it.
    """
    if not text:
        return []

    pages: list[Page] = []
    current = Page(number=1)
    line_no = 0

    for raw in text.split("\n"):
        stripped = raw.strip()

        marker = _PAGE_MARKER.match(stripped) or _RENDERED_PAGE.match(stripped)
        if marker:
            page_number = int(marker.group(1))
            if current.lines:
                pages.append(current)
            elif pages and pages[-1].number == page_number:
                # A marker repeated immediately (the extractor emits it twice).
                current = pages.pop()
                line_no = len(current.lines)
                continue
            current = Page(number=page_number)
            line_no = 0
            continue

        if _RULE.match(stripped) or not stripped:
            continue

        address = _RENDERED_ADDRESS.match(stripped)
        if address and int(address.group(1)) == current.number:
            stripped = stripped[address.end():]
            if not stripped:
                continue

        line_no += 1
        current.lines.append(Line(page=current.number, line=line_no, text=stripped))

    if current.lines:
        pages.append(current)

    # Merge pages the extractor emitted more than once, keeping reading order.
    merged: dict[int, Page] = {}
    for page in pages:
        if page.number in merged:
            existing = merged[page.number]
            for line in page.lines:
                existing.lines.append(Line(page=page.number, line=len(existing.lines) + 1, text=line.text))
        else:
            merged[page.number] = page
    return [merged[n] for n in sorted(merged)]


def iter_lines(pages: Iterable[Page]) -> list[Line]:
    return [line for page in pages for line in page.lines]


def parse_reference(ref: str) -> tuple[str, int, int, int] | None:
    """Read "GRADE-4-MATH 12:7" or "12:7-9" into its parts."""
    match = _REFERENCE.match(ref or "")
    if not match:
        return None
    page = int(match.group("page"))
    start = int(match.group("line"))
    end = int(match.group("end") or start)
    return (match.group("doc") or "", page, start, max(start, end))


def resolve_reference(pages: list[Page], ref: str) -> list[Line]:
    """The lines a reference points at, so a citation can be read back."""
    parsed = parse_reference(ref)
    if not parsed:
        return []
    _doc, page_number, start, end = parsed
    page = next((p for p in pages if p.number == page_number), None)
    if not page:
        return []
    return [l for l in page.lines if start <= l.line <= end]


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 3 and w not in _STOPWORDS}


def find_reference(pages: list[Page], quote: str, min_overlap: float = 0.6) -> dict[str, Any] | None:
    """Locate a quote in the document and return its address.

    Exact matches win. Failing that, the line sharing the most terms is
    returned with its score, so a paraphrase can still be traced — but the
    caller can see it was not verbatim.
    """
    needle = " ".join((quote or "").split())
    if not needle:
        return None

    lowered = needle.lower()
    for line in iter_lines(pages):
        if lowered in line.text.lower():
            return {**line.to_dict(), "match": "exact", "score": 1.0}

    wanted = _terms(needle)
    if not wanted:
        return None

    best: tuple[float, Line] | None = None
    for line in iter_lines(pages):
        overlap = len(wanted & _terms(line.text)) / len(wanted)
        if best is None or overlap > best[0]:
            best = (overlap, line)

    if best and best[0] >= min_overlap:
        return {**best[1].to_dict(), "match": "partial", "score": round(best[0], 3)}
    return None


def search(pages: list[Page], query: str, limit: int = 40) -> list[dict[str, Any]]:
    """Every line containing the query, with its address."""
    needle = (query or "").strip().lower()
    if not needle:
        return []
    return [l.to_dict() for l in iter_lines(pages) if needle in l.text.lower()][:limit]


def build_index(text: str, grade: str = "", subject: str = "") -> dict[str, Any]:
    pages = parse_pages(text)
    lines = iter_lines(pages)
    return {
        "code": document_code(grade, subject),
        "page_count": len(pages),
        "line_count": len(lines),
        "char_count": len(text or ""),
        "pages": [{"page": p.number, "heading": p.heading, "line_count": len(p.lines)} for p in pages],
    }

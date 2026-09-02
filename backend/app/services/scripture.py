"""Which scripture references are real, and which are a page number.

The fabrication check looked for "a capitalised word, then digits:digits" —
which is a Bible reference, and is also EXACTLY the `page:line` format this
system cites the KICD design with. So a PP1 design produced a list of the
"scripture it carries" that began:

    2 Bible 209:10 · Activities 219:12 · Approaching 217:9 · Creation 203:10
    Learning 203:4 · Page 199:2 · Portfolio 221:34 · Wallcharts 221:22

Around 170 entries, of which a dozen were scripture. Everything downstream then
compared against that list: a guide could cite almost any book and chapter and
find a "match", so the check that exists to catch an invented verse being read
aloud to a class caught nothing.

The fix is to know the books. There are sixty-six of them, they do not change,
and a name that is not one of them is not scripture however it is punctuated.

WHAT THIS DOES NOT CHECK: whether the verse exists within its chapter. Chapter
counts per book are fixed and known; verse counts per chapter are 1,189 numbers
this module does not have, and inventing them would produce confident findings
about real verses — which is worse than not checking, because a reviewer would
believe them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Chapters per book, Protestant canon — the Good News Bible and The Children's
# Bible, which are the two the KICD designs name.
CHAPTERS: dict[str, int] = {
    "Genesis": 50, "Exodus": 40, "Leviticus": 27, "Numbers": 36,
    "Deuteronomy": 34, "Joshua": 24, "Judges": 21, "Ruth": 4,
    "1 Samuel": 31, "2 Samuel": 24, "1 Kings": 22, "2 Kings": 25,
    "1 Chronicles": 29, "2 Chronicles": 36, "Ezra": 10, "Nehemiah": 13,
    "Esther": 10, "Job": 42, "Psalms": 150, "Proverbs": 31,
    "Ecclesiastes": 12, "Song of Solomon": 8, "Isaiah": 66, "Jeremiah": 52,
    "Lamentations": 5, "Ezekiel": 48, "Daniel": 12, "Hosea": 14, "Joel": 3,
    "Amos": 9, "Obadiah": 1, "Jonah": 4, "Micah": 7, "Nahum": 3,
    "Habakkuk": 3, "Zephaniah": 3, "Haggai": 2, "Zechariah": 14, "Malachi": 4,
    "Matthew": 28, "Mark": 16, "Luke": 24, "John": 21, "Acts": 28,
    "Romans": 16, "1 Corinthians": 16, "2 Corinthians": 13, "Galatians": 6,
    "Ephesians": 6, "Philippians": 4, "Colossians": 4,
    "1 Thessalonians": 5, "2 Thessalonians": 3, "1 Timothy": 6,
    "2 Timothy": 4, "Titus": 3, "Philemon": 1, "Hebrews": 13, "James": 5,
    "1 Peter": 5, "2 Peter": 3, "1 John": 5, "2 John": 1, "3 John": 1,
    "Jude": 1, "Revelation": 22,
}

# How the designs and the models actually write them. "Psalm" singular is the
# commonest, and a missing space after the number ("1Samuel 17:41") is how the
# KICD PDFs render it.
_ALIASES: dict[str, str] = {
    "psalm": "Psalms", "ps": "Psalms", "song of songs": "Song of Solomon",
    "canticles": "Song of Solomon", "gen": "Genesis", "ex": "Exodus",
    "exod": "Exodus", "lev": "Leviticus", "num": "Numbers", "deut": "Deuteronomy",
    "josh": "Joshua", "judg": "Judges", "prov": "Proverbs", "eccl": "Ecclesiastes",
    "isa": "Isaiah", "jer": "Jeremiah", "ezek": "Ezekiel", "dan": "Daniel",
    "matt": "Matthew", "mt": "Matthew", "mk": "Mark", "lk": "Luke",
    "jn": "John", "rom": "Romans", "cor": "1 Corinthians", "gal": "Galatians",
    "eph": "Ephesians", "phil": "Philippians", "col": "Colossians",
    "thess": "1 Thessalonians", "tim": "1 Timothy", "heb": "Hebrews",
    "jas": "James", "pet": "1 Peter", "rev": "Revelation",
    "revelations": "Revelation",
}

_LOOKUP: dict[str, str] = {name.lower(): name for name in CHAPTERS}
_LOOKUP.update(_ALIASES)
# "1Samuel", "2Kings" — no space, as the PDFs render them.
_LOOKUP.update({name.lower().replace(" ", ""): name for name in CHAPTERS})

# Found the other way round: locate `chapter:verse`, then look BACK for a book.
#
# Matching forwards let the preceding word be eaten — "and Jude 2:1" resolved
# its book as "and Jude", which is not a book, so a real reference with an
# impossible chapter was dropped instead of reported. Looking back tries the
# longest name first, so "1 Samuel" wins over "Samuel".
_CHAPTER_VERSE = re.compile(r"(\d{1,3}):(\d{1,3})([A-Za-z])?(?:\s*[-–]\s*(\d{1,3})[A-Za-z]?)?")
_TRAILING_BOOK = re.compile(r"((?:[1-3]\s*)?[A-Za-z][A-Za-z]*(?:\s+[A-Za-z]+){0,2})\s*$")

# The longest a book name gets: "Song of Solomon", "1 Thessalonians".
_MAX_BOOK_CHARS = 18

@dataclass(slots=True)
class Reference:
    book: str
    chapter: int
    verse: int
    end_verse: int = 0
    raw: str = ""

    def __str__(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse}"

    @property
    def valid_chapter(self) -> bool:
        return 1 <= self.chapter <= CHAPTERS.get(self.book, 0)


def canonical(book: str) -> str:
    """The book's proper name, or "" when it is not a book of the Bible."""
    key = re.sub(r"\s+", " ", str(book or "")).strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key]
    # "1 Samuel" written "1Samuel", or a trailing word caught by the pattern.
    tight = key.replace(" ", "")
    return _LOOKUP.get(tight, "")


def find(text: str) -> list[Reference]:
    """Every real scripture reference in a piece of text, in order.

    A page:line citation is not a reference here, however it is written —
    which is the whole point: `Page 199:2` and `Creation 203:10` are the
    design's own addresses, not verses.
    """
    out: list[Reference] = []
    for match in _CHAPTER_VERSE.finditer(text or ""):
        book = _book_before(text, match.start())
        if not book:
            continue
        out.append(Reference(
            book=book,
            chapter=int(match.group(1)),
            verse=int(match.group(2)),
            end_verse=int(match.group(4)) if match.group(4) else 0,
            raw=f"{book} {match.group(0).strip()}",
        ))
    return out


def _book_before(text: str, at: int) -> str:
    """The book name immediately before a chapter:verse, or ""."""
    lead = _TRAILING_BOOK.search(text[max(0, at - _MAX_BOOK_CHARS):at])
    if not lead:
        return ""
    words = lead.group(1).split()
    # Longest first: "1 Samuel" before "Samuel", "Song of Solomon" before
    # "Solomon" — a shorter suffix would otherwise win and mis-name the book.
    for start in range(len(words)):
        found = canonical(" ".join(words[start:]))
        if found:
            return found
    return ""


def suspect_books(text: str) -> list[str]:
    """References shaped like scripture that name no book of the Bible.

    "Hezekiah 3:1" is not caught by `find`, because there is no such book — and
    silently ignoring it is how an invented verse reaches a teacher who reads
    it aloud. Only where the chapter number is small enough to BE a chapter:
    the design's own addresses run to page 296, and no book has 296 chapters.
    """
    biggest = max(CHAPTERS.values())
    out: list[str] = []
    for match in _CHAPTER_VERSE.finditer(text or ""):
        if int(match.group(1)) > biggest:
            continue
        if _book_before(text, match.start()):
            continue
        lead = _TRAILING_BOOK.search(text[max(0, match.start() - _MAX_BOOK_CHARS):match.start()])
        name = (lead.group(1).split()[-1] if lead else "").strip()
        # A lower-case word before a colon-number is prose, not a citation.
        if name and name[0].isupper():
            out.append(f"{name} {match.group(0).strip()}")
    return sorted(set(out))


def impossible(reference: Reference) -> str:
    """Why this reference cannot exist, or "" if it might.

    Only what is decidable: the book, and whether the chapter is within it.
    Proverbs has 31 chapters, so "Proverbs 35:2" is wrong no matter which
    translation is open — and that is exactly the kind of reference a model
    produces and a teacher reads aloud before anybody checks.
    """
    total = CHAPTERS.get(reference.book, 0)
    if not total:
        return f"'{reference.book}' is not a book of the Bible."
    if reference.chapter < 1 or reference.chapter > total:
        return (f"{reference.book} has {total} chapter"
                f"{'' if total == 1 else 's'}; "
                f"'{reference}' names chapter {reference.chapter}.")
    if reference.end_verse and reference.end_verse < reference.verse:
        return f"'{reference.raw}' ends before it begins."
    return ""

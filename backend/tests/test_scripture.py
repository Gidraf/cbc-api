"""Which references are scripture, and which are a page number.

The fabrication check looked for "a capitalised word, then digits:digits" —
which is a Bible reference, and is also EXACTLY the `page:line` format this
system cites the KICD design with.
"""
from __future__ import annotations

from app.services import scripture

# Straight from a PP1 run's "scripture the design carries".
NOISE = ("Page 199:2 Creation 203:10 Learning 203:4 Wallcharts 221:22 "
         "Portfolio 221:34 Activities 219:12 Approaching 217:9 Bible 208:13")
REAL = ("Proverbs 22:6, 1Samuel 17:41-49, Mark 10:13-16, Matthew 22:39B, "
        "Exodus 20:3, Luke 2:4-7, Hebrews 13:16 A")


def test_a_page_line_address_is_not_scripture() -> None:
    assert scripture.find(NOISE) == []


def test_the_designs_real_references_are_all_found() -> None:
    found = {str(r) for r in scripture.find(REAL)}
    assert found == {
        "Proverbs 22:6", "1 Samuel 17:41", "Mark 10:13", "Matthew 22:39",
        "Exodus 20:3", "Luke 2:4", "Hebrews 13:16",
    }


def test_a_book_is_named_the_same_way_however_the_pdf_renders_it() -> None:
    """The designs render "1Samuel" with no space, and a reviewer comparing
    that against a guide's "1 Samuel" would call a real citation invented."""
    for spelling in ("1Samuel 17:41", "1 Samuel 17:41", "1  samuel 17:41"):
        assert str(scripture.find(spelling)[0]) == "1 Samuel 17:41", spelling
    assert str(scripture.find("Psalm 23:1")[0]) == "Psalms 23:1"
    assert str(scripture.find("Matt 5:9")[0]) == "Matthew 5:9"


def test_a_preceding_word_does_not_swallow_the_book() -> None:
    """"and Jude 2:1" resolved its book as "and Jude", which is not a book —
    so a real reference with an impossible chapter was dropped rather than
    reported."""
    found = scripture.find("The teacher reads and Jude 2:1 aloud.")
    assert [str(r) for r in found] == ["Jude 2:1"]


def test_a_chapter_that_cannot_exist_is_named_as_such() -> None:
    """Chapter counts are fixed and knowable, so this is decidable without any
    source: Proverbs has 31 chapters whichever translation is open."""
    checks = {
        "Proverbs 35:2": "Proverbs has 31 chapters",
        "Psalm 151:3": "Psalms has 150 chapters",
        "Jude 2:1": "Jude has 1 chapter;",
    }
    for text, expected in checks.items():
        reference = scripture.find(text)[0]
        assert expected in scripture.impossible(reference), text

    # And a real one is left alone.
    assert scripture.impossible(scripture.find("Mark 10:13-16")[0]) == ""


def test_verse_numbers_are_deliberately_not_checked() -> None:
    """Verse counts per chapter are 1,189 numbers this module does not have,
    and inventing them would produce confident findings about real verses."""
    source = (scripture.__doc__ or "") + (scripture.impossible.__doc__ or "")
    assert "verse counts" in source.lower()
    # A high verse in a real chapter is not reported, because it is not known.
    assert scripture.impossible(scripture.find("Psalm 119:176")[0]) == ""


def test_a_book_that_does_not_exist_is_reported() -> None:
    """Silently ignoring it is how an invented verse reaches a teacher who
    reads it aloud."""
    assert scripture.suspect_books("The teacher reads Hezekiah 3:1 aloud.") == ["Hezekiah 3:1"]
    # But the design's own addresses are not — no book has 296 chapters.
    assert scripture.suspect_books(NOISE) == []


def test_the_fabrication_check_reads_by_book_not_by_shape() -> None:
    from app.services import fabrication_check

    report = fabrication_check.check(
        {"body": "Read Proverbs 35:2 and Hezekiah 3:1 to the class."},
        design_text="Proverbs 22:6 is the basis. See Page 199:2 and Creation 203:10.",
    )
    kinds = {f.kind for f in report.findings}
    assert "impossible_scripture" in kinds
    assert "invented_scripture" in kinds
    # The design's own addresses never enter the list it compares against.
    assert report.scripture_in_design == ["Proverbs 22:6"]


def test_a_design_can_be_read_without_being_ingested() -> None:
    """Every ingest problem so far was diagnosed by inference: a count is wrong
    on one screen, so something upstream must be misreading a cover. Sixteen
    Grade 9 designs went to Grade 7 for want of a way to ask the parser what
    grade it thinks a document is."""
    from pathlib import Path

    from app.main import app

    assert "/api/v1/curriculum/factory/read-design" in [
        getattr(r, "path", "") for r in app.routes
    ]

    screen = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/ReadDesign.tsx")
        .read_text().split()
    )
    assert "Read a design without ingesting it" in screen
    assert "Would file under" in screen
    # The disagreement that caused this is called out explicitly.
    assert "They disagree — the cover wins" in screen
    # And an empty parse is not silently a success.
    assert "this would ingest as an empty design" in screen

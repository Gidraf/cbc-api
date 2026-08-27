"""KICD publishes Pre-Primary as one document holding seven learning areas.

Ingested whole, all seven were filed under the cover title "Pre-Primary 1" —
which is a level, not a learning area — so every area's sub-strands overwrote the
last, and a request to break down a strand of Language Activities was answered
with the strands of Christian Religious Education.
"""
from __future__ import annotations

from app.services.design_sections import is_combined_design, split_learning_areas

PP1_AREAS = [
    "LANGUAGE ACTIVITIES",
    "MATHEMATICAL ACTIVITIES",
    "CREATIVE ACTIVITIES",
    "ENVIRONMENTAL ACTIVITIES",
    "CHRISTIAN RELIGIOUS EDUCATION",
    "HINDU RELIGIOUS EDUCATION",
    "ISLAMIC RELIGIOUS EDUCATION",
]


def _page(number: int, body: str) -> str:
    rule = "=" * 80
    return f"{rule}\nPAGE {number} OF 296\n{rule}\n\n{body}\n"


def _pp1_document() -> str:
    pages = [
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nPRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1"),
        _page(3, "FOREWORD\nThe Government of Kenya is committed to ensuring that policy objectives for Education meet the aspirations of the Constitution."),
        _page(4, "PREFACE\nThe Ministry of Education nationally implemented the Competency Based Curriculum in 2019."),
    ]
    toc = ["TABLE OF CONTENTS",
           "FOREWORD ............................................................. iii",
           "PREFACE.............................................................. iv"]
    for offset, name in enumerate(PP1_AREAS):
        toc.append(f"{name}{'.' * max(4, 60 - len(name))}{offset * 30 + 1}")
    toc.append("CSL AT EARLY YEARS OF EDUCATION (PP1&2 AND GRADE 1-3).................280")
    toc.append("SUGGESTED ASSESSMENT METHODS, RESOURCES AND NON-FORMAL ACTIVITIES....283")
    pages.append(_page(6, "\n".join(toc)))
    pages.append(_page(7, "NATIONAL GOALS OF EDUCATION\n1. Foster nationalism, patriotism, and promote national unity\nThe people of Kenya belong to different communities."))
    pages.append(_page(9, "LESSON ALLOCATION FOR PRE-PRIMARY\nS/No Activity Area Number of Lessons per Week\n1. Language Activities 5"))

    number = 11
    for name in PP1_AREAS:
        pages.append(_page(number, name))                                   # banner page
        pages.append(_page(number + 1, f"Essence Statement\n{name.title()} builds on skills acquired at home."))
        pages.append(_page(number + 2, f"Summary of Strands and Sub Strands\n1.1 Listening and Speaking 1.1.1 Greetings and farewell 3"))
        number += 3

    pages.append(_page(290, "CSL AT EARLY YEARS OF EDUCATION (PP1&2 AND GRADE 1-3)\nAt this level the goal of the CSL activity is to provide linkages."))
    pages.append(_page(293, "SUGGESTED ASSESSMENT METHODS, RESOURCES AND NON-FORMAL ACTIVITIES\nStrand Sub-Strand Suggested Assessment Methods"))
    return "\n".join(pages)


def test_the_pre_primary_design_splits_into_its_seven_learning_areas() -> None:
    sections = split_learning_areas(_pp1_document())

    assert [s.learning_area for s in sections] == [a.title() for a in PP1_AREAS]
    assert is_combined_design(_pp1_document())


def test_front_matter_is_never_mistaken_for_a_learning_area() -> None:
    """A heading with its body beneath it is not a banner page."""
    names = " | ".join(s.learning_area.lower() for s in split_learning_areas(_pp1_document()))

    for matter in ("foreword", "preface", "national goals", "lesson allocation", "table of contents"):
        assert matter not in names


def test_back_matter_does_not_get_absorbed_into_the_last_learning_area() -> None:
    """Otherwise IRE's sub-strands are extracted from an assessment appendix."""
    sections = split_learning_areas(_pp1_document())
    last = sections[-1]

    assert last.learning_area == "Islamic Religious Education"
    assert "CSL AT EARLY YEARS" not in last.text
    assert "SUGGESTED ASSESSMENT METHODS" not in last.text


def test_each_area_gets_only_its_own_pages() -> None:
    sections = split_learning_areas(_pp1_document())
    language = next(s for s in sections if s.learning_area == "Language Activities")

    assert "Language Activities builds on skills" in language.text
    # The bug this exists to prevent: CRE content answering a Language request.
    assert "Christian Religious Education" not in language.text
    assert "Mathematical Activities" not in language.text

    starts = [s.start_page for s in sections]
    assert starts == sorted(starts), "sections must be in document order"
    for earlier, later in zip(sections, sections[1:]):
        assert earlier.end_page < later.start_page, "sections must not overlap"


def test_an_ordinary_single_subject_design_is_not_split() -> None:
    """Most designs are one learning area; splitting them would be the new bug."""
    doc = "\n".join([
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nGRADE 7 CURRICULUM DESIGN\nINTEGRATED SCIENCE"),
        _page(2, "Essence Statement\nIntegrated Science builds scientific literacy."),
        _page(3, "Summary of Strands and Sub Strands\n1.0 Mixtures, Elements and Compounds 1.1 Mixtures 12"),
        _page(4, "1.1 Mixtures\nBy the end of the sub strand the learner should be able to:"),
    ])

    assert split_learning_areas(doc) == []
    assert is_combined_design(doc) is False


def test_empty_and_tiny_documents_are_handled() -> None:
    assert split_learning_areas("") == []
    assert split_learning_areas("just some text") == []


def test_a_combined_document_is_ingested_once_per_learning_area(monkeypatch) -> None:
    """The split has to be wired in, not merely available."""
    from app.services import curriculum_extractor as extractor

    calls: list[tuple[str, int]] = []

    def fake_ingest_one(self, raw_text, payload_meta, learning_area=""):
        calls.append((learning_area, len(raw_text)))
        return {
            "status": "success",
            "subject": learning_area or "whole document",
            "design_id": f"cd_{learning_area.lower().replace(' ', '_')}",
            "substrand_count": 3,
        }

    monkeypatch.setattr(
        extractor.CurriculumExtractorService, "_ingest_one", fake_ingest_one, raising=True
    )

    result = extractor.curriculum_extractor.ingest_raw_curriculum(
        {"output": _pp1_document(), "file_id": "pp1-doc", "title": "PP1 Curriculum Design"}
    )

    assert [area for area, _ in calls] == [a.title() for a in PP1_AREAS]
    assert result["combined_design"] is True
    assert result["learning_area_count"] == 7
    # The top-level fields describe the first area, so existing callers still work.
    assert result["status"] == "success"
    assert result["subject"] == "Language Activities"
    # Each area gets only its own slice, never the whole 296-page document.
    whole = len(_pp1_document())
    assert all(size < whole / 2 for _area, size in calls)


def test_one_unreadable_learning_area_does_not_cost_the_others(monkeypatch) -> None:
    from app.services import curriculum_extractor as extractor

    def flaky(self, raw_text, payload_meta, learning_area=""):
        if learning_area == "Creative Activities":
            raise ValueError("unparseable section")
        return {"status": "success", "subject": learning_area,
                "design_id": "cd_x", "substrand_count": 1}

    monkeypatch.setattr(
        extractor.CurriculumExtractorService, "_ingest_one", flaky, raising=True
    )

    result = extractor.curriculum_extractor.ingest_raw_curriculum({"output": _pp1_document()})

    statuses = {a["subject"]: a["status"] for a in result["learning_areas"]}
    assert statuses["Creative Activities"] == "failed"
    assert statuses["Language Activities"] == "success"
    assert sum(1 for s in statuses.values() if s == "success") == 6


def test_an_ordinary_design_still_takes_the_single_ingest_path(monkeypatch) -> None:
    from app.services import curriculum_extractor as extractor

    seen: list[str] = []

    def fake_ingest_one(self, raw_text, payload_meta, learning_area=""):
        seen.append(learning_area)
        return {"status": "success", "subject": "Integrated Science", "design_id": "cd_is"}

    monkeypatch.setattr(
        extractor.CurriculumExtractorService, "_ingest_one", fake_ingest_one, raising=True
    )

    doc = "\n".join([
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nGRADE 7 CURRICULUM DESIGN\nINTEGRATED SCIENCE"),
        _page(2, "Essence Statement\nIntegrated Science builds scientific literacy."),
        _page(3, "Summary of Strands and Sub Strands\n1.0 Mixtures 1.1 Mixtures 12"),
        _page(4, "1.1 Mixtures\nBy the end of the sub strand the learner should be able to:"),
    ])
    result = extractor.curriculum_extractor.ingest_raw_curriculum({"output": doc})

    assert seen == [""], "a single-area design must not be split"
    assert "combined_design" not in result


def test_each_learning_area_is_saved_as_its_own_subject_under_the_same_grade() -> None:
    """The point of the split: seven subjects, one grade, no overwriting."""
    from app.services.curriculum_extractor import curriculum_extractor as X

    designs = []
    for section in split_learning_areas(_pp1_document()):
        designs.append(
            X._parse_curriculum_text(
                section.text,
                {"grade": "grade-pp1", "file_id": "pp1"},
                "dna_test",
                learning_area=section.learning_area,
            )
        )

    assert [d.subject for d in designs] == [a.title() for a in PP1_AREAS]
    # All seven sit at the same level, as they should.
    assert {d.grade for d in designs} == {"grade-pp1"}
    assert {d.level for d in designs} == {"Pre-Primary"}
    # The level must never be recorded as the subject.
    assert not any(d.subject.startswith("Pre-Primary") for d in designs)

    # Distinct ids and codes, or the rows collide on write and overwrite.
    assert len({d.design_id for d in designs}) == 7
    assert len({d.subject_code for d in designs}) == 7
    assert designs[0].subject_code == "LA"


def test_an_extraction_that_found_nothing_is_not_reported_as_complete() -> None:
    """KICD renders sub-strand tables as wrapped columns, so "1.1.1",
    "Greetings", "and Farewell", "(3 lessons)" arrive on four lines and match
    nothing. A learning area with zero sub-strands must not look like a
    finished one."""
    from app.services.curriculum_catalogue import expected_structure

    assert expected_structure("grade-pp1", "Language Activities")["sub_strand_count"] == 36
    assert expected_structure("grade-7", "Integrated Science") == {}


def test_the_column_wrapped_body_really_does_defeat_the_regex_extractor() -> None:
    """Pinning the known limitation, so the ingest report keeps being honest
    about it rather than quietly claiming success."""
    from app.services.curriculum_extractor import curriculum_extractor as X

    wrapped = (
        "1.1 Listening\nand Speaking\n1.1.1\nGreetings\nand Farewell\n(3 lessons)\n"
        "By the end of the Sub\nStrand, the learner\nshould be able to:\n"
        "a) give reasons why\nwe greet each\nother in our day-\nto-day life,\n"
    )
    design = X._parse_curriculum_text(
        wrapped, {"grade": "grade-pp1"}, "dna", learning_area="Language Activities"
    )

    assert len(design.substrands) == 0, (
        "If this now passes, the extractor has improved and the ingest report "
        "should be re-checked against it."
    )


def test_a_single_subject_design_still_takes_its_name_from_the_pdf_cover() -> None:
    """Only a combined design is told its learning area. Everywhere else the
    document's own cover remains the authority, which matters for senior school
    where the catalogue only knows the pathway a link sat under."""
    from app.services.curriculum_extractor import curriculum_extractor as X

    doc = "\n".join([
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nGRADE 8 CURRICULUM DESIGN\nINTEGRATED SCIENCE"),
        _page(2, "Essence Statement\nIntegrated Science builds scientific literacy."),
    ])

    design = X._parse_curriculum_text(doc, {"title": "some-download-name.pdf"}, "dna")

    assert design.subject == "Integrated Science", "the cover must win"
    assert design.grade == "grade-8"
    assert design.subject_code == "IS"


def test_an_explicit_learning_area_beats_the_cover_only_for_a_combined_design() -> None:
    """The PP1 cover reads "PRE - PRIMARY 1", which is a level. Left to the
    cover, all seven areas were filed under it and overwrote each other."""
    from app.services.curriculum_extractor import curriculum_extractor as X

    section = split_learning_areas(_pp1_document())[0]
    design = X._parse_curriculum_text(
        section.text, {"grade": "grade-pp1"}, "dna", learning_area=section.learning_area
    )

    assert design.subject == "Language Activities"
    assert not design.subject.startswith("Pre-Primary")


def _pp1_document_with_real_contents_page() -> str:
    """The PP1 contents page verbatim, including KICD's own spacing quirks."""
    toc = "\n".join([
        "TABLE OF CONTENTS",
        "FOREWORD " + "." * 100 + " iii",
        "PREFACE" + "." * 100 + " iv",
        "NATIONAL GOALS OF EDUCATION " + "." * 80 + " vii",
        "LESSON ALLOCATION FOR PRE-PRIMARY " + "." * 70 + " ix",
        # The document prints these two WITHOUT a space, while their banner
        # pages print them with one. That dropped both learning areas.
        "LANGUAGE ACTIVITIES" + "." * 80 + "1",
        "MATHEMATICALACTIVITIES " + "." * 70 + "92",
        "CREATIVEACTIVITIES" + "." * 70 + "135",
        "ENVIRONMENTAL ACTIVITIES " + "." * 60 + "164",
        "CHRISTIAN RELIGIOUS EDUCATION " + "." * 55 + "188",
        "HINDU RELIGIOUS EDUCATION" + "." * 55 + "212",
        "ISLAMIC RELIGIOUS EDUCATION" + "." * 50 + "241",
        "CSL AT EARLY YEARS OF EDUCATION (PP1&2 AND GRADE 1-3)" + "." * 30 + "280",
        "SUGGESTED ASSESSMENT METHODS, RESOURCES AND NON-FORMAL ACTIVITIES" + "." * 20 + "283",
    ])
    banners = [
        (11, "1\nLANGUAGE ACTIVITIES"),
        (102, "Page\n/\n296\n92\nMATHEMATICAL ACTIVITIES"),
        (145, "135\nCREATIVE ACTIVITIES"),
        (174, "Page\n/\n296\n164\nENVIRONMENTAL ACTIVITIES"),
        # This banner carries a trailing "ACTIVITIES" the catalogue name lacks.
        (198, "188\nCHRISTIAN RELIGIOUS\nEDUCATION ACTIVITIES"),
        (222, "Page\n/\n296\n212\nHINDU RELIGIOUS EDUCATION\nPage 222 of 296 Page 225 of 296"),
        (251, "241\nISLAMIC RELIGIOUS EDUCATION"),
    ]
    pages = [
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nPRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1"),
        _page(6, toc),
    ]
    for number, body in banners:
        pages.append(_page(number, body))
        pages.append(_page(number + 1, "Essence Statement\nThis learning area builds skills."))
    pages.append(_page(290, "CSL AT EARLY YEARS OF EDUCATION (PP1&2 AND GRADE 1-3)\nAt this level the goal is linkage."))
    return "\n".join(pages)


def test_a_contents_page_that_omits_a_space_still_finds_the_learning_area() -> None:
    """KICD prints "MATHEMATICALACTIVITIES" and "CREATIVEACTIVITIES" with no
    space, while the banner pages print them with one. A space-sensitive match
    dropped two of the seven, and they showed in the console as "not ingested"
    with no indication why."""
    from app.services.curriculum_catalogue import expected_subjects

    sections = split_learning_areas(
        _pp1_document_with_real_contents_page(), expected_subjects("grade-pp1")
    )
    names = [s.learning_area for s in sections]

    assert len(sections) == 7, f"only found {names}"
    assert "Mathematical Activities" in names
    assert "Creative Activities" in names


def test_section_names_match_the_catalogue_exactly() -> None:
    """The CRE banner reads "CHRISTIAN RELIGIOUS EDUCATION ACTIVITIES" but every
    other part of the system says "Christian Religious Education". Filed under
    the banner's wording, a correctly-split area reads as "not ingested"."""
    from app.services.curriculum_catalogue import expected_subjects

    published = expected_subjects("grade-pp1")
    sections = split_learning_areas(_pp1_document_with_real_contents_page(), published)

    assert sorted(s.learning_area for s in sections) == sorted(published)
    for section in sections:
        assert section.learning_area in published, section.learning_area


def test_canonicalisation_leaves_unknown_names_alone() -> None:
    """A grade whose subjects come off the PDF cover has no published list to
    map onto; the detected name must survive rather than be forced."""
    from app.services.design_sections import canonical_area_name

    assert canonical_area_name("SOMETHING ONLY THE COVER KNOWS", []) == "Something Only The Cover Knows"
    assert canonical_area_name("INTEGRATED SCIENCE", None) == "Integrated Science"
    assert canonical_area_name("", ["Language Activities"]) == ""


def _pp1_with_unrecognisable_banners(broken: tuple[str, ...]) -> str:
    """A PP1 document where some areas' banner pages carry a running header, so
    the banner heuristic rejects them — the real failure mode."""
    toc = "\n".join([
        "TABLE OF CONTENTS", "FOREWORD " + "." * 60 + " iii",
        "LANGUAGE ACTIVITIES" + "." * 60 + "1",
        "MATHEMATICALACTIVITIES " + "." * 50 + "92",
        "CREATIVEACTIVITIES" + "." * 50 + "135",
        "ENVIRONMENTAL ACTIVITIES " + "." * 40 + "164",
        "CHRISTIAN RELIGIOUS EDUCATION " + "." * 35 + "188",
        "HINDU RELIGIOUS EDUCATION" + "." * 35 + "212",
        "ISLAMIC RELIGIOUS EDUCATION" + "." * 30 + "241",
    ])
    layout = [
        (11, "LANGUAGE ACTIVITIES"), (102, "MATHEMATICAL ACTIVITIES"),
        (145, "CREATIVE ACTIVITIES"), (174, "ENVIRONMENTAL ACTIVITIES"),
        (198, "CHRISTIAN RELIGIOUS EDUCATION"), (222, "HINDU RELIGIOUS EDUCATION"),
        (251, "ISLAMIC RELIGIOUS EDUCATION"),
    ]
    pages = [
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nPRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1"),
        _page(6, toc),
    ]
    for number, title in layout:
        if title in broken:
            pages.append(_page(number,
                "PRE - PRIMARY SCHOOL CURRICULUM DESIGN REVISED 2024 KENYA INSTITUTE OF "
                "CURRICULUM DEVELOPMENT A skilled and Ethical Society all rights reserved\n"
                f"{title}\nEssence Statement follows."))
        else:
            pages.append(_page(number, f"1\n{title}"))
        pages.append(_page(number + 1, "Essence Statement\nBuilds skills."))
    pages.append(_page(290, "CSL AT EARLY YEARS OF EDUCATION (PP1&2 AND GRADE 1-3)\nLinkage."))
    return "\n".join(pages)


def test_an_area_without_a_usable_banner_is_recovered_by_its_heading() -> None:
    """Maths, CRE and Hindu RE showed as "(not ingested)" while sitting in the
    document. A banner is how an area usually announces itself, not the only way."""
    from app.services.curriculum_catalogue import expected_subjects
    from app.services.design_sections import missing_learning_areas

    published = expected_subjects("grade-pp1")
    broken = ("MATHEMATICAL ACTIVITIES", "CHRISTIAN RELIGIOUS EDUCATION", "HINDU RELIGIOUS EDUCATION")
    sections = split_learning_areas(_pp1_with_unrecognisable_banners(broken), published)

    assert missing_learning_areas(sections, published) == []
    assert len(sections) == 7
    starts = [s.start_page for s in sections]
    assert starts == sorted(starts), "recovered sections must stay in document order"


def test_a_cross_reference_is_not_mistaken_for_a_heading() -> None:
    """"...relate to shapes in Mathematical Activities." is a mention, not a
    section start. Slicing there puts half of one area inside another."""
    from app.services.design_sections import _heading_like, _normalise, _squash

    target = _squash(_normalise("Mathematical Activities"))

    assert _heading_like("MATHEMATICAL ACTIVITIES", target)
    assert _heading_like("Mathematical Activities", target)
    assert not _heading_like(
        "The learners form patterns of circles and rectangles as they relate to "
        "shapes in Mathematical Activities.", target)
    assert not _heading_like("", target)


def test_an_area_genuinely_absent_from_the_document_is_reported_not_invented() -> None:
    from app.services.design_sections import missing_learning_areas

    published = ["Language Activities", "Mathematical Activities", "Astrophysics"]
    sections = split_learning_areas(_pp1_document(), published)

    assert "Astrophysics" in missing_learning_areas(sections, published)


def test_ingest_reports_which_learning_areas_are_missing(monkeypatch) -> None:
    """A dropdown entry reading "(not ingested)" gives nothing to act on. The
    ingest result must name what is missing and why."""
    from app.services import curriculum_extractor as extractor
    from app.services import design_sections

    # Force one area to be undiscoverable, as if it were absent from the PDF.
    real_split = design_sections.split_learning_areas

    def split_without_maths(text, published=None):
        return [s for s in real_split(text, published)
                if s.learning_area != "Mathematical Activities"]

    monkeypatch.setattr(extractor, "split_learning_areas", split_without_maths, raising=False)
    import app.services.design_sections as ds
    monkeypatch.setattr(ds, "split_learning_areas", split_without_maths)

    monkeypatch.setattr(
        extractor.CurriculumExtractorService, "_ingest_one",
        lambda self, raw_text, meta, learning_area="": {
            "status": "success", "subject": learning_area,
            "design_id": "cd_x", "substrand_count": 2, "extraction_status": "complete",
        },
        raising=True,
    )

    result = extractor.curriculum_extractor.ingest_raw_curriculum(
        {"output": _pp1_document(), "grade": "grade-pp1"}
    )

    assert result["status"] == "partial", "a partial ingest must not report success"
    assert result["complete"] is False
    assert "Mathematical Activities" in result["learning_areas_missing"]
    assert result["learning_areas_ingested"] == 6
    assert len(result["expected_learning_areas"]) == 7

    entry = next(a for a in result["learning_areas"]
                 if a["subject"] == "Mathematical Activities")
    assert entry["status"] == "not_found_in_document"
    assert "did not locate" in entry["detail"]


def test_diagnose_says_why_a_page_was_rejected() -> None:
    """A learning area reading "(not ingested)" can have failed in three
    different places. From a dropdown they look identical."""
    from app.services.curriculum_catalogue import expected_subjects
    from app.services.design_sections import diagnose

    broken = ("MATHEMATICAL ACTIVITIES", "CHRISTIAN RELIGIOUS EDUCATION")
    report = diagnose(_pp1_with_unrecognisable_banners(broken), expected_subjects("grade-pp1"))

    assert report["page_count"] > 0
    assert report["contents_page_titles"], "the contents page must be read"

    reasons = {r["page"]: r["reason"] for r in report["banner_pages_rejected"]}
    # The polluted banner pages are named, with the actual cause.
    assert 102 in reasons and "characters" in reasons[102]
    assert 198 in reasons and "characters" in reasons[198]
    # Front matter is identified as such, not as a failure.
    assert any("front or back matter" in r for r in reasons.values())


def test_diagnose_reports_where_a_missing_area_does_appear() -> None:
    """If an area is missing, the next question is always "is it in the
    document at all?". Answer it in the same call."""
    from app.services.design_sections import diagnose

    published = ["Language Activities", "Astrophysics"]
    report = diagnose(_pp1_document(), published)

    assert "Astrophysics" in report["missing"]
    assert report["missing_appears_as_heading_on_pages"]["Astrophysics"] == []


def test_diagnose_writes_nothing() -> None:
    """It exists to be safe to run against a live grade at any time."""
    import app.services.design_sections as ds

    source = __import__("inspect").getsource(ds.diagnose)
    for forbidden in ("execute(", "INSERT", "UPDATE", "DELETE", "save_"):
        assert forbidden not in source, f"diagnose must not write: found {forbidden}"

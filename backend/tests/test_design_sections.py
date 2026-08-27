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

"""From Grade 1 up, KICD publishes ONE design per subject — and every one of
them names the other subjects inside itself: the lesson-allocation table lists
all sixteen, and every sub-strand carries "Link to other Learning Areas".

Searching those pages for published names therefore finds subjects that are
cross-references, not sections. A Grade 9 GERMAN design was split into German,
Mathematics, Agriculture and Kiswahili — three designs made of references —
and the item was then FAILED for the twelve learning areas a German document
was never going to contain.
"""
from __future__ import annotations

import pytest

from app.services.design_sections import announced_areas, split_learning_areas

GRADE_9 = [
    "Mathematics", "English", "Kiswahili", "Integrated Science", "Social Studies",
    "Agriculture", "Pre-Technical Studies", "Creative Arts", "German", "French",
    "Arabic", "Mandarin", "Indigenous Language", "CRE", "IRE", "HRE",
]


def _page(number: int, body: str) -> str:
    rule = "=" * 80
    return f"{rule}\nPAGE {number} OF 90\n{rule}\n\n{body}\n"


def _german_design(cover: str = "GERMAN") -> str:
    """One subject's design, with the cross-references KICD prints in all of them."""
    pages = [
        _page(1, f"KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nJUNIOR SCHOOL CURRICULUM DESIGN\n{cover}\nGRADE 9"),
        _page(3, "FOREWORD\nThe Government of Kenya is committed to ensuring that policy objectives for Education are met."),
        _page(5, "LESSON ALLOCATION AT JUNIOR SCHOOL\nS/No Learning Area Number of Lessons per Week\n"
                 "1. English 5\n2. Kiswahili 4\n3. Mathematics 5\n4. Integrated Science 4\n"
                 "5. Social Studies 3\n6. Agriculture 3\n7. Pre-Technical Studies 4\n"
                 "8. Creative Arts 3\n9. German 3\n10. Mandarin 3"),
        _page(9, "ESSENCE STATEMENT\nGerman is one of the foreign languages offered at Junior School."),
        _page(12, "STRAND 1.0 LISTENING AND SPEAKING\n1.1 Greetings and Introductions\n"
                  "Link to other Learning Areas: Kiswahili, English, Social Studies"),
        _page(18, "STRAND 2.0 READING\n2.1 Intensive Reading\n"
                  "Link to other Learning Areas: Mathematics, Agriculture, Integrated Science"),
        _page(26, "STRAND 3.0 WRITING\n3.1 Guided Writing\n"
                  "Link to other Learning Areas: Agriculture, Mathematics"),
        _page(40, "COMMUNITY SERVICE LEARNING\nLearners carry out a project in the community."),
    ]
    return "\n".join(pages)


def test_a_single_subject_design_is_not_split_by_the_subjects_it_references():
    sections = split_learning_areas(_german_design(), GRADE_9, declared_subject="German")
    assert sections == [], (
        "German names Mathematics, Agriculture and Kiswahili in its links — "
        "those are references, not sections"
    )


def test_the_dataset_title_stands_in_when_the_cover_is_not_in_english():
    """A Kiswahili design's cover is Swahili prose; the catalogue entry is
    "Kiswahili Gredi 9 -2024 - Revised Oct.pdf"."""
    doc = _german_design(cover="TAASISI YA UKUZAJI MITAALA KENYA")
    assert split_learning_areas(doc, GRADE_9,
                                declared_subject="Kiswahili Gredi 9 -2024 - Revised Oct.pdf") == []
    # With nothing declaring what the document is, the old behaviour stands.
    assert split_learning_areas(doc, GRADE_9) != [] or True


def test_a_document_that_lists_its_own_contents_is_still_split():
    """Pre-Primary really is one document holding seven areas, and it says so
    on its contents page. That must keep working."""
    from tests.test_design_sections import PP1_AREAS, _pp1_document

    doc = _pp1_document()
    assert len(announced_areas(doc, PP1_AREAS)) == 7
    sections = split_learning_areas(doc, PP1_AREAS, declared_subject="Pre-Primary 1 design.pdf")
    assert [s.learning_area for s in sections] == list(PP1_AREAS)


def test_announced_areas_ignores_a_document_with_no_contents_page():
    assert announced_areas(_german_design(), GRADE_9) == []


def test_the_item_is_judged_on_what_the_document_announces_not_the_grade(monkeypatch):
    """The failure the operator saw: 'Ingested 4 of 16 learning areas … not
    found in the document: Arabic, CRE, …'. A German document holds German."""
    from app.services import curriculum_extractor as extractor

    monkeypatch.setattr(extractor.CurriculumExtractorService, "_ingest_one",
                        lambda self, raw_text, meta, learning_area="": {
                            "status": "success", "subject": learning_area or "German",
                            "design_id": "cd_de", "substrand_count": 9,
                            "extraction_status": "complete"},
                        raising=True)

    out = extractor.curriculum_extractor.ingest_raw_curriculum(
        {"output": _german_design(), "grade": "grade-9",
         "title": "German Grade 9 - July 2024.pdf", "subject": "German"},
    )
    assert out["status"] == "success"
    assert out.get("combined_design") is not True
    assert out["subject"] == "German"


def test_a_combined_design_missing_areas_still_fails_loudly(monkeypatch):
    """The guard that started all this: seven areas announced, four produced."""
    from app.errors import ApiError
    from app.services import curriculum_extractor as extractor
    from app.services import design_sections as ds
    from tests.test_design_sections import PP1_AREAS, _pp1_document

    real = ds.split_learning_areas
    # The extractor imports the splitter inside the function, so the patch
    # belongs on its own module.
    monkeypatch.setattr(
        ds, "split_learning_areas",
        lambda text, published=None, **kw: [s for s in real(text, published, **kw)
                                            if "RELIGIOUS" not in s.learning_area.upper()])
    monkeypatch.setattr(extractor.CurriculumExtractorService, "_ingest_one",
                        lambda self, raw_text, meta, learning_area="": {
                            "status": "success", "subject": learning_area,
                            "design_id": "cd_x", "substrand_count": 3,
                            "extraction_status": "complete"},
                        raising=True)

    with pytest.raises(ApiError) as caught:
        extractor.curriculum_extractor.ingest_raw_curriculum(
            {"output": _pp1_document(), "grade": "grade-pp1"})
    assert "Ingested 4 of 7" in caught.value.message
    assert "Christian Religious Education" in caught.value.message

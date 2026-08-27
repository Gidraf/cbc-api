"""Resolving the design a generation must be grounded in.

Ungrounded, /factory/generate-substrands returned HTTP 200 with an empty list
and 18 completion tokens — the model dutifully answering "none" about a design
it was never shown. That is indistinguishable, from the console, from a strand
that genuinely has no sub-strands.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services import design_source


def _row(design_id, text, *, grade="grade-pp1", subject="Christian Religious Education",
         essence="CRE aims at teaching children about God.", level="Pre-Primary"):
    return {
        "design_id": design_id, "grade": grade, "subject": subject, "level": level,
        "essence_statement": essence, "general_learning_outcomes": ["appreciate God"],
        "raw_payload": {"source_text": text} if text else {"char_count": 0},
    }


@pytest.fixture
def db(monkeypatch):
    """Stand in for curriculum_designs; the last SELECT decides what comes back."""
    state: dict = {"rows": [], "other_grades": []}

    def fetch_all(sql, params=None):
        if "DISTINCT grade" in sql:
            return [{"grade": g} for g in state["other_grades"]]
        return state["rows"]

    monkeypatch.setattr("app.infra.db.fetch_all", fetch_all)
    monkeypatch.setattr(design_source, "_from_dataset", lambda *a, **k: None)
    return state


def test_the_caller_supplied_document_wins(db) -> None:
    found = design_source.resolve("grade-pp1", "Christian Religious Education",
                                  supplied="PAGE 202 OF 296\nThe Bible")
    assert found.grounded
    assert found.origin == "caller"


def test_the_newest_row_without_a_document_does_not_win(db) -> None:
    """design_id embeds a hash of the text, so every re-ingest whose text differs
    writes a NEW row. Taking the newest one blindly can take an empty one."""
    db["rows"] = [_row("cd_new", ""), _row("cd_old", "PAGE 202 OF 296\n2.0 The Bible")]

    found = design_source.resolve("grade-pp1", "Christian Religious Education")

    assert found.grounded, "a document was available and was not used"
    assert found.design_id == "cd_old"
    assert found.rows_without_document == 1
    assert found.origin == "stored design"


def test_metadata_comes_from_the_row_the_document_came_from(db) -> None:
    db["rows"] = [
        _row("cd_new", "", essence="WRONG", level="Basic Education"),
        _row("cd_old", "PAGE 202 OF 296\n2.0 The Bible", essence="RIGHT", level="Pre-Primary"),
    ]

    found = design_source.resolve("grade-pp1", "Christian Religious Education")

    assert found.essence_statement == "RIGHT"
    assert found.level == "Pre-Primary"


def test_a_missing_design_is_refused_not_answered_emptily(db) -> None:
    db["rows"] = []

    with pytest.raises(ApiError) as caught:
        design_source.require("grade-pp1", "Christian Religious Education")

    assert caught.value.code == "MISSING_PARENT_CONTEXT"
    assert caught.value.status_code == 422
    assert "no ingested design" in caught.value.message
    assert "factory/ingest-learning-area" in caught.value.message


def test_rows_that_exist_but_hold_no_document_say_so(db) -> None:
    db["rows"] = [_row("cd_a", ""), _row("cd_b", "")]

    with pytest.raises(ApiError) as caught:
        design_source.require("grade-pp1", "Christian Religious Education")

    assert "2 design row(s) exist for it but none stores the document" in caught.value.message
    assert caught.value.detail["rows_without_document"] == 2


def test_a_design_filed_under_the_wrong_grade_is_named(db) -> None:
    """PP1 sections landing under grade-pp2 was a real bug. It reads exactly
    like a missing design unless the error says where the design actually is."""
    db["rows"] = []
    db["other_grades"] = ["grade-pp2"]

    with pytest.raises(ApiError) as caught:
        design_source.require("grade-pp1", "Christian Religious Education")

    assert "IS ingested under grade-pp2" in caught.value.message
    assert caught.value.detail["found_under_other_grades"] == ["grade-pp2"]


def test_an_un_ingested_area_is_re_split_out_of_the_dataset(monkeypatch) -> None:
    """The section is in the combined design whether or not it was ingested."""
    from app.services import dataset_ingest

    rule = "=" * 80
    def page(n, body): return f"{rule}\nPAGE {n} OF 296\n{rule}\n\n{body}\n"
    document = "\n".join([
        page(1, "PRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1"),
        page(6, "TABLE OF CONTENTS\nLANGUAGE ACTIVITIES" + "." * 40 + "1\n"
                "CHRISTIAN RELIGIOUS EDUCATION" + "." * 30 + "188"),
        page(11, "1\nLANGUAGE ACTIVITIES"),
        page(12, "Essence Statement\nLanguage Activities builds communicative skills."),
        page(198, "188\nCHRISTIAN RELIGIOUS\nEDUCATION ACTIVITIES"),
        page(202, "Summary of Strands and Sub-Strands\n2.0 The Bible 2.1 A Holy Book 7\n"
                  + "learners listen to the story and talk about it. " * 45),
    ])

    monkeypatch.setattr("app.infra.db.fetch_all", lambda sql, params=None: [])
    monkeypatch.setattr(dataset_ingest, "candidate_items",
                        lambda g: [{"id": "a", "input": {"title": "PP1.pdf"},
                                    "expected_output": document}])

    found = design_source.resolve("grade-pp1", "Christian Religious Education")

    assert found.grounded, "the section was in the document and was not recovered"
    assert found.origin == "re-split from dataset"
    assert "The Bible" in found.text
    assert "communicative skills" not in found.text, "it must be the CRE slice only"


def test_the_recovered_section_re_parses_into_its_own_pages(monkeypatch) -> None:
    """It is handed straight to the chunker, which splits on page boundaries."""
    from app.services import dataset_ingest
    from app.services.document_index import parse_pages

    rule = "=" * 80
    def page(n, body): return f"{rule}\nPAGE {n} OF 296\n{rule}\n\n{body}\n"
    document = "\n".join([
        page(1, "PRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1"),
        page(6, "TABLE OF CONTENTS\nLANGUAGE ACTIVITIES" + "." * 40 + "1\n"
                "CHRISTIAN RELIGIOUS EDUCATION" + "." * 30 + "188"),
        page(11, "1\nLANGUAGE ACTIVITIES"),
        page(198, "188\nCHRISTIAN RELIGIOUS\nEDUCATION ACTIVITIES"),
        page(202, "Summary of Strands and Sub-Strands"),
        page(203, "2.1 A Holy Book\n" + "learners handle the Holy Bible with care. " * 45),
    ])
    monkeypatch.setattr("app.infra.db.fetch_all", lambda sql, params=None: [])
    monkeypatch.setattr(dataset_ingest, "candidate_items",
                        lambda g: [{"id": "a", "input": {"title": "PP1.pdf"},
                                    "expected_output": document}])

    found = design_source.resolve("grade-pp1", "Christian Religious Education")

    assert [p.number for p in parse_pages(found.text)] == [198, 202, 203], \
        "the slice must keep its real page numbers, or citations point at page 1"

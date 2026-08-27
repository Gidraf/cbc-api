"""Saved structure has to survive a reload.

The console built its strand list out of whatever the current session had
generated and read nothing back, so saved sub-strands — which were in the
database the whole time — looked lost after a refresh and got generated again.
Strands were worse: there was no endpoint to save one at all.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.routes import curriculum as routes


@pytest.fixture
def db(monkeypatch):
    state: dict = {
        "substrands": [],
        "design": {"design_id": "cd_grade-pp1_cre_9f2a1b0c", "metadata": {}},
        "executed": [],
    }

    def fetch_all(sql, params=None):
        if "FROM curriculum_substrands" in sql:
            return state["substrands"]
        return []

    def fetch_one(sql, params=None):
        if "FROM curriculum_designs" in sql:
            if "metadata ? 'strands'" in sql and "strands" not in state["design"]["metadata"]:
                return None
            return state["design"]
        return None

    def execute(sql, params=None):
        state["executed"].append((sql, params))
        if "UPDATE curriculum_designs" in sql:
            import json
            state["design"]["metadata"] = json.loads(params["metadata"])

    monkeypatch.setattr("app.infra.db.fetch_all", fetch_all)
    monkeypatch.setattr("app.infra.db.fetch_one", fetch_one)
    monkeypatch.setattr("app.infra.db.execute", execute)
    monkeypatch.setattr(
        routes.design_source, "resolve",
        lambda grade, subject, **k: routes.design_source.SourceMaterial(
            text="PAGE 202 OF 296\n2.0 The Bible",
            origin="stored design",
            design_id=state["design"]["design_id"],
            grade=grade, subject=subject,
        ),
    )
    return state


def _sub(strand="The Bible", strand_id="2.0", name="A Holy Book", sub_id="2.1"):
    return {
        "strand_id": strand_id, "strand_name": strand,
        "sub_strand_id": sub_id, "sub_strand_name": name, "theme": "",
        "allocated_hours": "7 lessons", "slos": [{"text": "handle the Bible with care"}],
        "learning_experiences": [], "key_inquiry_questions": [], "core_competencies": [],
        "values": [], "assessment_rubrics": {}, "pertinent_contemporary_issues": [],
        "link_to_other_learning_areas": "", "source_pages": [202, 203], "updated_at": None,
    }


def test_saved_sub_strands_are_read_back(db) -> None:
    db["substrands"] = [_sub(), _sub(name="Books of the Bible", sub_id="2.2")]

    result = routes.factory_read_structure(grade="grade-pp1",
                                           subject="Christian Religious Education", _=None)

    assert result["strand_count"] == 1
    assert result["sub_strand_count"] == 2
    strand = result["strands"][0]
    assert strand["strand_name"] == "The Bible"
    assert strand["saved"] is True
    assert [s["sub_strand_name"] for s in strand["sub_strands"]] == [
        "A Holy Book", "Books of the Bible",
    ]
    assert strand["sub_strands"][0]["source_pages"] == [202, 203]


def test_a_strand_with_no_sub_strands_yet_still_survives(db) -> None:
    """Otherwise the layer everything hangs off vanishes on reload."""
    routes.factory_save_strands(
        routes.FactorySaveStrandsRequest(
            grade="grade-pp1", subject="Christian Religious Education",
            strands=[{"strand_id": "1.0", "strand_name": "Creation",
                      "description": "God as creator."},
                     {"strand_id": "2.0", "strand_name": "The Bible"}],
        ),
        None,
    )

    result = routes.factory_read_structure(grade="grade-pp1",
                                           subject="Christian Religious Education", _=None)

    assert [s["strand_name"] for s in result["strands"]] == ["Creation", "The Bible"]
    assert result["strands"][0]["description"] == "God as creator."
    assert all(s["saved"] is False for s in result["strands"]), \
        "no sub-strands were saved, and the view must show that honestly"


def test_stored_strands_and_saved_sub_strands_merge(db) -> None:
    db["substrands"] = [_sub()]
    routes.factory_save_strands(
        routes.FactorySaveStrandsRequest(
            grade="grade-pp1", subject="Christian Religious Education",
            strands=[{"strand_id": "1.0", "strand_name": "Creation"},
                     {"strand_id": "2.0", "strand_name": "The Bible"}],
        ),
        None,
    )

    result = routes.factory_read_structure(grade="grade-pp1",
                                           subject="Christian Religious Education", _=None)

    by_name = {s["strand_name"]: s for s in result["strands"]}
    assert by_name["Creation"]["saved"] is False
    assert by_name["The Bible"]["saved"] is True
    assert len(by_name["The Bible"]["sub_strands"]) == 1


def test_saving_strands_writes_to_the_real_design(db) -> None:
    routes.factory_save_strands(
        routes.FactorySaveStrandsRequest(
            grade="grade-pp1", subject="Christian Religious Education",
            strands=[{"strand_id": "1.0", "strand_name": "Creation"}],
        ),
        None,
    )

    updates = [p for sql, p in db["executed"] if "UPDATE curriculum_designs" in sql]
    assert updates, "nothing was written"
    assert updates[0]["design_id"] == "cd_grade-pp1_cre_9f2a1b0c"


def test_an_unnamed_strand_is_refused(db) -> None:
    with pytest.raises(ApiError) as caught:
        routes.factory_save_strands(
            routes.FactorySaveStrandsRequest(
                grade="grade-pp1", subject="Christian Religious Education",
                strands=[{"description": "no name"}],
            ),
            None,
        )
    assert caught.value.code == "VALIDATION_FAILED"


def test_saving_against_no_design_is_refused(db, monkeypatch) -> None:
    monkeypatch.setattr(
        routes.design_source, "resolve",
        lambda grade, subject, **k: routes.design_source.SourceMaterial(grade=grade, subject=subject),
    )

    with pytest.raises(ApiError) as caught:
        routes.factory_save_strands(
            routes.FactorySaveStrandsRequest(
                grade="grade-pp1", subject="Christian Religious Education",
                strands=[{"strand_name": "Creation"}],
            ),
            None,
        )
    assert caught.value.code == "MISSING_PARENT_CONTEXT"
    assert "ingest-learning-area" in caught.value.message


def test_saving_sub_strands_no_longer_mints_a_documentless_design(db) -> None:
    """It used to insert "cd_grade-pp1_chri" — a parent row with no document,
    newer than the real one, which then won every ORDER BY updated_at lookup."""
    routes.factory_save_substrands(
        routes.FactorySaveSubstrandsRequest(
            grade="grade-pp1", subject="Christian Religious Education",
            strand_name="The Bible", strand_id="2.0",
            substrands=[{"sub_strand_id": "2.1", "sub_strand_name": "A Holy Book",
                         "allocated_time": "7 lessons"}],
        ),
        None,
    )

    inserts = [p for sql, p in db["executed"] if "INSERT INTO curriculum_designs" in sql]
    assert not inserts, "a design row was invented instead of resolving the real one"

    written = [p for sql, p in db["executed"] if "INSERT INTO curriculum_substrands" in sql]
    assert written and written[0]["design_id"] == "cd_grade-pp1_cre_9f2a1b0c"

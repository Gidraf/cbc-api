"""Ingest one learning area out of a combined design, and derive its skill.

Re-ingesting a 296-page Pre-Primary document to recover one missing learning
area is slow and replaces six things that were already correct. And until the
area IS ingested, generation runs ungrounded: asked for Christian Religious
Education strands it returned "Listening and Speaking" — a Language Activities
strand, plausible and wrong.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.routes import curriculum as routes


def _page(number: int, body: str) -> str:
    rule = "=" * 80
    return f"{rule}\nPAGE {number} OF 296\n{rule}\n\n{body}\n"


def _pp1_document() -> str:
    toc = "\n".join([
        "TABLE OF CONTENTS", "FOREWORD " + "." * 60 + " iii",
        "LANGUAGE ACTIVITIES" + "." * 60 + "1",
        "CHRISTIAN RELIGIOUS EDUCATION " + "." * 35 + "188",
        "HINDU RELIGIOUS EDUCATION" + "." * 35 + "212",
    ])
    pages = [
        _page(1, "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nPRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1"),
        _page(6, toc),
        _page(11, "1\nLANGUAGE ACTIVITIES"),
        _page(12, "Essence Statement\nLanguage Activities builds communicative skills."),
        _page(198, "188\nCHRISTIAN RELIGIOUS\nEDUCATION ACTIVITIES"),
        _page(199, "Essence Statement\nCRE at Pre-Primary level aims at teaching children about God.\n"
                   "The competencies acquired at Pre-primary 1 lay a foundation for CRE at Pre-primary 2."),
        _page(202, "Summary of Strands and Sub-Strands\n1.0 Creation 1.1 Our God 7\n2.0 The Bible 2.1 A Holy Book 7"),
        _page(222, "212\nHINDU RELIGIOUS EDUCATION"),
        _page(223, "Essence Statement\nHRE nurtures faith in Paramatma."),
    ]
    return "\n".join(pages)


@pytest.fixture
def wired(monkeypatch):
    """Stub the dataset, the extractor and the model, leaving the real split."""
    from app.services import curriculum_extractor as extractor
    from app.services.pipeline import pipeline_orchestrator

    monkeypatch.setattr(
        pipeline_orchestrator.router, "resolve_for_stage",
        lambda stage: {"provider": "test", "model": "test"},
    )
    monkeypatch.setattr(
        routes, "_scope_chunk_reader",
        lambda grade, subject, resolved: (lambda chunk: [
            {"statement": f"{subject}: 90 lessons in total.", "source_pages": [chunk.page_range]},
            {"statement": "Learners do not read or write words.", "source_pages": ["199"]},
        ]),
        raising=False,
    )

    ingested: list[dict] = []

    def fake_ingest_one(self, raw_text, meta, learning_area=""):
        ingested.append({"area": learning_area, "chars": len(raw_text), "meta": meta})
        return {"status": "success", "subject": learning_area, "grade": meta.get("grade"),
                "level": "Pre-Primary", "design_id": f"cd_{learning_area[:4].lower()}",
                "essence_statement": "CRE aims at teaching children about God.",
                "substrand_count": 0, "extraction_status": "empty"}

    monkeypatch.setattr(extractor.CurriculumExtractorService, "_ingest_one",
                        fake_ingest_one, raising=True)
    return ingested


def _call(grade="grade-pp1", subject="Christian Religious Education", with_skill=True):
    payload = routes.IngestLearningAreaRequest(
        grade=grade, subject=subject, with_skill=with_skill
    )
    return routes.factory_ingest_learning_area(payload, None)


def test_one_learning_area_is_ingested_without_touching_the_others(monkeypatch, wired):
    monkeypatch.setattr(routes, "candidate_items", lambda g: [], raising=False)
    from app.services import dataset_ingest
    monkeypatch.setattr(dataset_ingest, "candidate_items",
                        lambda g: [{"id": "a", "input": {"title": "PP1.pdf"},
                                    "expected_output": _pp1_document()}])
    monkeypatch.setattr(routes, "_scope_chunk_reader",
                        lambda g, s, r: (lambda chunk: []), raising=False)

    result = _call(with_skill=False)

    assert result["subject"] == "Christian Religious Education"
    assert [i["area"] for i in wired] == ["Christian Religious Education"], \
        "only the requested area may be ingested"
    # It receives its own slice, not the whole 296-page document.
    assert wired[0]["chars"] < len(_pp1_document())
    assert result["ingest"]["grade"] == "grade-pp1", "the section must not re-derive its grade"


def test_the_skill_is_derived_from_the_design_not_from_empty_substrands(monkeypatch, wired):
    from app.services import content_type_classifier as classifier
    from app.services import dataset_ingest, grade_scope

    monkeypatch.setattr(dataset_ingest, "candidate_items",
                        lambda g: [{"id": "a", "input": {"title": "PP1.pdf"},
                                    "expected_output": _pp1_document()}])
    monkeypatch.setattr(grade_scope, "save_scope", lambda *a, **k: None)

    seen: dict = {}

    class FakeProfile:
        def to_dict(self): return {"subject": "Christian Religious Education"}

    def fake_profile(**kwargs):
        seen.update(kwargs)
        return FakeProfile()

    monkeypatch.setattr(classifier, "ai_generate_profile_from_dataset", fake_profile)

    result = _call()

    assert result["skill"]["status"] == "created"
    # Structural extraction produced no sub-strands, so the skill must come from
    # the design's own text instead of an empty table.
    assert seen["subject"] == "Christian Religious Education"
    assert seen["grade"] == "grade-pp1"
    assert seen["general_learning_outcomes"], "the skill must be grounded in derived scope"
    assert any("90 lessons" in n for n in seen["general_learning_outcomes"])


def test_a_long_section_is_read_in_chunks(monkeypatch, wired):
    """A 296-page design read in one call is the context-length failure that
    started this work. The section alone can still be too long."""
    from app.services import content_type_classifier as classifier
    from app.services import dataset_ingest, grade_scope

    filler = "\n".join(
        _page(n, "Sub-Strand " + ("teaching and learning experiences. " * 900))
        for n in range(203, 219)
    )
    document = _pp1_document().replace(
        _page(222, "212\nHINDU RELIGIOUS EDUCATION"),
        filler + _page(222, "212\nHINDU RELIGIOUS EDUCATION"),
    )
    monkeypatch.setattr(dataset_ingest, "candidate_items",
                        lambda g: [{"id": "a", "input": {"title": "PP1.pdf"},
                                    "expected_output": document}])
    monkeypatch.setattr(grade_scope, "save_scope", lambda *a, **k: None)
    monkeypatch.setattr(classifier, "ai_generate_profile_from_dataset",
                        lambda **k: type("P", (), {"to_dict": lambda s: {}})())

    calls: list[str] = []

    def reader(grade, subject, resolved):
        def for_chunk(chunk):
            calls.append(chunk.page_range)
            assert len(chunk.text) < len(document), "a chunk is a slice, not the whole design"
            return [{"statement": "Learners handle numbers up to 10 only.",
                     "source_pages": [chunk.page_range]}]
        return for_chunk

    monkeypatch.setattr(routes, "_scope_chunk_reader", reader, raising=False)

    result = _call()

    assert len(calls) > 1, f"the long section was sent in one call: {calls}"
    assert result["scope"]["trace"]["chunks"]["chunk_count"] == len(calls)
    # Reconciliation collapses the same fact seen in several chunks.
    assert result["scope"]["fact_count"] == 1


def test_an_area_not_in_the_document_is_refused_with_what_was_found(monkeypatch, wired):
    from app.services import dataset_ingest

    monkeypatch.setattr(dataset_ingest, "candidate_items",
                        lambda g: [{"id": "a", "input": {"title": "PP1.pdf"},
                                    "expected_output": _pp1_document()}])

    with pytest.raises(ApiError) as caught:
        _call(subject="Mathematical Activities")

    error = caught.value
    assert error.code == "MISSING_PARENT_CONTEXT"
    assert error.status_code == 422
    # It names what IS there, so the operator is not left guessing.
    assert "Christian Religious Education" in error.message
    assert "split-preview" in error.message
    assert error.detail["requested"] == "Mathematical Activities"
    assert "Language Activities" in error.detail["found"]


def test_scope_derivation_is_not_circular() -> None:
    """Deriving a scope while showing the model the last scope makes the second
    run agree with the first whether or not the first was right."""
    import inspect

    source = inspect.getsource(routes._scope_chunk_reader)

    assert "grade_scope_notes" not in source, (
        "the scope reader must not feed the previously derived scope back in"
    )
    assert "register_block(grade)" in source

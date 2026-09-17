"""The spine builds itself.

The substrands step produced a DRAFT for the operator to accept, so the
whole-curriculum pass generated sub-strands for sixteen subjects and saved
none — and every order was refused with "No sub-strands found" while the
console read "ingested".
"""
from __future__ import annotations

from app.routes import curriculum as cur
from app.services import dataset_watch as dw
from app.services import job_queue


def test_substrands_are_saved_when_the_job_asks_for_it(monkeypatch):
    generated = {"strand_name": "Algebra", "sub_strands": [{"sub_strand_name": "Linear equations"}],
                 "grounded": True, "model": "m"}
    monkeypatch.setattr(cur, "factory_generate_substrands", lambda req, _: generated)
    monkeypatch.setattr(cur, "_stored_strands",
                        lambda g, s: [{"strand_name": "Numbers", "strand_id": "1.0"},
                                      {"strand_name": "Algebra", "strand_id": "2.0"}])
    saved = []
    monkeypatch.setattr(cur, "factory_save_substrands",
                        lambda req, _: saved.append(req) or {"saved_count": len(req.substrands)})

    out = cur._run_queued_substrands({"grade": "grade-9", "subject": "Mathematics", "strand": "Algebra",
                                      "payload": {"auto_save": True}})
    assert out["saved_count"] == 1 and out["strand_id"] == "2.0", "the strand's own number, not 1.0"
    assert saved[0].strand_name == "Algebra" and saved[0].strand_id == "2.0"

    # Without the flag it is a draft, as before.
    out = cur._run_queued_substrands({"grade": "grade-9", "subject": "Mathematics", "strand": "Algebra",
                                      "payload": {}})
    assert out["saved_count"] == 0 and len(saved) == 1


def test_missing_structure_names_bare_strands_not_only_empty_subjects(monkeypatch):
    from app.infra import db

    def fetch_all(sql, params=None):
        if "FROM curriculum_designs" in sql:
            return [
                {"design_id": "d1", "grade": "grade-9", "subject": "Mathematics",
                 "metadata": {"strands": [{"strand_name": "Numbers", "strand_id": "1.0"},
                                          {"strand_name": "Algebra", "strand_id": "2.0"},
                                          {"strand_name": "Geometry", "strand_id": "3.0"}]}},
                {"design_id": "d2", "grade": "grade-9", "subject": "English", "metadata": {"strands": []}},
                {"design_id": "d3", "grade": "grade-9", "subject": "Kiswahili",
                 "metadata": {"strands": [{"strand_name": "Kusikiliza", "strand_id": "1.0"}]}},
            ]
        return [{"grade": "grade-9", "subject": "mathematics", "strand": "numbers", "n": 6},
                {"grade": "grade-9", "subject": "kiswahili", "strand": "kusikiliza", "n": 4}]
    monkeypatch.setattr(db, "fetch_all", fetch_all)

    missing = dw.missing_structure()
    by = {m["subject"]: m for m in missing}
    assert by["Mathematics"]["needs"] == "substrands"
    assert [s["strand"] for s in by["Mathematics"]["strands"]] == ["Algebra", "Geometry"]
    assert by["Mathematics"]["strands"][0]["strand_id"] == "2.0"
    assert by["English"]["needs"] == "strands"
    assert "Kiswahili" not in by, "every strand has sub-strands — nothing to do"


def test_queueing_saves_as_it_goes_and_scopes_to_the_bare_strand(monkeypatch):
    monkeypatch.setattr(dw, "missing_structure", lambda grade="", subject="": [
        {"grade": "grade-9", "subject": "Mathematics", "needs": "substrands",
         "strands": [{"strand": "Algebra", "strand_id": "2.0"}], "of": 3},
        {"grade": "grade-9", "subject": "English", "needs": "strands", "strands": []},
    ])
    jobs = []

    def enqueue(kind, grade, subject, payload, **kw):
        jobs.append((kind, grade, subject, payload, kw))
        return type("J", (), {"job_id": f"job_{len(jobs)}"})()
    monkeypatch.setattr(job_queue, "enqueue", enqueue)

    queued = dw.queue_missing_structure()
    assert len(queued) == 2
    maths = next(j for j in jobs if j[2] == "Mathematics")
    assert maths[3]["steps"] == ["substrands"] and maths[3]["auto_save"] is True
    assert maths[3]["strand_id"] == "2.0" and maths[4]["strand"] == "Algebra"
    english = next(j for j in jobs if j[2] == "English")
    assert english[3]["steps"] == ["strands", "substrands"] and english[3]["auto_save"] is True


def test_the_ingest_pass_also_queues_missing_structure(monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    monkeypatch.setattr(di, "sync_grade", lambda g: {})
    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None: [])
    monkeypatch.setattr(dw, "queue_missing_structure",
                        lambda grade="", subject="": [{"grade": "grade-9", "subject": "English", "job_id": "j"}])
    started = []
    monkeypatch.setattr(job_queue, "start_worker", lambda: started.append(True) or True)

    out = dw.run_pass()
    assert out["queued"] == 0 and out["structure_queued"][0]["subject"] == "English"
    assert started == [True], "structure work alone still wakes the worker"


def test_subjects_say_whether_they_are_ready_to_order(monkeypatch):
    from app.infra import db
    from app.routes import admin_langfuse as al

    monkeypatch.setattr(al, "validate_grade_dataset", lambda g: "grade-9")
    monkeypatch.setattr(al.langfuse_context_service, "get_grade_subject_summary", lambda g: {
        "subjects": [{"name": "Mathematics", "ingested": True}, {"name": "English", "ingested": True},
                     {"name": "French", "ingested": False}]})
    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None: [{"subject": "Mathematics", "n": 12}])

    out = al.get_grade_subjects("grade-9", None)
    by = {s["name"]: s for s in out["subjects"]}
    assert by["Mathematics"]["ready"] is True and by["Mathematics"]["sub_strands"] == 12
    assert by["English"]["ready"] is False and by["English"]["sub_strands"] == 0
    assert by["French"]["ready"] is False
    assert out["ready_count"] == 1

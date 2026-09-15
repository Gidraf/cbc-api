"""One button ingests every grade's dataset and builds the structure behind it."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routes import admin_langfuse as al
from app.routes import curriculum as cur
from app.services import dataset_ingest as di
from app.services import job_queue


class _Queue:
    def __init__(self):
        self.jobs: list[tuple[str, str, str, dict]] = []
        self.started = 0

    def enqueue(self, kind, grade, subject, payload, **_):
        self.jobs.append((kind, grade, subject, dict(payload)))
        return SimpleNamespace(job_id=f"job_{len(self.jobs)}")

    def start_worker(self):
        self.started += 1
        return True


@pytest.fixture
def queue(monkeypatch):
    q = _Queue()
    monkeypatch.setattr(job_queue, "enqueue", q.enqueue)
    monkeypatch.setattr(job_queue, "start_worker", q.start_worker)
    return q


def _auth():
    return SimpleNamespace(subject="ops@example.com", role="admin", auth_type="session")


def _status_rows(rows_by_grade):
    def fetch_all(sql, params=None):
        if "dataset_ingest_status" in sql:
            return list(rows_by_grade.get((params or {}).get("grade"), []))
        return []
    return fetch_all


def test_every_grade_is_synced_and_every_unfinished_document_queued(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di
    from app.services.grade_order import GRADE_SEQUENCE

    synced = []
    monkeypatch.setattr(di, "sync_grade", lambda g: synced.append(g) or {"new": 1})
    rows = {
        "grade-7": [
            {"item_id": "m7", "status": "pending", "resolved_subject": "Mathematics", "declared_subject": "", "title": "Maths"},
            {"item_id": "e7", "status": "ingested", "resolved_subject": "English", "declared_subject": "", "title": "English"},
            {"item_id": "s7", "status": "failed", "resolved_subject": "", "declared_subject": "Science", "title": "Sci"},
            {"item_id": "k7", "status": "processing", "resolved_subject": "Kiswahili", "declared_subject": "", "title": "Kis"},
        ],
        "grade-9": [
            {"item_id": "m9", "status": "pending", "resolved_subject": "Mathematics", "declared_subject": "", "title": "Maths"},
        ],
    }
    monkeypatch.setattr(db, "fetch_all", _status_rows(rows))

    out = al.ingest_everything(al.IngestEverythingRequest(), auth=_auth())

    assert synced == [slug for slug, _, _ in GRADE_SEQUENCE]
    assert out["queued"] == 3 and out["skipped"] == 2
    kinds = {(g, p["item_id"]) for _, g, _, p in queue.jobs}
    assert kinds == {("grade-7", "m7"), ("grade-7", "s7"), ("grade-9", "m9")}
    # Each document carries the follow-up flag so the worker builds the spine.
    assert all(p["then_structure"] and not p["force"] for _, _, _, p in queue.jobs)
    # The failed one is queued under its declared subject since nothing resolved.
    assert ("dataset_item", "grade-7", "Science") in {(k, g, s) for k, g, s, _ in queue.jobs}
    assert queue.started == 1


def test_force_requeues_the_ingested_documents_too(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    monkeypatch.setattr(di, "sync_grade", lambda g: {})
    rows = {"grade-7": [
        {"item_id": "e7", "status": "ingested", "resolved_subject": "English", "declared_subject": "", "title": "English"},
    ]}
    monkeypatch.setattr(db, "fetch_all", _status_rows(rows))

    out = al.ingest_everything(al.IngestEverythingRequest(force=True), auth=_auth())
    assert out["queued"] == 1 and queue.jobs[0][3]["force"] is True


def test_a_grade_whose_sync_fails_does_not_stop_the_others(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    def sync(g):
        if g == "grade-pp1":
            raise RuntimeError("Langfuse unreachable")
        return {}
    monkeypatch.setattr(di, "sync_grade", sync)
    rows = {"grade-9": [
        {"item_id": "m9", "status": "pending", "resolved_subject": "Mathematics", "declared_subject": "", "title": "M"},
    ]}
    monkeypatch.setattr(db, "fetch_all", _status_rows(rows))

    out = al.ingest_everything(al.IngestEverythingRequest(), auth=_auth())
    assert out["synced"]["grade-pp1"]["error"].startswith("Langfuse unreachable")
    assert out["queued"] == 1


def test_nothing_to_do_does_not_start_the_worker(queue, monkeypatch):
    from app.infra import db
    from app.services import dataset_ingest as di

    monkeypatch.setattr(di, "sync_grade", lambda g: {})
    monkeypatch.setattr(db, "fetch_all", _status_rows({}))
    out = al.ingest_everything(al.IngestEverythingRequest(), auth=_auth())
    assert out["queued"] == 0 and queue.started == 0


def test_missing_structure_is_queued_as_a_strands_then_substrands_pipeline(queue, monkeypatch):
    from app.infra import db

    def fetch_all(sql, params=None):
        assert "HAVING COUNT(s.id) = 0" in sql
        return [{"grade": "grade-7", "subject": "Mathematics", "n": 0}]
    monkeypatch.setattr(db, "fetch_all", fetch_all)

    out = al.structure_everything(_auth())
    assert out["queued"] == 1
    kind, grade, subject, payload = queue.jobs[0]
    assert (kind, grade, subject) == ("pipeline", "grade-7", "Mathematics")
    assert payload["steps"] == ["strands", "substrands"] and payload["index"] == 0
    assert queue.started == 1


def test_an_ingested_document_queues_the_spine_for_bare_learning_areas(queue, monkeypatch):
    calls = []
    monkeypatch.setattr(di, "process_item", lambda item_id, force=False: calls.append((item_id, force)) or {"ok": True})
    monkeypatch.setattr(al, "_queue_missing_structure",
                        lambda grade="", subject="": [{"grade": grade, "subject": "Mathematics", "job_id": "job_x"}])

    out = cur._run_queued_dataset_item(
        {"grade": "grade-7", "payload": {"item_id": "m7", "then_structure": True}}
    )
    assert calls == [("m7", False)]
    assert out["structure_queued"] == [{"grade": "grade-7", "subject": "Mathematics", "job_id": "job_x"}]


def test_without_the_flag_the_document_is_ingested_and_nothing_follows(queue, monkeypatch):
    monkeypatch.setattr(di, "process_item", lambda item_id, force=False: {"ok": True})
    followed = []
    monkeypatch.setattr(al, "_queue_missing_structure", lambda **kw: followed.append(kw) or [])
    out = cur._run_queued_dataset_item({"grade": "grade-7", "payload": {"item_id": "m7"}})
    assert out == {"ok": True} and followed == []

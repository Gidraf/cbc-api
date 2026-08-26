"""Dataset item tracking: what is queued, what is running, what is done."""
from __future__ import annotations

import pytest

from app.services import dataset_ingest as di


class FakeDb:
    """Just enough of the table this module touches."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def fetch_all(self, query, params=None):
        params = params or {}
        if "SELECT item_id FROM dataset_ingest_status" in query:
            return [{"item_id": r["item_id"]} for r in self.rows.values()
                    if r["grade"] == params.get("grade")]
        if "GROUP BY grade, status" in query:
            out: dict[tuple, int] = {}
            for r in self.rows.values():
                key = (r["grade"], r["status"])
                out[key] = out.get(key, 0) + 1
            return [{"grade": g, "status": s, "n": n} for (g, s), n in out.items()]
        return [dict(r) for r in self.rows.values() if r["grade"] == params.get("grade")]

    def fetch_one(self, query, params=None):
        return self.rows.get((params or {}).get("item_id"))

    def execute(self, query, params=None):
        params = params or {}
        item_id = params.get("item_id")
        if query.strip().upper().startswith("INSERT"):
            self.rows.setdefault(item_id, {
                "item_id": item_id, "grade": params["grade"],
                "file_id": params.get("file_id", ""), "title": params.get("title", ""),
                "declared_subject": params.get("declared_subject", ""),
                "resolved_subject": "", "design_id": None, "status": "pending",
                "char_count": 0, "error": "", "selected_at": None,
                "started_at": None, "finished_at": None, "updated_at": None,
            })
            return
        row = self.rows[item_id]
        row["status"] = params["status"]
        for key in ("error", "resolved_subject", "design_id", "char_count"):
            if key in params:
                row[key] = params[key]
        if params["status"] == "pending" and "error" not in params:
            row["error"] = ""


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(di, "fetch_all", fake.fetch_all)
    monkeypatch.setattr(di, "fetch_one", fake.fetch_one)
    monkeypatch.setattr(di, "execute", fake.execute)
    return fake


def items(*specs):
    return [
        {"id": i, "input": {"file_id": f, "title": t, "subject": s},
         "expected_output": "TEXT", "metadata": {}}
        for i, f, t, s in specs
    ]


def stub_dataset(monkeypatch, data):
    monkeypatch.setattr(di.langfuse_context_service, "get_grade_dataset", lambda _g: data)


def test_sync_registers_new_items_as_pending(db, monkeypatch):
    stub_dataset(monkeypatch, items(
        ("grade-4__a", "a", "French.pdf", "French"),
        ("grade-4__b", "b", "Maths.pdf", "Mathematics"),
    ))
    result = di.sync_grade("grade-4")
    assert result["added"] == 2
    assert di.list_grade("grade-4")["counts"]["pending"] == 2


def test_resync_does_not_requeue_finished_work(db, monkeypatch):
    """A refresh must never reset an item that has already been ingested."""
    stub_dataset(monkeypatch, items(("grade-4__a", "a", "French.pdf", "French")))
    di.sync_grade("grade-4")
    di.set_status("grade-4__a", di.INGESTED, resolved_subject="French")

    again = di.sync_grade("grade-4")
    assert again["added"] == 0
    assert db.rows["grade-4__a"]["status"] == "ingested"


def test_placeholder_items_are_never_tracked(db, monkeypatch):
    """The development fallback is not curriculum and must not enter the queue."""
    stub_dataset(monkeypatch, [
        {"id": "itm_grade-4_default", "is_placeholder": True, "input": {}, "metadata": {}},
    ])
    result = di.sync_grade("grade-4")
    assert result["added"] == 0
    assert result["placeholders"] == 1


def test_status_progression_and_percentage(db, monkeypatch):
    stub_dataset(monkeypatch, items(
        ("grade-4__a", "a", "A.pdf", "French"),
        ("grade-4__b", "b", "B.pdf", "Maths"),
        ("grade-4__c", "c", "C.pdf", "CRE"),
        ("grade-4__d", "d", "D.pdf", "IRE"),
    ))
    di.sync_grade("grade-4")
    di.set_status("grade-4__a", di.INGESTED)
    di.set_status("grade-4__b", di.PROCESSING)
    di.set_status("grade-4__c", di.SELECTED)

    state = di.list_grade("grade-4")
    assert state["counts"] == {"pending": 1, "selected": 1, "processing": 1,
                               "ingested": 1, "failed": 0}
    assert state["ingested_percentage"] == 25.0
    assert state["in_progress"] == 2


def test_retry_clears_the_stale_error(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-4__a", "a", "A.pdf", "French")))
    di.sync_grade("grade-4")
    di.set_status("grade-4__a", di.FAILED, error="cover unreadable")
    assert db.rows["grade-4__a"]["error"] == "cover unreadable"

    di.set_status("grade-4__a", di.PENDING)
    assert db.rows["grade-4__a"]["status"] == "pending"
    assert db.rows["grade-4__a"]["error"] == ""


def test_unknown_status_is_rejected(db):
    with pytest.raises(ValueError, match="unknown status"):
        di.set_status("x", "almost-done")


def test_grade_summaries_report_each_grade_separately(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-4__a", "a", "A.pdf", "French")))
    di.sync_grade("grade-4")
    stub_dataset(monkeypatch, items(
        ("grade-10__x", "x", "X.pdf", "Pure Sciences"),
        ("grade-10__y", "y", "Y.pdf", "Pure Sciences"),
    ))
    di.sync_grade("grade-10")
    di.set_status("grade-10__x", di.INGESTED)

    summary = di.grade_summaries()
    assert summary["grade-4"]["total"] == 1
    assert summary["grade-10"]["total"] == 2
    assert summary["grade-10"]["ingested_percentage"] == 50.0


def test_processing_records_the_resolved_subject(db, monkeypatch):
    """The subject stored is the one the cover gave, not the catalogue label."""
    stub_dataset(monkeypatch, items(("grade-10__x", "x", "Chem.pdf", "Pure Sciences #2")))
    di.sync_grade("grade-10")

    import app.services.curriculum_extractor as extractor
    monkeypatch.setattr(
        extractor.curriculum_extractor, "ingest_raw_curriculum",
        lambda payload: {"subject": "Chemistry", "grade": "grade-10", "design_id": "d1"},
    )

    result = di.process_item("grade-10__x")
    assert result["subject"] == "Chemistry"
    row = db.rows["grade-10__x"]
    assert row["status"] == "ingested"
    assert row["resolved_subject"] == "Chemistry"
    assert row["declared_subject"] == "Pure Sciences #2"


def test_a_failed_ingest_is_recorded_and_reraised(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-4__a", "a", "A.pdf", "French")))
    di.sync_grade("grade-4")

    import app.services.curriculum_extractor as extractor

    def boom(_payload):
        raise RuntimeError("empty payload")

    monkeypatch.setattr(extractor.curriculum_extractor, "ingest_raw_curriculum", boom)

    with pytest.raises(RuntimeError, match="empty payload"):
        di.process_item("grade-4__a")

    row = db.rows["grade-4__a"]
    assert row["status"] == "failed"
    assert "empty payload" in row["error"]


def test_item_removed_from_langfuse_is_marked_failed(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-4__a", "a", "A.pdf", "French")))
    di.sync_grade("grade-4")
    stub_dataset(monkeypatch, [])

    with pytest.raises(LookupError):
        di.process_item("grade-4__a")
    assert db.rows["grade-4__a"]["status"] == "failed"

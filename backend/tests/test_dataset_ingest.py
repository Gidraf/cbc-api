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
        if "SELECT item_id FROM dataset_ingest_status WHERE grade = :grade" in query:
            return [{"item_id": r["item_id"]} for r in self.rows.values()
                    if r["grade"] == params.get("grade")]
        if "WHERE file_id = :file_id" in query:
            return [dict(r) for r in self.rows.values()
                    if r["file_id"] == params.get("file_id")]
        if "design_id = :design_id AND item_id <> :item_id" in query:
            return [
                {"item_id": r["item_id"]} for r in self.rows.values()
                if r.get("design_id") == params.get("design_id")
                and r["item_id"] != params.get("item_id")
                and r["status"] == "ingested"
            ]
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
    _DATASETS.clear()
    fake = FakeDb()
    monkeypatch.setattr(di, "fetch_all", fake.fetch_all)
    monkeypatch.setattr(di, "fetch_one", fake.fetch_one)
    monkeypatch.setattr(di, "execute", fake.execute)
    return fake


# Long enough to clear MIN_DOCUMENT_CHARS: a real curriculum design runs to
# tens of thousands of characters, and sync now refuses anything shorter as
# not-a-document.
DOC_TEXT = "CURRICULUM DESIGN\n" + ("STRAND 1.0 CONTENT LINE\n" * 60)


def items(*specs):
    return [
        {"id": i, "input": {"file_id": f, "title": t, "subject": s},
         "expected_output": DOC_TEXT, "metadata": {}}
        for i, f, t, s in specs
    ]


# Datasets are per grade, so the stub has to be too: replacing every grade's
# items at once made one grade's fixture erase another's.
_DATASETS: dict[str, list] = {}


def stub_dataset(monkeypatch, data, grade=None):
    if grade is None:
        grade = data[0]["id"].split("__")[0] if data else "grade-4"
    _DATASETS[grade] = data
    monkeypatch.setattr(
        di.langfuse_context_service, "get_grade_dataset",
        lambda g: _DATASETS.get(g, []),
    )


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
    ], grade="grade-4")
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
    stub_dataset(monkeypatch, [], grade="grade-4")

    with pytest.raises(LookupError):
        di.process_item("grade-4__a")
    assert db.rows["grade-4__a"]["status"] == "failed"


# ── Reprocessing and data hygiene ────────────────────────────────────────────

def _stub_extractor(monkeypatch, subject="Chemistry", design_id="d1"):
    import app.services.curriculum_extractor as extractor
    monkeypatch.setattr(
        extractor.curriculum_extractor, "ingest_raw_curriculum",
        lambda payload: {"subject": subject, "grade": "grade-10", "design_id": design_id},
    )


def test_processing_twice_is_refused(db, monkeypatch):
    """The same document must not be ingested repeatedly by accident."""
    stub_dataset(monkeypatch, items(("grade-10__x", "x", "Chem.pdf", "Pure Sciences")))
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch)

    di.process_item("grade-10__x")
    with pytest.raises(di.AlreadyIngested, match="already been ingested"):
        di.process_item("grade-10__x")


def test_force_replaces_the_previous_design(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-10__x", "x", "Chem.pdf", "Pure Sciences")))
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch, design_id="d1")
    di.process_item("grade-10__x")

    deleted: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if "DELETE FROM curriculum_designs" in query:
            deleted.append((params or {})["design_id"])
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    _stub_extractor(monkeypatch, subject="Chemistry", design_id="d1")
    di.process_item("grade-10__x", force=True)

    assert deleted == ["d1"], "the previous design should be discarded before re-ingest"
    assert db.rows["grade-10__x"]["status"] == "ingested"


def test_force_does_not_delete_a_design_another_item_still_claims(db, monkeypatch):
    """The Lower Primary design is filed under Grades 1-3; one must not wipe another."""
    stub_dataset(monkeypatch, items(("grade-1__a", "a", "Maths.pdf", "Mathematics")))
    di.sync_grade("grade-1")
    stub_dataset(monkeypatch, items(("grade-2__a", "a", "Maths.pdf", "Mathematics")))
    di.sync_grade("grade-2")

    _stub_extractor(monkeypatch, subject="Mathematics", design_id="shared")
    di.process_item("grade-1__a")
    di.process_item("grade-2__a")

    deleted: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if "DELETE FROM curriculum_designs" in query:
            deleted.append((params or {})["design_id"])
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    stub_dataset(monkeypatch, items(("grade-1__a", "a", "Maths.pdf", "Mathematics")))
    di.process_item("grade-1__a", force=True)

    assert deleted == [], "a design another ingested item still points at must survive"


def test_force_on_a_never_ingested_item_just_processes_it(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-10__x", "x", "Chem.pdf", "Pure Sciences")))
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch)

    result = di.process_item("grade-10__x", force=True)
    assert result["subject"] == "Chemistry"
    assert db.rows["grade-10__x"]["status"] == "ingested"


# ── Reconciling ingestion started outside process_item ───────────────────────

def test_finds_the_tracked_row_by_item_id(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-10__x", "x", "Chem.pdf", "Pure Sciences")))
    di.sync_grade("grade-10")
    assert di.find_tracked_item({"item_id": "grade-10__x"})["item_id"] == "grade-10__x"


def test_finds_the_tracked_row_by_file_id_when_unambiguous(db, monkeypatch):
    stub_dataset(monkeypatch, items(("grade-10__x", "chem-file", "Chem.pdf", "Pure Sciences")))
    di.sync_grade("grade-10")
    assert di.find_tracked_item({"file_id": "chem-file"})["item_id"] == "grade-10__x"


def test_ambiguous_file_id_matches_nothing(db, monkeypatch):
    """One document tracked under Grades 1-3 cannot be resolved by file_id alone."""
    for g in ("grade-1", "grade-2", "grade-3"):
        stub_dataset(monkeypatch, items((f"{g}__a", "shared-file", "Maths.pdf", "Mathematics")), grade=g)
        di.sync_grade(g)
    assert di.find_tracked_item({"file_id": "shared-file"}) is None


def test_external_ingest_marks_the_item_done(db, monkeypatch):
    """A run started from the legacy screen must still show as ingested."""
    stub_dataset(monkeypatch, items(("grade-10__x", "x", "Chem.pdf", "Pure Sciences")))
    di.sync_grade("grade-10")
    assert db.rows["grade-10__x"]["status"] == "pending"

    di.record_external_ingest(
        {"item_id": "grade-10__x", "output": "TEXT"},
        {"subject": "Chemistry", "design_id": "d1"},
    )

    row = db.rows["grade-10__x"]
    assert row["status"] == "ingested"
    assert row["resolved_subject"] == "Chemistry"
    assert row["design_id"] == "d1"


def test_external_ingest_of_an_untracked_payload_is_harmless(db):
    assert di.record_external_ingest({"file_id": "nope", "output": "x"}, {"subject": "X"}) is None


def test_result_records_written_back_by_the_extractor_are_never_queued(db, monkeypatch):
    """The shape that polluted grade-dte: no text, random id, no file_id.

    _sync_to_langfuse used to write ingest *results* into the same per-grade
    dataset that holds input, so they appeared as empty documents waiting to be
    processed.
    """
    stub_dataset(monkeypatch, [
        {"id": "1821b492-fb90-42b2-bb73-5c666da75250",
         "input": {"subject": "Diploma In Teacher Education"},
         "expected_output": "", "metadata": {"source": "curriculum_extractor"}},
        {"id": "grade-dte__real", "input": {"file_id": "real", "title": "DTE Agriculture.pdf"},
         "expected_output": DOC_TEXT, "metadata": {}},
    ], grade="grade-dte")

    result = di.sync_grade("grade-dte")
    assert result["added"] == 1
    assert result["skipped_empty"] == 1
    assert list(db.rows) == ["grade-dte__real"]


def test_blueprints_go_to_their_own_dataset():
    """Results must not be written into the dataset that holds input."""
    from app.services.langfuse_context import langfuse_context_service as svc

    assert svc.blueprint_dataset_name("grade-dte") == "grade-dte-blueprints"
    assert svc.blueprint_dataset_name("grade-dte") != "grade-dte"


# ── Documents are found wherever they live ───────────────────────────────────
# All 242 designs sit in one combined dataset. Requiring a re-upload before the
# console shows anything is a worse answer than routing by each item's grade.

def raw_row(dataset, item_id, title, level="", subject="", grade="", text=None):
    return {
        "dataset_name": dataset, "item_id": item_id, "title": title,
        "level": level, "subject": subject, "grade": grade,
        "file_id": item_id, "output": DOC_TEXT if text is None else text,
        "metadata": {},
    }


@pytest.mark.parametrize("row,expected", [
    (raw_row("CBC_Research_Curriculum_Designs", "a", "French Grade 4.pdf", level="Grade 4"), ["grade-4"]),
    (raw_row("CBC_Research_Curriculum_Designs", "b", "Chemistry Grade 12 - March 2026.pdf"), ["grade-12"]),
    (raw_row("CBC_Research_Curriculum_Designs", "c", "Maths.pdf", level="Lower Primary (Grades 1-3)"),
     ["grade-1", "grade-2", "grade-3"]),
    (raw_row("CBC_Research_Curriculum_Designs", "d", "DTE SOCIAL STUDIES.pdf"), ["grade-dte"]),
    (raw_row("CBC_Research_Curriculum_Designs", "e", "PP1.pdf", level="Pre-Primary 1 (PP1)"), ["grade-pp1"]),
    (raw_row("CBC_Research_Curriculum_Designs", "f", "x.pdf", grade="grade-9"), ["grade-9"]),
    (raw_row("CBC_Research_Curriculum_Designs", "g", "unknown.pdf"), []),
])
def test_grade_is_resolved_from_the_item_itself(row, expected):
    assert di.grades_for_item(row) == expected


def test_sync_picks_up_documents_from_the_combined_dataset(db, monkeypatch):
    """The real situation: grade datasets empty, everything in one dataset."""
    stub_dataset(monkeypatch, [], grade="grade-12")
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse",
        lambda: [
            raw_row("CBC_Research_Curriculum_Designs", "chem", "Chemistry Grade 12 - March 2026.pdf"),
            raw_row("CBC_Research_Curriculum_Designs", "geo", "Geography Grade 12 - March 2026.pdf"),
            raw_row("CBC_Research_Curriculum_Designs", "fr", "French Grade 4.pdf", level="Grade 4"),
        ],
    )

    result = di.sync_grade("grade-12")
    assert result["added"] == 2, "only the Grade 12 documents belong to this grade"
    assert sorted(db.rows) == ["chem", "geo"]
    assert db.rows["chem"]["title"] == "Chemistry Grade 12 - March 2026.pdf"


def test_sweep_still_ignores_the_empty_result_records(db, monkeypatch):
    stub_dataset(monkeypatch, [], grade="grade-dte")
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse",
        lambda: [
            raw_row("grade-dte", "1821b492-uuid", "", level="", text=""),
            raw_row("CBC_Research_Curriculum_Designs", "dte-real", "DTE SOCIAL STUDIES.pdf"),
        ],
    )

    result = di.sync_grade("grade-dte")
    assert result["added"] == 1
    assert list(db.rows) == ["dte-real"]


def test_an_item_in_both_places_is_registered_once(db, monkeypatch):
    stub_dataset(monkeypatch, items(("dup", "dup", "Chemistry Grade 12.pdf", "Chemistry")), grade="grade-12")
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse",
        lambda: [raw_row("CBC_Research_Curriculum_Designs", "dup", "Chemistry Grade 12.pdf")],
    )
    assert di.sync_grade("grade-12")["added"] == 1

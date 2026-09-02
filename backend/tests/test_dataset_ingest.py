"""Dataset item tracking: what is queued, what is running, what is done."""
from __future__ import annotations

import json

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
        if "design_id = :design_id OR design_ids::text LIKE" in query:
            wanted = params.get("design_id")
            return [
                {"item_id": r["item_id"]} for r in self.rows.values()
                if (r.get("design_id") == wanted or wanted in (r.get("design_ids") or []))
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
                "item_id": item_id, "source_item_id": params.get("source_item_id", item_id),
                "grade": params["grade"],
                "file_id": params.get("file_id", ""), "title": params.get("title", ""),
                "declared_subject": params.get("declared_subject", ""),
                "resolved_subject": "", "design_id": None, "design_ids": [],
                "learning_areas_missing": [], "status": "pending",
                "char_count": 0, "error": "", "selected_at": None,
                "started_at": None, "finished_at": None, "updated_at": None,
            })
            return
        if query.strip().upper().startswith("DELETE"):
            # Deletions target other tables (curriculum_designs and friends),
            # which this double does not model.
            return
        row = self.rows[item_id]
        if "SET status = 'pending'" in query:
            # The un-ingest reset: status is a literal in the SQL, not a param.
            row.update({
                "status": "pending", "design_id": None, "design_ids": [],
                "learning_areas_missing": [], "resolved_subject": "",
                "char_count": 0, "error": "", "selected_at": None,
                "started_at": None, "finished_at": None,
            })
            return
        row["status"] = params["status"]
        for key in ("error", "resolved_subject", "design_id", "char_count"):
            if key in params:
                row[key] = params[key]
        # set_status writes these as JSON text via CAST(... AS jsonb).
        for key in ("design_ids", "learning_areas_missing"):
            if key in params:
                value = params[key]
                row[key] = json.loads(value) if isinstance(value, str) else list(value or [])
        if params["status"] == "pending" and "error" not in params:
            row["error"] = ""


@pytest.fixture
def db(monkeypatch):
    _DATASETS.clear()
    # Default the cross-dataset sweep to empty; tests that exercise it override.
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse", lambda: []
    )
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


def stub_dataset(monkeypatch, data, grade="grade-4"):
    _DATASETS[grade] = data
    monkeypatch.setattr(
        di.langfuse_context_service, "get_grade_dataset",
        lambda g: _DATASETS.get(g, []),
    )


def test_sync_registers_new_items_as_pending(db, monkeypatch):
    stub_dataset(monkeypatch, items(
        ("a", "a", "French.pdf", "French"),
        ("b", "b", "Maths.pdf", "Mathematics"),
    ))
    result = di.sync_grade("grade-4")
    assert result["added"] == 2
    assert di.list_grade("grade-4")["counts"]["pending"] == 2


def test_resync_does_not_requeue_finished_work(db, monkeypatch):
    """A refresh must never reset an item that has already been ingested."""
    stub_dataset(monkeypatch, items(("a", "a", "French.pdf", "French")))
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
    # The sweep over other datasets must not resurrect it either.
    monkeypatch.setattr(di.langfuse_context_service, "fetch_raw_datasets_from_langfuse", lambda: [])
    result = di.sync_grade("grade-4")
    assert result["added"] == 0
    assert result["placeholders"] == 1


def test_status_progression_and_percentage(db, monkeypatch):
    stub_dataset(monkeypatch, items(
        ("a", "a", "A.pdf", "French"),
        ("b", "b", "B.pdf", "Maths"),
        ("c", "c", "C.pdf", "CRE"),
        ("d", "d", "D.pdf", "IRE"),
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
    stub_dataset(monkeypatch, items(("a", "a", "A.pdf", "French")))
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
    stub_dataset(monkeypatch, items(("a", "a", "A.pdf", "French")))
    di.sync_grade("grade-4")
    stub_dataset(monkeypatch, items(
        ("x", "x", "X.pdf", "Pure Sciences"),
        ("y", "y", "Y.pdf", "Pure Sciences"),
    ), grade="grade-10")
    di.sync_grade("grade-10")
    di.set_status("grade-10__x", di.INGESTED)

    summary = di.grade_summaries()
    assert summary["grade-4"]["total"] == 1
    assert summary["grade-10"]["total"] == 2
    assert summary["grade-10"]["ingested_percentage"] == 50.0


def test_processing_records_the_resolved_subject(db, monkeypatch):
    """The subject stored is the one the cover gave, not the catalogue label."""
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences #2")), grade="grade-10")
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
    stub_dataset(monkeypatch, items(("a", "a", "A.pdf", "French")))
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
    stub_dataset(monkeypatch, items(("a", "a", "A.pdf", "French")))
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
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch)

    di.process_item("grade-10__x")
    with pytest.raises(di.AlreadyIngested, match="already been ingested"):
        di.process_item("grade-10__x")


def test_force_replaces_the_previous_design(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
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
    doc = items(("a", "a", "Maths.pdf", "Mathematics"))
    stub_dataset(monkeypatch, doc, grade="grade-1")
    di.sync_grade("grade-1")
    stub_dataset(monkeypatch, doc, grade="grade-2")
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
    stub_dataset(monkeypatch, items(("a", "a", "Maths.pdf", "Mathematics")))
    di.process_item("grade-1__a", force=True)

    assert deleted == [], "a design another ingested item still points at must survive"


def test_force_on_a_never_ingested_item_just_processes_it(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch)

    result = di.process_item("grade-10__x", force=True)
    assert result["subject"] == "Chemistry"
    assert db.rows["grade-10__x"]["status"] == "ingested"


# ── Reconciling ingestion started outside process_item ───────────────────────

def test_finds_the_tracked_row_by_item_id(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    assert di.find_tracked_item({"item_id": "grade-10__x"})["item_id"] == "grade-10__x"


def test_finds_the_tracked_row_by_file_id_when_unambiguous(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "chem-file", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    assert di.find_tracked_item({"file_id": "chem-file"})["item_id"] == "grade-10__x"


def test_ambiguous_file_id_matches_nothing(db, monkeypatch):
    """One document tracked under Grades 1-3 cannot be resolved by file_id alone."""
    for g in ("grade-1", "grade-2", "grade-3"):
        stub_dataset(monkeypatch, items(("a", "shared-file", "Maths.pdf", "Mathematics")), grade=g)
        di.sync_grade(g)
    assert di.find_tracked_item({"file_id": "shared-file"}) is None


def test_external_ingest_marks_the_item_done(db, monkeypatch):
    """A run started from the legacy screen must still show as ingested."""
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
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
        {"id": "real", "input": {"file_id": "real", "title": "DTE Agriculture.pdf"},
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
    assert sorted(db.rows) == ["grade-12__chem", "grade-12__geo"]
    assert db.rows["grade-12__chem"]["title"] == "Chemistry Grade 12 - March 2026.pdf"


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
    assert list(db.rows) == ["grade-dte__dte-real"]


def test_an_item_in_both_places_is_registered_once(db, monkeypatch):
    stub_dataset(monkeypatch, items(("dup", "dup", "Chemistry Grade 12.pdf", "Chemistry")), grade="grade-12")
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse",
        lambda: [raw_row("CBC_Research_Curriculum_Designs", "dup", "Chemistry Grade 12.pdf")],
    )
    assert di.sync_grade("grade-12")["added"] == 1


# ── One document, several grades ─────────────────────────────────────────────
# KICD publishes a single Lower Primary design covering Grades 1-3. It must be
# tracked and processed independently under each, not claimed by whichever
# grade happened to sync first.

@pytest.mark.parametrize("title,expected", [
    ("Grade 1-3 CRE - Revised.pdf", ["grade-1", "grade-2", "grade-3"]),
    ("Grade 1-3 Mathematics - Revised.pdf", ["grade-1", "grade-2", "grade-3"]),
    ("Grades 1 to 3 Kiswahili.pdf", ["grade-1", "grade-2", "grade-3"]),
    ("Grade 4-6 Science.pdf", ["grade-4", "grade-5", "grade-6"]),
    # A single grade must still resolve to exactly one.
    ("Chemistry Grade 12 - March 2026.pdf", ["grade-12"]),
])
def test_a_grade_range_in_the_title_covers_every_grade_in_it(title, expected):
    assert di.grades_for_item(raw_row("CBC_Research_Curriculum_Designs", "x", title)) == expected


def test_the_same_document_is_tracked_under_each_of_its_grades(db, monkeypatch):
    """Grade 1 syncing first must not leave Grades 2 and 3 empty."""
    lower_primary = [
        raw_row("CBC_Research_Curriculum_Designs", "cre", "Grade 1-3 CRE - Revised.pdf"),
        raw_row("CBC_Research_Curriculum_Designs", "mat", "Grade 1-3 Mathematics - Revised.pdf"),
    ]
    for g in ("grade-1", "grade-2", "grade-3"):
        stub_dataset(monkeypatch, [], grade=g)
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse", lambda: lower_primary
    )

    for g in ("grade-1", "grade-2", "grade-3"):
        assert di.sync_grade(g)["added"] == 2, f"{g} should get both documents"

    for g in ("grade-1", "grade-2", "grade-3"):
        assert di.list_grade(g)["total"] == 2

    # Six tracking rows over two documents.
    assert len(db.rows) == 6
    assert db.rows["grade-2__cre"]["source_item_id"] == "cre"


def test_each_grade_is_processed_and_marked_independently(db, monkeypatch):
    docs = [raw_row("CBC_Research_Curriculum_Designs", "cre", "Grade 1-3 CRE - Revised.pdf")]
    for g in ("grade-1", "grade-2", "grade-3"):
        stub_dataset(monkeypatch, [], grade=g)
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse", lambda: docs
    )
    for g in ("grade-1", "grade-2", "grade-3"):
        di.sync_grade(g)

    import app.services.curriculum_extractor as extractor
    monkeypatch.setattr(
        extractor.curriculum_extractor, "ingest_raw_curriculum",
        lambda payload: {"subject": "CRE", "grade": payload.get("grade"), "design_id": "d-cre"},
    )

    di.process_item("grade-2__cre")

    assert db.rows["grade-2__cre"]["status"] == "ingested"
    assert db.rows["grade-1__cre"]["status"] == "pending"
    assert db.rows["grade-3__cre"]["status"] == "pending"
    assert di.list_grade("grade-2")["counts"]["ingested"] == 1
    assert di.list_grade("grade-1")["counts"]["pending"] == 1


# ── Un-ingest ────────────────────────────────────────────────────────────────

def test_uningest_removes_the_design_and_returns_the_item_to_pending(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch, subject="Chemistry", design_id="d1")
    di.process_item("grade-10__x")
    assert db.rows["grade-10__x"]["status"] == "ingested"

    deleted: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if "DELETE FROM curriculum_designs" in query:
            deleted.append((params or {})["design_id"])
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    monkeypatch.setattr(di, "fetch_all", lambda q, p=None: [{"n": 4}] if "COUNT(*)" in q else [])

    result = di.uningest_item("grade-10__x")

    assert deleted == ["d1"]
    assert result["removed"]["design"] == 1
    assert result["removed"]["substrands"] == 4


def test_uningest_leaves_generated_content_alone_by_default(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch, subject="Chemistry", design_id="d1")
    di.process_item("grade-10__x")

    touched: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if "substrand_resources" in query or "question_dna" in query:
            touched.append(query)
            return
        if "DELETE FROM curriculum_designs" in query:
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    monkeypatch.setattr(di, "fetch_all", lambda q, p=None: [{"n": 0}] if "COUNT(*)" in q else [])

    di.uningest_item("grade-10__x")
    assert touched == [], "notes and questions must survive unless purge is asked for"


def test_uningest_with_purge_removes_generated_content(db, monkeypatch):
    stub_dataset(monkeypatch, items(("x", "x", "Chem.pdf", "Pure Sciences")), grade="grade-10")
    di.sync_grade("grade-10")
    _stub_extractor(monkeypatch, subject="Chemistry", design_id="d1")
    di.process_item("grade-10__x")

    deletes: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if query.strip().upper().startswith("DELETE"):
            deletes.append(query)
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    monkeypatch.setattr(di, "fetch_all", lambda q, p=None: [{"n": 2}] if "COUNT(*)" in q else [])

    result = di.uningest_item("grade-10__x", purge_generated=True)

    assert any("substrand_resources" in q for q in deletes)
    assert any("question_dna" in q for q in deletes)
    assert result["removed"]["bundles"] == 2
    assert result["removed"]["questions"] == 2


def test_uningest_does_not_delete_a_design_another_grade_still_uses(db, monkeypatch):
    doc = items(("a", "a", "Maths.pdf", "Mathematics"))
    for g in ("grade-1", "grade-2"):
        stub_dataset(monkeypatch, doc, grade=g)
        di.sync_grade(g)
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
    di.uningest_item("grade-1__a")

    assert deleted == [], "Grade 2 still points at that design"
    assert db.rows["grade-1__a"]["status"] == "pending"
    assert db.rows["grade-2__a"]["status"] == "ingested"


# ── Backfilling a design's source document ──────────────────────────────────
# Designs ingested before the text was stored carry only a character count, so
# every agent asking for the source finds nothing and invents from its own
# knowledge. The document is still in Langfuse.

class AttachDb(FakeDb):
    def __init__(self, design):
        super().__init__()
        self.design = design
        self.updated = None

    def fetch_one(self, query, params=None):
        if "FROM curriculum_designs" in query:
            return self.design
        return super().fetch_one(query, params)

    def execute(self, query, params=None):
        if "UPDATE curriculum_designs" in query:
            self.updated = params
            return
        return super().execute(query, params)


@pytest.fixture
def attach(monkeypatch):
    design = {
        "design_id": "cd_pp1_lang", "grade": "grade-pp1", "subject": "Pre-Primary 1",
        "metadata": {"file_id": "doc-1"}, "raw_payload": {"meta": {}, "char_count": 91234},
    }
    db = AttachDb(design)
    monkeypatch.setattr(di, "fetch_all", db.fetch_all)
    monkeypatch.setattr(di, "fetch_one", db.fetch_one)
    monkeypatch.setattr(di, "execute", db.execute)
    monkeypatch.setattr(di, "to_json", lambda v: v)
    return db


def test_source_is_found_by_file_id_and_written_back(attach, monkeypatch):
    stub_dataset(monkeypatch, [], grade="grade-pp1")
    monkeypatch.setattr(
        di.langfuse_context_service, "fetch_raw_datasets_from_langfuse",
        lambda: [raw_row("CBC_Research_Curriculum_Designs", "doc-1", "PP1 Language.pdf",
                         level="Pre-Primary 1 (PP1)")],
    )
    result = di.attach_source_document(design_id="cd_pp1_lang")

    assert result["attached"] is True
    assert result["chars"] > di.MIN_DOCUMENT_CHARS
    assert attach.updated["p"]["source_text"].startswith("CURRICULUM DESIGN")


def test_a_design_that_already_has_its_text_is_left_alone(attach, monkeypatch):
    attach.design["raw_payload"] = {"source_text": DOC_TEXT}
    stub_dataset(monkeypatch, [], grade="grade-pp1")
    monkeypatch.setattr(di.langfuse_context_service, "fetch_raw_datasets_from_langfuse", lambda: [])

    result = di.attach_source_document(design_id="cd_pp1_lang")
    assert result["attached"] is False
    assert attach.updated is None, "an already-attached design must not be rewritten"


def test_a_missing_document_says_so_rather_than_attaching_nothing(attach, monkeypatch):
    stub_dataset(monkeypatch, [], grade="grade-pp1")
    monkeypatch.setattr(di.langfuse_context_service, "fetch_raw_datasets_from_langfuse", lambda: [])

    with pytest.raises(LookupError, match="Sync the grade"):
        di.attach_source_document(design_id="cd_pp1_lang")
    assert attach.updated is None


def _stub_combined_extractor(monkeypatch, areas, missing=()):
    """An extractor that behaves like a Pre-Primary ingest: many designs, one item."""
    from app.services import curriculum_extractor as extractor

    def fake(payload):
        return {
            "status": "partial" if missing else "success",
            "subject": areas[0],
            "design_id": f"cd_{areas[0].lower().replace(' ', '_')}",
            "combined_design": True,
            "expected_learning_areas": list(areas) + list(missing),
            "learning_areas_missing": list(missing),
            "learning_areas": [
                {"subject": a, "status": "success",
                 "design_id": f"cd_{a.lower().replace(' ', '_')}", "substrand_count": 3}
                for a in areas
            ],
        }

    monkeypatch.setattr(extractor.curriculum_extractor, "ingest_raw_curriculum", fake)


PP1_AREAS = ["Language Activities", "Mathematical Activities", "Creative Activities",
             "Environmental Activities", "Christian Religious Education",
             "Hindu Religious Education", "Islamic Religious Education"]


def test_reprocessing_a_combined_design_discards_every_design_it_made(db, monkeypatch):
    """One Pre-Primary document produces seven designs. Tracking recorded only
    the first, so force discarded one and orphaned six, then wrote seven more."""
    stub_dataset(monkeypatch, items(("a", "a", "PP1.pdf", "Pre-Primary 1")), grade="grade-pp1")
    di.sync_grade("grade-pp1")

    _stub_combined_extractor(monkeypatch, PP1_AREAS)
    di.process_item("grade-pp1__a")

    row = db.rows["grade-pp1__a"]
    assert len(row["design_ids"]) == 7, "every design the item produced must be tracked"

    deleted: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if "DELETE FROM curriculum_designs" in query:
            deleted.append((params or {})["design_id"])
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    stub_dataset(monkeypatch, items(("a", "a", "PP1.pdf", "Pre-Primary 1")), grade="grade-pp1")
    di.process_item("grade-pp1__a", force=True)

    assert len(deleted) == 7, f"only discarded {deleted}"
    assert "cd_hindu_religious_education" in deleted
    assert "cd_mathematical_activities" in deleted


def test_reprocess_runs_the_same_split_as_a_first_ingest(db, monkeypatch):
    """Reprocess must not be a lesser path: it calls the same extractor, so the
    splitting, canonicalisation and completeness check all apply."""
    stub_dataset(monkeypatch, items(("a", "a", "PP1.pdf", "Pre-Primary 1")), grade="grade-pp1")
    di.sync_grade("grade-pp1")

    calls: list[str] = []
    from app.services import curriculum_extractor as extractor

    def fake(payload):
        calls.append("ingest")
        return {
            "status": "success", "subject": "Language Activities",
            "design_id": "cd_language", "combined_design": True,
            "expected_learning_areas": PP1_AREAS, "learning_areas_missing": [],
            "learning_areas": [
                {"subject": a, "status": "success", "design_id": f"cd_{a[:4].lower()}",
                 "substrand_count": 1} for a in PP1_AREAS
            ],
        }

    monkeypatch.setattr(extractor.curriculum_extractor, "ingest_raw_curriculum", fake)

    di.process_item("grade-pp1__a")
    stub_dataset(monkeypatch, items(("a", "a", "PP1.pdf", "Pre-Primary 1")), grade="grade-pp1")
    di.process_item("grade-pp1__a", force=True)

    assert calls == ["ingest", "ingest"], "reprocess must go through the same extractor"
    assert db.rows["grade-pp1__a"]["status"] == "ingested"


def test_a_partial_ingest_raises_so_the_caller_can_catch_it(db, monkeypatch):
    """Six of seven learning areas is not "ingested". Returning quietly is how
    three learning areas sat unnoticed through several rounds of generation."""
    from app.errors import ApiError
    from app.services import curriculum_extractor as extractor

    stub_dataset(monkeypatch, items(("a", "a", "PP1.pdf", "Pre-Primary 1")), grade="grade-pp1")
    di.sync_grade("grade-pp1")

    missing = ["Christian Religious Education", "Hindu Religious Education",
               "Mathematical Activities"]
    partial = {
        "status": "partial", "complete": False,
        "subject": "Language Activities", "design_id": "cd_language",
        "expected_learning_areas": PP1_AREAS, "learning_areas_missing": missing,
        "learning_areas": [
            {"subject": a, "status": "success", "design_id": f"cd_{a[:4].lower()}",
             "substrand_count": 2} for a in PP1_AREAS[:4]
        ],
    }

    def raising(payload, strict=True):
        raise ApiError(
            code="PARTIAL_INGEST",
            message="Ingested 4 of 7 learning areas for grade-pp1. "
                    "Everything that succeeded has been saved; not found in the "
                    "document: " + ", ".join(missing) + ".",
            status_code=422, retryable=False, detail=partial,
        )

    monkeypatch.setattr(extractor.curriculum_extractor, "ingest_raw_curriculum", raising)

    with pytest.raises(ApiError) as caught:
        di.process_item("grade-pp1__a")

    error = caught.value
    assert error.code == "PARTIAL_INGEST"
    assert error.status_code == 422
    assert "Hindu Religious Education" in error.message
    # The caller gets the specifics without parsing prose.
    assert error.detail["learning_areas_missing"] == missing
    assert error.detail["complete"] is False
    saved = [a["subject"] for a in error.detail["learning_areas"]]
    assert "Language Activities" in saved and len(saved) == 4

    # And the four that DID succeed are still tracked, not thrown away.
    row = db.rows["grade-pp1__a"]
    assert row["status"] == "failed", "a partial ingest must not look complete"
    assert row["learning_areas_missing"] == missing
    assert len(row["design_ids"]) == 4, "work that succeeded must stay tracked"
    assert "Hindu Religious Education" in row["error"]


def test_uningesting_a_combined_item_removes_every_design(db, monkeypatch):
    """Un-ingesting only the primary left six learning areas in the database
    while the console reported the item as pending."""
    stub_dataset(monkeypatch, items(("a", "a", "PP1.pdf", "Pre-Primary 1")), grade="grade-pp1")
    di.sync_grade("grade-pp1")
    _stub_combined_extractor(monkeypatch, PP1_AREAS)
    di.process_item("grade-pp1__a")

    deleted: list[str] = []
    real_execute = di.execute

    def spy(query, params=None):
        if "DELETE FROM curriculum_designs" in query:
            deleted.append((params or {})["design_id"])
            return
        return real_execute(query, params)

    monkeypatch.setattr(di, "execute", spy)
    monkeypatch.setattr(di, "fetch_all", lambda q, p=None: (
        [{"n": 3}] if "COUNT(*)" in q else db.fetch_all(q, p)
    ))

    result = di.uningest_item("grade-pp1__a")

    assert len(deleted) == 7, f"only removed {deleted}"
    assert result["removed"]["design"] == 7
    assert db.rows["grade-pp1__a"]["design_ids"] == []


# ── processing a document must not hold the browser ─────────────────────────


def test_processing_queues_rather_than_running_on_the_request() -> None:
    """A 95KB design is about ninety seconds. Pressing Process on one document
    held the request open with every other control in the console disabled —
    sixteen documents was a browser tab nobody could touch for half an hour,
    and a proxy timeout in the middle threw away paid work.
    """
    import inspect

    from app.routes import admin_langfuse

    source = inspect.getsource(admin_langfuse.process_grade_items)
    assert "job_queue.enqueue(" in source
    assert '"dataset_item"' in source
    # The work is not done here any more.
    assert "process_item(item_id" not in source
    # Still one at a time in the worker: that was the point of doing them
    # sequentially, and only the browser stops waiting.
    assert "It is the BROWSER that no longer waits" in source


def test_two_documents_of_one_grade_are_not_taken_for_duplicates() -> None:
    """A grade's sixteen documents share a grade and often a subject, so
    without the item in the key the second queued was swallowed as a duplicate
    of the first and never ran."""
    import inspect

    from app.services import job_queue

    source = inspect.getsource(job_queue.enqueue)
    assert "COALESCE(payload->>'item_id', '') = :item_id" in source
    assert '"item_id": str((payload or {}).get("item_id") or "")' in source


def test_a_queued_item_counts_as_in_progress() -> None:
    """It is not `processing` until the worker picks it up, so a page polling
    on `processing` alone stops refreshing in the gap between pressing Process
    and the work starting — and reads as idle while the queue is full."""
    import inspect

    from app.services import dataset_ingest

    source = inspect.getsource(dataset_ingest.list_grade)
    assert "kind = 'dataset_item'" in source
    assert "counts[SELECTED] + counts[PROCESSING] + queued" in source
    assert '"queued": queued' in source


def test_the_console_stops_disabling_itself_while_it_queues() -> None:
    from pathlib import Path

    screen = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/Datasets.tsx")
        .read_text().split()
    )
    assert "const busy = actions.sync.isPending || actions.retry.isPending;" in screen
    assert "Queueing…" in screen
    assert "waiting for the worker" in screen


def test_a_dataset_item_is_not_a_pipeline_stage() -> None:
    """It is one document being read, not a stage of the chain — and the
    pipeline advances stage by stage against PIPELINE_STEPS."""
    from app.routes import curriculum

    assert "dataset_item" not in curriculum._PIPELINE_HANDLERS
    assert set(curriculum._PIPELINE_HANDLERS) == set(curriculum.PIPELINE_STEPS)


# ── seeing the document the ingest actually saw ─────────────────────────────


def test_the_text_the_ingest_receives_can_be_read_and_copied() -> None:
    """"Read but no design" was chased for several sessions by inference: a
    count is wrong on one screen, so something upstream must be misreading
    something. The document was never visible."""
    import inspect
    from pathlib import Path

    from app.main import app
    from app.routes import admin_langfuse

    assert "/api/v1/admin/langfuse/datasets/{grade}/items/{item_id}/text" in [
        getattr(r, "path", "") for r in app.routes
    ]

    source = inspect.getsource(admin_langfuse.get_item_text)
    # Nothing is written and nothing is re-run.
    assert "process_item" not in source
    assert "_persist_to_db" not in source

    screen = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/ItemText.tsx")
        .read_text().split()
    )
    assert "Copy the whole document" in screen
    assert "Copy the cover" in screen
    assert "as the ingest receives it" in screen


def test_it_shows_the_three_facts_whose_disagreement_is_the_bug() -> None:
    """The text, the parse, and the design rows that exist right now."""
    import inspect
    from pathlib import Path

    from app.routes import admin_langfuse

    source = inspect.getsource(admin_langfuse.get_item_text)
    assert '"text": text' in source
    assert '"parsed": parsed' in source
    # Counted the same way the grade list counts, so the two cannot disagree
    # for a reason nobody can see.
    assert "FROM curriculum_designs" in source
    assert "REPLACE(LOWER(grade), 'grade-', '')" in source
    # And a design the item CLAIMS that is not there is named.
    assert '"claimed_but_absent"' in source

    screen = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/ItemText.tsx")
        .read_text().split()
    )
    assert "reported success and nothing was written" in screen
    assert "The row was written and is gone, or was never written" in screen
    # An empty document would explain everything, so say so rather than showing
    # an empty box.
    assert "carries no text at all" in screen


def test_both_texts_are_shown_because_only_one_of_them_is_read() -> None:
    """The design keeps `raw_payload.source_text`, capped, and everything
    downstream works from THAT copy rather than from Langfuse. A document that
    arrives whole and is stored empty or truncated looks identical from the
    outside, and it is the copy nobody could see.
    """
    import inspect
    from pathlib import Path

    from app.routes import admin_langfuse

    source = inspect.getsource(admin_langfuse.get_item_text)
    assert '"text": text' in source, "as received"
    assert '"source_text"' in source, "as stored with the design"
    assert '"matches_received"' in source
    assert '"truncated"' in source

    screen = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/ItemText.tsx")
        .read_text().split()
    )
    assert "as the ingest receives it" in screen
    assert "as stored with the design" in screen
    assert "Copy the stored text" in screen
    # The stored panel only opens when the two differ — showing the same text
    # twice is noise, and the difference is the whole point.
    assert "!d.stored.matches_received" in screen


def test_a_missing_stored_copy_says_what_it_means() -> None:
    """Nothing downstream has the document to work from — which is a different
    and worse fact than a short one."""
    import inspect

    from app.routes import admin_langfuse

    source = inspect.getsource(admin_langfuse.get_item_text)
    # Wrapped in the source, so match on the halves rather than the line.
    assert "No design holds a stored copy" in source
    assert "nothing downstream has this " in source
    assert "reads the stored copy" in source

"""Today's checks over yesterday's bank."""
from __future__ import annotations

from app.services import bank_recheck
from app.services.question_dna import question_dna_service as svc


def _row(qid, text, *, status="draft", scheme="M1 A1", created="2026-09-01", parts=None, key="B"):
    content = {"question_type": "multiple_choice", "question_text": text, "marking_scheme": scheme,
               "options": [{"id": "A", "text": "+3,400", "is_correct": key == "A"},
                           {"id": "B", "text": "-3,400", "is_correct": key == "B"}],
               "structured_parts": parts or []}
    return {"question_id": qid, "status": status, "created_at": created, "content": content,
            "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"},
            "pedagogical_dna": {"max_marks": 1, "question_type": "multiple_choice"}, "review_audit": {}}


def test_recheck_repairs_shapes_and_flags_the_newer_clone(monkeypatch):
    rows = [
        _row("q-old", "State the directed integer that represents an outstanding debt of KSh 3,400 owed by "
                      "a school canteen cooperative in its ledger.", status="approved"),
        _row("q-new", "Learners in Nakuru County use opposite cards on a number line. State the directed "
                      "integer that represents an outstanding debt of KSh 3,500 in a school canteen ledger.",
             created="2026-09-15", scheme="{'step_1': 'B1 for the negative integer'}"),
        _row("q-parts", "A club has an opening deficit of KSh 120. Determine the final balance. (a) Write a "
                        "signed expression for the balance. (2 marks) (b) Calculate it. (3 marks)",
             parts=[{"part_id": "(a)", "sub_question": "Write a signed expression for the balance.", "marks": 2},
                    {"part_id": "(b)", "sub_question": "Calculate it.", "marks": 3}]),
    ]
    monkeypatch.setattr(svc, "list_questions", lambda **kw: rows)
    updated, statuses = {}, {}
    monkeypatch.setattr(svc, "update_question", lambda qid, content, review_audit=None: updated.__setitem__(qid, content))
    monkeypatch.setattr(svc, "set_status", lambda qid, status, review_audit=None: statuses.__setitem__(qid, (status, review_audit)))

    out = bank_recheck.run(grade="grade-9", subject="Mathematics")

    assert out["checked"] == 3
    assert updated["q-new"]["marking_scheme"] == "B1 for the negative integer", "the braces are gone"
    assert updated["q-parts"]["question_text"] == "A club has an opening deficit of KSh 120. Determine the final balance."
    flagged = {f["question_id"]: f for f in out["flagged"]}
    assert "q-new" in flagged and "q-old" not in flagged, "the approved original stays; the clone is flagged"
    assert any(w.startswith("same_task_in_batch") for w in flagged["q-new"]["why"])
    assert statuses["q-new"][0] == "needs_review"
    assert statuses["q-new"][1]["recheck"]["status_before"] == "draft"
    assert out["findings_by_kind"]["same_task_in_batch"] == 1


def test_dry_run_writes_nothing(monkeypatch):
    rows = [_row("q1", "Debt of KSh 3,400 owed by a canteen. State the directed integer.",
                 scheme="{'step_1': 'B1'}")]
    monkeypatch.setattr(svc, "list_questions", lambda **kw: rows)
    monkeypatch.setattr(svc, "update_question", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote")))
    monkeypatch.setattr(svc, "set_status", lambda *a, **k: (_ for _ in ()).throw(AssertionError("wrote")))
    out = bank_recheck.run(dry_run=True)
    assert out["dry_run"] and out["repaired_count"] == 1


def test_set_status_never_demotes_an_approved_item(monkeypatch):
    from app.services import question_dna as qd

    seen = {}
    monkeypatch.setattr(qd, "execute", lambda sql, params: seen.update(sql=sql, params=params))
    svc.set_status("q1", "needs_review", review_audit={"recheck": {}})
    assert "status <> 'approved'" in seen["sql"] and seen["params"]["status"] == "needs_review"

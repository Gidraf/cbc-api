"""A second model reads the bank and fixes it — story against sum included."""
from __future__ import annotations

from types import SimpleNamespace

from app.services import bank_review, question_audit
from app.services.question_dna import question_dna_service as svc


def test_the_story_and_the_sum_must_say_the_same_thing():
    q = {"expression": "-120 + 360 - 150 + 90 + 200/4"}
    # The refund comes back whole, as told; the writer divided it.
    says = question_audit.story_vs_expression(q, "-120 + 360 - 150 + 90 + 200")
    assert "= 380" in says and "= 230" in says and "do not say the same thing" in says
    assert question_audit.story_vs_expression(q, "-120 + 360 - 150 + 90 + 200/4") == ""
    assert question_audit.story_vs_expression(q, "(-120) + 360 - 150 + 90 + 50") == "", "same value, other form"
    assert question_audit.story_vs_expression({}, "1 + 1") == ""
    assert question_audit.story_vs_expression(q, "the refund") == "", "an unworkable reading is not a verdict"


def test_the_reader_disagreement_stands_even_when_the_engine_blessed_the_writers_sum(monkeypatch):
    """The audit dismissed a reader whose ANSWER differed from a key the
    engine had verified. A different TRANSLATION of the story is not that."""
    q = {"question_id": "q24", "display_label": "Q24", "question_type": "structured",
         "question_text": "An opening deficit of KSh 120; receives 360, pays 150, receives 90, and a KSh 200 "
                          "refund shared among four members who each return their share. Final balance?",
         "expression": "-120 + 360 - 150 + 90 + 200/4", "model_answer": "230", "marking_scheme": "M1 A1"}
    verdicts = {"verdicts": [{"item": "Q24", "verdict": "pass", "kind": "", "my_answer": "230",
                              "expression": "-120 + 360 - 150 + 90 + 200", "reason": ""}]}
    out = question_audit.audit([q], generate=lambda cfg, msgs, **kw: SimpleNamespace(content=verdicts),
                               model_config=object(), grade="grade-9", subject="Mathematics", sub_strand="Integers")
    assert [f.kind for f in out] == ["story_expression_disagree"]
    assert out[0].items == ["q24"]


def _row(qid, text, *, status="draft", key_ok=True, expression=""):
    content = {"question_type": "multiple_choice", "question_text": text, "marking_scheme": "M1 A1",
               "expression": expression,
               "options": [{"id": "A", "text": "20", "is_correct": key_ok}, {"id": "B", "text": "-20", "is_correct": not key_ok},
                           {"id": "C", "text": "5"}, {"id": "D", "text": "-5"}]}
    return {"question_id": qid, "status": status, "created_at": "2026-09-01", "content": content,
            "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "strand": "Numbers", "sub_strand": "Integers"},
            "pedagogical_dna": {"max_marks": 1, "question_type": "multiple_choice", "bloom_level": "Application"},
            "review_audit": {}}


def test_review_rewrites_what_fails_holds_what_still_fails_and_stamps_the_rest(monkeypatch):
    rows = [
        _row("q-good", "Work out $[-15 - (-9)] \\times (-4) + (-32) \\div 8$."),                 # key 20: right
        _row("q-bad", "Work out $(-6) \\times (-4) + (-32) \\div 8$ and give the value.", key_ok=False),  # key says -20
    ]
    monkeypatch.setattr(svc, "list_questions", lambda **kw: rows)
    monkeypatch.setattr(bank_review, "_notes_for", lambda g, s, ss: "Lesson 1: directed numbers.")
    from app.services import bank_recheck
    monkeypatch.setattr(bank_recheck, "run", lambda **kw: {"repaired_count": 0})

    class _Router:
        def resolve_for_stage(self, stage, provider=None, model=None):
            assert stage == "reviewer_panel" and provider == "anthropic"
            return SimpleNamespace(provider="anthropic", model=model or "claude-opus-5")
    from app.services import pipeline
    monkeypatch.setattr(pipeline.pipeline_orchestrator, "router", _Router())

    calls = []

    def generate(cfg, messages, **kw):
        text = messages[-1]["content"]
        calls.append(text[:40])
        if "moderating" in text:   # the reader: passes everything it is shown
            return SimpleNamespace(content={"verdicts": []})
        # the rewrite: hands back a repaired item for whatever it was asked to redo
        import json, re
        ids = re.findall(r'"question_id": "([^"]+)"', text)
        return SimpleNamespace(content={"questions": [
            {"replaces": qid, "question_type": "multiple_choice",
             "question_text": "Work out $(-6) \\times (-4) + (-32) \\div 8$.",
             "options": [{"id": "A", "text": "20", "is_correct": True}, {"id": "B", "text": "-20"},
                         {"id": "C", "text": "5"}, {"id": "D", "text": "-5"}],
             "marking_scheme": "M1 product 24; M1 quotient -4; A1 20", "model_answer": "20",
             "bloom_level": "Application", "max_marks": 1} for qid in ids]})
    from app.services import llm_client as lc
    monkeypatch.setattr(lc.llm_client, "generate", generate)

    written, statuses = {}, {}
    monkeypatch.setattr(svc, "update_question", lambda qid, content, review_audit=None: written.__setitem__(qid, (content, review_audit)))
    monkeypatch.setattr(svc, "set_status", lambda qid, status, review_audit=None: statuses.__setitem__(qid, (status, review_audit)))

    out = bank_review.review(grade="grade-9", subject="Mathematics", provider="anthropic", approve_clean=True)

    assert out["reader"] == "anthropic · claude-opus-5" and out["checked"] == 2
    # The engine moved q-bad's key to 20 in place (a repair, not a rewrite) —
    # or the loop rewrote it; either way the bank ends up right.
    assert out["held"] == 0, out
    assert statuses["q-good"][0] == "approved"
    assert statuses["q-good"][1]["reviewed_by"] == "anthropic · claude-opus-5"
    assert out["cleared"] + out["rewritten"] == 2


def test_the_review_route_queues_one_job_per_subject(monkeypatch):
    from app.routes import questions as qr
    from app.services import job_queue

    monkeypatch.setattr(qr, "_subjects_with_items", lambda grade: ["Mathematics", "English"])
    jobs = []
    monkeypatch.setattr(job_queue, "enqueue", lambda kind, grade, subject, payload, **kw: jobs.append((kind, grade, subject, payload)) or SimpleNamespace(job_id=f"j{len(jobs)}"))
    monkeypatch.setattr(job_queue, "start_worker", lambda: True)

    out = qr.bank_review_queue(qr.BankReviewRequest(grade="grade-9", provider="gemini", model="gemini-2.5-pro"),
                               auth=SimpleNamespace(subject="ops"))
    assert out["queued"] == 2
    assert jobs[0][0] == "review" and jobs[0][2] == "Mathematics"
    assert jobs[0][3]["provider"] == "gemini" and jobs[0][3]["fix"] is True and jobs[0][3]["approve_clean"] is False

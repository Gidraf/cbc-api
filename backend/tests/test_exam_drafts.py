"""A paper built step by step: scope, fill, correct, preview, freeze."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import exam_drafts as ed


class _Db:
    """exam_drafts and exams in memory; questions come from a fixture."""

    def __init__(self):
        self.drafts: dict[str, dict] = {}
        self.exams: list[dict] = []

    def execute(self, sql, params=None):
        params = params or {}
        if sql.strip().startswith("INSERT INTO exam_drafts"):
            self.drafts[params["id"]] = {
                "draft_id": params["id"], "owner": params["owner"], "title": params["title"],
                "grade": params["grade"], "subject": params["subject"], "kind": params["kind"],
                "term": params["term"], "scope": json.loads(params["scope"]), "items": [], "snapshot": {},
                "settings": json.loads(params["settings"]), "status": "draft", "exam_id": None,
                "created_at": "t", "updated_at": "t"}
        elif sql.strip().startswith("UPDATE exam_drafts SET status = 'frozen'"):
            self.drafts[params["id"]].update(status="frozen", exam_id=params["eid"])
        elif sql.strip().startswith("UPDATE exam_drafts"):
            row = self.drafts[params["id"]]
            for key, value in params.items():
                if key == "id":
                    continue
                row[key] = json.loads(value) if key in ("scope", "settings", "items", "snapshot") else value
        elif sql.strip().startswith("DELETE FROM exam_drafts"):
            self.drafts.pop(params["id"], None)
        elif sql.strip().startswith("INSERT INTO exams"):
            self.exams.append({**params, "snapshot": json.loads(params["snapshot"])})

    def fetch_one(self, sql, params=None):
        params = params or {}
        if "FROM exam_drafts" in sql:
            row = self.drafts.get(params["id"])
            return dict(row) if row else None
        return None

    def fetch_all(self, sql, params=None):
        params = params or {}
        if "FROM exam_drafts" in sql:
            return [{**r, "item_count": len(r["items"])} for r in self.drafts.values()
                    if params.get("everyone") or r["owner"] == params.get("owner")]
        return []


def _q(qid, ss, *, kind="multiple_choice", marks=1, figure=False, status="draft"):
    content = {"question_type": kind, "question_text": f"Question {qid} on {ss}: work out ${qid[-1]} + 2$.",
               "marking_scheme": "A1", "model_answer": "x",
               "options": [{"id": "A", "text": "x", "is_correct": True}, {"id": "B", "text": "y"}] if kind == "multiple_choice" else [],
               "structured_parts": [] if kind == "multiple_choice" else [
                   {"part_id": "(a)", "sub_question": "Do it.", "marks": marks, "model_answer": "z"}]}
    if figure:
        content["diagram"] = {"diagram_id": f"d-{qid}"}
    return {"question_id": qid, "status": status, "version": 1, "content": content,
            "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "strand": "Numbers", "sub_strand": ss},
            "pedagogical_dna": {"max_marks": marks, "question_type": kind}, "review_audit": {}, "provenance": {}}


BANK = ([_q(f"int{i}", "Integers", figure=(i < 3)) for i in range(12)]
        + [_q(f"fr{i}", "Fractions") for i in range(12)]
        + [_q(f"w{i}", "Integers", kind="structured_scenario", marks=4) for i in range(4)])


@pytest.fixture
def world(monkeypatch):
    from app.infra import db
    from app.services import product_orders
    from app.services.question_dna import question_dna_service as svc

    fake = _Db()
    monkeypatch.setattr(db, "execute", fake.execute)
    monkeypatch.setattr(db, "fetch_one", fake.fetch_one)
    monkeypatch.setattr(db, "fetch_all", fake.fetch_all)
    by_id = {q["question_id"]: q for q in BANK}

    def list_questions(**kw):
        ss = kw.get("sub_strand")
        return [q for q in BANK if not ss or q["curriculum_link"]["sub_strand"].lower() == ss.lower()]
    monkeypatch.setattr(svc, "list_questions", list_questions)
    monkeypatch.setattr(svc, "get_question", lambda qid: by_id[qid])
    updated = {}
    monkeypatch.setattr(svc, "update_question", lambda qid, content, review_audit=None: updated.__setitem__(qid, content) or {**by_id[qid], "content": content})
    monkeypatch.setattr(product_orders, "sub_strands_for", lambda g, s: [
        {"strand": "Numbers", "sub_strand": "Integers", "hours": 10},
        {"strand": "Numbers", "sub_strand": "Fractions", "hours": 10},
        {"strand": "Algebra", "sub_strand": "Equations", "hours": 10}])
    monkeypatch.setattr(product_orders, "term_scope", lambda g, s, t: [{"strand": "Numbers", "sub_strand": "Integers"}] if t == 1 else [])
    monkeypatch.setattr(product_orders, "_has_notes", lambda g, s, ss: ss == "Integers")
    monkeypatch.setattr(product_orders, "_items_in_bank", lambda g, s, ss: len(list_questions(sub_strand=ss)))
    return SimpleNamespace(db=fake, updated=updated)


def test_a_draft_is_created_scoped_filled_and_previewed(world):
    d = ed.create(owner="user:amina", grade="grade-9", subject="Mathematics", kind="topical",
                  title="Integers CAT", scope={"mode": "topical", "sub_strand": "Integers"})
    assert d["status"] == "draft" and d["settings"] == {"density": "compact"}
    assert [s["sub_strand"] for s in ed.scope_sub_strands(d)] == ["Integers"]

    summary = ed.bank_summary(d)
    assert summary[0]["items"] == 16 and summary[0]["with_figures"] == 3 and summary[0]["has_notes"]

    out = ed.fill(d["draft_id"], count=8, diagram_count=3)
    row = ed.get(d["draft_id"])
    assert out["items"] == len(row["items"]) > 0
    assert out["with_figures"] >= min(3, out["items"]), out
    assert row["snapshot"]["sections"], "the composition is kept on the draft"

    html = ed.render(row, with_scheme=True)
    assert "Integers CAT" in html and "TOPICAL ASSESSMENT" in html
    assert "font-size: 8.4pt" in html, "the draft's own density"


def test_topics_mode_takes_the_ticked_sub_strands_and_smart_takes_the_term(world):
    d = ed.create(owner="user:amina", grade="grade-9", subject="Mathematics", kind="endterm", term=1,
                  scope={"mode": "topics", "sub_strands": ["Fractions", "Integers", "Probability"]})
    names = [s["sub_strand"] for s in ed.scope_sub_strands(d)]
    assert names == ["Integers", "Fractions", "Probability"], "design order, plus a hand-typed topic kept"
    d2 = ed.create(owner="user:amina", grade="grade-9", subject="Mathematics", kind="endterm", term=1)
    assert [s["sub_strand"] for s in ed.scope_sub_strands(d2)] == ["Integers"]


def test_corrections_live_on_the_draft_and_reach_the_bank_at_the_freeze(world):
    d = ed.create(owner="user:amina", grade="grade-9", subject="Mathematics", kind="cat", title="CAT 1",
                  scope={"mode": "topical", "sub_strand": "Integers"})
    ed.fill(d["draft_id"], count=6)
    first = ed.get(d["draft_id"])["items"][0]["question_id"]
    ed.set_override(d["draft_id"], first, {"question_text": "Corrected stem: work out $3 + 2$.", "provenance": "no"})
    row = ed.get(d["draft_id"])
    assert row["items"][0]["overrides"] == {"question_text": "Corrected stem: work out $3 + 2$."}
    assert "Corrected stem" in ed.render(row)
    detail = ed.items_detail(row)
    assert detail[0]["question"]["question_text"].startswith("Corrected stem")
    assert "working" in detail[0] and "rung" in detail[0] and detail[0]["curriculum"]["sub_strand"] == "Integers"

    out = ed.freeze(d["draft_id"], created_by="amina", base="https://papers.example.co.ke")
    assert out["exam_id"].startswith("exam-") and out["render_urls"]["paper"].startswith("https://papers.example.co.ke/api/v1/exams/")
    assert "density=compact" in out["render_urls"]["paper"], "the draft's print settings travel on the link"
    assert world.updated[first]["question_text"].startswith("Corrected stem"), "written to the bank"
    frozen = ed.get(d["draft_id"])
    assert frozen["status"] == "frozen" and frozen["exam_id"] == out["exam_id"]
    assert world.db.exams[0]["snapshot"]["draft_id"] == d["draft_id"]
    with pytest.raises(Exception):
        ed.update(d["draft_id"], {"title": "x"})


def test_reorder_drops_and_reorders_within_sections(world):
    d = ed.create(owner="user:amina", grade="grade-9", subject="Mathematics", scope={"mode": "topical", "sub_strand": "Integers"})
    ed.fill(d["draft_id"], count=6)
    ids = [i["question_id"] for i in ed.get(d["draft_id"])["items"]]
    assert len(ids) >= 3
    new_order = list(reversed(ids[:-1]))
    ed.reorder(d["draft_id"], new_order)
    row = ed.get(d["draft_id"])
    assert [i["question_id"] for i in row["items"]] == new_order
    flat = [q for s in row["snapshot"]["sections"] for q in s["question_ids"]]
    assert set(flat) == set(new_order) and ids[-1] not in flat


def test_generate_queues_only_the_sub_strands_short_of_their_share(world, monkeypatch):
    from app.services import job_queue

    jobs = []
    monkeypatch.setattr(job_queue, "enqueue", lambda kind, g, s, payload, **kw: jobs.append((kind, payload, kw)) or SimpleNamespace(job_id=f"j{len(jobs)}"))
    monkeypatch.setattr(job_queue, "start_worker", lambda: True)
    d = ed.create(owner="user:amina", grade="grade-9", subject="Mathematics", kind="endterm",
                  scope={"mode": "topics", "sub_strands": ["Integers", "Equations"]})
    out = ed.generate(d["draft_id"], count=30)
    # 2 sub-strands → 30 each wanted; Integers has 16 and a guide, Equations nothing and no guide.
    by = {j[2]["sub_strand"]: j for j in jobs}
    assert set(by) == {"Integers", "Equations"}
    assert by["Integers"][1]["steps"] == ["questions"] and by["Integers"][1]["count"] == 14
    assert by["Equations"][1]["steps"] == ["notes", "questions"]


def test_a_user_sees_only_their_drafts_and_staff_see_all(world):
    ed.create(owner="user:amina", grade="grade-9", subject="Mathematics")
    ed.create(owner="user:otieno", grade="grade-7", subject="English")
    assert len(ed.list_for("user:amina")) == 1
    assert len(ed.list_for("admin:gm", everyone=True)) == 2
    other = ed.list_for("user:otieno")[0]["draft_id"]
    with pytest.raises(Exception):
        ed.get(other, "user:amina")
    assert ed.get(other, "admin:gm")["owner"] == "user:otieno"

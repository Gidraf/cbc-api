"""Phase 2: own questions, online tests, the video plan, locked answers, streaming.

The flows that keep money and students' work run against a real Postgres
(set CBC_TEST_PHASE2_DATABASE_URL to an empty database); the rest need none.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth as auth_service
from app.services import entitlements, online_tests, rate_limit, streaming, user_questions
from app.services.auth import AuthContext, get_auth_context

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    infra.run_migrations()
    rate_limit.reset_all()
    yield engine
    engine.dispose()


def _questions(owner: str) -> list[str]:
    ids = []
    for n in range(6):
        ids.append(user_questions.create(owner, {
            "question_text": f"What is {n} + 3?", "question_type": "short_answer", "correct_answer": f"$ {n} + 3 = {n + 3}$",
            "marking_scheme": "B1", "marks": 1, "grade": "Grade 9", "subject": "Mathematics"})["question_id"])
    ids.append(user_questions.create(owner, {
        "question_text": "Which is a negative integer?", "question_type": "multiple_choice",
        "options": [{"text": "-4", "is_correct": True}, {"text": "4"}, {"text": "0"}, {"text": "1/2"}],
        "marks": 2, "grade": "Grade 9", "subject": "Mathematics"})["question_id"])
    ids.append(user_questions.create(owner, {
        "question_text": "Explain why -3 is less than -1.", "question_type": "structured",
        "correct_answer": "On the number line -3 is further left of zero than -1.", "marking_scheme": "B1 position, B1 reason",
        "marks": 2, "grade": "Grade 9", "subject": "Mathematics"})["question_id"])
    return ids


def _paper(owner: str, ids: list[str]) -> str:
    from app.services import exam_drafts

    d = exam_drafts.create(owner=f"user:{owner}", grade="Grade 9", subject="Mathematics", kind="topical", title="Integers")
    exam_drafts.update(d["draft_id"], {"items": [{"question_id": q, "overrides": {}} for q in ids]}, owner=f"user:{owner}")
    return d["draft_id"]


# ── own questions ────────────────────────────────────────────────────────────

@needs_db
def test_own_questions_are_private_free_and_print_on_the_paper(db):
    from app.services import billing, exam_drafts

    ids = _questions("mwalimu")
    assert user_questions.get("mwalimu", ids[0])["question_text"] == "What is 0 + 3?"
    with pytest.raises(Exception):
        user_questions.get("someone-else", ids[0])               # another account never sees it
    draft = _paper("mwalimu", ids)
    paper = exam_drafts.paper_for(exam_drafts.get(draft, "user:mwalimu"))
    assert [q["question_id"] for q in paper.items] == ids
    q = billing.quote_paper("mwalimu", "user", list(paper.items))
    assert q["paid"] and q["total_ksh"] == 0                       # your own questions cost nothing
    # Someone else's id on a paper is simply not there.
    other = _paper("intruder", ids[:2])
    assert exam_drafts.paper_for(exam_drafts.get(other, "user:intruder")).items == []
    with pytest.raises(Exception):
        user_questions.create("mwalimu", {"question_text": "Pick one", "question_type": "multiple_choice",
                                          "options": [{"text": "a"}, {"text": "b"}]})   # no right option


# ── online tests ─────────────────────────────────────────────────────────────

@needs_db
def test_each_student_gets_their_own_deal_and_is_marked(db):
    ids = _questions("mwalimu")
    draft = _paper("mwalimu", ids)
    test = online_tests.create(owner="mwalimu", role="user", draft_id=draft, per_student=5, minutes=20)
    assert test["pool_size"] == 8 and test["per_student"] == 5 and len(test["code"]) == 6

    a = online_tests.start(test["code"], "Achieng", seed="one")
    b = online_tests.start(test["code"].lower(), "Brian", seed="two")
    qa, qb = [q["question_id"] for q in a["questions"]], [q["question_id"] for q in b["questions"]]
    assert len(qa) == len(qb) == 5 and qa != qb                    # their own selection and order
    for q in a["questions"] + b["questions"]:
        assert "answer" not in q and "correct_answer" not in q and "marking_scheme" not in q
        assert all(set(o) == {"letter", "text"} for o in q["options"])

    # Achieng answers everything right she can, using the letters she saw.
    answers = {}
    for q in a["questions"]:
        if q["options"]:
            answers[q["question_id"]] = next(o["letter"] for o in q["options"] if o["text"] == "-4")
        elif q["type"] == "short_answer":
            n = int(q["question"].split()[2])
            answers[q["question_id"]] = str(n + 3)
        else:
            answers[q["question_id"]] = "It is further from zero on the left."
    out = online_tests.submit(a["token"], answers)
    auto = [i for i in out["items"] if i["status"] != "to_mark"]
    assert all(i["status"] == "right" for i in auto)
    assert out["answers_shown"] and all("marking_scheme" in i for i in out["items"])
    assert online_tests.submit(a["token"], {}) == online_tests.result(a["token"])   # handing in twice changes nothing

    results = online_tests.results("mwalimu", test["test_id"])
    assert {r["name"] for r in results["attempts"]} == {"Achieng", "Brian"}
    achieng = next(r for r in results["attempts"] if r["name"] == "Achieng")
    if achieng["to_mark"]:
        written = achieng["to_mark"][0]["question_id"]
        marked = online_tests.mark_written("mwalimu", test["test_id"], achieng["attempt_id"], written, 5)
        assert marked["score"] == 2                                 # never above the question's marks
    with pytest.raises(Exception):
        online_tests.results("intruder", test["test_id"])           # only the teacher sees results

    online_tests.set_status("mwalimu", test["test_id"], "closed")
    with pytest.raises(Exception):
        online_tests.start(test["code"], "Late Comer")
    online_tests.delete("mwalimu", test["test_id"])
    with pytest.raises(Exception):
        online_tests.resume(a["token"])                              # names and answers go with the test


@needs_db
def test_a_paper_must_be_bought_before_a_class_takes_it(db):
    from app.services import exam_drafts

    from sqlalchemy import text
    with db.begin() as c:
        c.execute(text("""INSERT INTO question_dna (question_id, universal_id, curriculum_link, pedagogical_dna, content,
                          provenance, review_audit, status, created_at, updated_at, grade_ordinal, version, display_label)
                          VALUES ('q-bank-1', 'q-bank-1', CAST(:cl AS jsonb), CAST(:pd AS jsonb), CAST(:ct AS jsonb),
                                  '{}', '{}', 'approved', NOW(), NOW(), 11, 1, 'q')"""),
                  {"cl": '{"grade": "grade-9", "subject": "Mathematics"}', "pd": '{"max_marks": 1}',
                   "ct": '{"question_text": "2+2?", "correct_answer": "4", "question_type": "short_answer"}'})
    rows = [{"question_id": f"q-bank-1", "overrides": {}}]
    d = exam_drafts.create(owner="user:mama", grade="Grade 9", subject="Mathematics", kind="topical", title="T")
    exam_drafts.update(d["draft_id"], {"items": rows}, owner="user:mama")
    # One bank question within the free ten: free, but still "bought" first.
    with pytest.raises(Exception) as unpaid:
        online_tests.create(owner="mama", role="user", draft_id=d["draft_id"])
    assert "Buy the paper" in str(unpaid.value)


# ── the video plan ───────────────────────────────────────────────────────────

@needs_db
def test_the_video_plan_is_off_until_priced_then_paid_from_the_wallet(db, monkeypatch):
    from app.services import billing, platform_settings

    assert not entitlements.plan_status("mama", "user")["on_sale"]
    with pytest.raises(Exception):
        entitlements.subscribe("mama", "user")
    monkeypatch.setattr(platform_settings, "_load", lambda: {"billing_video_plan_ksh": "300", "billing_video_plan_days": 30})
    with pytest.raises(billing.PaymentRequired):
        entitlements.subscribe("mama", "user")
    billing.credit("mama", 700_00, kind="topup")
    first = entitlements.subscribe("mama", "user")
    second = entitlements.subscribe("mama", "user")                 # extends from the end, nothing lost
    assert first["charged_ksh"] == 300 and second["until"] > first["until"]
    assert entitlements.has_video_plan("mama", "user") and billing.balance("mama") == 100_00
    assert entitlements.may_open("mama", "user", "q-anything")


# ── locks, without a database ────────────────────────────────────────────────

@pytest.fixture()
def as_user(monkeypatch):
    who = {"subject": "mama", "role": "user"}
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(subject=who["subject"], role=who["role"], auth_type="bearer")
    rate_limit.reset_all()
    try:
        yield TestClient(app), who
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


def test_a_question_not_owned_is_locked_until_bought_or_on_the_plan(as_user, monkeypatch):
    from app.routes import play

    c, who = as_user
    state = {"owned": set(), "plan": False}
    monkeypatch.setattr(entitlements, "owned_ids", lambda o, ids: {i for i in ids if i in state["owned"]})
    monkeypatch.setattr(entitlements, "has_video_plan", lambda o, r: r in entitlements.STAFF or state["plan"])
    monkeypatch.setattr(entitlements, "plan_status", lambda o, r: {"on_sale": False})
    monkeypatch.setattr(play, "_one", lambda qid, owner="": {"question_id": qid, "question_text": "2+2?", "correct_answer": "4"})
    assert c.get("/api/v1/play/items/q1").status_code == 402
    assert c.get("/api/v1/play/items/q1/walkthrough.html").status_code == 402
    assert c.get("/api/v1/play/items/q1/watch").status_code == 402
    state["owned"].add("q1")
    assert c.get("/api/v1/play/items/q1").status_code == 200
    assert c.get("/api/v1/play/items/q1/watch").status_code == 402  # owning it is not the video plan
    who["role"] = "operator"
    assert c.get("/api/v1/play/items/q2").status_code == 200        # staff open everything


def test_production_tools_and_file_links_are_not_for_parents(as_user, monkeypatch):
    from app.services import platform_settings

    c, _ = as_user
    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: ["gidraf"] if k == "video_makers" else d)
    for path in ("/api/v1/play/videos?grade=Grade%209&subject=Mathematics",
                 "/api/v1/play/social?grade=Grade%209&subject=Mathematics",
                 "/api/v1/play/items/q1/social", "/api/v1/play/social/posts"):
        assert c.get(path).status_code == 403, path


def test_unowned_questions_in_the_builder_come_without_answers(monkeypatch):
    from app.routes.exam_builder import _hide_unowned

    monkeypatch.setattr(entitlements, "owned_ids", lambda o, ids: {"mine"})
    items = [{"question_id": "mine", "correct_answer": "4", "marking_scheme": "B1"},
             {"question_id": "theirs", "correct_answer": "9", "marking_scheme": "B1", "model_answer": "…",
              "options": [{"id": "A", "text": "9", "is_correct": True}]}]
    out = _hide_unowned(AuthContext("mama", "user", "bearer"), items)
    assert out[0]["correct_answer"] == "4"
    assert "correct_answer" not in out[1] and "marking_scheme" not in out[1] and out[1]["locked"]
    assert "is_correct" not in out[1]["options"][0]
    assert _hide_unowned(AuthContext("ops", "operator", "bearer"), items) == items


def test_a_watch_link_is_signed_short_and_for_one_video():
    link = streaming.watch_link("mama", "videos/q1/abc.mp4", ttl=60)
    token = link["stream_url"].rsplit("/", 1)[1]
    assert streaming.read(token)["obj"] == "videos/q1/abc.mp4"
    assert streaming.read(token[:-2] + "xx") is None                # tampered
    expired = streaming.watch_link("mama", "videos/q1/abc.mp4", ttl=-1)["stream_url"].rsplit("/", 1)[1]
    assert streaming.read(expired) is None
    access = auth_service.create_access_token("mama", "admin")      # a sign-in token is not a watch token
    assert streaming.read(access) is None
    r = TestClient(app).get(f"/api/v1/watch/{token[:-2]}xx")
    assert r.status_code == 403


def test_marking_reads_values_and_leaves_words_to_the_teacher():
    q = {"question_type": "short_answer", "correct_answer": "$-5+8=3^\\circ\\text{C}$", "pedagogy": {"max_marks": 2}}
    assert online_tests.mark_one(q, "3", None)["status"] == "right"
    assert online_tests.mark_one(q, " 3 °C ", None)["score"] == 2
    assert online_tests.mark_one(q, "13", None)["status"] == "wrong"
    assert online_tests.mark_one({"question_type": "short_answer", "correct_answer": "\\frac{3}{4}"}, "0.75", None)["status"] == "right"
    assert online_tests.mark_one({"question_type": "short_answer", "correct_answer": "Because it is colder"},
                                 "it is colder", None)["status"] == "to_mark"
    mcq = {"options": [{"id": "A", "text": "4", "is_correct": False}, {"id": "B", "text": "-4", "is_correct": True}]}
    assert online_tests.mark_one(mcq, "A", ["B", "A"])["status"] == "right"       # B was shown first, as "A"
    assert online_tests.mark_one(mcq, "A", ["A", "B"])["status"] == "wrong"
    assert online_tests.mark_one(mcq, "Z", ["A", "B"])["status"] == "wrong"


def test_figures_really_reach_students_and_developers(monkeypatch):
    """The figure SVG is built, not just promised: an import that does not
    exist once made every figure silently empty."""
    from app.services import content_api, question_paper

    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5" onclick="x()"/></svg>'
    monkeypatch.setattr(question_paper, "figures_for", lambda qs: {"d1": {"svg_markup": svg, "scene_document": {}}})
    q = {"question_id": "q1", "question_text": "Read it.", "diagram": {"diagram_id": "d1", "diagram_title": "T", "hide_layers": []}}
    student = online_tests._figure(q)
    assert student.startswith("<svg") and "onclick" not in student
    row = {"question_id": "q1", "content": {"question_text": "Read it.", "diagram": q["diagram"]}, "curriculum_link": {},
           "pedagogical_dna": {}}
    assert content_api.public(row)["figure"]["svg"].startswith("<svg")

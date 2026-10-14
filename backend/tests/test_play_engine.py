"""Every question, playable — and every number in a game from the engine."""
from __future__ import annotations

from fractions import Fraction

import pytest

from app.services import play_engine as P


def test_kinds_are_derived_from_the_expression():
    nl = P.number_line("-18 + 12 - 5 + 8")
    assert nl["start"] == -18 and nl["moves"] == [12, -5, 8] and nl["points"] == [-18, -6, -11, -3] and nl["target"] == -3
    assert nl["min"] < -18 and nl["max"] > -3

    bo = P.bodmas("-16 + (-28) \\div 4 \\times (-3) - (-9)")
    assert bo["target"] == 14 and [s["op"] for s in bo["steps"]] == ["÷", "×", "+", "-"]
    assert bo["steps"][0]["left"] == -28 and bo["steps"][0]["right"] == 4 and bo["steps"][0]["result"] == -7

    fb = P.fraction_bar("3/4 + 2/3")
    assert fb["common"] == 12 and fb["first_as"] == [9, 12] and fb["second_as"] == [8, 12] and fb["target"] == "17/12"

    ba = P.balance("2(x - 3) = x + 4")
    assert ba["target"] == 10 and [m["value"] for m in ba["moves"]] == ["x", "6"]
    assert P.balance("3x + 5 = 20")["moves"][-1] == {"op": "÷", "value": "3", "why": "Divide both sides by 3."}

    assert P.number_line("3 \\times 4") is None and P.balance("x + y = 3") is None and P.fraction_bar("3 + 4") is None


def test_the_writers_choice_is_honoured_where_the_engine_can_fill_it():
    q = {"expression": "-18 + 12 - 5 + 8", "interaction": {"kind": "bodmas"}}
    assert P.spec_for(q)["primary"]["kind"] == "bodmas"
    q = {"expression": "3 + 4", "interaction": {"kind": "balance"}}
    play = P.spec_for(q)
    assert "balance" in play["note"] and play["primary"]["kind"] in ("number_line", "bodmas")
    # No hint: the most visual kind the expression supports.
    assert P.spec_for({"expression": "-18 + 12 - 5 + 8"})["primary"]["kind"] == "number_line"
    # A bare calculation item carries its expression in the stem.
    assert P.spec_for({"question_text": "Work out $(-6) \\times (-4) + (-32) \\div 8$."})["primary"]["target"] == 20


def test_a_game_never_disagrees_with_the_key_silently():
    good = {"expression": "-18 + 12 - 5 + 8", "options": [{"id": "A", "text": "$-3$ m", "is_correct": True}, {"id": "B", "text": "3"}]}
    bad = {"expression": "-18 + 12 - 5 + 8", "options": [{"id": "A", "text": "$3$ m", "is_correct": True}, {"id": "B", "text": "-3"}]}
    frac = {"expression": "3/4 + 2/3", "options": [{"id": "A", "text": "$\\frac{17}{12}$", "is_correct": True}, {"id": "B", "text": "5/7"}]}
    assert P.spec_for(good)["key_agrees"] is True and P.spec_for(frac)["key_agrees"] is True
    assert P.spec_for(bad)["key_agrees"] is False
    rounds = P.session([good, bad], mode="mixed", count=5)
    assert len(rounds) == 1, "the item whose key the engine disputes is not played"


def test_a_round_mixes_the_kinds_and_choice_mode_plays_the_options():
    items = [{"question_id": f"n{i}", "expression": f"-{i + 2} + 5 - 3", "options": [{"id": "A", "text": str(-i), "is_correct": True}, {"id": "B", "text": "0"}]} for i in range(3)]
    items += [{"question_id": f"b{i}", "expression": f"{i + 2}x + 1 = {2 * (i + 2) + 1}"} for i in range(3)]
    mixed = P.session(items, mode="mixed", count=4)
    assert [r["spec"]["kind"] for r in mixed] == ["number_line", "balance", "number_line", "balance"]
    assert all(r["spec"]["kind"] == "choice" for r in P.session(items, mode="choice"))


def test_learners_answers_are_checked_as_values():
    assert P.check_answer("3/4", "0.75") and P.check_answer("3/4", "6/8") and P.check_answer(-3, " -3 ")
    assert not P.check_answer("3/4", "0.7") and not P.check_answer(5, "five")


def test_the_walkthrough_is_a_teacher_at_the_board():
    q = {"question_id": "q1", "question_text": "A diver at $-18$ m rises 12 m, drops 5 m, rises 8 m. Where is she?",
         "expression": "-18 + 12 - 5 + 8",
         "options": [{"id": "A", "text": "$-3$ m", "is_correct": True, "distractor_rationale": "Each move is added in turn."},
                     {"id": "B", "text": "$3$ m", "distractor_rationale": "Ignores the minus on the starting depth."}]}
    w = P.walkthrough(q)
    kinds = [s["scene"] for s in w["scenes"]]
    assert kinds[0] == "title" and kinds.count("number_line_jump") == 3 and kinds[-2:] == ["answer", "trap"]
    assert "negative 18" in w["scenes"][0]["say"]
    assert w["scenes"][3]["say"] == "Add 12: we move 12 to the right and land on negative 6."
    assert "Ignores the minus" in w["scenes"][-1]["say"]

    b = P.walkthrough({"question_text": "Solve $3x + 5 = 20$.", "expression": "3x + 5 = 20"})
    assert [s["scene"] for s in b["scenes"]][-3:] == ["balance_move", "balance_done", "answer"]


def test_the_writer_is_told_how_items_are_played_in_mathematics_only():
    assert "number_line" in P.prompt_block("Mathematics") and "balance" in P.prompt_block("Mathematics")
    assert P.prompt_block("English") == ""


def test_the_normaliser_keeps_only_a_known_kind():
    from app.services.question_normalizer import _interaction

    assert _interaction({"kind": "Number Line", "start": 999}) == {"kind": "number_line"}, "the engine fills the numbers"
    assert _interaction("balance") == {"kind": "balance"}
    assert _interaction({"kind": "rocket"}) == {} and _interaction(None) == {}


def test_an_unplayable_choice_is_a_finding():
    from app.services import question_check as qc

    findings: list = []
    qc._unplayable([{"question_id": "q1", "display_label": "Q1", "expression": "3 + 4", "interaction": {"kind": "balance"}}],
                   subject="Mathematics", findings=findings)
    assert [f.kind for f in findings] == ["unplayable"]
    findings = []
    qc._unplayable([{"question_id": "q2", "display_label": "Q2", "expression": "-18 + 12 - 5 + 8",
                     "options": [{"id": "A", "text": "3", "is_correct": True}, {"id": "B", "text": "-3"}]}],
                   subject="Mathematics", findings=findings)
    assert [f.kind for f in findings] == ["play_disagrees_with_key"]


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import question_rows
    from app.services.auth import AuthContext, get_auth_context
    from app.services.question_dna import question_dna_service as svc

    bank = [
        {"question_id": "q1", "status": "draft", "content": {"question_type": "multiple_choice", "question_text": "A diver…",
         "expression": "-18 + 12 - 5 + 8", "options": [{"id": "A", "text": "$-3$", "is_correct": True}, {"id": "B", "text": "3"}]},
         "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}, "pedagogical_dna": {"max_marks": 1}},
        {"question_id": "q2", "status": "draft", "content": {"question_type": "short_answer", "question_text": "Solve $3x + 5 = 20$.",
         "expression": "3x + 5 = 20", "model_answer": "x = 5"},
         "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Equations"}, "pedagogical_dna": {"max_marks": 2}},
        {"question_id": "q3", "status": "needs_review", "content": {"question_text": "held", "expression": "1 + 1"},
         "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}, "pedagogical_dna": {}},
    ]
    monkeypatch.setattr(svc, "list_questions", lambda **kw: bank)
    monkeypatch.setattr(svc, "get_question", lambda qid: next(r for r in bank if r["question_id"] == qid))
    from app.services import entitlements, user_questions

    # Amina is on the video plan: every question opens (test_classroom covers the locks).
    monkeypatch.setattr(entitlements, "has_video_plan", lambda owner, role: True)
    monkeypatch.setattr(user_questions, "list_for", lambda owner, **kw: [])
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(subject="amina", role="user", auth_type="session")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


def test_the_play_api_as_a_user(client):
    r = client.get("/api/v1/play/items?grade=grade-9&subject=Mathematics")
    assert r.status_code == 200
    assert {i["question_id"]: i["kind"] for i in r.json()["items"]} == {"q1": "number_line", "q2": "balance"}, "held items are not played"

    one = client.get("/api/v1/play/items/q2").json()
    assert one["play"]["primary"]["kind"] == "balance" and one["walkthrough"]["scenes"][0]["scene"] == "title"

    rnd = client.get("/api/v1/play/session?grade=grade-9&subject=Mathematics&mode=mixed&count=5&seed=x").json()
    assert rnd["count"] == 2

    assert client.post("/api/v1/play/check", json={"expected": "3/4", "given": "0.75"}).json() == {"correct": True}

    page = client.get("/api/v1/play/items/q1/walkthrough.html")
    assert page.status_code == 200 and "gsap" in page.text and "number_line_jump" in page.text


def test_without_the_plan_a_users_play_list_says_what_is_locked(client, monkeypatch):
    from app.services import entitlements

    monkeypatch.setattr(entitlements, "has_video_plan", lambda owner, role: False)
    monkeypatch.setattr(entitlements, "owned_ids", lambda owner, ids: {"q2"})
    monkeypatch.setattr(entitlements, "plan_status", lambda owner, role: {"on_sale": False})
    items = {i["question_id"]: i["locked"] for i in client.get("/api/v1/play/items?grade=grade-9&subject=Mathematics").json()["items"]}
    assert items == {"q1": True, "q2": False}
    assert client.get("/api/v1/play/items/q1").status_code == 402
    rnd = client.get("/api/v1/play/session?grade=grade-9&subject=Mathematics&mode=mixed&count=5&seed=x").json()
    assert [i["question_id"] for i in rnd["items"]] == ["q2"]          # only what Amina owns

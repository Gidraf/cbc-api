"""A chemistry item's step pictures as cards of its photo series, after the answer."""
from __future__ import annotations

from app.services import chem_stills, social_cards
from app.services import social_export as se

Q = {"question_id": "q1", "question_text": "In what order would you separate iron filings, sand and salt?",
     "chemistry": {"separate": ["iron filings", "sand", "salt", "iodine"], "focus": "order"}, "curriculum": {}}


def test_a_chemistry_series_carries_its_step_pictures_after_the_answer() -> None:
    chem = social_cards.chem_steps(Q)
    assert chem == ["steps0", "steps1", "anim0"]                 # five steps: two pictures, and the first animated
    assert se.series_steps(Q) == ["teaser", "question", "kicd", "answer", *chem, "walkthrough"]
    assert se._with_steps(Q, se.SERIES_SHORT) == ["question", "answer", *chem, "walkthrough"]
    assert se._with_steps(Q, ("walkthrough",)) == ["walkthrough"]
    plain = {"question_id": "m1", "question_text": "2 + 2?", "curriculum": {}}
    assert social_cards.chem_steps(plain) == [] and se.series_steps(plain)[-1] == "walkthrough"


def test_the_step_cards_are_the_step_pictures(monkeypatch) -> None:
    grids = [{"jpg": "g0.jpg", "gif": "g0.gif", "jpg_name": "n0.jpg", "gif_name": "n0.gif"},
             {"jpg_name": "n1.jpg", "gif_name": "n1.gif"}]
    monkeypatch.setattr(chem_stills, "status", lambda qid, q: {"grids": grids, "stills": []})
    assert social_cards.status("q1", "steps0", Q) == {"status": "ready", "url": "g0.jpg", "object_name": "n0.jpg"}
    assert social_cards.status("q1", "anim0", Q)["url"] == "g0.gif"
    assert social_cards.status("q1", "steps1", Q)["status"] == "none"
    assert se.series_steps(Q, ready_only=True) == ["teaser", "question", "kicd", "answer", "steps0", "anim0", "walkthrough"]
    cap = social_cards.caption(Q, "steps0")
    assert cap.startswith("🧩 Every step of the answer (1 of 2)") and Q["question_text"] in cap
    assert social_cards.caption(Q, "anim0").startswith("🎞️ The steps, animated")


def test_post_now_of_a_step_card_not_made_yet_has_it_made(monkeypatch) -> None:
    import app.infra.db as db
    import app.services.whiteboard as wb

    queued = []
    monkeypatch.setattr(wb, "load", lambda qid: Q)
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: None)
    monkeypatch.setattr(db, "execute", lambda sql, p=None: None)
    monkeypatch.setattr(se, "_plan_step", lambda *a, **k: None)
    monkeypatch.setattr(social_cards, "status", lambda qid, step, q=None: {"status": "none"})
    monkeypatch.setattr(social_cards, "enqueue", lambda qid, queued_by="": queued.append(qid))
    r = se.post_card("q1", "steps1")
    assert not r["ok"] and r["making"] and queued == ["q1"]

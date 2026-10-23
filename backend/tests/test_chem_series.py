"""A chemistry item's step pictures as cards of its photo series, after the answer."""
from __future__ import annotations

from app.services import chem_stills, social_cards
from app.services import social_export as se

Q = {"question_id": "q1", "question_text": "In what order would you separate iron filings, sand and salt?",
     "chemistry": {"separate": ["iron filings", "sand", "salt", "iodine"], "focus": "order"}, "curriculum": {}}


def test_a_chemistry_series_carries_its_step_pictures_after_the_answer() -> None:
    assert social_cards.chem_steps(Q) == ["steps0", "steps1", "anim0", "anim1"]    # five steps: two pictures, each animated
    chem = social_cards.series_chem_steps(Q)
    assert chem == ["anim0", "anim1"]                             # the series carries the animated ones
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
    assert se.series_steps(Q, ready_only=True) == ["teaser", "question", "kicd", "answer", "anim0", "walkthrough"]
    cap = social_cards.caption(Q, "steps0")
    assert cap.startswith("🧩 Every step of the answer (1 of 2)") and Q["question_text"] in cap
    assert social_cards.caption(Q, "anim0").startswith("🎞️ The steps, animated (1 of 2)")


def test_post_now_of_a_step_card_not_made_yet_has_it_made(monkeypatch) -> None:
    import app.infra.db as db
    import app.services.whiteboard as wb

    queued = []
    monkeypatch.setattr(wb, "load", lambda qid: Q)
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: None)
    monkeypatch.setattr(db, "execute", lambda sql, p=None: None)
    monkeypatch.setattr(se, "_plan_step", lambda *a, **k: None)
    monkeypatch.setattr(social_cards, "status", lambda qid, step, q=None: {"status": "none"})
    monkeypatch.setattr(social_cards, "enqueue", lambda qid, queued_by="", on_demand=False: queued.append((qid, on_demand)))
    r = se.post_card("q1", "steps1")
    assert not r["ok"] and r["making"] and queued == [("q1", True)]             # ahead of the queue
    assert "posts itself" in r["error"]
    r = se.post_card("q1", "answer")                                             # an animated card: the worker's too
    assert r["making"] and queued[-1] == ("q1", True)


def test_cards_made_after_post_now_go_out_in_order(monkeypatch) -> None:
    import app.infra.db as db
    import app.services.whiteboard as wb

    rows = [{"post_id": "p-teaser", "step": "teaser"}, {"post_id": "p-question", "step": "question"},
            {"post_id": "p-answer", "step": "answer"}]
    ready = {"teaser", "question"}
    sent = []
    monkeypatch.setattr(db, "fetch_all", lambda sql, p=None: rows)
    monkeypatch.setattr(wb, "load", lambda qid: Q)
    monkeypatch.setattr(se, "pull_poster", lambda: {"poster_id": "mac"})
    monkeypatch.setattr(social_cards, "status", lambda qid, step, q=None: {"status": "ready" if step in ready else "none"})
    monkeypatch.setattr(se, "queue_command", lambda a, p, pid, by="", options=None: sent.append(pid) or len(sent))
    assert se.hand_cards_when_made("q1") == [1, 2] and sent == ["p-teaser", "p-question"]   # never the answer first
    monkeypatch.setattr(se, "pull_poster", lambda: None)
    assert se.hand_cards_when_made("q1") == []


def test_a_chemistry_items_teaser_question_and_answer_are_animated(monkeypatch) -> None:
    import app.infra.storage as st

    monkeypatch.setattr(st.object_storage, "object_exists", lambda name: name.endswith(".gif"))
    monkeypatch.setattr(st, "public_object_url", lambda name: "u/" + name)
    for step in ("teaser", "question", "answer"):
        assert social_cards.animated(Q, step)
        r = social_cards.status("q1", step, Q)
        assert r["status"] == "ready" and r["url"].endswith(".gif")
    assert not social_cards.animated(Q, "kicd")                   # the KICD card stays a picture
    assert not social_cards.animated({"question_text": "2 + 2?"}, "teaser")
    doc = social_cards.page({**Q, "options": [{"text": "a", "is_correct": True}, {"text": "b"}]}, "teaser",
                            {**__import__("app.services.social", fromlist=["x"]).brand(), "accent": "#f59e0b"}, animate=True)
    assert "BREAKING" in doc and "window.__at" in doc and "ACCENT" not in doc


def test_a_chemistry_kicd_card_is_narrowed_to_its_question() -> None:
    slos = ["describe the structure of the atom", "separate mixtures using magnetism, sublimation and filtration",
            "appreciate the use of indicators", "classify substances as acids or bases"]
    got = social_cards.focused(Q, slos, 1)
    assert got == ["separate mixtures using magnetism, sublimation and filtration"]
    assert social_cards.focused(Q, slos, 2)[1] == slos[1] or slos[1] in social_cards.focused(Q, slos, 2)


def test_an_animated_card_posts_its_picture_and_comments_its_gif(monkeypatch) -> None:
    import app.infra.storage as st

    monkeypatch.setattr(st.object_storage, "object_exists", lambda name: True)
    monkeypatch.setattr(st, "public_object_url", lambda name: "u/" + name)
    r = social_cards.status("q1", "answer", Q)
    assert r["url"].endswith(".gif") and r["gif_url"] == r["url"] and r["still_url"].endswith(".jpg")
    grids = [{"jpg": "g0.jpg", "gif": "g0.gif", "jpg_name": "n0.jpg", "gif_name": "n0.gif"}]
    monkeypatch.setattr(chem_stills, "status", lambda qid, q: {"grids": grids, "stills": []})
    a = social_cards.status("q1", "anim0", Q)
    assert (a["still_url"], a["gif_url"]) == ("g0.jpg", "g0.gif")
    assert "gif_url" not in social_cards.status("q1", "steps0", Q)                  # a still card: no comment GIF
    assert social_cards.gif_comment("anim0").startswith("▶️ Every step") and social_cards.gif_comment("teaser").startswith("▶️ Breaking")

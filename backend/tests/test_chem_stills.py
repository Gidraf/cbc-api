"""Pictures of each step of a chemistry walkthrough: when, what they say, where they go."""
from __future__ import annotations

from app.services import chem_stills as X
from app.services import play_engine


def _scenes(chem: dict) -> list[dict]:
    q = {"question_id": "x", "question_text": "?", "chemistry": chem, "curriculum": {"subject": "Chemistry"}}
    return play_engine.walkthrough(q)["scenes"]


def test_a_reaction_has_its_set_up_its_steps_and_its_result() -> None:
    sc = _scenes({"reactants": ["NaOH", "CuSO4"]})
    ms = X.moments(sc, [5.0] * len(sc))
    roles = [m["role"] for m in ms]
    assert roles[0] == "setup" and "result" in roles
    kinds = [m["scene"] for m in ms]
    assert {"chem_lab", "chem_equation", "chem_atoms"} <= set(kinds)
    assert any("Cu(OH)₂" in m["caption"] for m in ms) and all(0 < m["f"] <= 1 for m in ms)


def test_bonding_and_separation_steps_each_get_a_picture() -> None:
    bond = X.moments(s := _scenes({"bond": ["Mg", "O"]}), [5.0] * len(s))
    assert [m["role"] for m in bond].count("step") >= 3 and "lattice" in bond[-1]["caption"]
    assert "outer electrons are" in next(m["caption"] for m in bond if "held weakly" in m["caption"])   # Mg has two
    sep = X.moments(s := _scenes({"separate": ["iron filings", "sand", "salt"]}), [5.0] * len(s))
    assert [m["caption"].split(":")[0] for m in sep] == ["🧪 Magnetic separation", "🧪 Dissolving", "🧪 Filtration", "🧪 Evaporation"]


def test_a_long_walkthrough_keeps_an_even_spread() -> None:
    sc = _scenes({"separate": ["iron filings", "sand", "salt", "iodine"]}) * 4
    assert len([m for m in X.moments(sc, [5.0] * len(sc)) if m["role"] != "setup"]) <= X.MAX_STILLS


def test_the_pictures_become_comments_and_the_cards_show_them(monkeypatch) -> None:
    from app.services import social_cards

    fake = {"status": "ready", "stills": [
        {"role": "setup", "caption": "set-up", "url": "u0", "scene": "chem_lab"},
        {"role": "step", "caption": "at the bench", "url": "u1", "scene": "chem_lab"},
        {"role": "result", "caption": "balanced", "url": "u2", "scene": "chem_equation"}]}
    monkeypatch.setattr(X, "status", lambda qid, q: fake)
    q = {"question_id": "x", "chemistry": {"reactants": ["Zn", "HCl"]}}
    assert X.comments("x", q) == [{"text": "at the bench", "image_url": "u1"}, {"text": "balanced", "image_url": "u2"}]
    assert social_cards._chem_figure(q, "question") == "u0" and social_cards._chem_figure(q, "answer") == "u2"
    assert social_cards._chem_figure({"question_id": "y"}, "question") == ""


def _made(chem: dict) -> list[dict]:
    sc = _scenes(chem)
    return [{**m, "url": f"u{k}"} for k, m in enumerate(X.moments(sc, [5.0] * len(sc)))]


def test_the_answer_card_shows_the_step_the_question_asks_about() -> None:
    q = {"question_text": "Sugar, tetrachloromethane and water are poured into a separating funnel. Which liquid forms the lower layer?",
         "chemistry": {"separate": ["sugar", "tetrachloromethane", "water"], "focus": "layer"}}
    assert X.pick_for(q, _made(q["chemistry"]), "answer")["method"] == "separating_funnel"     # not the crystallisation after it
    q = {"question_text": "What is the residue?", "chemistry": {"separate": ["iron filings", "sand", "salt"], "focus": "residue"}}
    assert X.pick_for(q, _made(q["chemistry"]), "answer")["method"] == "filtration"
    q = {"question_text": "Why can heating separate a mixture of iodine and sand?", "chemistry": {"separate": ["iodine", "sand"], "focus": "why"}}
    assert X.pick_for(q, _made(q["chemistry"]), "answer")["method"] == "sublimation"
    q = {"question_text": "In what order?", "chemistry": {"separate": ["iron filings", "sand", "salt"], "focus": "order"}}
    assert X.pick_for(q, _made(q["chemistry"]), "answer", [{"jpg": "grid.jpg"}])["url"] == "grid.jpg"   # every step
    q = {"question_text": "Which is the balanced equation?", "chemistry": {"reactants": ["Zn", "HCl"], "focus": "balancing"}}
    assert X.pick_for(q, _made(q["chemistry"]), "answer")["scene"] == "chem_equation"


def test_the_steps_go_four_to_a_picture_evenly() -> None:
    ms = [{"role": "step"}] * 5
    assert [len(g) for g in X._groups(ms)] == [3, 2]
    assert [len(g) for g in X._groups([{"role": "step"}] * 8)] == [4, 4]
    assert X._groups([{"role": "setup"}, {"role": "step"}]) == []                     # one step needs no grid


def test_the_step_pictures_lead_the_comments(monkeypatch) -> None:
    fake = {"status": "ready", "grids": [{"jpg": "g.jpg", "gif": "g.gif"}],
            "stills": [{"role": "step", "caption": "filter", "url": "u1", "scene": "chem_separation"}]}
    monkeypatch.setattr(X, "status", lambda qid, q: fake)
    got = X.comments("x", {"chemistry": {"separate": ["sand", "water"]}})
    assert [c["image_url"] for c in got] == ["g.jpg", "g.gif", "u1"]
    assert got[0]["text"].startswith("🧩") and got[1]["text"].startswith("🎞") and got[2]["text"] == "filter"

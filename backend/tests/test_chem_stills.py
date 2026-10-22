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

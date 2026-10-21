"""The chemistry engine: formulas, exact balancing, the reactions of school
chemistry by its rules, the walkthrough the board animates, and the checks
that send a writer's wrong key back."""
from __future__ import annotations

import pytest

from app.services import chem_engine as C
from app.services import chem_walkthrough as W


def test_formulas_are_read_with_brackets_and_hydrates() -> None:
    assert C.parse("Fe2(SO4)3") == {"Fe": 2, "S": 3, "O": 12}
    assert C.parse("Ca(OH)2") == {"Ca": 1, "O": 2, "H": 2}
    assert C.parse("CuSO4·5H2O") == {"Cu": 1, "S": 1, "O": 9, "H": 10}
    assert C.parse("CuSO₄") == {"Cu": 1, "S": 1, "O": 4}
    assert C.pretty("Fe2(SO4)3") == "Fe₂(SO₄)₃"
    with pytest.raises(ValueError):
        C.parse("Xx2")


@pytest.mark.parametrize("left,right,want", [
    (["Fe", "Cl2"], ["FeCl3"], ([2, 3], [2])),
    (["C3H8", "O2"], ["CO2", "H2O"], ([1, 5], [3, 4])),
    (["KMnO4", "HCl"], ["KCl", "MnCl2", "H2O", "Cl2"], ([2, 16], [2, 2, 8, 5])),
    (["Al", "O2"], ["Al2O3"], ([4, 3], [2])),
    (["Fe2O3", "CO"], ["Fe", "CO2"], ([1, 3], [2, 3])),
])
def test_equations_balance_exactly(left, right, want) -> None:
    assert C.balance(left, right) == want


def test_an_impossible_equation_is_refused() -> None:
    with pytest.raises(ValueError):
        C.balance(["H2"], ["O2"])


@pytest.mark.parametrize("a,b,cond,kind,equation", [
    ("Mg", "HCl", "", "metal_acid", "Mg + 2HCl → MgCl₂ + H₂"),
    ("Na", "H2O", "", "metal_water", "2Na + 2H₂O → 2NaOH + H₂"),
    ("Zn", "CuSO4", "", "displacement", "Zn + CuSO₄ → ZnSO₄ + Cu"),
    ("Cu", "AgNO3", "", "displacement", "Cu + 2AgNO₃ → Cu(NO₃)₂ + 2Ag"),
    ("HCl", "NaOH", "", "neutralisation", "HCl + NaOH → NaCl + H₂O"),
    ("H2SO4", "CuO", "", "neutralisation", "H₂SO₄ + CuO → CuSO₄ + H₂O"),
    ("HCl", "CaCO3", "", "acid_carbonate", "2HCl + CaCO₃ → CaCl₂ + H₂O + CO₂"),
    ("AgNO3", "NaCl", "", "precipitation", "AgNO₃ + NaCl → AgCl + NaNO₃"),
    ("NaOH", "FeCl3", "", "precipitation", "3NaOH + FeCl₃ → Fe(OH)₃ + 3NaCl"),
    ("CH4", "O2", "", "combustion", "CH₄ + 2O₂ → CO₂ + 2H₂O"),
    ("Mg", "O2", "", "metal_oxygen", "2Mg + O₂ → 2MgO"),
    ("Fe", "Cl2", "", "chlorination", "2Fe + 3Cl₂ → 2FeCl₃"),
    ("CaCO3", "", "heat", "decomposition", "CaCO₃ → CaO + CO₂"),
    ("Ca(HCO3)2", "", "boil", "decomposition", "Ca(HCO₃)₂ → CaCO₃ + H₂O + CO₂"),
    ("Fe", "H2O", "steam", "metal_water", "3Fe + 4H₂O → Fe₃O₄ + 4H₂"),
    ("Na", "FeCl3", "molten", "displacement", "3Na + FeCl₃ → 3NaCl + Fe"),
])
def test_the_reactions_of_school_chemistry(a, b, cond, kind, equation) -> None:
    r = C.react(a, b, condition=cond)
    assert r["reacts"] and r["type"] == kind and r["equation"] == equation
    assert r["observations"] and r["steps"][-1].startswith(("Balanced", "Test for"))
    after = r["atoms"]["after"]
    assert after["left"] == after["right"], "balanced: every atom on both sides"


@pytest.mark.parametrize("a,b,why", [
    ("Cu", "HCl", "below hydrogen"),
    ("Cu", "ZnSO4", "below zinc"),
    ("Au", "O2", "unreactive"),
    ("NaCl", "KNO3", "soluble"),
])
def test_what_does_not_react_says_why(a, b, why) -> None:
    r = C.react(a, b)
    assert r["reacts"] is False and r["covered"] and why in r["why"]


def test_what_the_rules_do_not_cover_is_never_guessed() -> None:
    r = C.react("Ne", "Ar")
    assert r["reacts"] is False and r["covered"] is False


def test_sodium_in_a_solution_reacts_with_the_water_first() -> None:
    r = C.react("Na", "FeCl3")
    assert r["type"] == "metal_water" and "molten" in r["note"]


def test_observations_carry_the_lab_animation_and_the_gas_test() -> None:
    r = C.react("HCl", "CaCO3")
    assert r["lab"]["bubbles"] == "CO2" and r["lab"]["limewater"]
    assert "limewater milky" in r["gas_tests"]["CO2"]
    ppt = C.react("NaOH", "CuSO4")
    assert ppt["lab"]["precipitate"] == C.COLOURS["Cu(OH)2"][1] and "blue precipitate" in ppt["observations"][0]


def test_the_walkthrough_shows_the_lab_the_series_and_the_balanced_equation() -> None:
    from app.services import play_engine

    q = {"question_id": "c1", "question_text": "What is seen when zinc is put in CuSO4 solution?",
         "chemistry": {"reactants": ["Zn", "CuSO4"]}, "curriculum": {"subject": "Integrated Science"}}
    w = play_engine.walkthrough(q)
    kinds = [s["scene"] for s in w["scenes"]]
    assert kinds[:5] == ["title", "chem_lab", "chem_series", "chem_word", "chem_equation"]
    assert "chem_list" in kinds and w["kind"] == "chemistry"
    assert "copper two sulphate" in w["scenes"][0]["say"], "a formula in the question is said as its name"
    series = w["scenes"][2]
    assert series["highlight"] == ["Zn", "Cu"]
    eq = w["scenes"][4]
    assert eq["equation"] == "Zn + CuSO₄ → ZnSO₄ + Cu" and "rewrite" not in kinds


def test_a_balancing_item_balances_atom_by_atom() -> None:
    scenes = W.scenes_for({"chemistry": {"equation": "Fe + Cl2 -> FeCl3"}})
    assert scenes[0]["scene"] == "chem_equation" and scenes[0]["wrong"] == ["Cl"]
    assert scenes[0]["equation"] == "2Fe + 3Cl₂ → 2FeCl₃"


def test_a_key_that_disagrees_with_the_engine_is_sent_back() -> None:
    from app.services.question_check import Finding, _chemistry_disagrees

    items = [
        {"question_id": "a", "question_text": "Does copper react with dilute HCl?", "chemistry": {"reactants": ["Cu", "HCl"]},
         "options": [{"id": "A", "text": "Yes, hydrogen is given off", "is_correct": True}]},
        {"question_id": "b", "question_text": "Balance it", "chemistry": {"equation": "Fe + Cl2 -> FeCl3"},
         "correct_answer": "Fe + Cl2 -> FeCl2"},
        {"question_id": "c", "question_text": "Zinc and copper sulphate", "chemistry": {"reactants": ["Zn", "CuSO4"]},
         "correct_answer": "Zn + CuSO4 -> ZnSO4 + Cu"},
        {"question_id": "d", "question_text": "?", "chemistry": {"reactants": ["Qq", "HCl"]}, "correct_answer": "x"},
        {"question_id": "e", "question_text": "Magnesium and acid", "chemistry": {"reactants": ["Mg", "HCl"]},
         "correct_answer": "Mg(s) + 2HCl(aq) → MgCl₂(aq) + H₂(g)"},
    ]
    found: list[Finding] = []
    _chemistry_disagrees(items, found)
    kinds = {f.items[0]: f.kind for f in found}
    assert kinds.get("a") == "chemistry_disagrees"
    assert kinds.get("b") == "chemistry_disagrees", "a wrong product (FeCl2) is caught"
    assert kinds.get("d") == "chemistry_unreadable"
    assert "c" not in kinds and "e" not in kinds, "a key that agrees passes (state symbols or not)"


def test_the_sciences_get_a_british_or_american_voice() -> None:
    from app.services.math_engine.tts_service import is_science, science_voice, voice_for

    assert is_science("Integrated Science") and is_science("Chemistry") and not is_science("Mathematics")
    assert science_voice("male", "q1").startswith(("en-GB-", "en-US-"))
    assert science_voice("male", "q1") == science_voice("male", "q1"), "the same item keeps its voice"
    assert voice_for("Integrated Science").startswith(("en-GB-", "en-US-"))


def test_the_lab_game_mixes_two_substances() -> None:
    out = W.lab("Mg", "HCl")
    assert out["reaction"]["equation"] == "Mg + 2HCl → MgCl₂ + H₂"
    assert out["walkthrough"]["scenes"][1]["scene"] == "chem_lab"
    groups = {g["group"] for g in W.substances()}
    assert {"Metals", "Acids", "Salts in solution"} <= groups
    for g in W.substances():
        for it in g["items"]:
            C.parse(it["formula"])          # every shelf item is a formula the engine reads


def test_the_prompts_own_examples_agree_with_the_engine() -> None:
    import json
    from pathlib import Path

    from app.services.question_check import Finding, _chemistry_disagrees

    doc = (Path(__file__).resolve().parents[2] / "docs" / "prompts" / "chemistry-questions.md").read_text()
    items = json.loads(doc.split("## Examples")[1].split("```json")[1].split("```")[0])
    for k, it in enumerate(items):
        it["question_id"] = f"ex{k}"
        assert W.scenes_for(it), f"example {k} makes a walkthrough"
    found: list[Finding] = []
    _chemistry_disagrees(items, found)
    assert found == []

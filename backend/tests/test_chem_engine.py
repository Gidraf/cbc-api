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
    assert kinds[:6] == ["title", "chem_hook", "chem_lab", "chem_series", "chem_word", "chem_equation"]
    assert "chem_list" in kinds and w["kind"] == "chemistry"
    assert "copper two sulphate" in w["scenes"][0]["say"], "a formula in the question is said as its name"
    series = w["scenes"][3]
    assert series["highlight"] == ["Zn", "Cu"]
    eq = w["scenes"][5]
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
    assert out["walkthrough"]["scenes"][2]["scene"] == "chem_lab"
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


@pytest.mark.parametrize("sym,arr,ion,ion_arr", [
    ("Na", "2.8.1", "Na⁺", "2.8"), ("Cl", "2.8.7", "Cl⁻", "2.8.8"), ("Mg", "2.8.2", "Mg²⁺", "2.8"),
    ("O", "2.6", "O²⁻", "2.8"), ("Al", "2.8.3", "Al³⁺", "2.8"), ("Ca", "2.8.8.2", "Ca²⁺", "2.8.8"),
    ("N", "2.5", "N³⁻", "2.8"), ("Ar", "2.8.8", "Ar", "2.8.8"),
])
def test_electron_arrangements_and_ions(sym, arr, ion, ion_arr) -> None:
    a = C.atom(sym)
    assert (a["arrangement"], a["ion"], a["ion_arrangement"]) == (arr, ion, ion_arr)
    assert a["protons"] == a["electrons"] == C.ATOMIC_NUMBER[sym]


@pytest.mark.parametrize("a,b,kind,formula", [
    ("Na", "Cl", "ionic", "NaCl"), ("Mg", "Cl", "ionic", "MgCl2"), ("Al", "O", "ionic", "Al2O3"), ("K", "S", "ionic", "K2S"),
    ("Li", "N", "ionic", "Li3N"), ("Cl", "Mg", "ionic", "MgCl2"),
    ("H", "Cl", "covalent", "HCl"), ("H", "O", "covalent", "H2O"), ("N", "H", "covalent", "NH3"), ("C", "H", "covalent", "CH4"),
    ("C", "O", "covalent", "CO2"), ("Cl", "Cl", "covalent", "Cl2"), ("O", "O", "covalent", "O2"),
])
def test_the_formula_comes_from_the_electrons(a, b, kind, formula) -> None:
    r = C.bond(a, b)
    assert r["kind"] == kind and r["formula"] == formula
    if kind == "ionic":
        q = abs(C.atom(r["metal"])["ion_charge"])
        assert len(r["moves"]) == r["counts"][r["metal"]] * q, "every electron given is shown moving"


def test_noble_gases_and_two_metals_do_not_bond() -> None:
    assert C.bond("Na", "Ne")["kind"] == "none" and C.bond("Na", "Mg")["kind"] == "metallic"


@pytest.mark.parametrize("parts,keep,names", [
    (["sand", "water"], "", ["Filtration"]), (["salt", "water"], "", ["Evaporation"]),
    (["salt", "water"], "water", ["Simple distillation"]), (["sand", "salt"], "", ["Dissolving", "Filtration", "Evaporation"]),
    (["iron filings", "sulphur"], "", ["Magnetic separation"]), (["ethanol", "water"], "", ["Fractional distillation"]),
    (["oil", "water"], "", ["Separating funnel"]), (["ink"], "", ["Paper chromatography"]), (["iodine", "sand"], "", ["Sublimation"]),
])
def test_separating_mixtures(parts, keep, names) -> None:
    assert C.separate(parts, keep)["names"] == names


def test_every_kind_of_item_makes_its_scenes() -> None:
    kinds = lambda chem: [s["scene"] for s in W.scenes_for({"chemistry": chem})]  # noqa: E731
    assert kinds({"atom": "Mg"}) == ["chem_atom", "chem_result"]
    assert kinds({"bond": ["Al", "O"]}) == ["chem_hook", "chem_atom", "chem_atom", "chem_ionic", "chem_result"]
    assert "chem_covalent" in kinds({"bond": ["C", "H"]})
    assert kinds({"separate": ["sand", "salt"]}).count("chem_separation") == 3
    react = kinds({"reactants": ["Mg", "Cl2"]})
    assert react[0] == "chem_hook" and "chem_atoms" in react and "chem_ionic" in react, "why it is MgCl2"


def test_the_atoms_scene_carries_exactly_the_equations_atoms() -> None:
    from collections import Counter

    for a, b, cond in [("NaOH", "CuSO4", ""), ("C", "CuO", "heat"), ("CH4", "O2", ""), ("Zn", "HCl", ""), ("Fe", "Cl2", ""),
                       ("H2SO4", "NaOH", ""), ("CaCO3", "HCl", ""), ("Pb(NO3)2", "KI", "")]:
        sc = next(s for s in W.scenes_for({"chemistry": {"reactants": [a, b], "condition": cond}}) if s["scene"] == "chem_atoms")
        side = lambda xs: Counter(at["el"] for sp in xs for _ in range(sp["count"]) for at in sp["atoms"])  # noqa: E731
        assert side(sc["left2"]) == side(sc["right2"]) == Counter(sc["tally"]), (a, b)


def test_structures_have_their_formulas_atoms() -> None:
    from collections import Counter

    for f in ["H2O", "CuSO4", "Cu(OH)2", "Fe2(SO4)3", "H2SO4", "CH3COOH", "C2H5OH", "(NH4)2SO4", "Ca(HCO3)2", "Ag2O", "Al2O3"]:
        assert Counter(a["el"] for a in W.structure(f)) == Counter(C.parse(C.normalize(f))), f
    ethanol = W.structure("C2H5OH")
    assert sum(1 for a in ethanol if a["el"] == "H" and ethanol[a["to"]]["el"] == "O") == 1     # one H on the O
    ethanoate = W.structure("NaCH3COO")
    assert not any(a["el"] == "H" and ethanoate[a["to"]]["el"] == "O" for a in ethanoate)      # the ion has lost that H
    acid = W.structure("CH3COOH")
    assert sum(1 for a in acid if a["el"] == "H" and acid[a["to"]]["el"] == "O") == 1
    pair = W.scenes_for({"chemistry": {"bond": ["Na", "Cl"]}})
    atoms = [s for s in pair if s["scene"] == "chem_atom"]
    assert [a["slot"] for a in atoms] == [0, 1], "the two atoms share a page, side by side"


def test_the_lab_picks_atoms_bonds_and_mixtures() -> None:
    assert W.lab("Na", mode="atom")["reaction"]["arrangement"] == "2.8.1"
    assert W.lab("Mg", "Cl", mode="bond")["reaction"]["formula"] == "MgCl2"
    assert W.lab("sand,salt", mode="separate")["reaction"]["names"][0] == "Dissolving"
    assert len(W.periodic()) == 20


def test_the_chemistry_api_answers_and_meters(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import chem_api, content
    from app.services.auth import AuthContext

    charged: list[list[dict]] = []
    monkeypatch.setattr(chem_api, "_charge", lambda auth, items, ref: charged.append(items) or {"charged_ksh": 0})
    monkeypatch.setattr(chem_api, "_usage_headers", lambda owner: {})
    app.dependency_overrides[content.DEVELOPER] = lambda: AuthContext(subject="dev1", role="developer", auth_type="api_key")
    try:
        c = TestClient(app)
        r = c.get("/api/v1/chemistry/react", params={"a": "Zn", "b": "CuSO4"})
        assert r.status_code == 200 and r.json()["equation"] == "Zn + CuSO₄ → ZnSO₄ + Cu"
        assert c.post("/api/v1/chemistry/balance", json={"equation": "Fe + Cl2 -> FeCl3"}).json()["equation"] == "2Fe + 3Cl₂ → 2FeCl₃"
        assert c.get("/api/v1/chemistry/atom/Mg").json()["arrangement"] == "2.8.2"
        assert c.get("/api/v1/chemistry/bond", params={"a": "Al", "b": "O"}).json()["formula"] == "Al2O3"
        assert c.get("/api/v1/chemistry/separate", params={"parts": "oil,water"}).json()["names"] == ["Separating funnel"]
        w = c.post("/api/v1/chemistry/walkthrough", json={"chemistry": {"reactants": ["HCl", "NaOH"]}})
        assert w.status_code == 200 and w.json()["scenes"][1]["scene"] == "chem_hook"
        page = c.post("/api/v1/chemistry/animation.html", json={"chemistry": {"atom": "Na"}})
        assert page.status_code == 200 and "WB_DATA" in page.text
        assert c.get("/api/v1/chemistry/react", params={"a": "Xq"}).status_code == 400
        assert charged.count([{"has_figure": True}]) == 2, "an animation is charged as a figure question"
        assert charged.count([{"has_figure": False}]) == 5
    finally:
        app.dependency_overrides.pop(content.DEVELOPER, None)


def test_atom_bond_and_separation_items_are_checked_too() -> None:
    from app.services.question_check import Finding, _chemistry_disagrees

    items = [
        {"question_id": "a1", "question_text": "?", "chemistry": {"atom": "Mg"}, "correct_answer": "2.8.2"},
        {"question_id": "b1", "question_text": "?", "chemistry": {"bond": ["Mg", "Cl"]}, "correct_answer": "MgCl2"},
        {"question_id": "b2", "question_text": "?", "chemistry": {"bond": ["Mg", "Cl"]}, "correct_answer": "MgCl"},
        {"question_id": "s1", "question_text": "?", "chemistry": {"separate": ["sand", "water"]}, "correct_answer": "Filtration"},
        {"question_id": "s2", "question_text": "?", "chemistry": {"separate": ["marbles"]}, "correct_answer": "?"},
        {"question_id": "a2", "question_text": "?", "chemistry": {"atom": "Fe"}, "correct_answer": "2.8.14.2"},
    ]
    found: list[Finding] = []
    _chemistry_disagrees(items, found)
    kinds = {f.items[0]: f.kind for f in found}
    assert kinds == {"b2": "chemistry_disagrees", "s2": "chemistry_not_covered", "a2": "chemistry_unreadable"}


def test_the_3d_layer_comes_only_with_atoms_bonds_and_lattices() -> None:
    from app.services import play_engine, whiteboard

    def page(chem: dict) -> str:
        w = play_engine.walkthrough({"question_id": "x", "question_text": "?", "chemistry": chem, "curriculum": {"subject": "Chemistry"}})
        return whiteboard.page(w, title="t", voice="en-GB", durations=[4.0] * len(w["scenes"]))

    bond = page({"bond": ["Na", "Cl"]})
    assert "__onChem3d" in bond and bond.index("__onChem3d = frame") < bond.index("window.__onChem3d(clock.t)")
    sep = page({"separate": ["sand", "water"]})
    assert "__onChem3d = frame" in sep and "window.__lab3d" in sep           # the apparatus in 3D too
    assert "window.__lab3d" in page({"reactants": ["Zn", "HCl"]})
    assert "__onChem3d = frame" not in page({"equation": "H2 + O2 -> H2O"})


def test_a_mixture_may_be_named_as_a_question_names_it() -> None:
    assert C.separate(["iron", "sulfur"])["methods"] == ["magnet"]
    assert C.separate(["sodium chloride", "sand"])["methods"][:2] == ["dissolve", "filtration"]



@pytest.mark.parametrize("a, b, cond, equation", [
    ("NaOH", "CuSO4", "", "2NaOH + CuSO₄ → Cu(OH)₂ + Na₂SO₄"),
    ("Ca(OH)2", "Na2CO3", "", "Ca(OH)₂ + Na₂CO₃ → CaCO₃ + 2NaOH"),
    ("NaOH", "AgNO3", "", "2NaOH + 2AgNO₃ → Ag₂O + 2NaNO₃ + H₂O"),
    ("HCl", "AgNO3", "", "HCl + AgNO₃ → AgCl + HNO₃"),
    ("H2SO4", "BaCl2", "", "H₂SO₄ + BaCl₂ → BaSO₄ + 2HCl"),
    ("Fe", "S", "heat", "Fe + S → FeS"),
    ("C", "CuO", "heat", "C + 2CuO → 2Cu + CO₂"),
    ("H2", "CuO", "heat", "H₂ + CuO → Cu + H₂O"),
    ("CaO", "H2O", "", "CaO + H₂O → Ca(OH)₂"),
    ("Cu(NO3)2", "", "heat", "2Cu(NO₃)₂ → 2CuO + 4NO₂ + O₂"),
    ("NaHCO3", "", "heat", "2NaHCO₃ → Na₂CO₃ + H₂O + CO₂"),
])
def test_more_of_school_chemistry(a, b, cond, equation) -> None:
    r = C.react(a, b, condition=cond)
    assert r["reacts"] and r["equation"] == equation


@pytest.mark.parametrize("a, b, cond, why", [
    ("Zn", "Fe", "", "alloy"), ("CH4", "CuSO4", "", "burns in oxygen"), ("HCl", "H2SO4", "", "Both are acids"),
    ("NaOH", "NaCl", "", "Both contain sodium"), ("CuO", "CuSO4", "", "Both contain copper"),
    ("CaCO3", "ZnSO4", "", "does not dissolve"), ("Mg", "BaCl2", "", "Barium"), ("C", "MgO", "heat", "above carbon"),
    ("Fe", "S", "", "only combine when heated"), ("Al", "H2O", "", "oxide"), ("NaCl", "H2O", "", "dissolves"),
    ("NaCl", "KI", "", "stay mixed in solution"),
])
def test_what_does_not_react_says_why_in_school_terms(a, b, cond, why) -> None:
    r = C.react(a, b, condition=cond)
    assert r["covered"] and r["reacts"] is False and why in r["why"]


def test_almost_every_pair_on_the_shelf_is_decided() -> None:
    import itertools

    from app.services.chem_walkthrough import SUBSTANCES

    shelf = [f for fs in SUBSTANCES.values() for f in fs]
    pairs = list(itertools.combinations(shelf, 2))
    open_ = [p for p in pairs if not C.react(*p)["covered"]]
    assert len(open_) / len(pairs) < 0.02, open_[:10]


def test_smelly_gases_are_smelt_on_their_way_across_the_room() -> None:
    from app.services import chem_walkthrough as W

    nh3 = C.react("NH4Cl", "NaOH", condition="heat")
    assert nh3["equation"] == "NH₄Cl + NaOH → NaCl + NH₃ + H₂O" and W.smell_of(nh3)["gas"] == "NH3"
    assert not C.react("NH4Cl", "NaOH")["reacts"]                                  # warmed, or hardly any
    h2s = C.react("FeS", "HCl")
    assert h2s["equation"] == "FeS + 2HCl → FeCl₂ + H₂S" and "rotten eggs" in W.smell_of(h2s)["like"]
    assert C.react("NH4NO3", condition="heat")["products"] == ["N2O", "H2O"]        # never (NH4)2O
    assert W.smell_of(C.react("Mg", "HCl")) is None                                 # hydrogen has no smell
    lab = W._lab(C.react("S", "O2"), ["sulphur", "oxygen"], {})
    assert lab["lab"]["smell"]["name"] == "sulphur dioxide" and any("struck match" in o for o in lab["observations"])

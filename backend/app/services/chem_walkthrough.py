"""A chemistry item's walkthrough: the scenes the board animates, from the
chemistry engine's reaction — the lab bench (what goes in, what you see),
the reactivity series when it decides the answer, the equation from words to
symbols to balanced (atom counts side by side), the observations and gas
tests, and where the reaction is used in life.

The narration names substances ("zinc", "copper(II) sulphate"), never
formulas, so the voice reads it as a teacher would; the board writes the
formulas. Nothing here is written by a model: the engine decides it all.
"""
from __future__ import annotations

import re
from typing import Any

from . import chem_engine as C

SERIES_TYPES = {"metal_acid", "metal_water", "displacement"}


def scenes_for(question: dict[str, Any]) -> list[dict[str, Any]]:
    spec = question.get("chemistry") or {}
    try:
        if spec.get("equation") and not spec.get("reactants"):
            return _balancing(spec["equation"])
        reactants = [C.normalize(r) for r in (spec.get("reactants") or []) if str(r).strip()][:2]
        if not reactants:
            return []
        result = C.react(reactants[0], reactants[1] if len(reactants) > 1 else "", condition=str(spec.get("condition") or ""))
    except ValueError:
        return []
    if not result.get("covered", True):
        return [{"scene": "working", "text": result["why"], "say": result["why"]}]
    out: list[dict[str, Any]] = []
    names = [C.name_of(r) for r in result.get("reactants") or reactants]
    out.append(_lab(result, names, spec))
    metals = [C._symbol_of(r) for r in (result.get("reactants") or reactants)]
    metals = [m for m in metals if m in C.REACTIVITY]
    other = _salt_metal(result.get("reactants") or reactants)
    if result.get("reacts") is False:
        if metals:
            out.append(_series(metals + ([other] if other else ["H"] if any(r in C.ACIDS for r in reactants) else []), result["why"]))
        out.append({"scene": "chem_result", "title": "No reaction", "text": result["why"], "say": result["why"]})
        return out
    if result["type"] in SERIES_TYPES and metals:
        pick = metals + ([other] if other else ["H"])
        out.append(_series(pick, result["why"]))
    if result.get("note"):
        out.append({"scene": "working", "text": result["note"], "say": result["note"]})
    out.append({"scene": "chem_word", "text": result["word"],
                "say": "In words: " + result["word"].replace("→", "gives").replace("+", "and") + "."})
    out.append(_equation(result))
    obs = list(result.get("observations") or [])
    out.append({"scene": "chem_list", "title": "What you see", "icon": "👀", "items": obs,
                "say": "What you see: " + ". ".join(obs) + "."})
    if result.get("gas_tests"):
        tests = [f"{C.GAS_NAMES[g].capitalize()}: {t}" for g, t in result["gas_tests"].items()]
        out.append({"scene": "chem_list", "title": "Testing the gas", "icon": "🧪", "items": tests,
                    "say": " ".join(f"To test for {C.GAS_NAMES[g]}: {t}." for g, t in result["gas_tests"].items())})
    if result.get("applications") and str(spec.get("focus") or "") != "balancing":
        apps = result["applications"][:3]
        out.append({"scene": "chem_list", "title": "Where it is used", "icon": "🌍", "items": apps,
                    "say": "Where this matters in real life: " + ". ".join(apps) + "."})
    return out


def _salt_metal(reactants: list[str]) -> str:
    for r in reactants:
        s = C.split_salt(r)
        if s:
            m = "Fe" if s[0] == "Fe3" else s[0]
            if m in C.REACTIVITY:
                return m
    return ""


def _lab(result: dict[str, Any], names: list[str], spec: dict[str, Any]) -> dict[str, Any]:
    lab = dict(result.get("lab") or {"vessel": "beaker"})
    reacts = result.get("reacts", True)
    if not reacts:
        lab = {k: v for k, v in lab.items() if k in ("vessel", "solid", "liquid")} or {"vessel": "beaker"}
        lab.setdefault("liquid", C.COLOURS["none"][1])
    cond = str(spec.get("condition") or "")
    how = " and heat it" if any(w in cond for w in ("heat", "steam", "boil", "molten")) else ""
    mix = " and ".join(names)
    say = (f"Let us try it: {mix}{how}. " if len(names) > 1 else f"Let us heat {mix}. ")
    if reacts:
        first = (result.get("observations") or [""])[0]
        say += f"Watch closely. {first}."
    else:
        say += "Watch closely. Nothing happens."
    return {"scene": "chem_lab", "reactants": [{"formula": C.pretty(r), "name": n} for r, n in zip(result.get("reactants") or [], names)],
            "lab": lab, "reacts": bool(reacts), "condition": cond, "observations": list(result.get("observations") or [])[:3],
            "say": say}


def _series(metals: list[str], why: str) -> dict[str, Any]:
    picked = [m for m in dict.fromkeys(metals) if m in C.REACTIVITY]
    order = [m for m in C.REACTIVITY if m not in ("Pt",)]
    return {"scene": "chem_series", "series": [{"symbol": m, "name": C.ELEMENTS.get(m, m)} for m in order],
            "highlight": picked, "say": "Look at the reactivity series. " + why}


def _equation(result: dict[str, Any]) -> dict[str, Any]:
    atoms = result["atoms"]
    wrong = [el for el in sorted(set(atoms["before"]["left"]) | set(atoms["before"]["right"]))
             if atoms["before"]["left"].get(el, 0) != atoms["before"]["right"].get(el, 0)]
    if wrong:
        say = ("Now in symbols. Count the atoms on each side: " +
               ", ".join(f"{C.ELEMENTS.get(el, el)} has {atoms['before']['left'].get(el, 0)} on the left and "
                         f"{atoms['before']['right'].get(el, 0)} on the right" for el in wrong) +
               ". We put numbers in front of the formulas, never changing a formula, until every atom balances.")
    else:
        say = "Now in symbols. Count the atoms on each side: they already balance."
    return {"scene": "chem_equation", "reactants": [C.pretty(r) for r in result["reactants"]],
            "products": [C.pretty(p) for p in result["products"]], "coefficients": result["coefficients"],
            "states": {C.pretty(k): v for k, v in (result.get("states") or {}).items()},
            "atoms": atoms, "wrong": wrong, "unbalanced": result["unbalanced"], "equation": result["equation"],
            "say": say + " Balanced, it reads: " + _spoken_equation(result) + "."}


def _spoken_equation(result: dict[str, Any]) -> str:
    def side(fs: list[str], cs: list[int]) -> str:
        return " plus ".join((f"{c} " if c != 1 else "") + C.name_of(f) for f, c in zip(fs, cs))
    return side(result["reactants"], result["coefficients"]["reactants"]) + " gives " + \
        side(result["products"], result["coefficients"]["products"])


def _balancing(equation: str) -> list[dict[str, Any]]:
    b = C.balance_given(equation)
    r = {"reactants": b["reactants"], "products": b["products"], "coefficients": b["coefficients"], "atoms": b["atoms"],
         "unbalanced": b["unbalanced"], "equation": b["equation"], "states": {}}
    return [_equation(r), {"scene": "chem_result", "title": "Balanced", "text": b["equation"],
                           "say": "Every atom now appears the same number of times on both sides: the equation is balanced."}]


def speakable_formulae(text: str) -> str:
    """A formula left in a narration said as its name where the engine knows it."""
    def name(m: re.Match) -> str:
        try:
            return C.name_of(m.group(0))
        except Exception:  # noqa: BLE001
            return m.group(0)
    return re.sub(r"\b(?:[A-Z][a-z]?\d*(?:\([A-Za-z0-9]+\)\d+)?){2,}\b", name, text)


# ── the lab game: pick two, mix, watch ───────────────────────────────────────

SUBSTANCES: dict[str, list[str]] = {
    "Metals": ["K", "Na", "Ca", "Mg", "Al", "Zn", "Fe", "Pb", "Cu", "Ag", "Au"],
    "Non-metals and gases": ["C", "S", "H2", "O2", "Cl2", "H2O"],
    "Acids": ["HCl", "H2SO4", "HNO3", "CH3COOH"],
    "Bases and alkalis": ["NaOH", "KOH", "Ca(OH)2", "CuO", "MgO", "ZnO", "CaO"],
    "Carbonates": ["CaCO3", "Na2CO3", "CuCO3", "ZnCO3", "MgCO3", "NaHCO3", "Ca(HCO3)2"],
    "Salts in solution": ["CuSO4", "FeSO4", "FeCl3", "ZnSO4", "AgNO3", "Pb(NO3)2", "NaCl", "KI", "BaCl2", "MgSO4", "CaCl2"],
    "Fuels": ["CH4", "C3H8", "C2H5OH"],
}


def substances() -> list[dict[str, Any]]:
    return [{"group": g, "items": [{"formula": f, "pretty": C.pretty(f), "name": C.name_of(f)} for f in fs]}
            for g, fs in SUBSTANCES.items()]


def lab(a: str, b: str = "", condition: str = "") -> dict[str, Any]:
    """The game's mix: the engine's reaction and its walkthrough (as for a question)."""
    from .play_engine import walkthrough

    names = " and ".join(C.name_of(x) for x in (a, b) if x)
    q = {"question_id": f"lab:{C.normalize(a)}+{C.normalize(b)}:{condition}",
         "question_text": f"What happens when {names} {'are' if b else 'is'} {'mixed' if b else 'heated'}"
                          + (f" ({condition})" if condition and b else "") + "?",
         "chemistry": {"reactants": [x for x in (a, b) if x], "condition": condition},
         "curriculum": {"subject": "Chemistry"}}
    reaction = C.react(a, b, condition=condition)
    return {"reaction": reaction, "walkthrough": walkthrough(q), "question": q}

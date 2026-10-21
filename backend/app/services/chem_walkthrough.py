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
        if spec.get("atom") and not spec.get("reactants"):
            return _atom_scenes(str(spec["atom"]))
        if spec.get("bond") and not spec.get("reactants"):
            pair = [str(x) for x in spec["bond"]][:2]
            return _bond_scenes(pair[0], pair[1])
        if spec.get("separate"):
            return _separation_scenes([str(x) for x in spec["separate"]], str(spec.get("keep") or ""))
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
    out: list[dict[str, Any]] = [_hook(result.get("reactants") or reactants, spec)]
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
    parts = _particles(result)
    if parts:
        out.append(parts)
    out += _where_the_formula_comes_from(result)
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


# ── the opening, the particles, the electrons ───────────────────────────────

CPK = {"H": "#f2f2f2", "C": "#3a3a3a", "N": "#3050f8", "O": "#e8261b", "F": "#90e050", "Cl": "#1fbf3f", "Br": "#a62929",
       "I": "#7a1fa2", "S": "#e6c200", "P": "#ff8000", "Na": "#9a5cf0", "K": "#8f40d4", "Li": "#cc80ff", "Ca": "#7f8c8d",
       "Mg": "#4caf50", "Al": "#b0b8c0", "Fe": "#c0632b", "Cu": "#c8792f", "Zn": "#7d80b0", "Ag": "#c0c0c0", "Pb": "#575961",
       "Ba": "#00c900", "Mn": "#9c7ac7", "Sn": "#668080", "Au": "#ffd123", "Si": "#d4b896", "He": "#d9ffff", "Ne": "#b3e3f5",
       "Ar": "#80d1e3", "Be": "#c2ff00", "B": "#ffb5b5", "Hg": "#b8b8d0", "Ni": "#50d050"}


def _tile(f: str) -> dict[str, Any]:
    sym = C._symbol_of(f)
    if sym and sym in C.ELEMENTS:
        return {"symbol": sym, "name": C.ELEMENTS[sym].capitalize(), "Z": C.ATOMIC_NUMBER.get(sym, ""),
                "colour": CPK.get(sym, "#999999"), "formula": C.pretty(C.DIATOMIC.get(sym, sym))}
    n = C.name_of(f)
    return {"symbol": C.pretty(f), "name": n[:1].upper() + n[1:], "Z": "", "colour": "#5b8db8", "formula": C.pretty(f)}


def _hook(reactants: list[str], spec: dict[str, Any]) -> dict[str, Any]:
    """The opening: two tiles from the periodic table slide in and meet."""
    tiles = [_tile(r) for r in reactants[:2]]
    names = " and ".join(t["name"].lower() for t in tiles)
    cond = str(spec.get("condition") or "")
    q = (f"What happens when {names} meet?" if len(tiles) > 1 else f"What happens when {names} is heated?")
    if cond and len(tiles) > 1:
        q = f"What happens when {names} meet" + {"heat": " and are heated", "steam": " in steam", "molten": " — molten",
                                                 "boil": " and are boiled"}.get(cond, "") + "?"
    return {"scene": "chem_hook", "tiles": tiles, "question": q, "say": q + " Let us find out."}


def _molecule(formula: str) -> list[list[Any]]:
    """A formula's atoms as [element, count] in order, for drawing a particle."""
    return [[el, n] for el, n in C.parse(formula).items()]


def _particles(result: dict[str, Any]) -> dict[str, Any] | None:
    """The balancing as particles side by side: each molecule drawn as its
    atoms; the numbers in front add copies until both sides match. Only
    when it stays drawable (a dozen particles at most, small molecules)."""
    rc, pc = result["coefficients"]["reactants"], result["coefficients"]["products"]
    if sum(rc) + sum(pc) > 14 or any(sum(C.parse(f).values()) > 9 for f in result["reactants"] + result["products"]):
        return None
    side = lambda fs, cs: [{"formula": C.pretty(f), "atoms": _molecule(f), "count": c} for f, c in zip(fs, cs)]  # noqa: E731
    return {"scene": "chem_particles", "left": side(result["reactants"], rc), "right": side(result["products"], pc),
            "colours": {el: CPK.get(el, "#999999") for f in result["reactants"] + result["products"] for el in C.parse(f)},
            "atoms": result["atoms"],
            "say": "Watch the particles. Atoms are never made or destroyed in a reaction — only rearranged. "
                   "So we add whole particles until every kind of atom is the same on both sides."}


def _where_the_formula_comes_from(result: dict[str, Any]) -> list[dict[str, Any]]:
    """A binary product of the first twenty elements: its formula from the
    electrons (Mg gives two, each Cl takes one: MgCl2)."""
    for p in result["products"]:
        els = list(C.parse(p))
        if len(els) == 2 and all(e in C.ATOMIC_NUMBER for e in els):
            try:
                b = C.bond(els[0], els[1])
            except ValueError:
                continue
            if b["kind"] == "ionic" and b["formula"] == C.normalize(p):
                return [_bond_scene(b, intro=f"Why is it {C.pretty(p)}? The electrons decide. ")]
    return []


def _atom_scene(sym: str, short: bool = False, slot: int = 0) -> dict[str, Any]:
    a = C.atom(sym)
    shells_said = ", ".join(f"{n} in the {['first', 'second', 'third', 'fourth'][k]} shell" for k, n in enumerate(a["shells"]))
    say = (f"{a['name'].capitalize()} has {a['protons']} protons, so {a['electrons']} electrons: {shells_said}. "
           f"We write it {' dot '.join(str(n) for n in a['shells'])}.") if not short else \
        f"{a['name'].capitalize()}: {' dot '.join(str(n) for n in a['shells'])}."
    return {"scene": "chem_atom", **a, "short": short, "slot": slot, "colour": CPK.get(a["symbol"], "#999999"), "say": say}


def _atom_scenes(sym: str) -> list[dict[str, Any]]:
    a = C.atom(sym)
    out = [_atom_scene(sym)]
    out.append({"scene": "chem_result", "title": f"{a['name'].capitalize()}: {a['arrangement']}",
                "text": f"Group {a['group']}, period {a['period']}. {a['why']}"
                        + (f" Its ion is {a['ion']} ({a['ion_arrangement']})." if a["ion_charge"] else ""),
                "say": f"It is in group {a['group']} and period {a['period']} of the periodic table. {a['why']}"
                       + (f" So it forms the ion {_spoken_ion(a)}, with the arrangement {' dot '.join(a['ion_arrangement'].split('.'))}."
                          if a["ion_charge"] else "")})
    return out


def _spoken_ion(a: dict[str, Any]) -> str:
    q = a["ion_charge"]
    return f"{a['name']} {abs(q) if abs(q) > 1 else ''} {'plus' if q > 0 else 'minus'}".replace("  ", " ")


def _bond_scene(b: dict[str, Any], intro: str = "") -> dict[str, Any]:
    if b["kind"] == "ionic":
        m, n = b["atoms"]
        return {"scene": "chem_ionic", "metal": {**m, "colour": CPK.get(m["symbol"], "#999")},
                "nonmetal": {**n, "colour": CPK.get(n["symbol"], "#999")}, "counts": b["counts"], "moves": b["moves"],
                "formula": C.pretty(b["formula"]), "ions": b["ions"], "say": intro + b["why"]}
    a, c = b["atoms"]
    return {"scene": "chem_covalent", "atoms": [{**a, "colour": CPK.get(a["symbol"], "#999")}, {**c, "colour": CPK.get(c["symbol"], "#999")}],
            "centre": b["centre"], "counts": b["counts"], "formula": C.pretty(b["formula"]), "shared_pairs": b["shared_pairs"],
            "say": intro + b["why"]}


def _bond_scenes(x: str, y: str) -> list[dict[str, Any]]:
    b = C.bond(x, y)
    if b["kind"] in ("none", "metallic"):
        return [_atom_scene(x, short=True), _atom_scene(y, short=True, slot=1),
                {"scene": "chem_result", "title": "No compound", "text": b["why"], "say": b["why"]}]
    return [_hook([x, y], {}), _atom_scene(x, short=True), _atom_scene(y, short=True, slot=1), _bond_scene(b),
            {"scene": "chem_result", "title": f"The formula: {C.pretty(b['formula'])}",
             "text": ("Ionic bonding: " if b["kind"] == "ionic" else "Covalent bonding: ") + b["why"],
             "say": f"So the formula is {' '.join(C.pretty(b['formula']))}: " + ("the charges cancel out." if b["kind"] == "ionic"
                                                                                  else "every atom now has a full outer shell.")}]


def _separation_scenes(parts: list[str], keep: str) -> list[dict[str, Any]]:
    r = C.separate(parts, keep)
    if not r["covered"]:
        return [{"scene": "working", "text": r["why"], "say": r["why"]}]
    out: list[dict[str, Any]] = [{"scene": "chem_hook", "tiles": [{"symbol": p.split()[0][:3].capitalize(), "name": p.capitalize(),
                                                                   "Z": "", "colour": "#5b8db8", "formula": p} for p in parts[:2]],
                                  "question": f"How do we separate {' and '.join(parts)}?",
                                  "say": f"How do we separate {' and '.join(parts)}? It depends on what each one is like."}]
    for m in r["methods"]:
        if m == "dissolve":
            out.append({"scene": "chem_separation", "method": "dissolve", "name": "Dissolve",
                        "steps": ["Add water and stir: the soluble part dissolves, the insoluble part does not"], "parts": parts,
                        "say": "First, add water and stir. One part dissolves; the other does not."})
            continue
        info = C.SEPARATIONS[m]
        out.append({"scene": "chem_separation", "method": m, "name": info["name"], "steps": info["steps"], "parts": parts,
                    "say": f"{info['name']}. " + ". ".join(info["steps"]) + "."})
    out.append({"scene": "chem_list", "title": "Where it is used", "icon": "🌍", "items": r["uses"],
                "say": "Where this is used: " + ". ".join(r["uses"]) + "."})
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


PERIODIC = [  # (symbol, period, group) for the first twenty — the picker's table
    ("H", 1, 1), ("He", 1, 18), ("Li", 2, 1), ("Be", 2, 2), ("B", 2, 13), ("C", 2, 14), ("N", 2, 15), ("O", 2, 16),
    ("F", 2, 17), ("Ne", 2, 18), ("Na", 3, 1), ("Mg", 3, 2), ("Al", 3, 13), ("Si", 3, 14), ("P", 3, 15), ("S", 3, 16),
    ("Cl", 3, 17), ("Ar", 3, 18), ("K", 4, 1), ("Ca", 4, 2)]


def periodic() -> list[dict[str, Any]]:
    return [{"symbol": s, "name": C.ELEMENTS[s], "Z": C.ATOMIC_NUMBER[s], "period": p, "group": g,
             "colour": CPK.get(s, "#999"), "metal": s in C.METALS} for s, p, g in PERIODIC]


def mixtures() -> list[str]:
    return list(C.COMPONENTS)


def substances() -> list[dict[str, Any]]:
    return [{"group": g, "items": [{"formula": f, "pretty": C.pretty(f), "name": C.name_of(f)} for f in fs]}
            for g, fs in SUBSTANCES.items()]


def lab(a: str, b: str = "", condition: str = "", mode: str = "react") -> dict[str, Any]:
    """The game's pick: a reaction (two substances, or one heated), an atom,
    a bond between two elements, or a mixture to separate — the engine's
    answer and its walkthrough (as for a question)."""
    from .play_engine import walkthrough

    if mode in ("atom", "bond", "separate"):
        if mode == "atom":
            chem, text, result = {"atom": a}, f"What is the electron arrangement of {C.name_of(a)}?", C.atom(a)
        elif mode == "bond":
            chem, text, result = ({"bond": [a, b]}, f"How do {C.name_of(a)} and {C.name_of(b)} bond, and what is the formula?",
                                  C.bond(a, b))
        else:
            parts = [x for x in (a.split(",") + ([b] if b else [])) if x.strip()]
            chem, text, result = {"separate": parts}, f"How do we separate {' and '.join(parts)}?", C.separate(parts)
        q = {"question_id": f"lab:{mode}:{a}:{b}", "question_text": text, "chemistry": chem, "curriculum": {"subject": "Chemistry"}}
        return {"reaction": {"mode": mode, **result}, "walkthrough": walkthrough(q), "question": q}
    names = " and ".join(C.name_of(x) for x in (a, b) if x)
    q = {"question_id": f"lab:{C.normalize(a)}+{C.normalize(b)}:{condition}",
         "question_text": f"What happens when {names} {'are' if b else 'is'} {'mixed' if b else 'heated'}"
                          + (f" ({condition})" if condition and b else "") + "?",
         "chemistry": {"reactants": [x for x in (a, b) if x], "condition": condition},
         "curriculum": {"subject": "Chemistry"}}
    reaction = C.react(a, b, condition=condition)
    return {"reaction": reaction, "walkthrough": walkthrough(q), "question": q}

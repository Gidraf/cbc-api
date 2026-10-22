"""Separating mixtures by the rules of school chemistry: from what each part
is like (its state, what it dissolves in, whether it is magnetic or sublimes,
its boiling point and density, its colour), the methods in the right order —
a magnet, sublimation, dissolving in the right solvent and filtering,
evaporating or crystallising, a separating funnel, simple or fractional
distillation, chromatography — each step saying what goes where, and why.

Nothing is guessed: a mixture the rules do not decide is `covered: False`.
`catalogue()` lists every mixture of two or three parts the rules decide, and
`questions()` turns each into exam questions of several kinds, all marked by
the plan itself — over a thousand walkthroughs, each different.
"""
from __future__ import annotations

import hashlib
import itertools
from functools import lru_cache
from typing import Any

# ── the parts ────────────────────────────────────────────────────────────────
# kind: solid | liquid | ink.  dissolves: the solvents it dissolves in.
# For a liquid: bp (°C), density (g/cm³), polar (mixes with water).
S, L, I = "solid", "liquid", "ink"
SUBSTANCES: dict[str, dict[str, Any]] = {
    # solids that do not dissolve in water
    "sand": {"kind": S, "colour": "#d8b27a", "looks": "brown grains"},
    "chalk": {"kind": S, "colour": "#f2f0ea", "looks": "white powder", "formula": "CaCO3"},
    "charcoal powder": {"kind": S, "colour": "#2b2b2b", "looks": "black powder", "formula": "C"},
    "copper(II) oxide": {"kind": S, "colour": "#1f1f1f", "looks": "black powder", "formula": "CuO"},
    "sawdust": {"kind": S, "colour": "#c99a5b", "looks": "light brown flakes", "floats": True},
    "iron(III) oxide": {"kind": S, "colour": "#9c3d1f", "looks": "reddish-brown powder", "formula": "Fe2O3"},
    "lead(II) iodide": {"kind": S, "colour": "#f2d10b", "looks": "yellow powder", "formula": "PbI2"},
    "barium sulphate": {"kind": S, "colour": "#f7f7f5", "looks": "white powder", "formula": "BaSO4"},
    "copper(II) carbonate": {"kind": S, "colour": "#3e9b6f", "looks": "green powder", "formula": "CuCO3"},
    "zinc oxide": {"kind": S, "colour": "#f4f4f2", "looks": "white powder", "formula": "ZnO"},
    "magnesium oxide": {"kind": S, "colour": "#f6f6f3", "looks": "white powder", "formula": "MgO"},
    # magnetic
    "iron filings": {"kind": S, "colour": "#5b6168", "looks": "grey filings", "magnetic": True, "formula": "Fe"},
    "nickel powder": {"kind": S, "colour": "#8a8f94", "looks": "silvery-grey powder", "magnetic": True, "formula": "Ni"},
    "cobalt powder": {"kind": S, "colour": "#6b7280", "looks": "grey powder", "magnetic": True, "formula": "Co"},
    # sublime on heating
    "iodine": {"kind": S, "colour": "#4c1d95", "looks": "grey-black crystals, purple vapour", "sublimes": True,
               "dissolves": ["ethanol", "propanone"], "formula": "I2"},
    "naphthalene": {"kind": S, "colour": "#fbfbf8", "looks": "white crystals", "sublimes": True, "dissolves": ["kerosene"]},
    "ammonium chloride": {"kind": S, "colour": "#fafaf7", "looks": "white powder", "sublimes": True,
                          "dissolves": ["water"], "formula": "NH4Cl"},
    # dissolve in another solvent
    "sulphur": {"kind": S, "colour": "#e6c200", "looks": "yellow powder", "dissolves": ["methylbenzene"], "formula": "S"},
    # dissolve in water
    "salt": {"kind": S, "colour": "#fafafa", "looks": "white crystals", "dissolves": ["water"], "formula": "NaCl",
             "solution": "#e6f3ff"},
    "sugar": {"kind": S, "colour": "#fbfbf6", "looks": "white crystals", "dissolves": ["water"], "chars": True,
              "solution": "#f3f0e2"},
    "copper(II) sulphate": {"kind": S, "colour": "#2563eb", "looks": "blue crystals", "dissolves": ["water"],
                            "hydrated": True, "formula": "CuSO4", "solution": "#3b82f6"},
    "iron(II) sulphate": {"kind": S, "colour": "#86b97a", "looks": "pale green crystals", "dissolves": ["water"],
                          "hydrated": True, "formula": "FeSO4", "solution": "#bfe3b0"},
    "nickel(II) sulphate": {"kind": S, "colour": "#3f9b5a", "looks": "green crystals", "dissolves": ["water"],
                            "hydrated": True, "formula": "NiSO4", "solution": "#7ccf8f"},
    "potassium nitrate": {"kind": S, "colour": "#fafafa", "looks": "white crystals", "dissolves": ["water"], "steep": True,
                          "formula": "KNO3", "solution": "#e6f3ff"},
    "potassium permanganate": {"kind": S, "colour": "#581c87", "looks": "purple crystals", "dissolves": ["water"],
                               "formula": "KMnO4", "solution": "#9d4edd"},
    "potassium dichromate": {"kind": S, "colour": "#ea580c", "looks": "orange crystals", "dissolves": ["water"], "steep": True,
                             "formula": "K2Cr2O7", "solution": "#fb923c"},
    "sodium carbonate": {"kind": S, "colour": "#fafafa", "looks": "white powder", "dissolves": ["water"],
                         "formula": "Na2CO3", "solution": "#e6f3ff"},
    "zinc sulphate": {"kind": S, "colour": "#fafafa", "looks": "white crystals", "dissolves": ["water"],
                      "hydrated": True, "formula": "ZnSO4", "solution": "#e6f3ff"},
    # liquids
    "water": {"kind": L, "colour": "#bfe3ff", "bp": 100, "density": 1.00, "polar": True, "formula": "H2O"},
    "ethanol": {"kind": L, "colour": "#e8f5ff", "bp": 78, "density": 0.79, "polar": True, "solvent": True},
    "methanol": {"kind": L, "colour": "#eef7ff", "bp": 65, "density": 0.79, "polar": True},
    "propanone": {"kind": L, "colour": "#f0f8ff", "bp": 56, "density": 0.79, "polar": True, "solvent": True},
    "cooking oil": {"kind": L, "colour": "#f6d365", "bp": 300, "density": 0.92, "polar": False},
    "kerosene": {"kind": L, "colour": "#f3e7b0", "bp": 200, "density": 0.80, "polar": False, "solvent": True},
    "petrol": {"kind": L, "colour": "#fde7a6", "bp": 70, "density": 0.74, "polar": False},
    "tetrachloromethane": {"kind": L, "colour": "#eef2f6", "bp": 77, "density": 1.59, "polar": False, "formula": "CCl4"},
    "methylbenzene": {"kind": L, "colour": "#f4f1e6", "bp": 111, "density": 0.87, "polar": False, "solvent": True},
    "hexane": {"kind": L, "colour": "#f5f5ee", "bp": 69, "density": 0.66, "polar": False},
    # coloured mixtures of dyes
    "black ink": {"kind": I, "colour": "#1f2937", "dyes": [("blue", "#1d4ed8"), ("red", "#e8261b"), ("yellow", "#e6c200")]},
    "blue ink": {"kind": I, "colour": "#1e3a8a", "dyes": [("blue", "#1d4ed8"), ("violet", "#7c3aed")]},
    "green food colouring": {"kind": I, "colour": "#15803d", "dyes": [("blue", "#2563eb"), ("yellow", "#eab308")]},
    "brown marker ink": {"kind": I, "colour": "#78350f", "dyes": [("red", "#dc2626"), ("yellow", "#eab308"), ("blue", "#1d4ed8")]},
    "chlorophyll extract": {"kind": I, "colour": "#166534", "solvent": "propanone",
                            "dyes": [("green", "#15803d"), ("yellow-green", "#84cc16"), ("orange", "#f59e0b")]},
    "red flower extract": {"kind": I, "colour": "#be123c", "dyes": [("crimson", "#be123c"), ("pink", "#f472b6")]},
}

ALIASES = {
    "iron": "iron filings", "iron powder": "iron filings", "nickel": "nickel powder", "cobalt": "cobalt powder",
    "sulfur": "sulphur", "sulphur powder": "sulphur", "common salt": "salt", "sodium chloride": "salt",
    "table salt": "salt", "calcium carbonate": "chalk", "carbon": "charcoal powder", "charcoal": "charcoal powder",
    "oil": "cooking oil", "paraffin": "kerosene", "alcohol": "ethanol", "acetone": "propanone",
    "toluene": "methylbenzene", "carbon tetrachloride": "tetrachloromethane", "ink": "black ink",
    "food colouring": "green food colouring", "food coloring": "green food colouring", "rust": "iron(III) oxide",
    "copper sulphate": "copper(II) sulphate", "copper(ii) sulphate": "copper(II) sulphate",
    "copper sulfate": "copper(II) sulphate", "copper oxide": "copper(II) oxide", "copper(ii) oxide": "copper(II) oxide",
    "sucrose": "sugar", "naphthalene balls": "naphthalene", "mothballs": "naphthalene",
}

METHODS: dict[str, dict[str, Any]] = {
    "magnet": {"name": "Magnetic separation", "apparatus": "a magnet",
               "uses": ["Sorting scrap iron from other waste", "Removing iron from crushed ore at a mine"]},
    "sublimation": {"name": "Sublimation", "apparatus": "an evaporating dish, an inverted funnel and a Bunsen burner",
                    "uses": ["Purifying iodine", "Separating ammonium chloride from common salt"]},
    "dissolve": {"name": "Dissolving", "apparatus": "a beaker and a glass rod",
                 "uses": ["Dissolving salt out of rock salt", "Dry cleaning: a solvent dissolves grease out of cloth"]},
    "filtration": {"name": "Filtration", "apparatus": "a filter funnel and filter paper",
                   "uses": ["Clearing muddy water at a water works", "Making tea with a strainer"]},
    "evaporation": {"name": "Evaporation", "apparatus": "an evaporating dish over a Bunsen burner",
                    "uses": ["Salt pans at the coast (Malindi, Ngomeni)", "Getting salt from Lake Magadi brine"]},
    "flotation": {"name": "Flotation", "apparatus": "a beaker of water and a spoon or sieve",
                  "uses": ["Removing chaff and husks when washing grain", "Froth flotation of copper ore at a mine"]},
    "fractional_crystallisation": {"name": "Fractional crystallisation",
                                   "apparatus": "a beaker, a Bunsen burner and a filter funnel",
                                   "uses": ["Getting potassium nitrate from mixed salts", "Purifying salts in industry"]},
    "crystallisation": {"name": "Crystallisation", "apparatus": "an evaporating dish, then a cool place to crystallise",
                        "uses": ["Making pure copper(II) sulphate crystals", "Refining sugar at Mumias and Kibos"]},
    "distillation": {"name": "Simple distillation", "apparatus": "a flask, a thermometer and a Liebig condenser",
                     "uses": ["Getting drinking water from sea water", "Distilled water for car batteries and labs"]},
    "fractional_distillation": {"name": "Fractional distillation",
                                "apparatus": "a flask with a fractionating column, a thermometer and a condenser",
                                "uses": ["Separating crude oil into petrol, kerosene and diesel (Mombasa refinery)",
                                         "Getting oxygen and nitrogen from liquid air"]},
    "separating_funnel": {"name": "Separating funnel", "apparatus": "a separating funnel",
                          "uses": ["Separating oil from water", "Extracting oils from plants in industry"]},
    "chromatography": {"name": "Paper chromatography", "apparatus": "filter paper, a solvent and a beaker",
                       "uses": ["Testing food colourings and inks", "Forensic tests on ink in documents and in drug tests"]},
}


def canonical(name: str) -> str:
    n = " ".join(str(name).strip().split())
    low = n.lower()
    if low in ALIASES:
        return ALIASES[low]
    for k in SUBSTANCES:
        if k.lower() == low:
            return k
    return n


def _dissolves(name: str, solvent: str) -> bool:
    return solvent in (SUBSTANCES[name].get("dissolves") or [])


# ── the plan ─────────────────────────────────────────────────────────────────

class _Plan:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.why = ""

    def fail(self, why: str) -> bool:
        """The rules cannot part these: say why, plainly (the first reason wins)."""
        self.why = self.why or why
        return False

    def add(self, method: str, text: str, why: str, look: dict[str, Any], gives: dict[str, Any]) -> None:
        self.steps.append({"method": method, "name": METHODS[method]["name"], "text": text, "why": why,
                           "look": look, "gives": gives})


PLURAL = {"iron filings"}


def _one(names: list[str]) -> bool:
    """One thing, for the verb: 'sand is', but 'iron filings are'."""
    return len(names) == 1 and names[0] not in PLURAL


def _list(names: list[str]) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


SOLVENTS = ("water", "ethanol", "methylbenzene", "propanone", "kerosene")


def _dry(plan: _Plan, solids: list[str], keep: str) -> bool:
    """A dry mixture of solids, worked through: a magnet takes what is
    magnetic, heat takes the one that sublimes, a solvent takes what dissolves
    in it (filtered off and got back); what one solvent dissolves together is
    dried and tried again with another. Each part ends on its own, or the
    rules say why they cannot part them."""
    if len(solids) < 2:
        return True
    mags = [s for s in solids if SUBSTANCES[s].get("magnetic")]
    if mags and len(mags) < len(solids):
        if len(mags) > 1:
            return plan.fail(f"{_list(mags).capitalize()} are all magnetic: a magnet cannot part them.")
        rest = [s for s in solids if s not in mags]
        plan.add("magnet", f"Pass a magnet over the mixture: the {_list(mags)} stick{'s' if _one(mags) else ''} to it; "
                 f"the {_list(rest)} stay{'s' if _one(rest) else ''} behind.",
                 f"{_list(mags).capitalize()} {'is' if _one(mags) else 'are'} magnetic; {_list(rest)} "
                 f"{'is' if _one(rest) else 'are'} not.",
                 {"magnetic": [_look(m) for m in mags], "others": [_look(r) for r in rest]},
                 {"taken": mags, "left": rest})
        return _dry(plan, rest, keep)
    if len(mags) == len(solids):
        return plan.fail(f"{_list(mags).capitalize()} are all magnetic: a magnet cannot part them.")
    subs = [s for s in solids if SUBSTANCES[s].get("sublimes")]
    if len(subs) == 1:
        rest = [s for s in solids if s not in subs]
        sub = subs[0]
        plan.add("sublimation", f"Heat the mixture under a cold inverted funnel: the {sub} turns straight to vapour and "
                 f"collects as a solid on the cold funnel; the {_list(rest)} stay{'s' if _one(rest) else ''} in the dish.",
                 f"{sub.capitalize()} sublimes (solid to gas without melting); {_list(rest)} "
                 f"{'does' if _one(rest) else 'do'} not.",
                 {"sublimer": _look(sub), "others": [_look(r) for r in rest]}, {"taken": [sub], "left": rest})
        return _dry(plan, rest, keep)
    floaters = [s for s in solids if SUBSTANCES[s].get("floats")]
    if floaters and len(floaters) < len(solids):
        rest = [s for s in solids if s not in floaters]
        plan.add("flotation", f"Stir the mixture into water: the {_list(floaters)} float{'s' if _one(floaters) else ''} and "
                 f"{'is' if _one(floaters) else 'are'} skimmed off; the {_list(rest)} sink{'s' if _one(rest) else ''}.",
                 f"{_list(floaters).capitalize()} {'is' if _one(floaters) else 'are'} less dense than water; "
                 f"{_list(rest)} {'is' if _one(rest) else 'are'} denser.",
                 {"solvent": _look("water"), "floats": [_look(x) for x in floaters], "stays": [_look(x) for x in rest],
                  "dissolves": []},
                 {"taken": floaters, "left": rest})
        # What sank is wet with water: anything soluble in it is now dissolved — handled as a wet mixture.
        sol = [(x, "water") for x in rest if _dissolves(x, "water")]
        ins = [x for x in rest if not _dissolves(x, "water")]
        return _dry(plan, floaters, keep) and (len(rest) < 2 or _wet(plan, ins, ["water"], sol, [], keep))
    # A solvent that takes out just one part first; then one that takes out several.
    for single in (True, False):
        for solvent in SOLVENTS:
            sol = [s for s in solids if _dissolves(s, solvent)]
            if not sol or len(sol) == len(solids) or (len(sol) == 1) != single:
                continue
            ins = [s for s in solids if s not in sol]
            what = _list(sol)
            plan.add("dissolve", f"Add {solvent} and stir: the {what} dissolve{'s' if _one(sol) else ''}; the {_list(ins)} "
                     f"{'does' if _one(ins) else 'do'} not.",
                     f"{what.capitalize()} {'is' if _one(sol) else 'are'} soluble in {solvent}; {_list(ins)} "
                     f"{'is' if _one(ins) else 'are'} not.",
                     {"solvent": _look(solvent), "dissolves": [_look(x, solution=True, solvent=solvent) for x in sol],
                      "stays": [_look(x) for x in ins]},
                     {"solution": f"{what} solution", "left": ins})
            plan.add("filtration", f"Filter: the {_list(ins)} stay{'s' if _one(ins) else ''} on the filter paper (residue); "
                     f"the {what} solution runs through (filtrate).",
                     f"The {_list(ins)} {'does' if _one(ins) else 'do'} not dissolve, so {'it is' if _one(ins) else 'they are'} "
                     f"left on the paper while the solution passes through.",
                     {"residue": [_look(x) for x in ins], "filtrate": _look(sol[0], solution=True, solvent=solvent)},
                     {"residue": ins, "filtrate": f"{what} solution"})
            if single:
                _recover(plan, sol[0], solvent, keep)
                return _dry(plan, ins, keep)
            return _dry(plan, ins, keep) and _several(plan, sol, solvent, keep)
    if all(_dissolves(x, "water") for x in solids) and sum(1 for x in solids if SUBSTANCES[x].get("steep")) == 1:
        plan.add("dissolve", f"Dissolve the mixture in a little hot water: the {_list(solids)} all dissolve.",
                 "They are all soluble in water; they will part as the solution cools.",
                 {"solvent": _look("water"), "dissolves": [_look(x, solution=True) for x in solids], "stays": []},
                 {"solution": f"{_list(solids)} solution", "left": []})
        return _several(plan, solids, "water", keep)
    return plan.fail(f"Nothing here parts the {_list(solids)}: none is magnetic or sublimes, and no solvent the rules "
                     f"know dissolves one but not the others.")


def _several(plan: _Plan, solutes: list[str], solvent: str, keep: str) -> bool:
    """Several solids dissolved together: one whose solubility falls steeply on
    cooling crystallises out first (fractional crystallisation); otherwise dry
    them and part them as solids."""
    steep = [x for x in solutes if SUBSTANCES[x].get("steep")]
    if solvent == "water" and len(steep) == 1:
        first, rest = steep[0], [x for x in solutes if x != steep[0]]
        plan.add("fractional_crystallisation", f"Heat the solution until it is saturated, then cool it: the {first} "
                 f"crystallises out first; filter it off — the {_list(rest)} stay{'s' if _one(rest) else ''} in solution.",
                 f"{first.capitalize()} is far more soluble in hot water than in cold, so it comes out as the solution cools; "
                 f"{_list(rest)} {'does' if _one(rest) else 'do'} not change much.",
                 {"solution": _look(first, solution=True), "crystals": _look(first)}, {"crystals": first, "left": rest})
        if len(rest) == 1:
            _recover(plan, rest[0], solvent, keep)
            return True
        return _several(plan, rest, solvent, keep)
    _to_dryness(plan, solutes, solvent)
    return _dry(plan, solutes, keep)


def _to_dryness(plan: _Plan, solutes: list[str], solvent: str) -> None:
    plan.add("evaporation", f"Evaporate the solution to dryness: the {solvent} boils off and the {_list(solutes)} are left "
             f"together as a dry solid.", f"The {solvent} evaporates; the dissolved solids do not.",
             {"solution": _look(solutes[0], solution=True, solvent=solvent), "crystals": _look(solutes[0])},
             {"solid": _list(solutes)})


def _recover(plan: _Plan, solute: str, solvent: str, keep: str) -> None:
    """The dissolved solid back from its solution — or the solvent, if that is wanted."""
    info = SUBSTANCES[solute]
    if keep == solvent:
        plan.add("distillation", f"Distil the solution: the {solvent} boils off at {SUBSTANCES[solvent]['bp']} °C, condenses "
                 f"and is collected (distillate); the {solute} stays in the flask.",
                 f"Only the {solvent} boils; the condenser turns its vapour back to liquid.",
                 {"solution": _look(solute, solution=True, solvent=solvent), "distillate": _look(solvent),
                  "temperature": SUBSTANCES[solvent]["bp"]},
                 {"distillate": solvent, "left": [solute]})
    elif info.get("hydrated") or info.get("chars") or keep == "crystals":
        why = ("evaporating to dryness would drive off its water of crystallisation and spoil the crystals"
               if info.get("hydrated") else "heating it to dryness would char (burn) it" if info.get("chars")
               else "slow cooling gives large, pure crystals")
        plan.add("crystallisation", f"Heat the {solute} solution until it is saturated, then leave it to cool: crystals of "
                 f"{solute} form; filter them off and dry them between filter papers.",
                 f"Crystallise, not evaporate to dryness: {why}.",
                 {"solution": _look(solute, solution=True, solvent=solvent), "crystals": _look(solute)},
                 {"crystals": solute})
    else:
        plan.add("evaporation", f"Evaporate the {solute} solution: the {solvent} boils off and the {solute} is left in the dish.",
                 f"The {solvent} evaporates; the {solute} does not.",
                 {"solution": _look(solute, solution=True, solvent=solvent), "crystals": _look(solute)},
                 {"solid": solute})


def _wet(plan: _Plan, solids: list[str], liquids: list[str], solutes: list[tuple[str, str]], inks: list[str], keep: str) -> bool:
    """A mixture with liquids in it, worked through: filter off what does not
    dissolve; part liquids that do not mix in a separating funnel (each layer
    taking what dissolves in it); part liquids that mix by fractional
    distillation; then get back what is dissolved — and find the dyes of an
    ink by chromatography."""
    if solids:
        rest_names = liquids + [x for x, _ in solutes] + inks
        filtrate = (_look(inks[0]) if inks else _look(solutes[0][0], solution=True, solvent=solutes[0][1]) if solutes
                    else _look(liquids[0]))
        plan.add("filtration", f"Filter: the {_list(solids)} stay{'s' if _one(solids) else ''} on the filter paper (residue); "
                 f"the {_list(rest_names)} run{'s' if _one(rest_names) else ''} through (filtrate).",
                 f"The {_list(solids)} {'does' if _one(solids) else 'do'} not dissolve in the {_list(liquids)}.",
                 {"residue": [_look(x) for x in solids], "filtrate": filtrate},
                 {"residue": solids, "filtrate": _list(rest_names)})
        return _dry(plan, solids, keep) and _wet(plan, [], liquids, solutes, inks, keep)
    polar = [x for x in liquids if SUBSTANCES[x]["polar"]]
    non = [x for x in liquids if not SUBSTANCES[x]["polar"]]
    if polar and non:
        if "water" not in polar:
            return plan.fail(f"{_list(polar).capitalize()} and {_list(non)} may partly mix: the rules cannot say how they "
                             f"would settle.")
        # Ethanol, methanol and propanone mix with water: they go with the water layer, away from the oil.
        dens = lambda xs: sum(SUBSTANCES[x]["density"] for x in xs) / len(xs)  # noqa: E731
        w_sol = [(x, v) for x, v in solutes if v in polar]
        n_sol = [(x, v) for x, v in solutes if v not in polar]
        water_layer, oil_layer = ["water"] + [x for x in polar if x != "water"], non
        top, bottom = (oil_layer, water_layer) if dens(oil_layer) < 1.0 else (water_layer, oil_layer)
        tl, bl = _list(top), _list(bottom)
        layer = lambda xs: {"name": _list(xs), "colour": SUBSTANCES[xs[0]]["colour"]}  # noqa: E731
        plan.add("separating_funnel", f"Pour the mixture into a separating funnel and let it settle: the {tl} "
                 f"({dens(top):.2f} g/cm³) floats on the {bl} ({dens(bottom):.2f} g/cm³). Open the tap to run off the {bl}, "
                 f"then close it: the {tl} stays."
                 + (f" What is dissolved goes with its liquid: the {_list([x for x, _ in w_sol] + inks)} with the water"
                    if w_sol or inks else "")
                 + (f"{'; ' if w_sol or inks else ' What is dissolved goes with its liquid: '}the {_list([x for x, _ in n_sol])} "
                    f"with the {_list(non)}" if n_sol else "") + ("." if w_sol or n_sol or inks else ""),
                 f"{_list(water_layer).capitalize()} and {_list(non)} do not mix (they are immiscible); the denser layer sinks.",
                 {"top": layer(top), "bottom": layer(bottom)}, {"lower": bl, "upper": tl})
        return _wet(plan, [], water_layer, w_sol, inks, keep) and _wet(plan, [], oil_layer, n_sol, [], keep)
    if inks and len(liquids) == 1 and not solutes and keep in (liquids[0], "solvent"):
        # The solvent is wanted, not the dyes: distil it off.
        solv, what = liquids[0], _list(inks)
        plan.add("distillation", f"Distil the {what}: the {solv} boils off and condenses; the dyes stay in the flask.",
                 f"Only the {solv} boils at {SUBSTANCES[solv]['bp']} °C.",
                 {"solution": _look(inks[0]), "distillate": _look(solv), "temperature": SUBSTANCES[solv]["bp"]},
                 {"distillate": solv})
        return True
    if inks:
        dyes = [d for ink in inks for d in SUBSTANCES[ink]["dyes"]]
        dyes = list(dict.fromkeys(dyes))
        solv = SUBSTANCES[inks[0]].get("solvent", "water")
        what = _list(inks)
        plan.add("chromatography", f"Put a spot of the {what} on a pencil line on filter paper and stand it in {solv}: as the "
                 f"{solv} rises it carries the dyes apart — " + _list([n for n, _ in dyes]) +
                 f". The {what} {'is a mixture' if len(inks) == 1 else 'are mixtures'} of {len(dyes)} dyes.",
                 "Each dye dissolves in the solvent and sticks to the paper differently, so each travels a different distance.",
                 {"ink": _look(inks[0]), "solvent": _look(solv), "dyes": [{"name": n, "colour": c} for n, c in dyes]},
                 {"dyes": [n for n, _ in dyes]})
        if solutes:
            # Take the colour out: charcoal holds the dyes back (adsorbs them); the solution runs through clear.
            names = [x for x, _ in solutes]
            plan.add("filtration", f"Add charcoal powder, stir and filter: the charcoal holds back the dyes on the paper; a "
                     f"colourless {_list(names)} solution runs through.",
                     "Charcoal adsorbs coloured substances (decolourising), as when brown sugar is made white.",
                     {"residue": [_look("charcoal powder")], "filtrate": _look(names[0], solution=True, solvent=solutes[0][1])},
                     {"residue": ["charcoal powder", "dyes"], "filtrate": f"{_list(names)} solution"})
            return _wet(plan, [], liquids, solutes, [], keep)
        if len(liquids) > 1 or keep in liquids or keep == "solvent":
            return _wet(plan, [], liquids, [], [], keep or liquids[0])
        return True
    if len(liquids) > 1:
        order = sorted(liquids, key=lambda x: SUBSTANCES[x]["bp"])
        bps = [SUBSTANCES[x]["bp"] for x in order]
        if any(b2 - b1 < 8 for b1, b2 in zip(bps, bps[1:])):
            close = next((order[i], order[i + 1]) for i in range(len(bps) - 1) if bps[i + 1] - bps[i] < 8)
            return plan.fail(f"{close[0].capitalize()} and {close[1]} boil within a few degrees of each other: "
                             f"distillation cannot part them cleanly.")
        left = [x for x, _ in solutes]
        plan.add("fractional_distillation", f"Fractional distillation: heat the mixture in a flask with a fractionating column. "
                 f"The {order[0]} boils off first (at {bps[0]} °C) and is collected; then "
                 + _list([f"the {x} at {SUBSTANCES[x]['bp']} °C" for x in order[1:]])
                 + (f". The {_list(left)} {'is' if _one(left) else 'are'} left in the flask." if left else "."),
                 "The liquids mix (they are miscible) but boil at different temperatures; the column keeps the "
                 "higher-boiling one back.",
                 {"liquids": [_look(x) for x in order], "temperatures": bps}, {"first": order[0], "order": order})
        return _dry(plan, left, keep)
    liquid = liquids[0]
    if not solutes:
        return True
    if len(solutes) == 1:
        _recover(plan, solutes[0][0], liquid, keep)
        return True
    return _several(plan, [x for x, _ in solutes], liquid, keep)


def _look(name: str, *, solution: bool = False, solvent: str = "water") -> dict[str, Any]:
    """What the animation needs to draw a part: its name and colour (its
    solution's colour, for a dissolved one)."""
    info = SUBSTANCES[name]
    out = {"name": name, "colour": info.get("solution") if solution and info.get("solution") else info["colour"],
           "kind": info["kind"]}
    if solution:
        out["in"] = solvent
        out["solid"] = info["colour"]
        if solvent != "water":
            out["colour"] = {"iodine": "#a0522d", "sulphur": "#f3e48a", "naphthalene": "#f5f5ee"}.get(name, out["colour"])
    for k in ("bp", "density", "magnetic", "sublimes", "hydrated"):
        if k in info:
            out[k] = info[k]
    if "dyes" in info:
        out["dyes"] = [{"name": n, "colour": c} for n, c in info["dyes"]]
    return out


def separate(parts: list[str], keep: str = "") -> dict[str, Any]:
    """How to separate a mixture: the methods in order, each step saying
    what happens and why, and what the animation draws."""
    ps = list(dict.fromkeys(canonical(p) for p in parts if str(p).strip()))
    unknown = [p for p in ps if p not in SUBSTANCES]
    if unknown:
        return {"covered": False, "why": f"The separation rules here do not know {', '.join(unknown)}."}
    if len(ps) < 1:
        return {"covered": False, "why": "Name the parts of the mixture."}
    keep = canonical(keep) if keep and keep != "crystals" else keep
    plan = _Plan()
    solids = [p for p in ps if SUBSTANCES[p]["kind"] == S]
    liquids = [p for p in ps if SUBSTANCES[p]["kind"] == L]
    inks = [p for p in ps if SUBSTANCES[p]["kind"] == I]
    # An ink is dyes dissolved in its solvent: that solvent is in the mixture too.
    for ink in inks:
        solv = SUBSTANCES[ink].get("solvent", "water")
        if solv not in liquids:
            liquids.append(solv)
    if liquids:
        suspended, solutes = [], []
        for x in solids:
            where = next((v for v in liquids if _dissolves(x, v)), None)
            if where:
                solutes.append((x, where))
            else:
                suspended.append(x)
        ok = _wet(plan, suspended, liquids, solutes, inks, keep)
    else:
        ok = len(solids) >= 2 and _dry(plan, solids, keep)
    if not ok or not plan.steps:
        return {"covered": False, "parts": ps,
                "why": plan.why or "The separation rules here do not decide that mixture (one substance alone is not a mixture)."}
    methods = [st["method"] for st in plan.steps]
    main = next((m for m in methods if m not in ("dissolve",)), methods[0])
    return {"covered": True, "parts": ps, "keep": keep, "methods": methods, "names": [st["name"] for st in plan.steps],
            "steps": [st["text"] for st in plan.steps], "plan": plan.steps,
            "why": " Then ".join(f"{st['name']}: {st['why']}" for st in plan.steps),
            "uses": METHODS[main]["uses"], "looks": [_look(p) for p in ps]}


# ── every mixture, and its questions ──────────────────────────────────────────

@lru_cache(maxsize=2)
def _catalogue(max_parts: int) -> tuple[dict[str, Any], ...]:
    return tuple(_catalogue_build(max_parts))


def catalogue(max_parts: int = 3) -> list[dict[str, Any]]:
    """Every mixture of two (and three) parts the rules decide (worked out once)."""
    return list(_catalogue(max_parts))


def _catalogue_build(max_parts: int = 3) -> list[dict[str, Any]]:
    """Every mixture of two (and three) parts the rules decide, with the
    part to keep where that changes the method."""
    names = sorted(SUBSTANCES)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in range(2, max_parts + 1):
        for combo in itertools.combinations(names, n):
            kinds = [SUBSTANCES[c]["kind"] for c in combo]
            if n == 3 and kinds.count(L) > 2:
                continue
            for keep in _keeps(combo):
                r = separate(list(combo), keep)
                if not r["covered"]:
                    continue
                key = "|".join(r["methods"]) + "/" + "+".join(combo) + "/" + keep
                if key in seen:
                    continue
                seen.add(key)
                out.append({"parts": list(combo), "keep": keep, "methods": r["methods"]})
    return out


def _keeps(combo: tuple[str, ...]) -> list[str]:
    liquids = [c for c in combo if SUBSTANCES[c]["kind"] == L]
    soluble = [c for c in combo if SUBSTANCES[c]["kind"] == S and SUBSTANCES[c].get("dissolves")]
    inks = [c for c in combo if SUBSTANCES[c]["kind"] == I]
    out = [""]
    if len(liquids) == 1 and soluble:
        out.append(liquids[0])                     # keep the solvent: distil
    if inks:
        out.append("water")
    return out


FOCUSES = ("method", "order", "residue", "layer", "first", "why", "apparatus")


def questions(mix: dict[str, Any]) -> list[dict[str, Any]]:
    """Exam questions on one mixture, each marked by the plan (multiple
    choice, the wrong options from the other methods and parts)."""
    r = separate(mix["parts"], mix.get("keep", ""))
    if not r["covered"]:
        return []
    parts, keep, plan = r["parts"], r["keep"], r["plan"]
    mixture = _list(parts)
    seed = int(hashlib.sha1(("|".join(parts) + keep).encode()).hexdigest()[:8], 16)
    all_methods = [m["name"] for m in METHODS.values() if m["name"] != "Dissolving"]
    out: list[dict[str, Any]] = []

    def mcq(focus: str, stem: str, right: str, wrong: list[str]) -> None:
        wrong = [w for w in dict.fromkeys(wrong) if w and w != right][:3]
        if len(wrong) < 3:
            return
        opts = [right, *wrong]
        k = (seed + len(out)) % 4
        opts = opts[1:k + 1] + [right] + opts[k + 1:]
        letters = "ABCD"
        out.append({"focus": focus, "question_text": stem, "question_type": "multiple_choice",
                    "options": [{"id": letters[i], "text": o, "is_correct": o == right} for i, o in enumerate(opts)],
                    "correct_answer": right, "marks": 1,
                    "marking_scheme": " ".join(st["why"] for st in plan),
                    "model_answer": " ".join(st["text"] for st in plan),
                    "chemistry": {"separate": parts, **({"keep": keep} if keep else {}), "focus": focus}})

    goal = f" to obtain the {keep}" if keep and keep != "crystals" else ""
    names = [st["name"] for st in plan if st["method"] != "dissolve"]
    if len(names) == 1:
        mcq("method", f"Which method would best separate a mixture of {mixture}{goal}?", names[0],
            [m for m in all_methods if m != names[0]][seed % 5:][:3] + all_methods)
        mcq("apparatus", f"Which apparatus is used to separate {mixture}{goal}?",
            METHODS[plan[-1]["method"]]["apparatus"].capitalize(),
            [m["apparatus"].capitalize() for k, m in METHODS.items() if k != plan[-1]["method"]][seed % 4:])
    if len(plan) > 1:
        right = " → ".join(st["name"] for st in plan)
        shuffles = [" → ".join(st["name"] for st in p) for p in itertools.permutations(plan) if list(p) != plan]
        rnd = [shuffles[(seed + i * 7) % len(shuffles)] for i in range(len(shuffles))] if shuffles else []
        mcq("order", f"In what order would you separate a mixture of {mixture}{goal}?", right,
            rnd + [" → ".join(reversed([st["name"] for st in plan]))])
    for st in plan:
        g = st["gives"]
        if st["method"] == "filtration" and g.get("residue"):
            res = _list(g["residue"])
            others = [p for p in SUBSTANCES if p not in g["residue"] and SUBSTANCES[p]["kind"] != I]
            mcq("residue", f"A mixture of {mixture} is separated. In the filtration step, what is the residue?", res.capitalize(),
                [g.get("filtrate", "").capitalize()] + [o.capitalize() for o in parts if o not in g["residue"]]
                + [o.capitalize() for o in others[seed % 20:seed % 20 + 3]])
        if st["method"] == "separating_funnel":
            mcq("layer", f"{mixture.capitalize()} are poured into a separating funnel. Which liquid forms the lower layer, "
                f"and why?", f"{g['lower'].capitalize()}: it is denser",
                [f"{g['upper'].capitalize()}: it is denser", f"{g['lower'].capitalize()}: it boils at a higher temperature",
                 f"{g['upper'].capitalize()}: it is less dense"])
        if st["method"] == "fractional_distillation":
            o = g["order"]
            mcq("first", f"A mixture of {mixture} is separated by fractional distillation. Which liquid distils first, and why?",
                f"{o[0].capitalize()}: it has the lowest boiling point",
                [f"{o[-1].capitalize()}: it has the highest boiling point", f"{o[-1].capitalize()}: it is the densest",
                 f"{o[0].capitalize()}: it is the densest"])
        if st["method"] in ("magnet", "sublimation", "crystallisation", "chromatography"):
            # The wrong reasons in the same form as the right one, so its wording does not give it away.
            a_ = _list(g.get("taken") or [g.get("crystals") or parts[0]]).capitalize()
            b_ = _list(g.get("left") or [p for p in parts if p not in (g.get("taken") or [])] or ["the rest"])
            wrongs = {"magnet": [f"{a_} is denser than {b_}", f"{a_} has a lower boiling point than {b_}",
                                 f"{a_} is less soluble in water than {b_}"],
                      "sublimation": [f"{a_} melts at a lower temperature than {b_}", f"{a_} is magnetic; {b_} is not",
                                      f"{a_} is less dense than {b_}"],
                      "crystallisation": ["Crystals form faster when the solution is boiled dry",
                                          "Evaporating to dryness gives larger crystals", "The solution would boil over"],
                      "chromatography": ["The dyes have different boiling points",
                                         "The dyes are particles of different sizes that the paper filters",
                                         "The dyes have different densities"]}[st["method"]]
            stem = {"magnet": f"Why can a magnet separate a mixture of {mixture}?",
                    "sublimation": f"Why can heating separate a mixture of {mixture}?",
                    "crystallisation": f"Why is the {g.get('crystals')} crystallised rather than evaporated to dryness?",
                    "chromatography": f"Why does the {parts[0] if SUBSTANCES[parts[0]]['kind'] == I else mixture} separate into "
                                      f"colours on the paper?"}[st["method"]]
            mcq("why", stem, st["why"].rstrip(".").capitalize(), wrongs)
    return out


@lru_cache(maxsize=1)
def _all_questions() -> tuple[dict[str, Any], ...]:
    return tuple(q for mix in catalogue() for q in questions(mix))


def all_questions(limit: int = 0) -> list[dict[str, Any]]:
    """Every question on every mixture (the first `limit`, if given), worked out once."""
    qs = _all_questions()
    return list(qs[:limit] if limit else qs)


def pick(limit: int, focuses: list[str] | None = None) -> list[dict[str, Any]]:
    """`limit` questions spread across the methods and the kinds of question
    (round robin), so a batch of videos is never fifty filtrations in a row."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for q in all_questions():
        if (focuses and q["focus"] not in focuses) or q["question_text"] in seen:
            continue
        seen.add(q["question_text"])
        r = separate(q["chemistry"]["separate"], q["chemistry"].get("keep", ""))
        main = "+".join(r["methods"])
        groups.setdefault((main, q["focus"]), []).append(q)
    for g in groups.values():                     # a stable shuffle within each group
        g.sort(key=lambda q: hashlib.sha1(q["question_text"].encode()).hexdigest())
    keys = sorted(groups, key=lambda k: hashlib.sha1("/".join(k).encode()).hexdigest())
    out: list[dict[str, Any]] = []
    depth = 0
    while len(out) < limit and keys:
        alive = False
        for k in keys:
            if depth < len(groups[k]):
                out.append(groups[k][depth])
                alive = True
                if len(out) >= limit:
                    break
        if not alive:
            break
        depth += 1
    return out


def summary() -> dict[str, Any]:
    from collections import Counter

    mixes = catalogue()
    qs = all_questions()
    return {"substances": len(SUBSTANCES), "mixtures": len(mixes), "questions": len(qs),
            "by_method": dict(Counter(m for x in mixes for m in dict.fromkeys(x["methods"])).most_common()),
            "by_focus": dict(Counter(q["focus"] for q in qs).most_common()),
            "sample": [q["question_text"] for q in pick(8)]}


def bank(curriculum: dict[str, str], limit: int, focuses: list[str] | None = None, *, by: str = "") -> dict[str, Any]:
    """Save `limit` engine-made questions to the bank at this point of the
    curriculum, approved (the rules mark them). The same question at the same
    point keeps its id, so saving again adds only what is new."""
    from ..infra.db import fetch_all
    from .question_dna import question_dna_service

    chosen = pick(max(1, min(int(limit), 5000)), focuses)
    from .grade_order import normalize_grade

    link = {k: str(curriculum.get(k) or "").strip() for k in ("grade", "subject", "strand", "sub_strand")}
    link["grade"] = normalize_grade(link["grade"]) or link["grade"]      # as Play looks it up: grade-7
    point = "|".join(link.values()).lower()
    ids = [f"q-chem-sep-{hashlib.sha1((point + '|' + q['question_text']).encode()).hexdigest()[:14]}" for q in chosen]
    have = {r["question_id"] for r in (fetch_all("SELECT question_id FROM question_dna WHERE question_id = ANY(:i)",
                                                 {"i": ids}) or [])}
    saved = 0
    for qid, q in zip(ids, chosen):
        if qid in have:
            continue
        content = {k: q[k] for k in ("question_text", "question_type", "options", "correct_answer", "marks",
                                     "marking_scheme", "model_answer", "chemistry")}
        question_dna_service.save_question(
            question_id=qid, universal_id=f"chem-separation-{q['focus']}", curriculum_link=link,
            pedagogical_dna={"question_type": "multiple_choice", "bloom": "apply" if q["focus"] in ("method", "order") else "understand",
                             "focus": q["focus"]},
            content=content,
            provenance={"provider": "engine", "model": "chemistry-separation", "written_by": "chemistry engine",
                        **({"saved_by": by} if by else {})},
            review_audit={"checked_by": "chemistry engine rules", "verdict": "approved"},
            status="approved")
        saved += 1
    return {"saved": saved, "already": len(have), "asked": len(chosen), "curriculum": link}

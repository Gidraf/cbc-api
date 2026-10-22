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
    "sawdust": {"kind": S, "colour": "#c99a5b", "looks": "light brown flakes"},
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
    "potassium nitrate": {"kind": S, "colour": "#fafafa", "looks": "white crystals", "dissolves": ["water"],
                          "formula": "KNO3", "solution": "#e6f3ff"},
    "potassium permanganate": {"kind": S, "colour": "#581c87", "looks": "purple crystals", "dissolves": ["water"],
                               "formula": "KMnO4", "solution": "#9d4edd"},
    "potassium dichromate": {"kind": S, "colour": "#ea580c", "looks": "orange crystals", "dissolves": ["water"],
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


def _solids(plan: _Plan, solids: list[str], keep: str) -> bool:
    """A dry mixture of solids: take out what a magnet or heat takes, then
    dissolve what dissolves, filter, and get the dissolved one back."""
    left = list(solids)
    mags = [s for s in left if SUBSTANCES[s].get("magnetic")]
    if mags and len(mags) < len(left):
        rest = [s for s in left if s not in mags]
        plan.add("magnet", f"Pass a magnet over the mixture: the {_list(mags)} stick{'s' if _one(mags) else ''} to it; "
                 f"the {_list(rest)} stay{'s' if _one(rest) else ''} behind.",
                 f"{_list(mags).capitalize()} {'is' if _one(mags) else 'are'} magnetic; {_list(rest)} "
                 f"{'is' if _one(rest) else 'are'} not.",
                 {"magnetic": [_look(m) for m in mags], "others": [_look(r) for r in rest]},
                 {"taken": mags, "left": rest})
        left = rest
    if len(left) < 2:
        return True
    subs = [s for s in left if SUBSTANCES[s].get("sublimes")]
    if len(subs) == 1:
        rest = [s for s in left if s not in subs]
        sub = subs[0]
        plan.add("sublimation", f"Heat the mixture under a cold inverted funnel: the {sub} turns straight to vapour and "
                 f"collects as a solid on the cold funnel; the {_list(rest)} stay{'s' if _one(rest) else ''} in the dish.",
                 f"{sub.capitalize()} sublimes (solid to gas without melting); {_list(rest)} "
                 f"{'does' if _one(rest) else 'do'} not.",
                 {"sublimer": _look(sub), "others": [_look(r) for r in rest]}, {"taken": [sub], "left": rest})
        left = rest
        if len(left) < 2:
            return True
    # Dissolve one part out: water first, then another solvent.
    for solvent in ("water", "ethanol", "methylbenzene", "propanone", "kerosene"):
        sol = [s for s in left if _dissolves(s, solvent)]
        if not sol or len(sol) == len(left):
            continue
        ins = [s for s in left if s not in sol]
        if len(sol) > 1:
            continue                  # two dissolved together: not separated by this solvent
        solute = sol[0]
        plan.add("dissolve", f"Add {solvent} and stir: the {solute} dissolves; the {_list(ins)} "
                 f"{'does' if _one(ins) else 'do'} not.",
                 f"{solute.capitalize()} is soluble in {solvent}; {_list(ins)} {'is' if _one(ins) else 'are'} not.",
                 {"solvent": _look(solvent), "dissolves": [_look(solute, solution=True)], "stays": [_look(x) for x in ins]},
                 {"solution": f"{solute} solution", "left": ins})
        plan.add("filtration", f"Filter: the {_list(ins)} stay{'s' if _one(ins) else ''} on the filter paper (residue); "
                 f"the {solute} solution runs through (filtrate).",
                 f"The {_list(ins)} {'does' if _one(ins) else 'do'} not dissolve, so {'it is' if _one(ins) else 'they are'} "
                 f"too big to pass through the paper.",
                 {"residue": [_look(x) for x in ins], "filtrate": _look(solute, solution=True, solvent=solvent)},
                 {"residue": ins, "filtrate": f"{solute} solution"})
        _recover(plan, solute, solvent, keep)
        if len(ins) > 1:
            return _solids(plan, ins, keep)
        return True
    return False


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


def _liquids(plan: _Plan, liquids: list[str], solutes: list[str], keep: str) -> bool:
    """Liquids (with anything dissolved in them): layers first, then boiling points."""
    if len(liquids) == 1:
        if solutes:
            _recover(plan, solutes[0], liquids[0], keep)
        return True
    polar = [x for x in liquids if SUBSTANCES[x]["polar"]]
    non = [x for x in liquids if not SUBSTANCES[x]["polar"]]
    # Only water is sure not to mix with an oil: ethanol, propanone and methanol mix with too much to say.
    if polar and non:
        if polar != ["water"]:
            return False
        layers = sorted(["water", *non][:2], key=lambda x: SUBSTANCES[x]["density"])
        if len(non) > 1:
            return False
        top, bottom = layers[0], layers[1]
        plan.add("separating_funnel", f"Pour the mixture into a separating funnel and let it settle: the {top} "
                 f"({SUBSTANCES[top]['density']:.2f} g/cm³) floats on the {bottom} ({SUBSTANCES[bottom]['density']:.2f} g/cm³). "
                 f"Open the tap to run off the {bottom}, then close it: the {top} stays.",
                 f"{top.capitalize()} and {bottom} do not mix (they are immiscible), and the denser one, {bottom}, sinks.",
                 {"top": _look(top), "bottom": _look(bottom)}, {"lower": bottom, "upper": top})
        return True
    # All mix: by boiling point, the lowest first.
    order = sorted(liquids, key=lambda x: SUBSTANCES[x]["bp"])
    bps = [SUBSTANCES[x]["bp"] for x in order]
    if any(b2 - b1 < 8 for b1, b2 in zip(bps, bps[1:])):
        return False                  # too close to separate by school methods
    first = order[0]
    plan.add("fractional_distillation", f"Fractional distillation: heat the mixture in a flask with a fractionating column. "
             f"The {first} boils off first (at {bps[0]} °C) and is collected; then "
             + _list([f"the {x} at {SUBSTANCES[x]['bp']} °C" for x in order[1:]]) + ".",
             f"The liquids mix (they are miscible) but boil at different temperatures; the column keeps the "
             f"higher-boiling one back.",
             {"liquids": [_look(x) for x in order], "temperatures": bps}, {"first": first, "order": order})
    return True


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
    ok = True
    if inks:
        if len(inks) > 1 or liquids or any(SUBSTANCES[s].get("dissolves") for s in solids):
            ok = False
        else:
            ink = inks[0]
            if solids:
                plan.add("filtration", f"Filter: the {_list(solids)} stay{'s' if _one(solids) else ''} on the paper; "
                         f"the {ink} runs through.", f"The {_list(solids)} {'does' if _one(solids) else 'do'} not dissolve.",
                         {"residue": [_look(x) for x in solids], "filtrate": _look(ink)}, {"residue": solids, "filtrate": ink})
            dyes = SUBSTANCES[ink]["dyes"]
            solv = SUBSTANCES[ink].get("solvent", "water")
            if keep == "water" or keep == "solvent":
                plan.add("distillation", f"Distil the {ink}: the {solv} boils off and condenses; the dyes stay in the flask.",
                         f"Only the {solv} boils at {SUBSTANCES[solv]['bp']} °C.",
                         {"solution": _look(ink), "distillate": _look(solv), "temperature": SUBSTANCES[solv]["bp"]},
                         {"distillate": solv})
            else:
                plan.add("chromatography", f"Put a spot of the {ink} on a pencil line on filter paper and stand it in "
                         f"{solv}: as the {solv} rises it carries the dyes apart — "
                         + _list([n for n, _ in dyes]) + f". The {ink} is a mixture of {len(dyes)} dyes.",
                         "Each dye dissolves in the solvent and sticks to the paper differently, so each travels a different distance.",
                         {"ink": _look(ink), "solvent": _look(solv), "dyes": [{"name": n, "colour": c} for n, c in dyes]},
                         {"dyes": [n for n, _ in dyes]})
    elif liquids:
        liq_set = list(liquids)
        dissolved: list[str] = []
        suspended: list[str] = []
        for s in solids:
            solvents = [x for x in liq_set if _dissolves(s, x)]
            (dissolved if solvents else suspended).append(s)
        if len(dissolved) > 1:
            ok = False
        else:
            if suspended:
                mixture = [*liq_set, *dissolved]
                plan.add("filtration", f"Filter: the {_list(suspended)} stay{'s' if _one(suspended) else ''} on the filter paper "
                         f"(residue); the {_list(mixture)} run{'s' if _one(mixture) else ''} through (filtrate).",
                         f"The {_list(suspended)} {'does' if _one(suspended) else 'do'} not dissolve in the "
                         f"{_list(liq_set)}.",
                         {"residue": [_look(x) for x in suspended],
                          "filtrate": _look(dissolved[0], solution=True, solvent=liq_set[0]) if dissolved else _look(liq_set[0])},
                         {"residue": suspended, "filtrate": _list(mixture)})
                if len(suspended) > 1:
                    ok = _solids(plan, suspended, keep) and ok
            if dissolved and len(liq_set) > 1:
                ok = False            # a solid dissolved in a mixture of liquids: not a school case
            elif ok:
                ok = _liquids(plan, liq_set, dissolved, keep)
    else:
        ok = len(solids) >= 2 and _solids(plan, solids, keep)
    if not ok or not plan.steps:
        return {"covered": False, "why": "The separation rules here do not decide that mixture.", "parts": ps}
    methods = [st["method"] for st in plan.steps]
    main = next((m for m in methods if m not in ("dissolve",)), methods[0])
    return {"covered": True, "parts": ps, "keep": keep, "methods": methods, "names": [st["name"] for st in plan.steps],
            "steps": [st["text"] for st in plan.steps], "plan": plan.steps,
            "why": " Then ".join(f"{st['name']}: {st['why']}" for st in plan.steps),
            "uses": METHODS[main]["uses"], "looks": [_look(p) for p in ps]}


# ── every mixture, and its questions ──────────────────────────────────────────

def catalogue(max_parts: int = 3) -> list[dict[str, Any]]:
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


def all_questions(limit: int = 0) -> list[dict[str, Any]]:
    """Every question on every mixture (the first `limit`, if given)."""
    out: list[dict[str, Any]] = []
    for mix in catalogue():
        out.extend(questions(mix))
        if limit and len(out) >= limit:
            return out[:limit]
    return out


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
    link = {k: str(curriculum.get(k) or "").strip() for k in ("grade", "subject", "strand", "sub_strand")}
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

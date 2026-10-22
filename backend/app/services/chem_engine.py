"""The chemistry engine: what happens when substances meet, worked out by
rules a school chemistry teacher uses — never guessed.

Like the maths engine, it decides everything itself, so a walkthrough costs
nothing and is always right for what it covers:

* formulas are read (Fe2(SO4)3, Ca(OH)2, CuSO4·5H2O) and equations balanced
  exactly (SymPy's rational null space — the method ChemPy uses);
* a reaction is found from the reactants by the rules of school chemistry:
  the reactivity series (metals with acids, water, oxygen; displacement),
  neutralisation, acids with carbonates, precipitation by the solubility
  rules, combustion, burning in chlorine, and thermal decomposition
  (limestone, temporary hardness of water);
* each reaction carries what you would see — gas and its test, a
  precipitate and its colour, a solution changing colour, a metal coating,
  heat — as a lab-bench animation spec, the steps of the explanation, and
  where the reaction is used in life.

A pair the rules do not cover says so ("not covered") rather than inventing
a reaction; a pair that does not react says why (copper is below hydrogen).
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

# ── formulas ─────────────────────────────────────────────────────────────────

_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_TO_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def normalize(formula: str) -> str:
    """'CuSO₄', 'cuso4 (aq)' → 'CuSO4'; a hydrate's dot kept as '.'."""
    f = str(formula or "").translate(_SUB).strip()
    f = re.sub(r"\((s|l|g|aq)\)\s*$", "", f).strip()
    return f.replace("·", ".").replace("*", ".").replace(" ", "")


def parse(formula: str) -> dict[str, int]:
    """Atoms in a formula: 'Fe2(SO4)3' → {'Fe': 2, 'S': 3, 'O': 12}."""
    f = normalize(formula)
    total: dict[str, int] = {}
    for part in f.split("."):
        m = re.match(r"^(\d+)(.*)$", part)
        mult, part = (int(m.group(1)), m.group(2)) if m else (1, part)
        for el, n in _parse_group(part).items():
            total[el] = total.get(el, 0) + n * mult
    if not total:
        raise ValueError(f"Not a formula: {formula!r}")
    return total


def _parse_group(s: str) -> dict[str, int]:
    stack: list[dict[str, int]] = [{}]
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in "([":
            stack.append({})
            i += 1
        elif ch in ")]":
            i += 1
            m = re.match(r"\d+", s[i:])
            n = int(m.group()) if m else 1
            i += len(m.group()) if m else 0
            inner = stack.pop()
            for el, c in inner.items():
                stack[-1][el] = stack[-1].get(el, 0) + c * n
        else:
            m = re.match(r"([A-Z][a-z]?)(\d*)", s[i:])
            if not m:
                raise ValueError(f"Not a formula: {s!r}")
            el, n = m.group(1), int(m.group(2) or 1)
            if el not in ELEMENTS:
                raise ValueError(f"No element {el!r}")
            stack[-1][el] = stack[-1].get(el, 0) + n
            i += len(m.group())
    if len(stack) != 1:
        raise ValueError(f"Unbalanced brackets in {s!r}")
    return stack[0]


def pretty(formula: str) -> str:
    """'Fe2(SO4)3' → 'Fe₂(SO₄)₃' (subscripts, as the board writes them)."""
    f = normalize(formula)
    out = re.sub(r"(?<=[A-Za-z\)\]])(\d+)", lambda m: m.group(1).translate(_TO_SUB), f)
    return out.replace(".", "·")


# ── balancing ────────────────────────────────────────────────────────────────

def balance(reactants: list[str], products: list[str]) -> tuple[list[int], list[int]]:
    """Smallest whole-number coefficients, exactly: the null space of the
    atom-count matrix. Raises ValueError when the equation cannot balance
    (or balances more than one way)."""
    from sympy import Matrix, lcm

    species = [parse(f) for f in reactants] + [parse(f) for f in products]
    elements = sorted({el for s in species for el in s})
    rows = [[s.get(el, 0) * (1 if k < len(reactants) else -1) for k, s in enumerate(species)] for el in elements]
    space = Matrix(rows).nullspace()
    if len(space) != 1:
        raise ValueError("That equation cannot be balanced as written." if not space else
                         "That equation balances more than one way — name the products.")
    v = space[0]
    v = v * lcm([x.q for x in v])
    nums = [int(x) for x in v]
    if all(n < 0 for n in nums):
        nums = [-n for n in nums]
    if any(n <= 0 for n in nums):
        raise ValueError("That equation cannot be balanced as written.")
    from math import gcd
    from functools import reduce

    g = reduce(gcd, nums)
    nums = [n // g for n in nums]
    return nums[:len(reactants)], nums[len(reactants):]


def equation_text(reactants: list[str], products: list[str], rc: list[int] | None = None, pc: list[int] | None = None,
                  states: dict[str, str] | None = None) -> str:
    """'2Na + 2H₂O → 2NaOH + H₂' (coefficients of 1 left out; state symbols if given)."""
    def side(fs: list[str], cs: list[int] | None) -> str:
        out = []
        for k, f in enumerate(fs):
            c = cs[k] if cs else 1
            st = f"({states[f]})" if states and states.get(f) else ""
            out.append(f"{c if c != 1 else ''}{pretty(f)}{st}")
        return " + ".join(out)
    return f"{side(reactants, rc)} → {side(products, pc)}"


def tally(formulas: list[str], coefficients: list[int] | None = None) -> dict[str, int]:
    """Atoms of each element on one side of an equation."""
    out: dict[str, int] = {}
    for k, f in enumerate(formulas):
        c = coefficients[k] if coefficients else 1
        for el, n in parse(f).items():
            out[el] = out.get(el, 0) + n * c
    return out


# ── the elements and ions school chemistry uses ──────────────────────────────

ELEMENTS: dict[str, str] = {
    "H": "hydrogen", "He": "helium", "Li": "lithium", "Be": "beryllium", "B": "boron", "C": "carbon", "N": "nitrogen",
    "O": "oxygen", "F": "fluorine", "Ne": "neon", "Na": "sodium", "Mg": "magnesium", "Al": "aluminium", "Si": "silicon",
    "P": "phosphorus", "S": "sulphur", "Cl": "chlorine", "Ar": "argon", "K": "potassium", "Ca": "calcium",
    "Mn": "manganese", "Fe": "iron", "Cu": "copper", "Zn": "zinc", "Br": "bromine", "Ag": "silver", "Sn": "tin",
    "I": "iodine", "Ba": "barium", "Au": "gold", "Hg": "mercury", "Pb": "lead", "Cr": "chromium", "Ni": "nickel",
    "Co": "cobalt", "Pt": "platinum",
}
DIATOMIC = {"H": "H2", "N": "N2", "O": "O2", "F": "F2", "Cl": "Cl2", "Br": "Br2", "I": "I2"}

# Most reactive first; hydrogen's place decides what an acid does.
REACTIVITY = ["K", "Na", "Ca", "Mg", "Al", "C", "Zn", "Fe", "Sn", "Pb", "H", "Cu", "Hg", "Ag", "Au", "Pt"]

CATIONS: dict[str, tuple[str, int]] = {      # symbol in a salt → (name, charge)
    "K": ("potassium", 1), "Na": ("sodium", 1), "Li": ("lithium", 1), "Ag": ("silver", 1), "NH4": ("ammonium", 1),
    "H": ("hydrogen", 1), "Ca": ("calcium", 2), "Mg": ("magnesium", 2), "Zn": ("zinc", 2), "Ba": ("barium", 2),
    "Cu": ("copper(II)", 2), "Pb": ("lead(II)", 2), "Sn": ("tin(II)", 2), "Fe": ("iron(II)", 2), "Fe3": ("iron(III)", 3),
    "Al": ("aluminium", 3), "Mn": ("manganese(II)", 2), "Ni": ("nickel(II)", 2),
}
ANIONS: dict[str, tuple[str, int, str]] = {  # group → (name, charge, acid it comes from)
    "Cl": ("chloride", 1, "HCl"), "Br": ("bromide", 1, "HBr"), "I": ("iodide", 1, "HI"), "NO3": ("nitrate", 1, "HNO3"),
    "SO4": ("sulphate", 2, "H2SO4"), "CO3": ("carbonate", 2, ""), "HCO3": ("hydrogencarbonate", 1, ""),
    "OH": ("hydroxide", 1, ""), "O": ("oxide", 2, ""), "PO4": ("phosphate", 3, "H3PO4"), "CH3COO": ("ethanoate", 1, "CH3COOH"),
}
POLY = {"NO3", "SO4", "CO3", "HCO3", "OH", "PO4", "NH4", "CH3COO"}
ACIDS = {"HCl": "hydrochloric acid", "H2SO4": "sulphuric acid", "HNO3": "nitric acid", "H3PO4": "phosphoric acid",
         "CH3COOH": "ethanoic acid", "HBr": "hydrobromic acid", "HI": "hydroiodic acid"}

# Colours of what you see: ions in water, solids, precipitates (hex for the animation, words for the narration).
COLOURS: dict[str, tuple[str, str]] = {
    "Cu2+": ("blue", "#2f7fd8"), "Fe2+": ("pale green", "#a8d5a2"), "Fe3+": ("yellow-brown", "#c98a2b"),
    "Ni2+": ("green", "#4caf50"), "Mn2+": ("very pale pink", "#f4d6dc"), "none": ("colourless", "#dff3ff"),
    "Cu": ("reddish-brown", "#a5512b"), "Fe": ("grey", "#7d7d7d"), "Zn": ("grey", "#9aa3ab"), "Ag": ("silvery-grey", "#c0c0c0"),
    "Pb": ("grey", "#6e6e6e"), "Mg": ("silvery", "#d8d8d8"), "Na": ("silvery", "#e3e3e3"), "Ca": ("grey-white", "#e6e6e0"),
    "Al": ("silvery", "#d4d7da"), "K": ("silvery", "#e3e3e3"), "Sn": ("silvery", "#cfcfcf"),
    "Cu(OH)2": ("blue", "#3b7dd8"), "Fe(OH)2": ("green", "#5c8a4a"), "Fe(OH)3": ("reddish-brown", "#9c4a1a"),
    "Zn(OH)2": ("white", "#f5f5f5"), "Mg(OH)2": ("white", "#f5f5f5"), "Ca(OH)2": ("white", "#f5f5f5"),
    "Al(OH)3": ("white", "#f5f5f5"), "Pb(OH)2": ("white", "#f5f5f5"), "AgCl": ("white", "#f7f7f7"),
    "AgBr": ("cream", "#f3e7c3"), "AgI": ("yellow", "#f2d64b"), "BaSO4": ("white", "#f7f7f7"), "PbSO4": ("white", "#f7f7f7"),
    "CaCO3": ("white", "#f7f7f7"), "PbI2": ("bright yellow", "#f6d40c"), "PbCl2": ("white", "#f7f7f7"),
    "CuO": ("black", "#1f1f1f"), "MgO": ("white", "#f7f7f7"), "ZnO": ("white (yellow when hot)", "#f7f7f7"),
    "CaO": ("white", "#f7f7f7"), "Fe2O3": ("reddish-brown", "#8a3b12"), "Al2O3": ("white", "#f7f7f7"),
    "CuCO3": ("green", "#3c8f6a"), "FeCl3": ("brown", "#8a4b12"),
}
GAS_TESTS = {
    "H2": "a lighted splint placed at the mouth of the tube goes out with a 'pop'",
    "CO2": "bubbled through limewater, it turns the limewater milky",
    "O2": "it relights a glowing splint",
    "Cl2": "it bleaches damp blue litmus paper (turning it red first)",
    "NH3": "it turns damp red litmus paper blue",
    "SO2": "it turns orange acidified potassium dichromate green",
}
GAS_NAMES = {"H2": "hydrogen", "CO2": "carbon dioxide", "O2": "oxygen", "Cl2": "chlorine", "NH3": "ammonia",
             "SO2": "sulphur dioxide", "H2O": "steam"}


def _symbol_of(formula: str) -> str | None:
    """'Mg' → 'Mg' for an element, 'Cl2' → 'Cl'; None for a compound."""
    f = normalize(formula)
    if f in ELEMENTS:
        return f
    for el, d in DIATOMIC.items():
        if f == d:
            return el
    return None


def salt(cation: str, anion: str) -> str:
    """The formula of a salt from its ions: ('Fe3', 'SO4') → 'Fe2(SO4)3'."""
    from math import gcd

    c_sym = "Fe" if cation == "Fe3" else cation
    qc, qa = CATIONS[cation][1], ANIONS[anion][1]
    g = gcd(qc, qa)
    nc, na = qa // g, qc // g
    def part(sym: str, n: int) -> str:
        if n == 1:
            return sym
        return f"({sym}){n}" if sym in POLY else f"{sym}{n}"
    return part(c_sym, nc) + part(anion, na)


def split_salt(formula: str) -> tuple[str, str] | None:
    """A salt's ions, by trying the known ones: 'FeCl3' → ('Fe3', 'Cl'); None if it is not one."""
    target = parse(formula)
    for cat in CATIONS:
        for an in ANIONS:
            if cat == "H":
                continue
            try:
                if parse(salt(cat, an)) == target:
                    return cat, an
            except (KeyError, ValueError):
                continue
    return None


def name_of(formula: str) -> str:
    f = normalize(formula)
    if f in ACIDS:
        return ACIDS[f]
    if f == "H2O":
        return "water"
    sym = _symbol_of(f)
    if sym:
        return ELEMENTS[sym]
    if f in GAS_NAMES:
        return GAS_NAMES[f]
    s = split_salt(f)
    if s:
        return f"{CATIONS[s[0]][0]} {ANIONS[s[1]][0]}"
    return pretty(f)


def _soluble(formula: str) -> bool:
    """The solubility rules of school chemistry."""
    s = split_salt(formula)
    if not s:
        return True
    cat, an = s
    if cat in ("Na", "K", "NH4", "Li") or an == "NO3" or an == "CH3COO":
        return True
    if an in ("Cl", "Br", "I"):
        return cat not in ("Ag", "Pb")
    if an == "SO4":
        return cat not in ("Ba", "Pb", "Ca")
    if an in ("CO3", "PO4"):
        return False
    if an == "HCO3":
        return True
    if an in ("OH", "O"):
        return cat in ("Ba",)
    return True


def _ion_colour(formula: str) -> tuple[str, str]:
    s = split_salt(formula)
    key = "none"
    if s:
        key = {"Cu": "Cu2+", "Fe": "Fe2+", "Fe3": "Fe3+", "Ni": "Ni2+", "Mn": "Mn2+"}.get(s[0], "none")
    return COLOURS[key]


def _above(a: str, b: str) -> bool:
    """Is metal a above b in the reactivity series?"""
    return REACTIVITY.index(a) < REACTIVITY.index(b)


# ── finding the reaction ─────────────────────────────────────────────────────

APPLICATIONS = {
    "metal_acid": ["Making salts such as zinc sulphate in the laboratory", "Why acidic foods are not stored in zinc or iron containers",
                   "Preparing small amounts of hydrogen gas"],
    "metal_water": ["Why sodium and potassium are stored under oil", "Producing hydrogen from reactive metals",
                    "Why iron rusts faster in water and air"],
    "metal_oxygen": ["Magnesium in flares and fireworks for its bright white light", "Rusting and corrosion of metals",
                     "Protective oxide layers on aluminium window frames"],
    "displacement": ["Extracting copper from copper sulphate solution using scrap iron", "Galvanising: zinc protects iron from rusting",
                     "The thermite reaction (aluminium and iron oxide) to weld railway lines"],
    "neutralisation": ["Antacid tablets neutralising excess stomach acid", "Farmers liming acidic soil",
                       "Treating bee stings and acidic factory waste"],
    "acid_carbonate": ["Limewater test for carbon dioxide", "Baking powder making dough rise",
                       "Acid rain wearing away limestone buildings and statues"],
    "precipitation": ["Testing for ions in water samples", "Removing hardness from water with washing soda",
                      "Making insoluble salts such as barium sulphate for X-ray meals"],
    "combustion": ["Burning fuels (LPG, kerosene) for cooking and heating", "Why burning needs a good supply of air (carbon monoxide danger)",
                   "Energy in car engines"],
    "chlorination": ["Making iron(III) chloride for treating water", "Making table salt from its elements (in theory)"],
    "decomposition": ["Making quicklime from limestone in a lime kiln", "Scale (fur) in kettles from temporarily hard water",
                      "Softening temporarily hard water by boiling"],
    "synthesis": ["Water is formed when hydrogen burns — a clean fuel", "Making ammonia for fertilisers (Haber process)"],
}


def react(a: str, b: str = "", *, condition: str = "") -> dict[str, Any]:
    """What happens when a meets b (or a alone, heated). Always a dict:
    'reacts' True with the reaction, or False with 'why' — and 'covered'
    False when the rules do not decide it."""
    a, b = normalize(a), normalize(b)
    condition = (condition or "").lower()
    for f in (a, b):
        if f:
            parse(f)                                   # a formula, or ValueError
    pair = [x for x in (a, b) if x]
    found = (_decompose(a, condition) if not b else None) or _rules(a, b, condition) or (_rules(b, a, condition) if b else None)
    if found is None:
        return {"reacts": False, "covered": False, "reactants": pair,
                "why": "The rules of school chemistry here do not cover this combination — no reaction is assumed."}
    if found.get("reacts") is False:
        return {"covered": True, "reactants": pair, **found}
    return _finish(found)


def _rules(x: str, y: str, condition: str) -> dict[str, Any] | None:
    sx, sy = _symbol_of(x), _symbol_of(y)
    # metal + acid
    if sx and sx in REACTIVITY and sx not in ("H", "C") and y in ACIDS:
        if not _above(sx, "H"):
            return {"reacts": False, "why": f"{ELEMENTS[sx].capitalize()} is below hydrogen in the reactivity series, "
                                            f"so it cannot push hydrogen out of {ACIDS.get(y, y)}: no reaction."}
        an = {"HCl": "Cl", "H2SO4": "SO4", "HNO3": "NO3", "H3PO4": "PO4", "CH3COOH": "CH3COO", "HBr": "Br", "HI": "I"}[y]
        cat = sx
        product = salt(cat, an)
        fast = REACTIVITY.index(sx) <= REACTIVITY.index("Na")
        obs = [f"Bubbles of gas (effervescence){' — violently, it is dangerous' if fast else ''}",
               f"The {ELEMENTS[sx]} gets smaller and disappears", "The test tube gets warm"]
        colour = _ion_colour(product)
        if colour[0] != "colourless":
            obs.append(f"The solution turns {colour[0]}")
        return {"type": "metal_acid", "reactants": [x, y], "products": [product, "H2"],
                "states": {x: "s", y: "aq", product: "aq", "H2": "g"}, "observations": obs,
                "lab": {"vessel": "test_tube", "solid": COLOURS.get(sx, ("grey", "#999"))[1], "solid_shrinks": True,
                        "liquid": COLOURS["none"][1], "liquid_to": colour[1], "bubbles": "H2", "heat": True},
                "why": f"{ELEMENTS[sx].capitalize()} is above hydrogen in the reactivity series, so it displaces hydrogen "
                       f"from the acid, forming {name_of(product)} and hydrogen gas.",
                "word": f"{ELEMENTS[sx]} + {ACIDS[y]} → {name_of(product)} + hydrogen"}
    # metal + water / steam
    if sx and y == "H2O" and sx in REACTIVITY:
        steam = "steam" in condition
        if sx in ("K", "Na", "Ca") and not steam:
            hyd = salt(sx, "OH")
            return {"type": "metal_water", "reactants": [x, "H2O"], "products": [hyd, "H2"],
                    "states": {x: "s", "H2O": "l", hyd: "aq", "H2": "g"},
                    "observations": (["The metal floats, melts into a ball and darts about on the water", "Fizzing as hydrogen is given off"]
                                     + (["A lilac flame as the hydrogen catches fire"] if sx == "K" else [])
                                     if sx in ("K", "Na") else ["The calcium sinks and bubbles steadily", "The water turns cloudy (calcium hydroxide)"])
                                    + ["The solution turns universal indicator purple (alkaline)"],
                    "lab": {"vessel": "trough", "solid": COLOURS[sx][1], "solid_shrinks": True, "solid_moves": sx in ("K", "Na"),
                            "liquid": COLOURS["none"][1], "liquid_to": "#efe9ff" if sx != "Ca" else "#eeeeee", "bubbles": "H2",
                            "flame": "#c77dff" if sx == "K" else "", "heat": True},
                    "why": f"{ELEMENTS[sx].capitalize()} is near the top of the reactivity series: it reacts with cold water, "
                           f"forming {name_of(hyd)} (an alkali) and hydrogen.",
                    "word": f"{ELEMENTS[sx]} + water → {name_of(hyd)} + hydrogen"}
        if sx in ("Mg", "Zn", "Fe") and (steam or sx == "Mg"):
            if sx == "Mg" and not steam:
                hyd = "Mg(OH)2"
                return {"type": "metal_water", "reactants": [x, "H2O"], "products": [hyd, "H2"],
                        "states": {x: "s", "H2O": "l", hyd: "s", "H2": "g"},
                        "observations": ["Very slow: a few bubbles form on the magnesium over days"],
                        "lab": {"vessel": "test_tube", "solid": COLOURS["Mg"][1], "liquid": COLOURS["none"][1], "bubbles": "H2", "slow": True},
                        "why": "Magnesium reacts only very slowly with cold water; with steam it burns brightly.",
                        "word": "magnesium + water → magnesium hydroxide + hydrogen"}
            oxide = "Fe3O4" if sx == "Fe" else salt(sx, "O")
            return {"type": "metal_water", "reactants": [x, "H2O"], "products": [oxide, "H2"],
                    "states": {x: "s", "H2O": "g", oxide: "s", "H2": "g"},
                    "observations": (["The magnesium glows with a bright white light", "A white solid (magnesium oxide) is left"]
                                     if sx == "Mg" else [f"The {ELEMENTS[sx]} glows when heated in steam", "A gas that 'pops' is collected"]),
                    "lab": {"vessel": "heated_tube", "solid": COLOURS[sx][1], "solid_to": COLOURS.get(oxide, ("", "#333"))[1],
                            "bubbles": "H2", "flame": "#ffffff" if sx == "Mg" else "", "heat": True},
                    "why": f"{ELEMENTS[sx].capitalize()} is too low in the series to react with cold water quickly, "
                           f"but hot enough steam gives its oxide and hydrogen.",
                    "word": f"{ELEMENTS[sx]} + steam → {name_of(oxide) if oxide != 'Fe3O4' else 'triiron tetroxide'} + hydrogen"}
        if not _above(sx, "H"):
            return {"reacts": False, "why": f"{ELEMENTS[sx].capitalize()} is below hydrogen: it does not react with water or steam."}
    # element + oxygen (burning)
    if sx and y == "O2":
        if sx in ("Au", "Pt", "Ag"):
            return {"reacts": False, "why": f"{ELEMENTS[sx].capitalize()} is so unreactive that it does not burn or tarnish in air."}
        oxide = {"C": "CO2", "S": "SO2", "H": "H2O", "P": "P4O10", "Fe": "Fe3O4", "Cu": "CuO", "Na": "Na2O", "K": "K2O",
                 "Ca": "CaO", "Mg": "MgO", "Al": "Al2O3", "Zn": "ZnO", "Pb": "PbO"}.get(sx)
        if not oxide:
            return None
        flame = {"Mg": ("a brilliant white", "#ffffff"), "Na": ("a yellow", "#ffd23f"), "K": ("a lilac", "#c77dff"),
                 "Ca": ("a brick-red", "#e2583e"), "S": ("a blue", "#4ea8ff"), "C": ("an orange glow", "#ff8c42"),
                 "H": ("a pale blue", "#9ad1ff"), "Cu": ("no", ""), "Fe": ("an orange sparkle", "#ffb347"),
                 "Zn": ("a bluish-green", "#7fd1b9"), "Al": ("a bright white", "#ffffff")}.get(sx, ("a", "#ffb347"))
        typ = "synthesis" if sx == "H" else "metal_oxygen" if sx in REACTIVITY and sx not in ("H", "C") else "combustion"
        obs = ([f"It burns with {flame[0]} flame"] if flame[1] else [f"The {ELEMENTS[sx]} turns black on the surface when heated"])
        obs.append(f"A {COLOURS.get(oxide, ('', ''))[0] or 'new'} product forms: {name_of(oxide)}" if oxide not in ("CO2", "SO2", "H2O")
                   else f"A gas forms: {name_of(oxide)}" if oxide != "H2O" else "Droplets of water form")
        return {"type": typ, "reactants": [DIATOMIC.get(sx, sx), "O2"], "products": [oxide],
                "states": {DIATOMIC.get(sx, sx): "g" if sx == "H" else "s", "O2": "g", oxide: "g" if oxide in ("CO2", "SO2") else "l" if oxide == "H2O" else "s"},
                "observations": obs,
                "lab": {"vessel": "spoon", "solid": COLOURS.get(sx, ("", "#555"))[1], "solid_to": COLOURS.get(oxide, ("", "#eee"))[1],
                        "flame": flame[1], "heat": True, "smoke": oxide in ("MgO", "Al2O3", "ZnO")},
                "why": f"{ELEMENTS[sx].capitalize()} combines with oxygen from the air when heated, forming {name_of(oxide)}.",
                "word": f"{ELEMENTS[sx]} + oxygen → {name_of(oxide)}"}
    # metal + chlorine
    if sx and sx in CATIONS and y == "Cl2":
        cat = "Fe3" if sx == "Fe" else sx
        product = salt(cat, "Cl")
        return {"type": "chlorination", "reactants": [x, "Cl2"], "products": [product],
                "states": {x: "s", "Cl2": "g", product: "s"},
                "observations": ["The metal glows as it burns in the green chlorine gas",
                                 f"A {COLOURS.get(product, ('white', ''))[0]} solid forms: {name_of(product)}",
                                 "The green colour of the chlorine fades"],
                "lab": {"vessel": "gas_jar", "gas": "#c6e86b", "gas_fades": True, "solid": COLOURS.get(sx, ("", "#999"))[1],
                        "solid_to": COLOURS.get(product, ("", "#f7f7f7"))[1], "flame": "#ffb347", "heat": True},
                "why": f"{ELEMENTS[sx].capitalize()} combines directly with chlorine"
                       + (" — iron gives iron(III) chloride, as chlorine is a strong oxidiser." if sx == "Fe" else "."),
                "word": f"{ELEMENTS[sx]} + chlorine → {name_of(product)}"}
    # displacement: metal + salt of another metal
    if sx and sx in REACTIVITY and sx not in ("H", "C"):
        s = split_salt(y)
        if s:
            other = "Fe" if s[0] == "Fe3" else s[0]
            if other in REACTIVITY and other != sx:
                if not _above(sx, other):
                    return {"reacts": False, "why": f"{ELEMENTS[sx].capitalize()} is below {ELEMENTS[other]} in the reactivity series, "
                                                    f"so it cannot displace {ELEMENTS[other]} from {name_of(y)}: no reaction."}
                if sx in ("K", "Na", "Ca") and _soluble(y) and "melt" not in condition and "molten" not in condition:
                    # In water these react with the water first: the honest school answer.
                    out = _rules(x, "H2O", condition)
                    if out:
                        out = dict(out)
                        out["note"] = (f"{ELEMENTS[sx].capitalize()} is so reactive that in a solution it reacts with the water "
                                       f"first; it displaces {ELEMENTS[other]} only from the molten (dry) {name_of(y)}.")
                    return out
                cat = sx if sx != "Fe" else "Fe"
                new = salt(cat, s[1])
                molten = "molten" in condition or "melt" in condition
                c_old, c_new = _ion_colour(y), _ion_colour(new)
                if molten:
                    obs = ["A bright glow and a lot of heat as the reaction starts",
                           f"{ELEMENTS[other].capitalize()} metal is left among {name_of(new)}"]
                else:
                    obs = [f"A {COLOURS.get(other, ('', ''))[0]} coating of {ELEMENTS[other]} forms on the {ELEMENTS[sx]}"]
                    if c_old[0] != c_new[0]:
                        obs.append(f"The {c_old[0]} solution turns {c_new[0]}")
                    obs.append("The mixture gets warm")
                return {"type": "displacement", "reactants": [x, y], "products": [new, DIATOMIC.get(other, other)],
                        "states": {x: "s", y: "l" if molten else "aq", new: "s" if molten else "aq", other: "s"},
                        "observations": obs,
                        "lab": ({"vessel": "crucible", "solid": COLOURS.get(sx, ("", "#999"))[1], "solid_to": COLOURS.get(other, ("", "#777"))[1],
                                 "flame": "#ffb347", "heat": True, "burner": True} if molten else
                                {"vessel": "beaker", "solid": COLOURS.get(sx, ("", "#999"))[1], "coating": COLOURS.get(other, ("", "#a5512b"))[1],
                                 "liquid": c_old[1], "liquid_to": c_new[1], "heat": True}),
                        "why": f"{ELEMENTS[sx].capitalize()} is above {ELEMENTS[other]} in the reactivity series, so it pushes "
                               f"{ELEMENTS[other]} out of its compound: {ELEMENTS[sx]} takes its place.",
                        "word": f"{ELEMENTS[sx]} + {name_of(y)} → {name_of(new)} + {ELEMENTS[other]}"}
    # acid + base / carbonate
    if x in ACIDS:
        s = split_salt(y)
        if s and s[1] in ("OH", "O", "CO3", "HCO3"):
            an = {"HCl": "Cl", "H2SO4": "SO4", "HNO3": "NO3", "H3PO4": "PO4", "CH3COOH": "CH3COO", "HBr": "Br", "HI": "I"}[x]
            new = salt(s[0], an)
            colour = _ion_colour(new)
            if s[1] in ("CO3", "HCO3"):
                return {"type": "acid_carbonate", "reactants": [x, y], "products": [new, "H2O", "CO2"],
                        "states": {x: "aq", y: "s", new: "aq", "H2O": "l", "CO2": "g"},
                        "observations": ["Effervescence: bubbles of a colourless gas", f"The {name_of(y)} dissolves",
                                         "The gas turns limewater milky (carbon dioxide)"] + ([f"The solution turns {colour[0]}"] if colour[0] != "colourless" else []),
                        "lab": {"vessel": "beaker", "solid": COLOURS.get(y, ("white", "#f3f3f3"))[1], "solid_shrinks": True,
                                "liquid": COLOURS["none"][1], "liquid_to": colour[1], "bubbles": "CO2", "limewater": True},
                        "why": f"Every acid reacts with a carbonate to give a salt, water and carbon dioxide.",
                        "word": f"{ACIDS[x]} + {name_of(y)} → {name_of(new)} + water + carbon dioxide"}
            return {"type": "neutralisation", "reactants": [x, y], "products": [new, "H2O"],
                    "states": {x: "aq", y: "aq" if _soluble(y) and s[1] == "OH" else "s", new: "aq", "H2O": "l"},
                    "observations": ["The mixture gets warm (the reaction gives out heat)",
                                     "Universal indicator turns from red, through green (neutral, pH 7)"]
                                    + ([f"The {name_of(y)} dissolves", f"The solution turns {colour[0]}"] if s[1] == "O" and colour[0] != "colourless" else []),
                    "lab": {"vessel": "beaker", "liquid": "#ff6b6b", "liquid_to": "#4caf50", "drops": True, "heat": True,
                            **({"solid": COLOURS.get(y, ("", "#222"))[1], "solid_shrinks": True} if s[1] == "O" else {})},
                    "why": "An acid and a base cancel each other out: the H⁺ of the acid and the OH⁻ (or O²⁻) of the base make water, "
                           "leaving a salt.",
                    "word": f"{ACIDS[x]} + {name_of(y)} → {name_of(new)} + water"}
    # two salts in solution: precipitation
    sxs, sys = split_salt(x), split_salt(y)
    if sxs and sys and sxs[0] != sys[0] and _soluble(x) and _soluble(y):
        p1, p2 = salt(sxs[0], sys[1]), salt(sys[0], sxs[1])
        insol = [p for p in (p1, p2) if not _soluble(p)]
        if not insol:
            return {"reacts": False, "why": f"Both possible products ({name_of(p1)} and {name_of(p2)}) are soluble, "
                                            "so the ions just stay mixed in solution: no reaction is seen."}
        ppt = insol[0]
        other = p2 if ppt == p1 else p1
        return {"type": "precipitation", "reactants": [x, y], "products": [ppt, other],
                "states": {x: "aq", y: "aq", ppt: "s", other: "aq"},
                "observations": [f"A {COLOURS.get(ppt, ('white', ''))[0]} precipitate forms at once: {name_of(ppt)}",
                                 "The precipitate settles at the bottom if left to stand"],
                "lab": {"vessel": "test_tube", "liquid": _ion_colour(x)[1], "drops": True, "drop_colour": _ion_colour(y)[1],
                        "precipitate": COLOURS.get(ppt, ("white", "#f5f5f5"))[1]},
                "why": f"{name_of(ppt).capitalize()} does not dissolve in water, so its ions come together as a solid "
                       "the moment the two solutions meet.",
                "word": f"{name_of(x)} + {name_of(y)} → {name_of(ppt)} + {name_of(other)}"}
    # hydrocarbon + oxygen
    if y == "O2" and set(parse(x)) <= {"C", "H", "O"} and "C" in parse(x) and "H" in parse(x):
        return {"type": "combustion", "reactants": [x, "O2"], "products": ["CO2", "H2O"],
                "states": {x: "g", "O2": "g", "CO2": "g", "H2O": "l"},
                "observations": ["It burns with a blue flame in plenty of air", "Droplets of water form on a cold surface",
                                 "The gas turns limewater milky (carbon dioxide)"],
                "lab": {"vessel": "burner", "flame": "#4ea8ff", "heat": True, "bubbles": "CO2"},
                "why": "A hydrocarbon burning in plenty of oxygen gives carbon dioxide and water — and a lot of heat.",
                "word": f"{name_of(x)} + oxygen → carbon dioxide + water"}
    return None


def _decompose(a: str, condition: str) -> dict[str, Any] | None:
    """One substance heated."""
    if not a or ("heat" not in condition and "boil" not in condition):
        return None
    s = split_salt(a)
    if a == "Ca(HCO3)2" or (s and s[1] == "HCO3" and s[0] in ("Ca", "Mg")):
        carb = salt(s[0], "CO3")
        return {"type": "decomposition", "reactants": [a], "products": [carb, "H2O", "CO2"],
                "states": {a: "aq", carb: "s", "H2O": "l", "CO2": "g"},
                "observations": ["Bubbles of carbon dioxide as the water boils", f"A white solid ({name_of(carb)}) forms: scale or 'fur'",
                                 "The water no longer forms scum with soap — its temporary hardness is gone"],
                "lab": {"vessel": "beaker", "liquid": COLOURS["none"][1], "bubbles": "CO2", "precipitate": "#f5f5f5", "heat": True, "burner": True},
                "why": f"{name_of(a).capitalize()} in temporarily hard water breaks down when boiled into insoluble "
                       f"{name_of(carb)}, which comes out as scale.",
                "word": f"{name_of(a)} → {name_of(carb)} + water + carbon dioxide"}
    if s and s[1] == "CO3" and s[0] not in ("Na", "K"):
        oxide = salt(s[0], "O")
        return {"type": "decomposition", "reactants": [a], "products": [oxide, "CO2"],
                "states": {a: "s", oxide: "s", "CO2": "g"},
                "observations": [f"The {COLOURS.get(a, ('', ''))[0] or ''} solid changes to a {COLOURS.get(oxide, ('', ''))[0]} solid".replace("  ", " "),
                                 "The gas given off turns limewater milky"],
                "lab": {"vessel": "heated_tube", "solid": COLOURS.get(a, ("", "#f3f3f3"))[1], "solid_to": COLOURS.get(oxide, ("", "#eee"))[1],
                        "bubbles": "CO2", "limewater": True, "heat": True, "burner": True},
                "why": f"Heating breaks {name_of(a)} down into {name_of(oxide)} and carbon dioxide.",
                "word": f"{name_of(a)} → {name_of(oxide)} + carbon dioxide"}
    if s and s[0] in ("Na", "K") and s[1] == "CO3":
        return {"reacts": False, "why": f"{name_of(a).capitalize()} does not break down at the heat of a Bunsen burner."}
    return None


def _finish(r: dict[str, Any]) -> dict[str, Any]:
    """Balance it, add the atom tallies, the steps and the applications."""
    rc, pc = balance(r["reactants"], r["products"])
    before = {"left": tally(r["reactants"]), "right": tally(r["products"])}
    after = {"left": tally(r["reactants"], rc), "right": tally(r["products"], pc)}
    gases = [p for p in r["products"] if p in GAS_TESTS]
    steps = [r["why"], f"Word equation: {r['word']}",
             f"Symbol equation (not yet balanced): {equation_text(r['reactants'], r['products'])}"]
    for el in sorted(set(before["left"]) | set(before["right"])):
        if before["left"].get(el, 0) != before["right"].get(el, 0):
            steps.append(f"{ELEMENTS.get(el, el).capitalize()} atoms: {before['left'].get(el, 0)} on the left, "
                         f"{before['right'].get(el, 0)} on the right — they must be equal.")
    steps.append(f"Balanced: {equation_text(r['reactants'], r['products'], rc, pc, r.get('states'))}")
    for g in gases:
        steps.append(f"Test for {GAS_NAMES[g]}: {GAS_TESTS[g]}.")
    return {"reacts": True, "covered": True, **r, "coefficients": {"reactants": rc, "products": pc},
            "equation": equation_text(r["reactants"], r["products"], rc, pc),
            "equation_states": equation_text(r["reactants"], r["products"], rc, pc, r.get("states")),
            "unbalanced": equation_text(r["reactants"], r["products"]),
            "atoms": {"before": before, "after": after}, "gas_tests": {g: GAS_TESTS[g] for g in gases},
            "steps": steps, "applications": APPLICATIONS.get(r["type"], [])}


def balance_given(equation: str) -> dict[str, Any]:
    """An equation written by a question ('Fe + Cl2 -> FeCl3'): balanced, with the atom tallies."""
    sides = re.split(r"\s*(?:->|→|=)\s*", equation.translate(_SUB))
    if len(sides) != 2:
        raise ValueError("Write the equation as reactants → products.")
    strip = lambda s: [re.sub(r"^\d+(?=[A-Z(])", "", normalize(x)) for x in s.split("+") if x.strip()]  # noqa: E731
    rs, ps = strip(sides[0]), strip(sides[1])
    rc, pc = balance(rs, ps)
    return {"reactants": rs, "products": ps, "coefficients": {"reactants": rc, "products": pc},
            "unbalanced": equation_text(rs, ps), "equation": equation_text(rs, ps, rc, pc),
            "atoms": {"before": {"left": tally(rs), "right": tally(ps)},
                      "after": {"left": tally(rs, rc), "right": tally(ps, pc)}}}


def molar_mass(formula: str) -> Fraction:
    """Relative formula mass from the school table of relative atomic masses."""
    return sum((Fraction(str(RAM[el])) * n for el, n in parse(formula).items()), Fraction(0))


RAM = {"H": 1, "He": 4, "C": 12, "N": 14, "O": 16, "Na": 23, "Mg": 24, "Al": 27, "Si": 28, "P": 31, "S": 32, "Cl": 35.5,
       "K": 39, "Ca": 40, "Mn": 55, "Fe": 56, "Cu": 63.5, "Zn": 65, "Br": 80, "Ag": 108, "Sn": 119, "I": 127, "Ba": 137,
       "Au": 197, "Hg": 201, "Pb": 207, "Li": 7, "Be": 9, "B": 11, "F": 19, "Ne": 20, "Ar": 40, "Cr": 52, "Ni": 59, "Co": 59, "Pt": 195}


# ── atoms: electron arrangement, ions and bonds ─────────────────────────────
#
# The first twenty elements, as school chemistry draws them: shells of 2, 8,
# 8 and 2. From the outer shell come the ion an atom forms (a metal loses its
# outer electrons, a non-metal gains enough to make eight) and so the formula
# of the compound — the electrons decide it, and the animation shows them move.

ATOMIC_NUMBER = {"H": 1, "He": 2, "Li": 3, "Be": 4, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "Ne": 10, "Na": 11,
                 "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ar": 18, "K": 19, "Ca": 20}
MASS_NUMBER = {"H": 1, "He": 4, "Li": 7, "Be": 9, "B": 11, "C": 12, "N": 14, "O": 16, "F": 19, "Ne": 20, "Na": 23,
               "Mg": 24, "Al": 27, "Si": 28, "P": 31, "S": 32, "Cl": 35, "Ar": 40, "K": 39, "Ca": 40}
METALS = {"Li", "Be", "Na", "Mg", "Al", "K", "Ca"}
NOBLE = {"He", "Ne", "Ar"}


def shells(symbol: str) -> list[int]:
    """'Na' → [2, 8, 1] (the school model: 2, 8, 8, 2)."""
    z = ATOMIC_NUMBER[symbol]
    out, caps = [], [2, 8, 8, 2]
    for cap in caps:
        if z <= 0:
            break
        take = min(cap, z)
        out.append(take)
        z -= take
    return out


def atom(symbol: str) -> dict[str, Any]:
    """An atom as the board draws it: protons, neutrons, shells, its ion and why."""
    sym = _symbol_of(symbol) or symbol
    if sym not in ATOMIC_NUMBER:
        raise ValueError(f"The electron model here covers the first twenty elements, not {symbol!r}.")
    sh = shells(sym)
    outer = sh[-1]
    z = ATOMIC_NUMBER[sym]
    if sym in NOBLE:
        charge, why = 0, f"Its outer shell is full ({outer}), so it is stable: it does not form ions."
    elif sym in METALS:
        charge, why = outer, f"It has {outer} electron{'s' if outer > 1 else ''} in its outer shell, which it loses to be stable."
    elif sym == "H":
        charge, why = 1, "It has one electron; it can lose it (H⁺) or share it."
    elif outer >= 4 and sym in ("C", "Si"):
        charge, why = 0, f"It has {outer} outer electrons: it shares them (covalent bonds) rather than forming ions."
    else:
        charge, why = -(8 - outer), f"It has {outer} electrons in its outer shell and gains {8 - outer} to make eight."
    ion_shells = list(sh)
    if charge > 0:
        ion_shells = sh[:-1] if sh[-1] == charge else sh[:-1] + [sh[-1] - charge]
    elif charge < 0:
        ion_shells = sh[:-1] + [sh[-1] - charge]
    return {"symbol": sym, "name": ELEMENTS[sym], "Z": z, "protons": z, "electrons": z,
            "neutrons": MASS_NUMBER[sym] - z, "mass_number": MASS_NUMBER[sym], "shells": sh,
            "arrangement": ".".join(str(n) for n in sh), "group": (8 if sym in NOBLE and sym != "He" else outer) if sym != "He" else 8,
            "period": len(sh), "metal": sym in METALS, "valency": abs(charge) if charge else (outer if sym in ("C", "Si") else 0),
            "ion_charge": charge, "ion_shells": ion_shells, "ion_arrangement": ".".join(str(n) for n in ion_shells),
            "ion": _ion_name(sym, charge), "why": why}


def _ion_name(sym: str, charge: int) -> str:
    sup = {1: "⁺", 2: "²⁺", 3: "³⁺", -1: "⁻", -2: "²⁻", -3: "³⁻"}.get(charge, "")
    return f"{sym}{sup}" if sup else sym


def bond(a: str, b: str) -> dict[str, Any]:
    """How two elements bond, and so the formula of their compound: ionic
    (a metal gives its outer electrons to a non-metal) or covalent (two
    non-metals share pairs). The counts come from the electrons."""
    from math import gcd

    x, y = atom(a), atom(b)
    if x["symbol"] in NOBLE or y["symbol"] in NOBLE:
        return {"kind": "none", "why": "A noble gas has a full outer shell: it does not bond."}
    if x["metal"] == y["metal"]:
        if x["metal"]:
            return {"kind": "metallic", "why": "Two metals do not form a compound this way; they can mix as an alloy."}
        # covalent: each shares as many electrons as it needs
        va, vb = (x["valency"] or 1), (y["valency"] or 1)
        g = gcd(va, vb)
        na, nb = vb // g, va // g
        if x["symbol"] == y["symbol"]:
            na, nb = 1, 1
        if x["symbol"] in ("C", "Si") or (y["symbol"] == "H" and x["symbol"] != "H"):
            centre, outer, nc, no = x, y, na, nb
        else:
            centre, outer, nc, no = y, x, nb, na
        if x["symbol"] == y["symbol"]:
            formula = f"{x['symbol']}2"
        elif "H" in (centre["symbol"], outer["symbol"]) and ({centre["symbol"], outer["symbol"]} - {"H"}) <= {"F", "Cl", "Br", "I", "O", "S"}:
            other = centre if outer["symbol"] == "H" else outer
            formula = _formula_of({"H": no if outer["symbol"] == "H" else nc, other["symbol"]: nc if outer["symbol"] == "H" else no})
        else:
            formula = _formula_of({centre["symbol"]: nc, outer["symbol"]: no})     # NH3, CH4, CO2: the centre first
        shared = (centre["valency"] or 1) * nc if x["symbol"] != y["symbol"] else (x["valency"] or 1)
        return {"kind": "covalent", "atoms": [x, y], "centre": centre["symbol"], "counts": {centre["symbol"]: nc, outer["symbol"]: no}
                if x["symbol"] != y["symbol"] else {x["symbol"]: 2},
                "formula": formula, "shared_pairs": shared,
                "why": (f"Both are non-metals: they share electrons. {centre['name'].capitalize()} needs {centre['valency']} more and "
                        f"{outer['name']} needs {outer['valency']}, so they share pairs until every atom has a full outer shell: "
                        f"{pretty(formula)}." if x["symbol"] != y["symbol"] else
                        f"Two {x['name']} atoms each need {x['valency']} more electron{'s' if x['valency'] > 1 else ''}: they share "
                        f"{x['valency']} pair{'s' if x['valency'] > 1 else ''}, making {pretty(formula)}.")}
    metal, non = (x, y) if x["metal"] else (y, x)
    qm, qn = metal["ion_charge"], -non["ion_charge"]
    g = gcd(qm, qn)
    nm, nn = qn // g, qm // g
    formula = _formula_of({metal["symbol"]: nm, non["symbol"]: nn})
    moves = []                                       # each electron: from metal atom i to non-metal atom j
    for i in range(nm):
        for e in range(qm):
            k = i * qm + e
            moves.append({"from": i, "to": k // qn})
    return {"kind": "ionic", "atoms": [metal, non], "metal": metal["symbol"], "nonmetal": non["symbol"],
            "counts": {metal["symbol"]: nm, non["symbol"]: nn}, "formula": formula, "moves": moves,
            "ions": [metal["ion"], non["ion"]],
            "why": (f"{metal['name'].capitalize()} ({metal['arrangement']}) gives away {qm} electron{'s' if qm > 1 else ''}; "
                    f"{non['name']} ({non['arrangement']}) takes {qn}. "
                    + (f"So {nm} {metal['name']} atom{'s' if nm > 1 else ''} give{'s' if nm == 1 else ''} electrons to "
                       f"{nn} {non['name']} atom{'s' if nn > 1 else ''}: " if (nm, nn) != (1, 1) else "One for one: ")
                    + f"the ions {metal['ion']} and {non['ion']} attract, and the formula is {pretty(formula)}.")}


def _formula_of(counts: dict[str, int]) -> str:
    return "".join(f"{el}{n if n > 1 else ''}" for el, n in counts.items())


# ── separating mixtures ──────────────────────────────────────────────────────

SEPARATIONS: dict[str, dict[str, Any]] = {
    "filtration": {"name": "Filtration", "when": "an insoluble solid from a liquid",
                   "steps": ["Fold a filter paper into a cone and fit it in a filter funnel over a beaker",
                             "Pour the mixture in slowly", "The liquid (filtrate) runs through; the solid (residue) stays on the paper"],
                   "uses": ["Clearing muddy water at a water works", "Making tea or coffee with a filter", "Separating sand from water"]},
    "evaporation": {"name": "Evaporation", "when": "a dissolved solid from its solution (the solvent is not kept)",
                    "steps": ["Pour the solution into an evaporating dish", "Heat it gently over a water bath or Bunsen burner",
                              "The water evaporates; the solid is left behind"],
                    "uses": ["Salt pans at the coast (Malindi, Ngomeni)", "Getting sugar from sugarcane juice"]},
    "crystallisation": {"name": "Crystallisation", "when": "pure crystals of a dissolved solid",
                        "steps": ["Heat the solution until it is saturated (crystals form on a cold glass rod)",
                                  "Leave it to cool slowly", "Crystals form; filter them off and dry them between filter papers"],
                        "uses": ["Making pure copper(II) sulphate crystals", "Purifying table salt"]},
    "distillation": {"name": "Simple distillation", "when": "a pure liquid (the solvent) from a solution",
                     "steps": ["Heat the solution in a flask", "The solvent boils off as vapour and passes into a Liebig condenser",
                               "Cold water around the condenser turns the vapour back to liquid (distillate), collected in a beaker",
                               "The dissolved solid stays in the flask"],
                     "uses": ["Getting drinking water from sea water", "Making distilled water for car batteries and labs"]},
    "fractional_distillation": {"name": "Fractional distillation", "when": "liquids that mix but boil at different temperatures",
                                "steps": ["Heat the mixture in a flask with a fractionating column",
                                          "The liquid with the lower boiling point vaporises first and reaches the condenser",
                                          "Collect each liquid as the thermometer shows its boiling point"],
                                "uses": ["Separating crude oil into petrol, kerosene and diesel", "Getting oxygen and nitrogen from liquid air"]},
    "separating_funnel": {"name": "Separating funnel", "when": "two liquids that do not mix",
                          "steps": ["Pour the mixture into a separating funnel and let it settle into two layers",
                                    "Open the tap to run off the lower (denser) layer", "Close the tap: the upper layer stays"],
                          "uses": ["Separating oil from water", "Extracting oils in industry"]},
    "magnet": {"name": "Magnetic separation", "when": "a magnetic solid (iron, nickel, cobalt) from a non-magnetic one",
               "steps": ["Spread the mixture on paper", "Pass a magnet over it", "The iron sticks to the magnet; the rest stays behind"],
               "uses": ["Sorting scrap iron from other waste", "Removing iron from crushed ore"]},
    "chromatography": {"name": "Paper chromatography", "when": "dyes or colours mixed in a solution",
                       "steps": ["Put a spot of the mixture on a pencil line near the bottom of a filter paper",
                                 "Stand the paper in a solvent (water or ethanol) below the line",
                                 "The solvent rises and carries each dye a different distance: the colours separate"],
                       "uses": ["Testing food colourings and inks", "Forensic tests on ink in documents"]},
    "sublimation": {"name": "Sublimation", "when": "a solid that sublimes (iodine, ammonium chloride) from one that does not",
                    "steps": ["Heat the mixture in a dish covered by an inverted funnel or cold surface",
                              "The subliming solid turns straight to vapour", "It turns back to solid on the cold surface; the rest stays"],
                    "uses": ["Purifying iodine", "Separating ammonium chloride from salt"]},
}

# component → its properties (how it behaves in a mixture)
COMPONENTS: dict[str, dict[str, Any]] = {
    "sand": {"state": "solid", "soluble": False}, "chalk": {"state": "solid", "soluble": False},
    "salt": {"state": "solid", "soluble": True, "formula": "NaCl"}, "sugar": {"state": "solid", "soluble": True},
    "copper(II) sulphate": {"state": "solid", "soluble": True, "formula": "CuSO4"},
    "water": {"state": "liquid", "bp": 100}, "ethanol": {"state": "liquid", "bp": 78, "mixes": True},
    "oil": {"state": "liquid", "mixes": False}, "kerosene": {"state": "liquid", "mixes": False},
    "iron filings": {"state": "solid", "soluble": False, "magnetic": True}, "sulphur": {"state": "solid", "soluble": False},
    "iodine": {"state": "solid", "soluble": False, "sublimes": True}, "ammonium chloride": {"state": "solid", "soluble": True, "sublimes": True},
    "ink": {"state": "solution", "dyes": True}, "food colouring": {"state": "solution", "dyes": True},
}


# Other names a question may use for a component.
ALIASES = {"iron": "iron filings", "iron powder": "iron filings", "sulfur": "sulphur", "sulphur powder": "sulphur",
           "common salt": "salt", "sodium chloride": "salt"}


def separate(parts: list[str], keep: str = "") -> dict[str, Any]:
    """How to separate a mixture: the method(s) from what the parts are like."""
    ps = [ALIASES.get(p.strip().lower(), p.strip().lower()) for p in parts if p.strip()]
    unknown = [p for p in ps if p not in COMPONENTS]
    if unknown:
        return {"covered": False, "why": f"The separation rules here do not know {', '.join(unknown)}."}
    props = {p: COMPONENTS[p] for p in ps}
    method: list[str] = []
    if any(v.get("dyes") for v in props.values()):
        method = ["chromatography"]
    elif any(v.get("magnetic") for v in props.values()):
        method = ["magnet"]
    elif any(v.get("sublimes") for v in props.values()) and all(v["state"] == "solid" for v in props.values()):
        method = ["sublimation"]
    elif all(v["state"] == "liquid" for v in props.values()):
        method = ["fractional_distillation"] if all(v.get("mixes", True) for v in props.values()) else ["separating_funnel"]
    else:
        solids = [p for p, v in props.items() if v["state"] == "solid"]
        liquids = [p for p, v in props.items() if v["state"] == "liquid"]
        insoluble = [p for p in solids if not props[p].get("soluble")]
        soluble = [p for p in solids if props[p].get("soluble")]
        if insoluble and soluble and not liquids:
            method = ["dissolve", "filtration", "evaporation"]
        elif insoluble and liquids:
            method = ["filtration"]
        elif soluble and liquids:
            method = ["distillation"] if keep in liquids else (["crystallisation"] if "crystal" in keep else ["evaporation"])
        else:
            return {"covered": False, "why": "The separation rules here do not cover that mixture."}
    steps: list[str] = []
    for m in method:
        if m == "dissolve":
            steps.append("Add water and stir: the soluble part dissolves, the insoluble part does not")
        else:
            steps.extend(SEPARATIONS[m]["steps"])
    named = [SEPARATIONS[m]["name"] if m in SEPARATIONS else "Dissolving" for m in method]
    main = next((m for m in method if m in SEPARATIONS), method[0])
    return {"covered": True, "parts": ps, "methods": method, "names": named, "steps": steps,
            "why": f"{' then '.join(named)}: for {SEPARATIONS[main]['when']}.",
            "uses": SEPARATIONS[main]["uses"]}

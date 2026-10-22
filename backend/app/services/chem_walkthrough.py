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
    atoms = _atoms_scene(result)
    if atoms:
        out.append(atoms)
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


# ── the reaction atom by atom ───────────────────────────────────────────────
# Each species built as its particle — a molecule's atoms round a centre, a
# salt's ions side by side (S in the middle of SO4, H on the O of OH) — and
# copied as many times as the balanced equation says, so the animation's
# atoms are exactly the equation's: every one leaves a reactant and lands in
# a product, none made, none lost.

_DIRS = {
    1: [(1, 0, 0)],
    2: [(1, 0, 0), (-1, 0, 0)],
    3: [(1, 0, 0), (-0.5, 0.866, 0), (-0.5, -0.866, 0)],
    4: [(0, 1, 0), (0.943, -0.333, 0), (-0.471, -0.333, 0.816), (-0.471, -0.333, -0.816)],
    5: [(0, 1, 0), (0, -1, 0), (1, 0, 0), (-0.5, 0, 0.866), (-0.5, 0, -0.866)],
    6: [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
}
_CENTRE_ORDER = ["C", "S", "N", "P", "Si", "Mn", "Cr", "Cl", "Br", "I", "O", "F", "H"]
RADIUS = {"H": 0.32, "C": 0.5, "N": 0.48, "O": 0.46, "F": 0.42, "Cl": 0.6, "Br": 0.66, "I": 0.72, "S": 0.6, "P": 0.6}


def _radius(el: str) -> float:
    return RADIUS.get(el, 0.62 if el in C.CATIONS or el in C.REACTIVITY else 0.55)


def _ring(n: int, r: float, tilt: float = 0.0) -> list[tuple[float, float, float]]:
    import math

    return [(math.cos(tilt + 2 * math.pi * k / n) * r, math.sin(tilt + 2 * math.pi * k / n) * r * 0.75,
             math.sin(tilt + 2 * math.pi * k / n + 1) * r * 0.5) for k in range(n)]


def _group(counts: dict[str, int], ion: bool = False) -> list[dict[str, Any]]:
    """A covalent particle (a molecule, or an anion group): a centre with
    the others round it; hydrogens on oxygens when there are oxygens — except
    in an ion such as ethanoate, which has lost the acid's H from its O."""
    atoms: list[dict[str, Any]] = []
    els = [e for e in counts if counts[e] > 0]
    if sum(counts.values()) == 1:
        return [{"el": els[0], "pos": [0.0, 0.0, 0.0], "to": -1}]
    if len(els) == 1:                                    # O2, Cl2, H2: a chain
        n = counts[els[0]]
        bl = 2 * _radius(els[0]) * 0.92
        return [{"el": els[0], "pos": [(k - (n - 1) / 2) * bl, 0.0, 0.0], "to": k - 1 if k else -1} for k in range(n)]
    cands = [e for e in els if e != "H"] or els
    organic = "C" in counts and "H" in counts
    centre = "C" if organic else min(cands, key=lambda e: (counts[e], _CENTRE_ORDER.index(e) if e in _CENTRE_ORDER else 0))
    rest = dict(counts)
    rest[centre] -= 1
    atoms.append({"el": centre, "pos": [0.0, 0.0, 0.0], "to": -1})
    hs = rest.pop("H", 0) if centre != "H" else 0
    ligands = [e for e in rest for _ in range(rest[e])]
    if centre == "O" and hs:                              # water, hydroxide: the H on the O itself
        ligands += ["H"] * hs
        hs = 0
    n = max(1, len(ligands))
    dirs = _DIRS.get(n) or _ring(n, 1.0)
    for e, d in zip(ligands, dirs):
        bl = (_radius(centre) + _radius(e)) * 0.95
        atoms.append({"el": e, "pos": [d[0] * bl, d[1] * bl, d[2] * bl], "to": 0})
    if organic:
        # Carbon compounds: the hydrogens on the carbons; one on an oxygen (the -OH of an alcohol or acid).
        carbons = [0] + [i for i, a in enumerate(atoms) if a["el"] == "C" and i > 0]
        oxy = [i for i, a in enumerate(atoms) if a["el"] == "O" and i > 0]
        on_o = 1 if oxy and hs and not ion else 0
        import math
        for k in range(hs):
            host = oxy[0] if k < on_o else carbons[(k - on_o) % len(carbons)]
            hx, hy, hz = atoms[host]["pos"]
            ang = 2.4 * k
            step = (_radius(atoms[host]["el"]) + _radius("H")) * 0.95
            off = (math.cos(ang) * step, math.sin(ang) * step * 0.8, math.sin(ang + 1.2) * step * 0.6) if host == 0 else \
                  (hx / max(1e-6, abs(hx) + abs(hy) + abs(hz)) * step + math.cos(ang) * 0.25,
                   hy / max(1e-6, abs(hx) + abs(hy) + abs(hz)) * step + math.sin(ang) * 0.45,
                   hz / max(1e-6, abs(hx) + abs(hy) + abs(hz)) * step + 0.3 * math.sin(ang + 2))
            atoms.append({"el": "H", "pos": [hx + off[0], hy + off[1], hz + off[2]], "to": host})
        return atoms
    oxy = [i for i, a in enumerate(atoms) if a["el"] == "O" and i > 0]
    for k in range(hs):                                   # acids: the H on an O; otherwise on the centre
        if oxy:
            host = oxy[k % len(oxy)]
            hx, hy, hz = atoms[host]["pos"]
            norm = max(1e-6, (hx * hx + hy * hy + hz * hz) ** 0.5)
            step = (_radius("O") + _radius("H")) * 0.95
            atoms.append({"el": "H", "pos": [hx + hx / norm * step, hy + hy / norm * step + 0.15 * (k % 2), hz + hz / norm * step],
                          "to": host})
        else:
            d = (_DIRS.get(hs) or _ring(hs, 1.0))[k]
            bl = (_radius(centre) + _radius("H")) * 0.95
            atoms.append({"el": "H", "pos": [d[0] * bl, d[1] * bl, d[2] * bl], "to": 0})
    return atoms


def structure(formula: str) -> list[dict[str, Any]]:
    """A species as its particle: [{el, pos, to}] — `to` is the atom it is
    bonded to (-1: none); ions of a salt stand side by side, unbonded."""
    f = C.normalize(formula)
    counts = dict(C.parse(f))
    sp = None
    try:
        sp = C.split_salt(f)
    except ValueError:
        sp = None
    if not sp or len(counts) == 1:
        return _group(counts)
    cat, an = sp
    cat_el = "Fe" if cat == "Fe3" else cat
    an_counts = dict(C.parse(an)) if an not in ("O", "S") else {an: 1}
    n_cat = counts.get(cat_el, 1) if cat_el in counts else 1
    if cat == "NH4":
        n_cat = counts.get("N", 1) if an not in ("NO3",) else 1
    key = next(iter(an_counts))
    n_an = max(1, round((counts.get(key, 1) - (counts.get(key, 0) if False else 0)) / an_counts[key]))
    if cat == "NH4" and key == "H":
        n_an = 1
    atoms: list[dict[str, Any]] = []
    group = _group(an_counts, ion=True)
    spread = 1.9
    centres = [(0.0, 0.0, 0.0)] if n_an == 1 else [(p[0] * spread * 0.8, p[1] * spread * 0.8, p[2] * spread * 0.6) for p in _ring(n_an, 1.0)]
    for c in centres:                                       # the anion groups
        base = len(atoms)
        for a in group:
            atoms.append({"el": a["el"], "pos": [a["pos"][0] + c[0], a["pos"][1] + c[1], a["pos"][2] + c[2]],
                          "to": a["to"] + base if a["to"] >= 0 else -1})
    cat_group = _group(dict(C.parse("NH4"))) if cat == "NH4" else [{"el": cat_el, "pos": [0.0, 0.0, 0.0], "to": -1}]
    far = 1.55 + (0.6 if n_an > 1 else 0.3)
    cat_pos = [(0.0, far, 0.0)] if n_cat == 1 else _ring(n_cat, far, tilt=0.6)
    for c in cat_pos:                                       # the cations beside them
        base = len(atoms)
        for a in cat_group:
            atoms.append({"el": a["el"], "pos": [a["pos"][0] + c[0], a["pos"][1] + c[1], a["pos"][2] + c[2]],
                          "to": a["to"] + base if a["to"] >= 0 else -1, "ion": True})
    got: dict[str, int] = {}
    for a in atoms:
        got[a["el"]] = got.get(a["el"], 0) + 1
    if got != counts:                                       # a salt the grouping cannot read: as one cluster
        return _group(counts)
    return atoms


def _atoms_scene(result: dict[str, Any]) -> dict[str, Any] | None:
    """The reaction at the level of atoms: each particle of the balanced
    equation, its atoms leaving their old partners for new ones."""
    rc, pc = result["coefficients"]["reactants"], result["coefficients"]["products"]
    total = sum(c * sum(C.parse(f).values()) for f, c in zip(result["reactants"] + result["products"], rc + pc))
    if total > 140:
        return None
    side = lambda fs, cs: [{"formula": C.normalize(f), "pretty": C.pretty(f), "count": c, "atoms": structure(f),  # noqa: E731
                            "name": C.name_of(f)} for f, c in zip(fs, cs)]
    left, right = side(result["reactants"], rc), side(result["products"], pc)
    els = sorted({a["el"] for sp in left + right for a in sp["atoms"]})
    after = result["atoms"]["after"]["left"]
    tally = ", ".join(f"{after[e]} {C.ELEMENTS.get(e, e)}" for e in sorted(after, key=lambda e: -after[e]))
    word = lambda xs: " and ".join(f"{d['count']} {d['name']}" if d["count"] > 1 else d["name"] for d in xs)  # noqa: E731
    part = _particles(result) or {}
    return {"scene": "chem_atoms", "left2": left, "right2": right,
            "colours": {e: CPK.get(e, "#999999") for e in els}, "radii": {e: round(_radius(e), 2) for e in els},
            "equation": result["equation"], "tally": after,
            # the whiteboard's own particle drawing, when there is no 3D
            **{k: part[k] for k in ("left", "right", "atoms") if k in part}, "flat": bool(part),
            "say": f"Now zoom in to the atoms. The particles of {word(left)} break apart. Every atom keeps going, into new "
                   f"partners: {word(right)}. Count them: {tally} — the same on both sides. Atoms are only rearranged, "
                   f"never made or destroyed. That is why the equation balances."}


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
    """The mixture's own walkthrough: what each part is like, then each step
    of the plan on its apparatus — drawn with these substances' colours, the
    residue and filtrate, the layers, the boiling points named — and the uses."""
    from . import chem_separation as X

    r = X.separate(parts, keep)
    if not r["covered"]:
        return [{"scene": "working", "text": r["why"], "say": r["why"]}]
    ps = r["parts"]
    mixture = X._list(ps)
    out: list[dict[str, Any]] = [{"scene": "chem_hook", "tiles": [{"symbol": _tile_symbol(p), "name": p.capitalize(), "Z": "",
                                                                   "colour": X.SUBSTANCES[p]["colour"], "formula": p} for p in ps[:3]],
                                  "question": f"How do we separate {mixture}?",
                                  "say": f"How do we separate {mixture}? It depends on what each one is like."}]
    out.append({"scene": "chem_list", "title": "What each part is like", "icon": "🔎", "items": [_trait(p) for p in ps],
                "say": "Look at each part. " + ". ".join(_trait(p) for p in ps) + "."})
    for k, st in enumerate(r["plan"]):
        lead = "First" if k == 0 and len(r["plan"]) > 1 else "Then" if k < len(r["plan"]) - 1 else ("Finally" if k else "")
        out.append({"scene": "chem_separation", "method": st["method"], "name": st["name"], "steps": [st["text"], st["why"]],
                    "parts": ps, "look": st["look"], "gives": st["gives"],
                    "say": (f"{lead}, {st['name'].lower()}. " if lead else f"{st['name']}. ") + st["text"] + " " + st["why"]})
    out.append({"scene": "chem_list", "title": "Where it is used", "icon": "🌍", "items": r["uses"],
                "say": "Where this is used: " + ". ".join(r["uses"]) + "."})
    return out


def _tile_symbol(p: str) -> str:
    from . import chem_separation as X

    f = X.SUBSTANCES[p].get("formula")
    return C.pretty(f) if f else p.split()[0][:3].capitalize()


def _trait(p: str) -> str:
    """One line on what a part is like, as far as separating goes."""
    from . import chem_separation as X

    i = X.SUBSTANCES[p]
    if i["kind"] == "ink":
        return f"{p.capitalize()}: a mixture of {len(i['dyes'])} dyes"
    if i["kind"] == "liquid":
        mix = "mixes with water" if i["polar"] else "does not mix with water"
        return f"{p.capitalize()}: a liquid, boils at {i['bp']} °C, density {i['density']:.2f} g/cm³, {mix}"
    bits = [i["looks"]]
    if i.get("magnetic"):
        bits.append("magnetic")
    if i.get("sublimes"):
        bits.append("sublimes when heated")
    sol = i.get("dissolves") or []
    bits.append(f"dissolves in {' and '.join(sol)}" if sol else "does not dissolve in water")
    return f"{p.capitalize()}: " + ", ".join(bits)


def _salt_metal(reactants: list[str]) -> str:
    for r in reactants:
        s = C.split_salt(r)
        if s:
            m = "Fe" if s[0] == "Fe3" else s[0]
            if m in C.REACTIVITY:
                return m
    return ""


# Gases a learner would smell, what they smell like, and the colour their wisps are drawn in
# (the real colour where there is one: chlorine yellow-green, nitrogen dioxide brown).
SMELLS = {
    "SO2": ("sulphur dioxide", "a choking smell, like a struck match", "#e9e2a8"),
    "NH3": ("ammonia", "a sharp, pungent smell that stings the nose", "#cfe8ff"),
    "H2S": ("hydrogen sulphide", "a smell of rotten eggs", "#d9e8a0"),
    "Cl2": ("chlorine", "a choking smell, like a swimming pool", "#c6e86b"),
    "NO2": ("nitrogen dioxide", "a choking smell, with brown fumes", "#b5651d"),
    "HCl": ("hydrogen chloride", "a sharp smell, with steamy fumes in moist air", "#e8eef2"),
}


def smell_of(result: dict[str, Any]) -> dict[str, str] | None:
    """The smell a reaction gives off, if one of its gaseous products has one."""
    if not result.get("reacts", True):
        return None
    states = result.get("states") or {}
    for p in result.get("products") or []:
        if p in SMELLS and states.get(p, "g") == "g":
            name, like, colour = SMELLS[p]
            return {"gas": p, "name": name, "like": like, "colour": colour}
    return None


def _lab(result: dict[str, Any], names: list[str], spec: dict[str, Any]) -> dict[str, Any]:
    lab = dict(result.get("lab") or {"vessel": "beaker"})
    reacts = result.get("reacts", True)
    sm = smell_of(result)
    obs = list(result.get("observations") or [])
    if sm:
        lab["smell"] = sm
        if not any("smell" in o.lower() for o in obs):
            obs.insert(1, f"{sm['like'][0].upper()}{sm['like'][1:]}: {sm['name']}")
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
            "lab": lab, "reacts": bool(reacts), "condition": cond, "observations": obs[:3],
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
    "Ammonium salts and sulphides": ["NH4Cl", "(NH4)2SO4", "NH4NO3", "FeS", "ZnS"],
}


PERIODIC = [  # (symbol, period, group) for the first twenty — the picker's table
    ("H", 1, 1), ("He", 1, 18), ("Li", 2, 1), ("Be", 2, 2), ("B", 2, 13), ("C", 2, 14), ("N", 2, 15), ("O", 2, 16),
    ("F", 2, 17), ("Ne", 2, 18), ("Na", 3, 1), ("Mg", 3, 2), ("Al", 3, 13), ("Si", 3, 14), ("P", 3, 15), ("S", 3, 16),
    ("Cl", 3, 17), ("Ar", 3, 18), ("K", 4, 1), ("Ca", 4, 2)]


def periodic() -> list[dict[str, Any]]:
    return [{"symbol": s, "name": C.ELEMENTS[s], "Z": C.ATOMIC_NUMBER[s], "period": p, "group": g,
             "colour": CPK.get(s, "#999"), "metal": s in C.METALS} for s, p, g in PERIODIC]


def mixtures() -> list[str]:
    from . import chem_separation as X

    return list(X.SUBSTANCES)


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

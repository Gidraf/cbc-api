"""Chemistry questions made and marked by the engine, for the bank — so every
part of the Chemistry lab (reactions, electron arrangements, bonding,
separating mixtures) gets what Play gives a question: its video, its social
cut, its photo series, posting and scheduling.

Each kind walks everything the engine knows — every reaction between the
lab's substances, the first twenty elements, every pair that bonds, every
mixture the separation rules decide — and asks the exam's questions about
it, multiple choice, the wrong options taken from the engine's other answers
(never a right one). Each carries its `chemistry` block, so its walkthrough
is the engine's animated one.
"""
from __future__ import annotations

import hashlib
import itertools
from functools import lru_cache
from typing import Any

from . import chem_engine as C

KINDS = ("reactions", "atoms", "bonding", "separations")
TYPE_NAMES = {
    "metal_acid": "A metal with an acid (displacement of hydrogen)", "metal_water": "A metal with water or steam",
    "metal_oxygen": "Burning in oxygen (oxidation)", "chlorination": "Burning in chlorine",
    "displacement": "Displacement by a more reactive metal", "neutralisation": "Neutralisation",
    "acid_carbonate": "An acid with a carbonate", "precipitation": "Precipitation (double decomposition)",
    "combustion": "Combustion of a fuel", "decomposition": "Thermal decomposition",
    "reduction": "Reduction (oxygen taken from a metal oxide)", "metal_sulphur": "A metal combining with sulphur",
    "hydration": "Slaking (an oxide combining with water)", "synthesis": "Synthesis (elements combining)",
}


def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _mcq(out: list[dict[str, Any]], focus: str, stem: str, right: str, wrong: list[str], chemistry: dict[str, Any],
         why: str, model: str = "") -> None:
    """One multiple-choice question: the right answer among three wrong ones
    (different from it and from each other), in a place fixed by its wording."""
    wrong = [w for w in dict.fromkeys(wrong) if w and w.strip().lower() != right.strip().lower()][:3]
    if len(wrong) < 3:
        return
    k = _seed(stem) % 4
    opts = wrong[:k] + [right] + wrong[k:]
    out.append({"focus": focus, "question_text": stem, "question_type": "multiple_choice",
                "options": [{"id": "ABCD"[i], "text": o, "is_correct": o == right} for i, o in enumerate(opts)],
                "correct_answer": right, "marks": 1, "marking_scheme": why, "model_answer": model or why,
                "chemistry": chemistry})


def _pick(pool: list[str], seed: int, n: int = 6) -> list[str]:
    if not pool:
        return []
    return [pool[(seed + i * 7919) % len(pool)] for i in range(min(n, len(pool)))]


# ── reactions ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _reactions() -> list[dict[str, Any]]:
    """Every reaction (and instructive non-reaction) between the lab's substances."""
    from .chem_walkthrough import SUBSTANCES

    shelf = [f for fs in SUBSTANCES.values() for f in fs]
    metals = SUBSTANCES["Metals"]
    solutions = set(SUBSTANCES["Acids"]) | set(SUBSTANCES["Salts in solution"])
    oxides = ["CuO", "ZnO", "PbO", "Fe2O3", "MgO", "CaO"]
    out: list[dict[str, Any]] = []
    tried: set[tuple[str, str, str]] = set()
    acids, salts = set(SUBSTANCES["Acids"]), set(SUBSTANCES["Salts in solution"])
    bases, carbonates, fuels = set(SUBSTANCES["Bases and alkalis"]), set(SUBSTANCES["Carbonates"]), set(SUBSTANCES["Fuels"])
    alkalis = {"NaOH", "KOH", "Ca(OH)2"}

    def meets(a: str, b: str) -> bool:
        """Two things put together the way a lab puts them: a metal into an acid,
        a salt solution, water, oxygen or chlorine; an acid onto a base or a
        carbonate; two solutions (or an alkali and a salt) for a precipitate;
        a fuel or an element burnt in oxygen. Not nitric acid with a metal
        (school chemistry: it gives no hydrogen), nor lead in an acid (it coats over)."""
        for x, y in ((a, b), (b, a)):
            if x in metals:
                if y == "HNO3" or (x == "Pb" and y in acids):
                    return False
                if y in acids | salts | {"H2O", "O2", "Cl2"}:
                    return True
            if x in acids and y in bases | carbonates | salts:
                return True
            if x == "CaO" and y == "H2O":
                return True
            if x in salts and y in salts | alkalis:
                return True
            if x in fuels | {"C", "S", "H2"} and y == "O2":
                return True
        return False

    # Mixed as they are; heated alone; steam over a metal; a metal heated with a metal oxide.
    pairs = [(a, b, "") for a, b in itertools.combinations(shelf, 2) if meets(a, b)]
    pairs += [(a, "", "heat") for a in shelf] + [(m, "H2O", "steam") for m in metals] + \
             [(m, o, "molten") for m in metals for o in oxides] + \
             [(r, o, "heat") for r in ("C", "H2") for o in oxides] + [(m, "S", "heat") for m in metals] + [("H2", "Cl2", "")]
    for a, b, cond in pairs:
        key = (a, b, cond)
        if key in tried:
            continue
        tried.add(key)
        try:
            r = C.react(a, b, condition=cond)
        except (ValueError, KeyError, IndexError):
            continue
        if not r.get("covered"):
            continue
        if not r.get("reacts"):
            # Only the instructive non-reactions: a metal in an acid or a salt solution, or
            # heated with an oxide — where the reactivity series decides.
            pair = {a, b}
            if not (pair & set(metals) and (pair & solutions or cond == "molten")) or "reactivity series" not in str(r.get("why") or ""):
                continue
        out.append({**r, "_a": a, "_b": b, "_cond": cond})
    return out


def _names(r: dict[str, Any]) -> str:
    a, b = C.name_of(r["_a"]), C.name_of(r["_b"]) if r["_b"] else ""
    if r["_cond"] == "heat" and not b:
        return f"{a} is heated strongly"
    if r["_cond"] == "steam":
        return f"steam is passed over heated {a}"
    if r["_cond"] in ("molten", "heat") and b:
        return f"{a} is heated with {b}"
    return f"{a} is added to {b}"


def _equation(r: dict[str, Any], co: dict[str, list[int]]) -> str:
    side = lambda fs, cs: " + ".join((f"{c}" if c != 1 else "") + C.pretty(f) for f, c in zip(fs, cs))  # noqa: E731
    return side(r["reactants"], co["reactants"]) + " → " + side(r["products"], co["products"])


def reaction_questions() -> list[dict[str, Any]]:
    rs = _reactions()
    all_obs = sorted({o for r in rs if r.get("reacts") for o in r.get("observations") or []})
    all_types = sorted({TYPE_NAMES[r["type"]] for r in rs if r.get("type") in TYPE_NAMES})
    out: list[dict[str, Any]] = []
    for r in rs:
        what = _names(r)
        chem = {"reactants": [x for x in (r["_a"], r["_b"]) if x], **({"condition": r["_cond"]} if r["_cond"] else {})}
        sd = _seed(r["_a"], r["_b"], r["_cond"])
        if not r.get("reacts"):
            why = r["why"][:1].lower() + r["why"][1:]
            _mcq(out, "no_reaction", f"What is observed when {what}? Explain.", f"No change: {why}",
                 [o + "." for o in _pick([o for o in all_obs], sd)], {**chem, "focus": "observations"}, r["why"])
            continue
        mine = set(r.get("observations") or [])
        _mcq(out, "observation", f"What is observed when {what}?", r["observations"][0],
             _pick([o for o in all_obs if o not in mine], sd), {**chem, "focus": "observations"},
             " ".join(r.get("steps") or [r["why"]]), "; ".join(r["observations"]) + ".")
        co = r["coefficients"]
        wrong = []
        if r.get("unbalanced") and r["unbalanced"] != r["equation"]:
            wrong.append(r["unbalanced"])
        for side in ("reactants", "products"):
            for i in range(len(co[side])):
                bumped = {k: list(v) for k, v in co.items()}
                bumped[side][i] += 1
                wrong.append(_equation(r, bumped))
        _mcq(out, "equation", f"Which is the balanced equation when {what}?", r["equation"], _pick(wrong, sd, 8),
             {**chem, "focus": "balancing"}, f"Balanced: {r['equation']}. Every atom appears the same number of times on both sides.")
        if r.get("type") in TYPE_NAMES:
            _mcq(out, "type", f"What type of reaction takes place when {what}?", TYPE_NAMES[r["type"]],
                 _pick([t for t in all_types if t != TYPE_NAMES[r["type"]]], sd), chem, r["why"])
        for gas, test in (r.get("gas_tests") or {}).items():
            gname = C.GAS_NAMES.get(gas, gas) if hasattr(C, "GAS_NAMES") else gas
            right = f"{gname.capitalize()}: {test}"
            others = [f"{C.GAS_NAMES.get(g, g).capitalize()}: {t}" for g, t in C.GAS_TESTS.items() if g != gas]
            _mcq(out, "gas", f"Which gas is given off when {what}, and how is it tested?", right, _pick(others, sd),
                 {**chem, "focus": "observations"}, f"The gas is {gname}: {test}.")
    return out


# ── atoms ────────────────────────────────────────────────────────────────────

def _arr_wrong(shells: list[int]) -> list[str]:
    """Plausible wrong arrangements: electrons moved between shells, or a shell overfilled."""
    out = []
    s = list(shells)
    for i in range(len(s) - 1):
        a = s[:]
        if a[i] > 1:
            a[i] -= 1; a[i + 1] += 1; out.append(".".join(map(str, a)))
        b = s[:]
        if b[i + 1] > 0:
            b[i] += 1; b[i + 1] -= 1; out.append(".".join(map(str, [x for x in b if x])))
    total = sum(s)
    out.append(".".join(map(str, [min(total, 8)] + ([total - 8] if total > 8 else []))))
    out.append(".".join(map(str, [2] + [total - 2] if total > 2 else [total])))
    out.append(".".join(map(str, [2, 8, total - 10] if total > 10 else [1, total - 1])))
    return [x for x in out if x != ".".join(map(str, shells))]


def atom_questions() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    syms = sorted((s for s, z in C.ATOMIC_NUMBER.items() if z <= 20), key=lambda s: C.ATOMIC_NUMBER[s])
    for sym in syms:
        a = C.atom(sym)
        name = a["name"]
        chem = {"atom": sym}
        _mcq(out, "arrangement", f"What is the electron arrangement of {name} (atomic number {a['Z']})?", a["arrangement"],
             _arr_wrong(a["shells"]), chem, f"{a['Z']} electrons: {a['arrangement']} (2 in the first shell, up to 8 in the next).")
        p, n, e = a["protons"], a["neutrons"], a["electrons"]
        _mcq(out, "particles", f"An atom of {name} has mass number {a['mass_number']} and atomic number {a['Z']}. How many "
             f"protons, neutrons and electrons does it have?", f"{p} protons, {n} neutrons, {e} electrons",
             [f"{p} protons, {a['mass_number']} neutrons, {e} electrons", f"{n} protons, {p} neutrons, {n} electrons",
              f"{p} protons, {n} neutrons, {a['mass_number']} electrons", f"{a['mass_number']} protons, {n} neutrons, {e} electrons"],
             chem, f"Protons = electrons = atomic number ({p}); neutrons = mass number − atomic number ({a['mass_number']} − {p} = {n}).")
        if a.get("group") and a.get("period"):
            g, pd = a["group"], a["period"]
            _mcq(out, "position", f"In which group and period of the periodic table is {name} ({a['arrangement']})?",
                 f"Group {g}, period {pd}", [f"Group {pd}, period {g}", f"Group {g}, period {pd + 1}", f"Group {(g % 8) + 1}, period {pd}",
                                             f"Group {g + 1 if g < 8 else g - 1}, period {max(1, pd - 1)}"],
                 chem, f"The number of shells gives the period ({pd}); the electrons in the outer shell give the group ({g}).")
        if a.get("ion_charge"):
            q = a["ion_charge"]
            sup = {1: "", 2: "²", 3: "³"}
            ion = lambda c: f"{sym}{sup.get(abs(c), '')}{'⁺' if c > 0 else '⁻'}"  # noqa: E731
            wrong = [ion(-q), ion(q + (1 if q > 0 else -1)), ion(-(q + (1 if q > 0 else -1)))]
            reason = a["why"].rstrip(".")
            _mcq(out, "ion", f"Which ion does {name} ({a['arrangement']}) form, and why?", f"{ion(q)}: {reason[:1].lower() + reason[1:]}",
                 [f"{w}: it {'loses' if w.endswith('⁺') else 'gains'} electrons to fill its outer shell" for w in wrong],
                 {**chem, "focus": "ion"}, a["why"])
    return out


# ── bonding ──────────────────────────────────────────────────────────────────

def _formula_wrong(f: str, a: str, b: str) -> list[str]:
    cands = [f"{a}{b}", f"{a}2{b}", f"{a}{b}2", f"{a}2{b}3", f"{a}3{b}2", f"{a}{b}3", f"{a}3{b}", f"{a}{b}4"]
    return [C.pretty(x) for x in cands if x != f]


def bonding_questions() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    syms = sorted((s for s, z in C.ATOMIC_NUMBER.items() if z <= 20 and s not in C.NOBLE), key=lambda s: C.ATOMIC_NUMBER[s])
    for a, b in itertools.combinations_with_replacement(syms, 2):
        try:
            r = C.bond(a, b)
        except (ValueError, KeyError):
            continue
        if r.get("kind") not in ("ionic", "covalent") or not r.get("formula"):
            continue
        A, B = C.name_of(a), C.name_of(b)
        pair = f"{A} and {B}" if a != b else f"two {A} atoms"
        f = r["formula"]
        first, second = (r.get("metal"), r.get("nonmetal")) if r["kind"] == "ionic" else (a, b)
        chem = {"bond": [a, b]}
        _mcq(out, "formula", f"What is the formula of the compound formed between {pair}?" if a != b else
             f"What is the formula of the molecule formed by {pair}?", C.pretty(f),
             _formula_wrong(f, first or a, second or b), chem, r["why"])
        if a != b:
            right = ("Ionic: electrons are transferred from the metal to the non-metal" if r["kind"] == "ionic"
                     else "Covalent: the atoms share pairs of electrons")
            _mcq(out, "bond_type", f"What type of bond forms between {A} and {B}, and how?", right,
                 ["Ionic: electrons are transferred from the metal to the non-metal", "Covalent: the atoms share pairs of electrons",
                  "Metallic: a sea of delocalised electrons", "No bond: both atoms already have full outer shells"],
                 chem, r["why"])
    return out


# ── all of them, a batch, the bank ───────────────────────────────────────────

def questions(kind: str) -> list[dict[str, Any]]:
    if kind == "separations":
        from . import chem_separation

        return chem_separation.all_questions()
    return {"reactions": reaction_questions, "atoms": atom_questions, "bonding": bonding_questions}[kind]()


@lru_cache(maxsize=4)
def _cached(kind: str) -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    out = []
    for q in questions(kind):
        if q["question_text"] not in seen:
            seen.add(q["question_text"])
            out.append(q)
    return tuple(out)


def pick(kind: str, limit: int) -> list[dict[str, Any]]:
    """`limit` of a kind, spread across its kinds of question (round robin)."""
    if kind == "separations":
        from . import chem_separation

        return chem_separation.pick(limit)
    groups: dict[str, list[dict[str, Any]]] = {}
    for q in _cached(kind):
        groups.setdefault(q["focus"], []).append(q)
    for g in groups.values():
        g.sort(key=lambda q: hashlib.sha1(q["question_text"].encode()).hexdigest())
    out: list[dict[str, Any]] = []
    depth = 0
    while len(out) < limit and any(depth < len(g) for g in groups.values()):
        for g in groups.values():
            if depth < len(g):
                out.append(g[depth])
                if len(out) >= limit:
                    break
        depth += 1
    return out


def summary() -> dict[str, Any]:
    from collections import Counter

    out: dict[str, Any] = {}
    for kind in KINDS:
        qs = list(_cached(kind)) if kind != "separations" else None
        if kind == "separations":
            from . import chem_separation

            s = chem_separation.summary()
            out[kind] = {"questions": s["questions"], "by_focus": s["by_focus"], "sample": s["sample"][:5]}
        else:
            out[kind] = {"questions": len(qs), "by_focus": dict(Counter(q["focus"] for q in qs).most_common()),
                         "sample": [q["question_text"] for q in pick(kind, 5)]}
    return out


def bank(kind: str, curriculum: dict[str, str], limit: int, *, by: str = "") -> dict[str, Any]:
    """Save `limit` engine-made questions of a kind to the bank at a point of
    the curriculum, approved (the engine marks them). The same question at the
    same point keeps its id, so saving again adds only what is new."""
    from ..infra.db import fetch_all
    from .question_dna import question_dna_service

    if kind not in KINDS:
        raise ValueError(f"A kind is one of: {', '.join(KINDS)}.")
    chosen = pick(kind, max(1, min(int(limit), 5000)))
    from .grade_order import normalize_grade

    link = {k: str(curriculum.get(k) or "").strip() for k in ("grade", "subject", "strand", "sub_strand")}
    link["grade"] = normalize_grade(link["grade"]) or link["grade"]      # as Play looks it up: grade-7
    point = "|".join(link.values()).lower()
    prefix = "q-chem-sep-" if kind == "separations" else f"q-chem-{kind[:5]}-"
    ids = [prefix + hashlib.sha1((point + "|" + q["question_text"]).encode()).hexdigest()[:14] for q in chosen]
    have = {r["question_id"] for r in (fetch_all("SELECT question_id FROM question_dna WHERE question_id = ANY(:i)",
                                                 {"i": ids}) or [])}
    saved = 0
    for qid, q in zip(ids, chosen):
        if qid in have:
            continue
        content = {k: q[k] for k in ("question_text", "question_type", "options", "correct_answer", "marks",
                                     "marking_scheme", "model_answer", "chemistry")}
        question_dna_service.save_question(
            question_id=qid, universal_id=f"chem-{kind}-{q['focus']}", curriculum_link=link,
            pedagogical_dna={"question_type": "multiple_choice", "focus": q["focus"],
                             "bloom": "apply" if q["focus"] in ("method", "order", "equation", "formula") else "understand"},
            content=content,
            provenance={"provider": "engine", "model": f"chemistry-{kind}", "written_by": "chemistry engine",
                        **({"saved_by": by} if by else {})},
            review_audit={"checked_by": "chemistry engine rules", "verdict": "approved"},
            status="approved")
        saved += 1
    return {"saved": saved, "already": len(have), "asked": len(chosen), "curriculum": link, "kind": kind}

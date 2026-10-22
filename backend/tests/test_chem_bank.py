"""Chemistry questions for the bank: every kind, each marked by the engine."""
from __future__ import annotations

import pytest

from app.services import chem_bank as B
from app.services import chem_engine as C


@pytest.mark.parametrize("kind, at_least", [("reactions", 600), ("atoms", 60), ("bonding", 150)])
def test_each_kind_makes_many_questions_with_one_right_answer(kind, at_least) -> None:
    qs = B.questions(kind)
    assert len(qs) >= at_least
    for q in qs:
        assert len(q["options"]) == 4 and sum(o["is_correct"] for o in q["options"]) == 1
        assert len({o["text"] for o in q["options"]}) == 4
        assert q["chemistry"]


def test_the_reactions_are_the_ones_a_lab_does() -> None:
    rs = B._reactions()
    assert not any("HNO3" in (r["_a"], r["_b"]) and ({r["_a"], r["_b"]} & set(C.METALS)) for r in rs)   # no H2 from nitric acid
    assert not any(r["_cond"] == "" and {r["_a"], r["_b"]} & set(C.METALS) and {r["_a"], r["_b"]} & {"CuO", "ZnO", "MgO", "CaO"}
                   for r in rs)                                                                        # an oxide is heated, not mixed
    zn = [q for q in B.questions("reactions") if q["question_text"] == "Which is the balanced equation when zinc is added to hydrochloric acid?"]
    assert zn and zn[0]["correct_answer"] == "Zn + 2HCl → ZnCl₂ + H₂"


def test_atoms_and_bonds_agree_with_the_engine() -> None:
    mg = next(q for q in B.questions("atoms") if q["question_text"].startswith("What is the electron arrangement of magnesium"))
    assert mg["correct_answer"] == "2.8.2"
    mgcl = next(q for q in B.questions("bonding") if q["chemistry"] == {"bond": ["Mg", "Cl"]} and q["focus"] == "formula")
    assert mgcl["correct_answer"] == "MgCl₂"


def test_saving_puts_them_where_play_finds_them(monkeypatch) -> None:
    import app.infra.db as db
    from app.services import question_dna

    saved: dict[str, dict] = {}
    monkeypatch.setattr(db, "fetch_all", lambda sql, p: [{"question_id": i} for i in p["i"] if i in saved])
    monkeypatch.setattr(question_dna.question_dna_service, "save_question", lambda **kw: saved.__setitem__(kw["question_id"], kw))
    out = B.bank("reactions", {"grade": "Grade 10", "subject": "Chemistry", "strand": "Inorganic", "sub_strand": "Reactions"}, 40)
    assert out["saved"] == 40 and all(k.startswith("q-chem-react-") for k in saved)
    one = next(iter(saved.values()))
    assert one["curriculum_link"]["grade"] == "grade-10" and one["content"]["chemistry"]["reactants"]
    assert len({q["content"]["question_text"] for q in saved.values()}) == 40
    assert len({kw["pedagogical_dna"]["focus"] for kw in saved.values()}) >= 4                         # spread across sorts
    assert B.bank("reactions", {"grade": "Grade 10", "subject": "Chemistry", "strand": "Inorganic", "sub_strand": "Reactions"}, 40)["saved"] == 0

"""Chemistry on autopilot: each kind placed where the curriculum teaches it, then saved and booked."""
from __future__ import annotations

from app.services import chem_autopilot as A

ROWS = [   # written as the KICD designs word them
    {"grade": "grade-7", "subject": "Integrated Science", "strand_name": "Mixtures, Elements and Compounds",
     "sub_strand_name": "Mixtures", "slos": ["classify mixtures as homogeneous or heterogeneous",
                                              "describe methods of separating mixtures (filtration, evaporation, distillation, chromatography)"],
     "key_inquiry_questions": ["How can we separate mixtures?"]},
    {"grade": "grade-7", "subject": "Integrated Science", "strand_name": "Mixtures, Elements and Compounds",
     "sub_strand_name": "Acids, Bases and Indicators", "slos": ["classify substances as acids or bases using indicators"],
     "key_inquiry_questions": ["How do we tell an acid from a base?"]},
    {"grade": "grade-9", "subject": "Integrated Science", "strand_name": "Mixtures, Elements and Compounds",
     "sub_strand_name": "Structure of the Atom", "slos": ["describe the structure of the atom", "write the electron arrangement of the first 20 elements",
                                                         "relate the electron arrangement to the position in the periodic table"],
     "key_inquiry_questions": ["What is an atom made of?"]},
    {"grade": "grade-9", "subject": "Integrated Science", "strand_name": "Mixtures, Elements and Compounds",
     "sub_strand_name": "Metals and Alloys", "slos": ["describe the reactions of metals with air, water and acids"],
     "key_inquiry_questions": ["Why are alloys used?"]},
    {"grade": "grade-10", "subject": "Chemistry", "strand_name": "Inorganic Chemistry",
     "sub_strand_name": "Chemical Bonding", "slos": ["explain ionic and covalent bonding", "write chemical formulae of compounds"],
     "key_inquiry_questions": ["Why do atoms bond?"]},
    {"grade": "grade-10", "subject": "Chemistry", "strand_name": "Inorganic Chemistry",
     "sub_strand_name": "Chemical Reactions", "slos": ["write balanced chemical equations", "describe the reactivity series of metals",
                                                      "describe reactions of acids with metals, bases and carbonates"],
     "key_inquiry_questions": ["How do we know a chemical reaction has happened?"]},
    {"grade": "grade-5", "subject": "Science and Technology", "strand_name": "Matter", "sub_strand_name": "Mixtures",
     "slos": ["separate mixtures by sieving and picking"], "key_inquiry_questions": []},
]


def test_each_kind_goes_where_the_curriculum_teaches_it() -> None:
    got = {p["kind"]: (p["grade"], p["subject"], p["sub_strand"]) for p in A.place(ROWS)}
    assert got["separations"] == ("grade-7", "Integrated Science", "Mixtures")          # not Grade 5's sieving
    assert got["atoms"] == ("grade-9", "Integrated Science", "Structure of the Atom")
    assert got["bonding"] == ("grade-10", "Chemistry", "Chemical Bonding")
    assert got["reactions"] == ("grade-10", "Chemistry", "Chemical Reactions")


def test_without_senior_chemistry_the_junior_science_takes_it() -> None:
    junior = [r for r in ROWS if r["subject"] != "Chemistry"]
    got = {p["kind"]: p["sub_strand"] for p in A.place(junior)}
    assert got["reactions"] in ("Metals and Alloys", "Acids, Bases and Indicators")
    assert "bonding" not in got or got["bonding"] != "Mixtures"


def test_nothing_to_place_says_so() -> None:
    assert A.place([]) == []


def test_running_it_saves_books_and_keeps_booking(monkeypatch) -> None:
    from app.services import chem_bank, platform_settings, social_export

    monkeypatch.setattr(A, "_rows", lambda: ROWS)
    saved, filled, settings = [], [], {}
    monkeypatch.setattr(chem_bank, "summary", lambda: {k: {"questions": 1000} for k in chem_bank.KINDS})
    monkeypatch.setattr(chem_bank, "bank", lambda kind, link, n, by="", cap=None: saved.append((kind, link["sub_strand"], n)) or {"saved": n, "already": 0})
    monkeypatch.setattr(social_export, "auto_book_rules", lambda: {"enabled": False, "per_day": 10, "days": 30, "scopes": [], "platforms": ["facebook"]})
    monkeypatch.setattr(social_export, "_scopes_booked_before", lambda: [("grade-6", "Mathematics", "")])
    monkeypatch.setattr(social_export, "month_view", lambda y, m, platforms, per_day: {"days": []})
    monkeypatch.setattr(social_export, "fill_days", lambda days, scopes, **kw: filled.append(scopes) or {"videos": 5, "posts": 5})
    monkeypatch.setattr(social_export, "book_series", lambda *a, **kw: {"photos": 3, "videos": 1, "first_day": "d", "last_day": "e"})
    monkeypatch.setattr(platform_settings, "set_many", lambda values, updated_by="": settings.update(values))
    plan = A.run(dry=True)
    assert plan["dry"] and not saved and len(plan["placements"]) == 4
    out = A.run(keep_booking=True, photo_days=3, by="me")
    assert {k for k, _, _ in saved} == {"separations", "atoms", "bonding", "reactions"}
    assert dict((k, n) for k, _, n in saved) == {"separations": 1000, "atoms": 1000, "bonding": 1000, "reactions": 1000}  # all of each
    assert len(filled) == 2 and ("grade-10", "Chemistry", "Chemical Reactions") in filled[0]      # this month and next
    assert settings["poster_auto_book"] is True
    assert "grade-6|Mathematics|" in settings["poster_auto_book_scopes"]                         # what was booked before stays
    assert "grade-7|Integrated Science|Mixtures" in settings["poster_auto_book_scopes"]
    assert out["photos"] and out["auto_book"]["enabled"]


GENERAL = {"grade": "grade-10", "subject": "General Science", "strand_name": "Chemistry",
           "sub_strand_name": "Acids, Bases and Salts", "slos": ["describe reactions of acids with metals, bases and carbonates",
                                                                 "write balanced chemical equations"], "key_inquiry_questions": []}


def test_chemistry_wins_over_general_science_when_its_design_is_in() -> None:
    got = {p["kind"]: (p["subject"], p["sub_strand"]) for p in A.place(ROWS + [GENERAL])}
    assert got["reactions"] == ("Chemistry", "Chemical Reactions")
    alone = {p["kind"]: p for p in A.place([r for r in ROWS if r["subject"] != "Chemistry"] + [GENERAL])}
    assert alone["reactions"]["subject"] == "General Science"                      # no Chemistry design: the next best
    assert any(o["sub_strand"] == "Acids, Bases and Indicators" for o in alone["reactions"]["options"])   # to choose instead


def test_a_kind_can_be_put_where_you_choose(monkeypatch) -> None:
    from app.services import chem_bank

    monkeypatch.setattr(A, "_rows", lambda: ROWS + [GENERAL])
    monkeypatch.setattr(chem_bank, "summary", lambda: {k: {"questions": 1003} for k in chem_bank.KINDS})
    plan = A.run(dry=True, overrides={"reactions": {"grade": "Grade 7", "subject": "Integrated Science",
                                                    "strand": "Mixtures, Elements and Compounds", "sub_strand": "Acids, Bases and Indicators"}})
    r = next(p for p in plan["placements"] if p["kind"] == "reactions")
    assert (r["grade"], r["sub_strand"], r["questions"]) == ("grade-7", "Acids, Bases and Indicators", 1003)

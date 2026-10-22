"""The separation planner: textbook cases, the catalogue, its questions, the bank."""
from __future__ import annotations

import pytest

from app.services import chem_separation as X


@pytest.mark.parametrize("parts, keep, methods", [
    (["sand", "salt"], "", ["dissolve", "filtration", "evaporation"]),
    (["iron", "sand", "salt"], "", ["magnet", "dissolve", "filtration", "evaporation"]),
    (["salt", "water"], "water", ["distillation"]),
    (["salt", "water"], "", ["evaporation"]),
    (["copper(II) sulphate", "water"], "", ["crystallisation"]),          # hydrated: never evaporated to dryness
    (["sugar", "water"], "", ["crystallisation"]),                        # chars if heated to dryness
    (["oil", "water"], "", ["separating_funnel"]),
    (["ethanol", "water"], "", ["fractional_distillation"]),
    (["petrol", "kerosene"], "", ["fractional_distillation"]),
    (["iodine", "sand"], "", ["sublimation"]),
    (["ammonium chloride", "salt"], "", ["sublimation"]),
    (["sulphur", "sand"], "", ["dissolve", "filtration", "evaporation"]),  # sulphur dissolves in methylbenzene
    (["black ink"], "", ["chromatography"]),
    (["black ink"], "water", ["distillation"]),
    (["sand", "water"], "", ["filtration"]),
    # worked through, however many parts
    (["iron", "sand", "salt", "iodine"], "", ["magnet", "sublimation", "dissolve", "filtration", "evaporation"]),
    (["sawdust", "sand", "salt"], "", ["flotation", "filtration", "evaporation"]),
    (["potassium nitrate", "salt"], "", ["dissolve", "fractional_crystallisation", "evaporation"]),
    (["potassium nitrate", "salt", "sand"], "", ["dissolve", "filtration", "fractional_crystallisation", "evaporation"]),
    (["black ink", "cooking oil"], "", ["separating_funnel", "chromatography"]),
    (["black ink", "salt"], "", ["chromatography", "filtration", "evaporation"]),           # charcoal takes the dyes
    (["cooking oil", "ethanol", "water", "salt"], "", ["separating_funnel", "fractional_distillation"]),
    (["sand", "salt", "water", "iron"], "", ["filtration", "magnet", "evaporation"]),
])
def test_textbook_separations(parts, keep, methods) -> None:
    r = X.separate(parts, keep)
    assert r["covered"] and r["methods"] == methods


def test_each_step_says_what_goes_where_and_why() -> None:
    r = X.separate(["tetrachloromethane", "water"])
    step = r["plan"][0]
    assert step["gives"] == {"lower": "tetrachloromethane", "upper": "water"}       # 1.59 g/cm³ sinks
    assert "denser" in step["why"] and step["look"]["bottom"]["name"] == "tetrachloromethane"
    sulphur = X.separate(["sulphur", "sand"])["plan"][0]
    assert "methylbenzene" in sulphur["text"]
    assert X.separate(["iron", "sulphur"])["steps"][0].startswith("Pass a magnet over the mixture: the iron filings stick")


def test_what_the_rules_do_not_decide_is_not_guessed_and_says_why() -> None:
    assert not X.separate(["marbles", "sand"])["covered"]
    assert "Nothing here parts" in X.separate(["salt", "sugar"])["why"]            # both dissolve in water
    assert "may partly mix" in X.separate(["ethanol", "kerosene"])["why"]
    assert "Nothing here parts the sand and chalk" in X.separate(["sand", "chalk"])["why"]
    assert "all magnetic" in X.separate(["iron", "nickel", "sand"])["why"]


def test_most_mixtures_of_three_and_four_are_decided() -> None:
    import itertools
    import random

    names = sorted(X.SUBSTANCES)
    random.seed(7)
    for n, share in ((3, 0.65), (4, 0.48)):
        sample = random.sample(list(itertools.combinations(names, n)), 1500)
        assert sum(X.separate(list(c))["covered"] for c in sample) / len(sample) > share


def test_the_catalogue_gives_well_over_a_thousand_walkthroughs() -> None:
    mixes = X.catalogue()
    assert len(mixes) > 1000
    assert {m for x in mixes for m in x["methods"]} >= set(X.METHODS)


def test_every_question_has_one_right_answer_among_four() -> None:
    qs = X.all_questions(limit=3000)
    assert len(qs) == 3000
    for q in qs:
        assert len(q["options"]) == 4 and sum(o["is_correct"] for o in q["options"]) == 1
        assert q["correct_answer"] == next(o["text"] for o in q["options"] if o["is_correct"])
        assert X.separate(q["chemistry"]["separate"], q["chemistry"].get("keep", ""))["covered"]
    assert len({q["question_text"] for q in X.all_questions()}) > 1000


def test_a_batch_is_spread_across_methods_and_kinds() -> None:
    batch = X.pick(60)
    assert len(batch) == 60
    assert len({q["focus"] for q in batch}) >= 5
    assert len({tuple(X.separate(q["chemistry"]["separate"])["methods"]) for q in batch}) >= 6


def test_saving_to_the_bank_keeps_ids_and_adds_only_new(monkeypatch) -> None:
    import app.infra.db as db
    from app.services import question_dna

    saved: dict[str, dict] = {}
    monkeypatch.setattr(db, "fetch_all", lambda sql, p: [{"question_id": i} for i in p["i"] if i in saved])
    monkeypatch.setattr(question_dna.question_dna_service, "save_question",
                        lambda **kw: saved.__setitem__(kw["question_id"], kw))
    point = {"grade": "Grade 7", "subject": "Integrated Science", "strand": "Mixtures", "sub_strand": "Separating mixtures"}
    first = X.bank(point, 25)
    assert first["saved"] == 25 and all(k.startswith("q-chem-sep-") for k in saved)
    one = next(iter(saved.values()))
    assert one["status"] == "approved" and one["content"]["chemistry"]["separate"]
    assert one["curriculum_link"] == {**point, "grade": "grade-7"}          # as Play looks it up
    again = X.bank(point, 30)
    assert again == {**again, "saved": 5, "already": 25}


def test_a_separation_walkthrough_is_drawn_with_its_own_substances() -> None:
    from app.services import chem_walkthrough as W

    scenes = W._separation_scenes(["copper(II) oxide", "potassium permanganate"], "")
    sep = [s for s in scenes if s["scene"] == "chem_separation"]
    assert [s["method"] for s in sep] == ["dissolve", "filtration", "evaporation"]
    assert sep[1]["look"]["residue"][0]["name"] == "copper(II) oxide"
    assert sep[1]["look"]["filtrate"]["colour"] == X.SUBSTANCES["potassium permanganate"]["solution"]
    assert scenes[1]["title"] == "What each part is like"

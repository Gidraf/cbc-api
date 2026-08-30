"""A guide has to agree with itself.

A PP1 "Our God" guide scored 97.9 with two plain contradictions in it. Neither
needed a model to find: both halves were the guide's own words.
"""
from __future__ import annotations

from app.services import notes_integrity

DESIGN = [
    "say the name of God in their mother tongue or language of catchment area",
    "use gestures to describe God; Mungu ni mkuu na wa ajabu sana kwamba hawezi "
    "kuonekana kwa macho ya duniani.",
    "sing songs about God in groups",
    "in turns, say what they know about God (loving, creator, and provider)",
    "listen to a recorded clip of a short prayer",
    "say a short prayer to God in groups",
    "sing songs in groups",
]

QUALITIES = "identify three qualities of God"
PRAYERS = "practice saying short prayers"
LOVE = "appreciate God as a loving heavenly father"

FULL = {
    "duration_minutes": 30, "learning_intent": "…", "formative_check": "…",
    "differentiation": {"struggling": "…", "confident": "…", "sne": "…"},
    "key_questions": ["…"], "resources_needed": ["…"],
    "common_misconceptions": [{"misconception": "…"}],
    "citations": [{"ref": "203:26", "claim": "…", "quote": "…"}],
}


def _module(n: int, title: str, slo: str, used: list[str]) -> dict:
    return {**FULL, "module_number": n, "title": f"Lesson {n}: {title}",
            "slos_covered": [slo], "learning_experiences_used": used}


def _guide(**over) -> dict:
    guide = {
        "slo_map": [
            {"slo": QUALITIES, "taught_in": [1, 2], "assessed_in": [2]},
            {"slo": PRAYERS, "taught_in": [3], "assessed_in": [3]},
            {"slo": LOVE, "taught_in": [4], "assessed_in": [4]},
        ],
        "modules": [
            _module(1, "Introducing God", QUALITIES, [DESIGN[0], DESIGN[2]]),
            _module(2, "Qualities of God", QUALITIES, [DESIGN[3]]),
            _module(3, "Practicing Prayer", PRAYERS, [DESIGN[4], DESIGN[5]]),
            _module(4, "God's Love", LOVE, [DESIGN[1], DESIGN[6]]),
        ],
    }
    guide.update(over)
    return guide


# ── the map has to match the modules ────────────────────────────────────────


def test_a_map_naming_a_lesson_that_teaches_something_else_is_caught():
    """`slo_map` said prayer was taught in lesson 4. Lesson 4 is "Appreciating
    God's Love" and no prayer appears in it. A scheme of work is built from the
    map, so a head of department finds this on the first read."""
    guide = _guide()
    guide["slo_map"][1]["taught_in"] = [3, 4]

    findings = notes_integrity.check_slo_map(guide)

    assert any(PRAYERS in f and "lesson 4" in f for f in findings)


def test_a_lesson_in_no_row_of_the_map_is_caught():
    """Lesson 7 appeared in no row. It is funded, so it has to carry an
    outcome or it cannot be justified on the scheme."""
    guide = _guide()
    guide["modules"].append(_module(5, "Celebrating", LOVE, [DESIGN[2]]))

    findings = notes_integrity.check_slo_map(guide)

    assert any("Lesson 5" in f and "no row" in f for f in findings)


def test_a_map_pointing_at_a_lesson_that_does_not_exist_is_caught():
    guide = _guide()
    guide["slo_map"][0]["assessed_in"] = [9]

    assert any("there is no lesson 9" in f
               for f in notes_integrity.check_slo_map(guide))


def test_an_outcome_that_is_never_assessed_is_caught():
    """The design's rubric has a row for it, so a teacher has nothing to fill
    that row from."""
    guide = _guide()
    guide["slo_map"][2]["assessed_in"] = []

    assert any("never assessed" in f
               for f in notes_integrity.check_slo_map(guide))


def test_a_guide_whose_map_matches_its_modules_is_clean():
    assert notes_integrity.check_slo_map(_guide()) == []


# ── learning experiences come from the design, not from the outcomes ────────


def test_an_outcome_listed_as_a_learning_experience_is_caught():
    """Three modules listed "appreciate God as a loving heavenly father" under
    `learning_experiences_used`. That is an OUTCOME. The gate still reported
    "7 of 7 of the design's suggested learning experiences are taught"."""
    guide = _guide()
    guide["modules"][3]["learning_experiences_used"] = [LOVE]

    findings = notes_integrity.check_learning_experiences(guide, DESIGN)

    assert any(LOVE in f and "the design does not suggest it" in f
               for f in findings)


def test_a_shortened_experience_is_accepted():
    """The guide may write "use gestures to describe God" for a bullet that
    runs on into its Swahili gloss. Flagging that would be a false alarm on
    correct work."""
    guide = _guide()
    guide["modules"][3]["learning_experiences_used"] = [
        "use gestures to describe God", DESIGN[6]]

    findings = notes_integrity.check_learning_experiences(guide, DESIGN)

    assert not any("does not suggest" in f for f in findings)


def test_a_design_experience_no_lesson_teaches_is_named():
    guide = _guide()
    guide["modules"][2]["learning_experiences_used"] = [DESIGN[5]]

    findings = notes_integrity.check_learning_experiences(guide, DESIGN)

    assert any(DESIGN[4] in f and "no lesson uses it" in f for f in findings)


def test_with_no_design_to_compare_against_nothing_is_claimed():
    assert notes_integrity.check_learning_experiences(_guide(), []) == []


# ── fields the schema asks for ──────────────────────────────────────────────


def test_a_field_missing_from_every_module_is_reported_once():
    guide = _guide()
    for module in guide["modules"]:
        module.pop("formative_check")

    findings = notes_integrity.check_required_fields(guide)

    assert any("`formative_check`" in f and "every module" in f
               for f in findings)


def test_a_field_missing_from_some_modules_says_how_many():
    guide = _guide()
    guide["modules"][0].pop("key_questions")

    assert any("1 of 4 modules" in f
               for f in notes_integrity.check_required_fields(guide))


# ── the score ───────────────────────────────────────────────────────────────


def test_a_clean_guide_scores_full_marks():
    report = notes_integrity.check(_guide(), DESIGN)

    assert report["clean"]
    assert report["score"] == 100.0


def test_contradictions_cost_the_measured_score():
    from app.services import quality_score

    guide = _guide()
    guide["slo_map"][1]["taught_in"] = [3, 4]
    report = notes_integrity.check(guide, DESIGN)

    scored = quality_score.score(
        {"grounded": True, "source_material_length": 1, "integrity": report},
        "notes")
    consistent = next(c for c in scored.components if c.name == "consistent")

    assert not report["clean"]
    assert consistent.measured and consistent.score < 100


def test_a_station_that_does_not_produce_lessons_is_not_scored_on_this():
    from app.services import quality_score

    scored = quality_score.score({"grounded": True, "source_material_length": 1},
                                 "strands")
    consistent = next(c for c in scored.components if c.name == "consistent")

    assert not consistent.measured


def test_the_notes_station_reports_what_it_was_grounded_in():
    """`grounded` carries the heaviest weight and read "not reported by this
    station" on a run that had just consumed 31,689 characters of the design."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert '"grounded": bool(source_text)' in source
    assert '"source_material_length": len(source_text or "")' in source

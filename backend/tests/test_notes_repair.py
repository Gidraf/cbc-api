"""The defects the PP1 CRE 'Our God' run exposed, held down by tests.

That run produced seven modules between 498 and 798 characters against a
1,500-character floor, and every measurement downstream reported success:
the audit scored 100 for depth, the pedagogical approver 91, and the guide was
stored as artifact v1. The numbers here are that run's own.
"""
from __future__ import annotations

from types import SimpleNamespace

from app.services import notes_coverage, notes_repair
from app.services.dna_scoring import score_notes


def _allocation(modules: int = 7):
    return SimpleNamespace(
        modules=modules, unit="lessons", total_minutes=modules * 30,
        minutes_each=30, stated=f"{modules} lessons",
        phrase=lambda: f"{modules} lessons (30 minutes each)",
    )


def _module(number: int, chars: int) -> dict:
    return {
        "module_number": number,
        "title": f"Lesson {number}",
        "duration_minutes": 30,
        "teacher_exposition": "x" * chars,
        "lesson_flow": [],
    }


def _guide(sizes: list[int]) -> dict:
    return {
        "title": "Teacher's Guide: Our God",
        "intro": "An introduction.",
        "modules": [_module(i, c) for i, c in enumerate(sizes, start=1)],
        "practical_connections": {"safety_precautions": ""},
    }


# ── the floor is now acted on, not logged ────────────────────────────────────


def test_the_run_that_prompted_this_is_still_caught():
    guide = _guide([798, 658, 638, 498, 572, 517, 618])
    coverage = notes_coverage.check(guide, _allocation())

    assert len(coverage.thin_modules) == 7
    assert coverage.percentage == 0
    assert not coverage.complete


def test_a_thin_guide_is_sent_back_and_the_expansion_is_kept():
    guide = _guide([600] * 7)
    coverage = notes_coverage.check(guide, _allocation())

    def generate(config, messages, temperature=0.2):
        return SimpleNamespace(content={"modules": [
            {"module_number": n, "teacher_exposition": "y" * 2_000}
            for n in range(1, 8)
        ]})

    repaired, report = notes_repair.repair(
        guide, coverage, generate=generate, model_config=None,
        base_messages=[{"role": "system", "content": "register"}],
        design_block="Suggested learning experiences:\n- sing songs in groups",
        allocation_phrase="7 lessons", sub_strand="Our God",
    )

    assert report.attempted
    assert report.modules_expanded == [1, 2, 3, 4, 5, 6, 7]
    assert not report.modules_still_thin
    assert notes_coverage.check(repaired, _allocation()).complete


def test_a_repair_that_loses_content_is_discarded():
    """A rewrite shorter than what it replaces is a regression that passes counts."""
    guide = _guide([1_200] * 7)
    coverage = notes_coverage.check(guide, _allocation())

    def generate(config, messages, temperature=0.2):
        return SimpleNamespace(content={"modules": [
            {"module_number": n, "teacher_exposition": "short"} for n in range(1, 8)
        ]})

    repaired, report = notes_repair.repair(
        guide, coverage, generate=generate, model_config=None,
        base_messages=[], design_block="", allocation_phrase="7 lessons",
        sub_strand="Our God",
    )

    assert report.modules_expanded == []
    assert len(repaired["modules"][0]["teacher_exposition"]) == 1_200


def test_the_repair_cannot_invent_a_lesson_the_design_did_not_fund():
    guide = _guide([600] * 7)
    coverage = notes_coverage.check(guide, _allocation())

    def generate(config, messages, temperature=0.2):
        return SimpleNamespace(content={"modules": [
            {"module_number": 8, "teacher_exposition": "z" * 3_000}
        ]})

    repaired, _ = notes_repair.repair(
        guide, coverage, generate=generate, model_config=None,
        base_messages=[], design_block="", allocation_phrase="7 lessons",
        sub_strand="Our God",
    )

    assert len(repaired["modules"]) == 7


def test_a_failed_repair_returns_the_guide_rather_than_losing_it():
    guide = _guide([600] * 7)
    coverage = notes_coverage.check(guide, _allocation())

    def generate(config, messages, temperature=0.2):
        raise TimeoutError("upstream went away")

    repaired, report = notes_repair.repair(
        guide, coverage, generate=generate, model_config=None,
        base_messages=[], design_block="", allocation_phrase="7 lessons",
        sub_strand="Our God",
    )

    assert repaired is guide
    assert "TimeoutError" in report.error


def test_the_repair_carries_the_register_and_faith_scope_forward():
    """Depth produced without them is correct for no grade in particular."""
    guide = _guide([600] * 7)
    coverage = notes_coverage.check(guide, _allocation())
    seen: list[list[dict]] = []

    def generate(config, messages, temperature=0.2):
        seen.append(messages)
        return SimpleNamespace(content={"modules": []})

    notes_repair.repair(
        guide, coverage, generate=generate, model_config=None,
        base_messages=[
            {"role": "system", "content": "LEVEL REGISTER: pre-literate"},
            {"role": "system", "content": "FAITH SCOPE: Christian"},
            {"role": "user", "content": "the original 55k-char instruction"},
        ],
        design_block="", allocation_phrase="7 lessons", sub_strand="Our God",
    )

    carried = " ".join(m["content"] for m in seen[0] if m["role"] == "system")
    assert "pre-literate" in carried and "Christian" in carried
    # The 55k original is not resent; the repair is a focused second call.
    assert "55k-char" not in " ".join(m["content"] for m in seen[0])


# ── the design's own lesson steps ────────────────────────────────────────────


def test_a_dropped_learning_experience_is_named():
    """'listen to a recorded clip of a short prayer' was demoted to an optional
    resource, used by no module, and `gaps` came back empty."""
    experiences = [
        "sing songs about God in groups",
        "listen to a recorded clip of a short prayer",
    ]
    guide = _guide([2_000] * 7)
    guide["modules"][0]["learning_experiences_used"] = ["sing songs about God in groups"]

    coverage = notes_coverage.check(guide, _allocation(), experiences=experiences)

    assert coverage.experiences_unused == ["listen to a recorded clip of a short prayer"]
    assert not coverage.complete


def test_an_experience_the_guide_actually_teaches_is_not_flagged():
    experiences = ["say the name of God in their mother tongue or language of catchment area"]
    guide = _guide([100] * 7)
    guide["modules"][0]["teacher_exposition"] = (
        "Ask the learners to say the name of God in their own mother tongue, "
        "or in the language of the catchment area around the school."
    )

    coverage = notes_coverage.check(guide, _allocation(), experiences=experiences)
    assert coverage.experiences_unused == []


def test_the_repair_names_the_dropped_step_and_asks_for_it_verbatim():
    guide = _guide([2_000] * 7)
    coverage = notes_coverage.check(
        guide, _allocation(),
        experiences=["listen to a recorded clip of a short prayer"],
    )
    seen: list[str] = []

    def generate(config, messages, temperature=0.2):
        seen.append(messages[-1]["content"])
        return SimpleNamespace(content={"modules": []})

    notes_repair.repair(
        guide, coverage, generate=generate, model_config=None, base_messages=[],
        design_block="", allocation_phrase="7 lessons", sub_strand="Our God",
    )

    assert "listen to a recorded clip of a short prayer" in seen[0]
    assert "VERBATIM" in seen[0]


# ── the measurements that reported success on a failing guide ────────────────


def test_depth_is_measured_over_the_body_and_not_the_duplication():
    """The route mirrors `modules` into `hour_modules`; flattening counts both."""
    guide = _guide([600] * 7)
    guide["hour_modules"] = guide["modules"]

    scores = score_notes(guide, [], grade_ordinal=1, raw_source="")
    depth = scores.scores["content_depth"]

    assert depth.method == "body_chars_vs_module_floor"
    # 4,200 real characters against 7 x 1,500 — not a pass.
    assert depth.value < 0.5


def test_grounding_no_longer_punishes_a_guide_for_staying_in_scope():
    """The design section holds five strands; this guide covers one sub-strand."""
    design = (
        "1.1 Our God: say the name of God in their mother tongue, sing songs "
        "about God in groups, say a short prayer to God in groups. "
        "2.1 A Holy Book: select the Holy Bible from other books. "
        "2.2 David and Goliath: retell the story of David and Goliath. "
        "3.1 The Birth of Jesus Christ: observe drawn pictures of the parents. "
        "4.2 Love for Neighbour: say the names of their deskmates. "
        "5.2 Church Activities: dramatize activities they do in church."
    )
    guide = _guide([10] * 7)
    guide["modules"][0]["teacher_exposition"] = (
        "Learners say the name of God in their mother tongue and sing songs "
        "about God in groups, then say a short prayer to God in groups."
    )

    off_design = _guide([10] * 7)
    off_design["modules"][0]["teacher_exposition"] = (
        "Learners calculate the lime tonnage required to correct soil pH across "
        "a hectare of Embu county farmland, then tabulate the agricultural GDP."
    )

    grounded = score_notes(guide, [], grade_ordinal=1, raw_source=design)
    ungrounded = score_notes(off_design, [], grade_ordinal=1, raw_source=design)

    assert grounded.scores["source_grounding"].method == "notes_term_containment_in_design"
    # Symmetric Jaccard scored the in-scope guide 0.20 — it was punished for
    # every word of the eleven sub-strands it correctly left out — and the
    # compliance approver rejected the run on that number. What matters is that
    # the measure now separates a grounded guide from an invented one.
    assert grounded.scores["source_grounding"].value > 0.65
    assert ungrounded.scores["source_grounding"].value < 0.5


def test_the_teachers_guide_is_not_scored_against_a_four_year_olds_reading_level():
    guide = _guide([10] * 7)
    guide["modules"][0]["teacher_exposition"] = (
        "Gather the learners in a circle before you begin the lesson. "
        "Hold up the picture card and wait until every child is looking at it. "
        "Ask the first question slowly, then pause and count to five silently."
    )

    scores = score_notes(guide, [], grade_ordinal=1, raw_source="")
    fit = scores.scores["reading_level_fit"]

    assert fit.method == "sentence_length_vs_teacher_band"
    assert fit.value > 0.75


def test_what_is_said_to_the_child_is_still_scored_against_the_child():
    guide = _guide([10] * 7)
    guide["modules"][0]["key_questions"] = [
        "Who made you?", "What is God like?", "How do we say thank you?",
    ]

    scores = score_notes(guide, [], grade_ordinal=1, raw_source="")
    fit = scores.scores["learner_language_fit"]

    assert fit.method == "sentence_length_vs_grade_band"
    assert fit.value is not None

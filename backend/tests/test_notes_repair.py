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


# ── the review cycle must chase something achievable ────────────────────────


def test_grounding_a_guide_means_teaching_the_designs_own_lesson():
    """Term overlap scored a sound guide 0.37 — a guide is mostly pedagogy,
    none of which is in the design and none of which should be. Worse, the
    number named nothing to do, so three review cycles went 78 -> 83 -> 79
    chasing it."""
    from app.services.dna_scoring import score_notes

    experiences = [
        "say the name of God in their mother tongue or language of catchment area",
        "sing songs about God in groups",
        "listen to a recorded clip of a short prayer",
    ]
    guide = {
        "title": "Teacher's Guide: Our God",
        "modules": [{
            "module_number": 1,
            "teacher_exposition": (
                "Ask each learner to say the name of God in their own mother tongue, "
                "or the language of the catchment area. Then sing songs about God in "
                "groups. Play the recorded clip of a short prayer and let them listen."
            ),
            "lesson_flow": [],
        }],
    }

    scored = score_notes(guide, [], grade_ordinal=1, raw_source="unrelated design text",
                         experiences=experiences)
    grounding = scored.scores["source_grounding"]

    assert grounding.method == "design_experiences_taught"
    assert grounding.value == 1.0


def test_a_dropped_experience_makes_the_finding_actionable():
    """"Improve source grounding" names nothing to do. "You did not teach:
    listen to a recorded clip of a short prayer" does."""
    from app.services.dna_scoring import score_notes

    experiences = ["sing songs about God in groups",
                   "listen to a recorded clip of a short prayer"]
    guide = {"modules": [{"teacher_exposition": "Sing songs about God in groups.",
                          "lesson_flow": []}]}

    grounding = score_notes(guide, [], 1, "", experiences=experiences).scores["source_grounding"]

    assert grounding.value == 0.5
    assert "recorded clip of a short prayer" in grounding.evidence


def test_a_revision_directive_is_not_a_search_query():
    """On a review cycle `custom_instructions` carries the whole revision block,
    and it went into the web search string and then into the stored dossier."""
    from app.services.web_research import web_research_agent

    directive = (
        "=== REVISION 2: WHAT THE REVIEW FOUND ===\n"
        "The previous version of this content scored 83/100 and did not pass "
        "the quality gate. Fix these, in this order: 1. Improve source grounding"
    )
    queries = web_research_agent._generate_search_queries(
        "Christian Religious Education", "Creation", "Our God",
        "grade-pp1", "notes", directive,
    )

    assert all("===" not in q for q in queries)
    assert all(len(q) < 200 for q in queries)


# ── a lesson written as topics, not as one block ────────────────────────────


def _topic_module(number: int, segments: list[tuple[str, int, str]]):
    return {
        "module_number": number,
        "title": f"Lesson {number}",
        "duration_minutes": 30,
        "teacher_exposition": "Two sentences framing the lesson.",
        "lesson_flow": [],
        "exposition_segments": [
            {"topic": topic, "body": "x" * chars, "bridge": bridge}
            for topic, chars, bridge in segments
        ],
    }


def test_topics_of_450_clear_a_floor_the_single_instruction_never_did():
    """Asked for 1,500 characters in one go the model produced about a
    thousand and stopped — across a repair pass and three review cycles. Asked
    for four topics of four hundred, it writes four topics of four hundred."""
    guide = {"modules": [_topic_module(1, [
        ("Saying God's name", 470, "Now they can name Him."),
        ("The Kiswahili phrase", 460, "Next, the gestures."),
        ("Gestures for greatness", 480, "Now they can show it."),
        ("Putting it together", 300, "This leads into lesson 2."),
    ])]}

    body = notes_coverage._body_of(guide["modules"][0])
    assert len(body) > notes_coverage.MIN_BODY_CHARS

    coverage = notes_coverage.check(guide, _allocation(1))
    assert coverage.thin_modules == []


def test_a_module_written_as_one_block_is_still_reported():
    guide = {"modules": [{"module_number": 1, "teacher_exposition": "x" * 900,
                          "lesson_flow": []}]}
    coverage = notes_coverage.check(guide, _allocation(1))

    assert coverage.modules_without_topics == [1]
    assert len(coverage.thin_modules) == 1


def test_a_topic_that_is_a_heading_with_a_sentence_is_named():
    """"Write more" is not actionable. "Topic 2 is 120 characters and should be
    450" is."""
    guide = {"modules": [_topic_module(1, [
        ("Saying God's name", 470, "Now they can name Him."),
        ("The Kiswahili phrase", 120, "Next, gestures."),
        ("Gestures", 90, "This leads to lesson 2."),
    ])]}
    coverage = notes_coverage.check(guide, _allocation(1))

    named = {t["topic"] for t in coverage.thin_topics}
    assert named == {"The Kiswahili phrase", "Gestures"}
    assert all(t["target"] == notes_coverage.SEGMENT_TARGET_CHARS
               for t in coverage.thin_topics)


def test_a_topic_with_no_handover_is_reported():
    """A lesson that is four disconnected paragraphs is not a lesson — the
    teacher reads them in order and the children live through them in order."""
    guide = {"modules": [_topic_module(1, [
        ("First", 460, "hands over"),
        ("Second", 460, ""),
        ("Third", 460, "leads to lesson 2"),
    ])]}
    coverage = notes_coverage.check(guide, _allocation(1))

    assert [b["topic"] for b in coverage.broken_handovers] == ["Second"]


def test_the_repair_names_the_short_topic_rather_than_the_module():
    """A short topic is a small, bounded thing to fix. A short module is not,
    which is why asking for the module to be longer had not worked."""
    guide = {"modules": [_topic_module(1, [
        ("Saying God's name", 430, "Now they can name Him."),
        ("The Kiswahili phrase", 120, "Next, gestures."),
    ])]}
    coverage = notes_coverage.check(guide, _allocation(1))
    seen: list[str] = []

    def generate(config, messages, temperature=0.2):
        seen.append(messages[-1]["content"])
        return SimpleNamespace(content={"modules": []})

    notes_repair.repair(
        guide, coverage, generate=generate, model_config=None, base_messages=[],
        design_block="", allocation_phrase="7 lessons", sub_strand="Our God",
    )

    assert 'topic 2 "The Kiswahili phrase" is only 120 characters' in seen[0]
    assert "Work topic by topic" in seen[0]


def test_the_prompt_asks_for_topics_with_handovers():
    import inspect

    import app.routes.curriculum as routes

    source = inspect.getsource(routes.factory_generate_notes)
    assert "WRITE EACH LESSON AS TOPICS, NOT AS ONE BLOCK" in source
    assert "exposition_segments" in source
    assert "THE TOPICS MUST JOIN UP" in source
    # And it explains why, because a rule without a reason gets optimised away.
    assert "One long passage comes out shallow" in source


# ── analogies are a teaching device; claims are not ─────────────────────────


_DESIGN_WITH_SCRIPTURE = (
    "206:37 watch or listen to the Bible story in; Mark 10:13-16. "
    "200:13 Proverbs 22:6 which states"
)


def _claim_guide(text: str) -> dict:
    return {"modules": [{"module_number": 1, "teacher_exposition": text}]}


def test_an_analogy_is_never_treated_as_a_claim():
    """"God cares for you the way your mother does" is exactly the right
    teaching of a four-year-old, and it asserts nothing about the world."""
    from app.services.fabrication_check import check

    report = check(_claim_guide(
        "Say: 'God loves you just like your mother loves you when she gives "
        "you food.' Imagine a time you felt safe. Think of the way rain helps "
        "plants grow. Just like when you share 2 out of 3 sweets with a friend."
    ), _DESIGN_WITH_SCRIPTURE)

    assert report.clean, [f.to_dict() for f in report.findings]
    assert report.score == 100


def test_a_scripture_the_design_never_names_is_caught():
    """A teacher will read an invented chapter and verse aloud to a class."""
    from app.services.fabrication_check import check

    report = check(_claim_guide("Read John 3:16 to the children."), _DESIGN_WITH_SCRIPTURE)

    assert not report.clean
    kinds = {f.kind for f in report.findings}
    assert kinds == {"invented_scripture"}
    # And it says what the design DOES carry, so the fix is obvious.
    assert "Mark 10:13" in report.findings[0].text


def test_the_designs_own_scripture_passes():
    from app.services.fabrication_check import check

    report = check(
        _claim_guide("Watch or listen to the Bible story in Mark 10:13-16."),
        _DESIGN_WITH_SCRIPTURE,
    )
    assert report.clean


def test_a_leaked_statistic_is_caught():
    """Every statistic this pipeline has produced came from the dossier's own
    unverified figures."""
    from app.services.fabrication_check import check

    report = check(
        _claim_guide("Studies show 75% of Kenyan children pray daily."),
        _DESIGN_WITH_SCRIPTURE,
    )
    assert {f.kind for f in report.findings} == {"invented_statistic"}


def test_an_authority_nobody_retrieved_is_caught():
    from app.services.fabrication_check import check

    report = check(
        _claim_guide("According to the KNBS 2023 Survey, engagement is high."),
        _DESIGN_WITH_SCRIPTURE, has_sources=False,
    )
    assert {f.kind for f in report.findings} == {"invented_authority"}


def test_invention_counts_against_the_measured_score():
    from app.services.quality_score import WEIGHTS, score

    assert round(sum(WEIGHTS.values()), 3) == 1.0

    scored = score({
        "grounded": True, "source_material_length": 31689,
        "fabrication": {"checked_chars": 5000, "score": 50.0,
                        "findings": [{"kind": "invented_scripture"},
                                     {"kind": "invented_statistic"}]},
    }, "notes")

    invention = scored.scores["no_invention"] if hasattr(scored, "scores") else None
    assert scored.weakest == "no_invention"
    assert invention is None or invention.value == 50.0


def test_the_prompt_draws_the_line_between_analogy_and_claim():
    import inspect

    import app.routes.curriculum as routes

    source = inspect.getsource(routes.factory_generate_notes)
    assert "ANALOGIES YES, INVENTION NO" in source
    assert "NEVER cite a scripture reference the design does not name" in source
    assert "NEVER state a statistic" in source
    # Topic count follows the material rather than a fixed number.
    assert "Let the material decide" in source


def test_every_reviewer_is_told_to_check_the_claims():
    from app.services import review_layers

    artifact = type("A", (), {"kind": "notes", "grade": "grade-pp1",
                              "subject": "CRE", "strand_name": "Creation",
                              "sub_strand_name": "Our God", "version": 1,
                              "content": {}})()
    for layer in (1, 2, 3):
        system = review_layers.build_messages(artifact, layer)[0]["content"]
        assert "CHECK EVERY CLAIM AGAINST THE DESIGN" in system, layer
        assert "survives inspection" in system, layer

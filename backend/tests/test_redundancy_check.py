"""Padding is the defect a reviewer misses most reliably.

Layer 2 passed a PP1 "Our God" guide at 90% whose lessons 5 and 6 shared two
verbatim exposition segments, an identical misconception, identical
differentiation, an identical formative check and identical homework. Its one
reported issue was that a resource list had got shorter.

It missed it because it read forwards. Lesson 6 is fine on its own; it is only
wrong beside lesson 5.
"""
from __future__ import annotations

from app.services import redundancy_check

SINGING = (
    "Guide learners to sing a song that emphasizes God's love for children. "
    "Choose a song like 'Jesus Loves Me' or 'God is So Good.' Encourage them "
    "to use gestures while singing to make it more engaging."
)
APPRECIATION = (
    "Encourage learners to share ways they can show appreciation to God, such "
    "as through prayer, kindness, and love for others. You might say, 'How can "
    "we show God we love Him back?'"
)
MISCONCEPTION = [{
    "misconception": "Learners may think God's love is distant or abstract.",
    "why_it_happens": "They might not connect it to their everyday experiences.",
    "how_to_correct_it": "Use relatable examples from their lives.",
}]


def _lesson(n: int, title: str, opening: str, segments: list[str],
            **over) -> dict:
    module = {
        "title": f"Lesson {n}: {title}",
        "module_number": n,
        "formative_check": "Observe if learners can express ways to appreciate God.",
        "homework_or_follow_up": "Ask learners to think of one way to show appreciation.",
        "common_misconceptions": MISCONCEPTION,
        "exposition_segments": [
            {"topic": "Opening", "body": opening, "minutes": 10},
            *[{"topic": f"Part {i + 2}", "body": b, "minutes": 10}
              for i, b in enumerate(segments)],
        ],
    }
    module.update(over)
    return module


def _guide(mirror: bool = False) -> dict:
    modules = [
        _lesson(5, "Appreciating God's Love",
                "Begin by discussing how God shows His love to us. Ask learners "
                "how their parents care for them and relate it to God's care.",
                [SINGING, APPRECIATION]),
        _lesson(6, "God's Love in Action",
                "Begin by discussing how learners can recognize God's love in "
                "their daily lives. Ask them to share a time they felt it.",
                [SINGING, APPRECIATION]),
        _lesson(3, "Talking to God",
                "Begin by explaining what prayer is in simple terms: prayer is "
                "talking to God, just like you talk to your parents.",
                ["Play a recorded clip of a short prayer and ask the learners "
                 "what the prayer thanked God for and how it made them feel."]),
    ]
    guide = {"title": "Our God", "modules": modules}
    if mirror:
        # NOT `hour_modules` — that pair is a deliberate alias this pipeline
        # keeps for older readers, and is excluded by name.
        guide["lessons"] = modules
    return guide


# ── what it finds ───────────────────────────────────────────────────────────


def test_the_two_padded_lessons_are_named():
    report = redundancy_check.inspect(_guide())
    pairs = {(p["a"], p["b"]) for p in report["near_duplicates"]}

    assert ("Lesson 5: Appreciating God's Love",
            "Lesson 6: God's Love in Action") in pairs


def test_it_says_which_fields_were_copied_word_for_word():
    report = redundancy_check.inspect(_guide())
    fields = set(report["near_duplicates"][0]["identical_fields"])

    assert {"formative_check", "homework_or_follow_up",
            "common_misconceptions"} <= fields


def test_a_shared_exposition_block_is_reported_with_both_lessons():
    report = redundancy_check.inspect(_guide())
    shared = [s for s in report["repeated_segments"]
              if "sing a song" in s["excerpt"]]

    assert shared, "the verbatim singing segment was not detected"
    assert len(shared[0]["places"]) == 2


def test_lessons_on_different_topics_are_not_flagged():
    """The check has to survive normal overlap: lessons in one sub-strand share
    a register, a vocabulary and a subject by design."""
    report = redundancy_check.inspect(_guide())
    named = {p["a"] for p in report["near_duplicates"]} | \
            {p["b"] for p in report["near_duplicates"]}

    assert not any("Talking to God" in n for n in named)


DISTINCT = [
    ("Saying God's Name",
     "Ask the learners what God is called in the language spoken at home. Let "
     "each child say the name aloud and hear the others say theirs."),
    ("Talking to God",
     "Explain that prayer is talking to God, the way they talk to a parent. "
     "Play the recorded prayer and ask what it thanked God for."),
    ("Praying Together",
     "In small groups the children take turns finishing the sentence 'Dear "
     "God, thank you for'. Nobody is corrected; every ending is accepted."),
    ("God Made Everything",
     "Take the class outside. Ask them to point at something nobody built — a "
     "tree, a cloud, an ant — and name it for the others."),
    ("God Gives Us What We Need",
     "Lay out a cup of water, a plate and a blanket. Ask who provides each "
     "one at home, then who provides the rain that filled the cup."),
    ("Being Kind Like God",
     "Act out two short scenes: a child sharing a mango, and a child helping "
     "another who has fallen. Ask which one they did this week."),
    ("Singing What We Learned",
     "Close the sub-strand with the songs from the earlier lessons, sung "
     "through once each, with the gestures the class invented for them."),
]


def test_a_guide_with_genuinely_distinct_lessons_is_clean():
    modules = [
        _lesson(n, title, opening,
                [f"The children then {title.lower()} in pairs while the "
                 f"teacher moves between the groups and listens."],
                formative_check=f"Can each child {title.lower()} unprompted?",
                homework_or_follow_up=f"At home, {title.lower()} with a parent.",
                common_misconceptions=[{"misconception": f"Some think {title.lower()} is only for adults."}])
        for n, (title, opening) in enumerate(DISTINCT, start=1)
    ]
    report = redundancy_check.inspect({"modules": modules})

    assert report["clean"], report["near_duplicates"]
    assert redundancy_check.render(report) == ""


def test_templated_lessons_that_differ_only_by_a_topic_word_are_flagged():
    """Not a false positive. A lesson set generated by filling one template
    seven times is seven copies of one lesson, and reads that way to a class."""
    modules = [
        _lesson(n, f"Topic {n}",
                f"Opening exposition about topic {n}, which covers material "
                f"specific to lesson {n} and nothing else.",
                [f"A second block of teaching, again about subject matter {n}."])
        for n in range(1, 8)
    ]
    report = redundancy_check.inspect({"modules": modules})

    assert not report["clean"]


# ── the mirrored payload ────────────────────────────────────────────────────


def test_the_mirrored_lesson_list_is_reported():
    """`modules` and `hour_modules` held the same seven lessons, which doubled
    the artifact past the reviewer's truncation limit — so it was told the tail
    was missing when the tail was a copy of the head."""
    report = redundancy_check.inspect(_guide(mirror=True))

    assert report["mirrors"]
    assert {report["mirrors"][0]["a"], report["mirrors"][0]["b"]} == \
           {"modules", "lessons"}


def test_a_mirrored_list_is_not_compared_against_itself():
    """Otherwise every finding is reported twice, and lesson 5 is reported as a
    100% duplicate of lesson 5."""
    plain = redundancy_check.inspect(_guide())
    mirrored = redundancy_check.inspect(_guide(mirror=True))

    assert len(mirrored["near_duplicates"]) == len(plain["near_duplicates"])
    assert not any(p["a"] == p["b"] for p in mirrored["near_duplicates"])


# ── what the reviewer is told ───────────────────────────────────────────────


def test_the_block_distinguishes_padding_from_deliberate_repetition():
    """A song sung in three lessons is how a four-year-old learns it. The same
    teacher exposition delivered as new teaching is padding. The reviewer has
    to be told to tell them apart rather than to report every repeat."""
    rendered = redundancy_check.render(redundancy_check.inspect(_guide()))

    assert "Repetition is sometimes right" in rendered
    assert "padded to fill an allocation" in rendered


def test_the_reviewer_receives_the_measurement():
    from app.services import review_layers

    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "Creation", "sub_strand_name": "Our God", "version": 4,
        "content": _guide(mirror=True),
    })()
    user = review_layers.build_messages(artifact, 2)[1]["content"]

    assert "=== REPETITION IN THIS ARTIFACT, ALREADY MEASURED ===" in user
    assert "MIRRORED" in user
    assert "Lesson 6: God's Love in Action" in user


def test_the_pipelines_own_alias_is_not_reported_as_padding():
    """The notes station mirrors `modules` into `hour_modules` for readers
    written against the older name. Reporting that blames the model for
    something we do, and a regeneration cannot fix it — we put it back every
    time, so the finding would return on every version for ever."""
    guide = _guide()
    guide["hour_modules"] = guide["modules"]
    report = redundancy_check.inspect(guide)

    assert not report["mirrors"]
    assert report["aliases"]
    assert not any("hour_modules" in f for f in report["findings"])


def test_the_alias_is_stripped_before_the_artifact_reaches_a_reviewer():
    """Sending both copies doubled the guide and pushed it past the truncation
    limit, so the reviewer was told the tail was missing when the tail was a
    copy of the head."""
    from app.services import review_layers

    guide = _guide()
    guide["hour_modules"] = guide["modules"]
    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "", "sub_strand_name": "", "version": 1,
        "content": guide,
    })()
    user = review_layers.build_messages(artifact, 2)[1]["content"]

    assert '"hour_modules"' not in user
    assert '"modules"' in user


def test_a_clean_artifact_gets_no_block():
    from app.services import review_layers

    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "", "sub_strand_name": "", "version": 1,
        "content": {"modules": [_lesson(1, "Only", "One lesson here.", [])]},
    })()
    user = review_layers.build_messages(artifact, 2)[1]["content"]

    assert "REPETITION IN THIS ARTIFACT" not in user


# ── the finding survives the reviewer not noticing ──────────────────────────


def test_the_reviewer_is_required_to_report_it():
    """Being shown a measurement is not enough. The reviewer was shown resolved
    citations, told to judge whether the quote matched, and wrote "the citation
    is correctly used" about an invented sentence. So the obligation is stated
    as an obligation."""
    from app.services import review_layers

    artifact = type("A", (), {"kind": "notes", "grade": "grade-pp1",
                              "subject": "CRE", "strand_name": "",
                              "sub_strand_name": "", "version": 1,
                              "content": {}})()
    system = review_layers.build_messages(artifact, 2)[0]["content"]

    assert "CHECK THE LESSONS AGAINST EACH OTHER" in system
    assert "you MUST raise it in `issues` naming the lessons" in system
    assert "Repeating an ACTIVITY is not the defect" in system


def test_repetition_counts_against_the_measured_score():
    """A duplicated lesson clears every length check there is, so it has to
    cost something that is not a reviewer's opinion."""
    from app.services import quality_score

    padded = quality_score.score(
        {"grounded": True, "source_material_length": 1,
         "repetition": redundancy_check.inspect(_guide(mirror=True))}, "notes")
    clean = quality_score.score(
        {"grounded": True, "source_material_length": 1,
         "repetition": {"checked": True, "score": 100.0, "findings": []}},
        "notes")

    distinct = next(c for c in padded.components if c.name == "distinct")

    assert padded.score < clean.score
    assert distinct.measured and distinct.score < 100


def test_the_findings_tell_a_regeneration_what_to_do():
    report = redundancy_check.inspect(_guide(mirror=True))
    joined = " ".join(report["findings"])

    assert "Emit the lessons once." in joined
    assert "Rewrite it to teach something the earlier lesson does not" in joined


def test_a_measured_defect_reaches_the_regeneration_without_a_reviewer():
    """Reviewers miss comparison defects. The directive block must not depend
    on one having noticed."""
    from app.services import revision_directives

    built = revision_directives.build(
        reviews=[], comments=None,
        measured=redundancy_check.inspect(_guide())["findings"],
    )

    assert "MEASURED DEFECTS" in built["directives"]
    assert "Lesson 6: God's Love in Action" in built["directives"]
    assert built["measured"]


def test_no_measured_defects_leaves_the_directive_block_empty():
    from app.services import revision_directives

    assert revision_directives.build([], None, measured=[])["directives"] == ""


# ── the score has to scale with the artifact ────────────────────────────────


def _padded_set(n_total: int, n_padded: int) -> dict:
    """`n_total` lessons of which `n_padded` are copies of lesson 1."""
    original = _lesson(1, DISTINCT[0][0], DISTINCT[0][1], [SINGING])
    modules = [original]
    for i in range(n_padded):
        copy = _lesson(2 + i, DISTINCT[0][0], DISTINCT[0][1], [SINGING])
        modules.append(copy)
    words = ["mango", "river", "goat", "drum", "basket", "shamba", "matatu",
             "jiko", "sisal", "acacia", "millet", "calabash", "kanga",
             "boda", "hibiscus", "papyrus", "tilapia", "baobab", "cassava",
             "guava", "sorghum", "flamingo", "pawpaw", "ugali", "njugu",
             "mbuzi", "kibanda", "shuka", "ngoma", "chapati"]
    # Filler that is genuinely distinct, so the test measures the scorer and
    # not the fixture. Varying only a noun inside one template produces lessons
    # that ARE 81% identical — a true finding about the fixture — so the
    # sentence shape varies too.
    shapes = [
        ("Bring a {w} to the front of the class. Ask the children what it is "
         "for, who in their home uses one, and what would be different if "
         "there were none in the village.",
         "The children draw one and tell a partner something about it.",
         "Can the child name a use for a {w}?"),
        ("Sit the class in a circle and pass a {w} from hand to hand without "
         "speaking. When it has gone all the way round, ask what they "
         "noticed with their fingers rather than their eyes.",
         "Each child says one word for how it felt to hold.",
         "Does the child use a describing word unprompted?"),
        ("Sing the counting song, clapping once for every {w} the teacher "
         "holds up. Stop at four and ask whether anyone can hear the "
         "difference between three claps and four.",
         "In pairs they clap a number for each other to guess.",
         "Can the child clap a number between one and five?"),
        ("Walk the class to the edge of the compound and look for a {w}. "
         "Nobody picks anything up. Back inside, ask who saw one and where, "
         "and let two children point on the way past the window.",
         "They model what they saw in clay while it is fresh.",
         "Can the child say where the thing was?"),
        ("Act out a short scene in which one child has a {w} and another has "
         "none. Play it twice, once ending in sharing and once not, and ask "
         "the watching children which ending they liked.",
         "Two volunteers act it a third time with their own ending.",
         "Does the child give a reason for the ending they chose?"),
    ]
    for i in range(n_total - 1 - n_padded):
        w = words[i % len(words)]
        opening, follow, check = shapes[i % len(shapes)]
        modules.append(_lesson(
            100 + i, f"The {w} lesson", opening.format(w=w),
            [f"{follow} They use the {w} from the opening."],
            formative_check=check.format(w=w),
            homework_or_follow_up=f"Find a {w} at home and count how many.",
            common_misconceptions=[{"misconception": f"Every {w} is the same."}]))
    return {"modules": modules}


def test_the_same_two_copies_cost_less_in_a_longer_guide():
    """A flat per-defect penalty scored both at zero. Two duplicates among
    seven lessons leaves five that teach; two among three leaves one."""
    long_guide = redundancy_check.inspect(_padded_set(7, 2))["score"]
    short_guide = redundancy_check.inspect(_padded_set(3, 2))["score"]

    assert long_guide > 65
    assert short_guide < 40


def test_the_lesson_that_was_copied_is_not_charged_for_being_copied():
    """Lesson 1 is the real lesson. Only the copy is waste, so seven lessons
    with one copy is six sevenths distinct, not five sevenths."""
    assert redundancy_check.inspect(_padded_set(7, 1))["score"] == 85.7


def test_a_guide_of_distinct_lessons_scores_full_marks_at_any_length():
    assert redundancy_check.inspect(_padded_set(3, 0))["score"] == 100.0
    assert redundancy_check.inspect(_padded_set(7, 0))["score"] == 100.0


def test_a_mirror_is_a_flat_cost():
    """It wastes the reviewer's context window, not the class's time, so it
    does not scale with the lesson count."""
    mirrored = _padded_set(7, 0)
    mirrored["lessons"] = mirrored["modules"]

    assert redundancy_check.inspect(mirrored)["score"] == 85.0


def test_the_alias_costs_nothing():
    aliased = _padded_set(7, 0)
    aliased["hour_modules"] = aliased["modules"]

    assert redundancy_check.inspect(aliased)["score"] == 100.0


# ── the same lesson, rewritten rather than copied ───────────────────────────

TEMPLATE = [
    ("Appreciating God's Love", LOVE_REF := "203:22", [
        ("God's Love as a Father",
         "Begin by discussing how a father cares for his children. Ask the "
         "children, 'How does your father show you love?' Relate this to God's "
         "love by saying, 'Just like your fathers care for you, God cares for "
         "you even more.'"),
        ("Expressing Love Through Gestures",
         "Guide the children to create gestures that represent God's love. Say, "
         "'Let's hug ourselves to show how God embraces us.' Encourage them to "
         "share their gestures with the class."),
        ("Singing a Song of Appreciation",
         "Choose a song that expresses appreciation for God's love, such as "
         "'Jesus Loves Me.' Teach it by singing first, then encouraging them "
         "to join in."),
    ]),
    ("God's Provision", "203:22", [
        ("Understanding God's Provision",
         "Begin by discussing how parents provide for their children. Ask, "
         "'What do your parents provide for you?' Relate this to God's "
         "provision by saying, 'Just as your parents care for you, God "
         "provides for all your needs.'"),
        ("Expressing Gratitude Through Gestures",
         "Guide the children to create gestures that represent gratitude. Say, "
         "'Let's place our hands over our hearts to show appreciation.' "
         "Encourage them to share their gestures with the class."),
        ("Singing a Song of Gratitude",
         "Choose a song that expresses gratitude for God's provision, such as "
         "'Thank You, Lord.' Teach it by singing first, then encouraging them "
         "to join in."),
    ]),
    ("God's Care", "203:22", [
        ("Understanding God's Care",
         "Begin by discussing how parents care for their children. Ask, 'How "
         "do your parents show they care for you?' Relate this to God's care "
         "by saying, 'Just as your parents care for you, God cares for you in "
         "every situation.'"),
        ("Expressing Appreciation Through Gestures",
         "Guide the children to create gestures that represent appreciation "
         "for God's care. Say, 'Let's place our hands together in a prayer "
         "position.' Encourage them to share their gestures."),
        ("Singing a Song of Appreciation",
         "Choose a song that expresses appreciation for God's care, such as "
         "'He's Got the Whole World in His Hands.' Teach it by singing first."),
    ]),
]

LOVE = "appreciate God as a loving heavenly father"


def _templated() -> dict:
    modules = [
        {"title": f"Lesson {n}: {title}", "module_number": n,
         "slos_covered": [LOVE],
         "citations": [{"ref": ref, "claim": "c", "quote": "q"}],
         "exposition_segments": [
             {"topic": t, "body": b, "minutes": 10} for t, b in segs]}
        for n, (title, ref, segs) in enumerate(TEMPLATE, start=4)
    ]
    modules.insert(0, {
        "title": "Lesson 3: Practicing Prayer", "module_number": 3,
        "slos_covered": ["practice saying short prayers"],
        "citations": [{"ref": "203:21", "claim": "c", "quote": "q"}],
        "exposition_segments": [
            {"topic": "Understanding Prayer", "minutes": 10,
             "body": "Begin by explaining what prayer is in simple terms. Say, "
                     "'Prayer is talking to God, just like you talk to your "
                     "parents.' Ask whether they have ever talked to God."},
            {"topic": "Listening to a Recorded Prayer", "minutes": 10,
             "body": "Play a recorded clip of a short prayer. After listening, "
                     "ask the children what they liked about it and how it "
                     "made them feel."},
            {"topic": "Saying Short Prayers in Groups", "minutes": 10,
             "body": "Divide the children into small groups and encourage them "
                     "to say short prayers together, with prompts like 'Let's "
                     "thank God for our families'."}]})
    return {"modules": modules}


def test_paraphrased_lessons_are_caught_even_though_the_prose_differs():
    """These run 7% to 16% alike as prose — nowhere near the copy threshold —
    and are the same lesson three times: discuss how a parent does it, invent a
    gesture, sing a song. The prose check scored this guide 100/100."""
    report = redundancy_check.inspect(_templated())

    assert not report["clean"]
    assert report["parallel_shapes"]
    assert not report["near_duplicates"], "these are not copies"


def test_the_finding_shows_the_beats_side_by_side():
    report = redundancy_check.inspect(_templated())
    beats = " ".join(report["parallel_shapes"][0]["beats"])

    assert "↔" in beats
    assert "Gestures" in beats


def test_a_lesson_on_a_different_outcome_is_not_flagged():
    report = redundancy_check.inspect(_templated())
    named = {p["a"] for p in report["parallel_shapes"]} | \
            {p["b"] for p in report["parallel_shapes"]}

    assert not any("Practicing Prayer" in n for n in named)


def test_lessons_sharing_an_outcome_and_a_cited_line_are_reported():
    """Not a defect on its own — an outcome can honestly need three lessons.
    It is the fact a head of department checks first, and it is exact."""
    report = redundancy_check.inspect(_templated())
    group = report["same_outcome_same_source"][0]

    assert group["ref"] == "203:22"
    assert len(group["lessons"]) == 3


def test_a_standard_lesson_frame_is_not_mistaken_for_a_template():
    """A guide whose every lesson runs Introduction / Development / Conclusion
    is using the standard shape. Comparing those names matches every pair, and
    reporting the whole guide would mean nothing."""
    modules = [
        {"title": f"Lesson {n}", "module_number": n, "slos_covered": [f"slo {n}"],
         "exposition_segments": [
             {"topic": "Introduction", "body": f"Opening for lesson {n}."},
             {"topic": "Development", "body": f"Main work for lesson {n}."},
             {"topic": "Conclusion", "body": f"Closing for lesson {n}."}]}
        for n in range(1, 6)
    ]
    report = redundancy_check.inspect({"modules": modules})

    assert not report["parallel_shapes"]


def test_a_templated_lesson_counts_against_the_score_like_a_copied_one():
    """It wastes the same lesson."""
    assert redundancy_check.inspect(_templated())["score"] < 70

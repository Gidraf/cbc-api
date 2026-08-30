"""KICD's own rubrics, read from the pages they are printed on, then checked.

Measured against a PP1 CRE run: five of twelve sub-strands fell back to
generated rubrics that the design had published two pages away, one carried a
level lifted from another strand's table, and one had its whole scale shifted
down a level. None of these defects is specific to Religious Education — the
causes are a heading that does not exist, a table that lives between
sub-strands, and no check on what came out.
"""
from __future__ import annotations

import pathlib

from app.services import rubric_integrity, rubric_tables, source_pages

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# The rubric pages as the PDF extraction actually renders them: columns
# flattened into a stream, cells wrapped across lines, spaces lost after verbs,
# and cells missing outright.
DESIGN = """[PAGE 202]
202:5  Summary of Strands and Sub-Strands
202:7  1.0 Creation 1.1 Our God 7
[PAGE 203]
203:2  STRAND 1.0: CREATION
203:10  1.1
203:11  Our God
203:12  (7 lessons)
[PAGE 205]
205:11  1.0 Creation 1.2
205:12  God our
205:13  Creator
[PAGE 207]
207:2  Suggested Assessment Rubric s
207:3  Level
207:4  Indicator
207:5  Exceeds
207:6  Expectations
207:7  Meets Expectations Approaches Expectations Below Expectations
207:8  Ability to identify three
207:9  qualities of God.
207:10  Identifies more than
207:11  three qualities of
207:12  God.
207:13  Identifies three
207:14  Identifiestwo qualities of
207:15  Identifies one quality
207:16  of God.
207:17  Ability to name three
207:18  things created by God.
207:19  Names three things
207:20  created by God
207:21  illustratively.
207:22  Namesthree things
207:23  created by God.
207:24  Namestwo things created
207:25  by God.
207:26  Names one thing
"""

SUBS = [
    {"sub_strand_name": "Our God", "sub_strand_id": "1.1",
     "slos": ["identify three qualities of God"]},
    {"sub_strand_name": "God our Creator", "sub_strand_id": "1.2",
     "slos": ["mention three things created by God"]},
]


# ── reading the tables ──────────────────────────────────────────────────────


def test_the_heading_kicd_actually_prints_is_the_one_searched_for():
    """The extractor looked for "Suggested Formative Assessment Rubrics". No
    KICD design contains the word "Formative", so nothing ever matched — in
    every subject."""
    assert rubric_tables._HEADING.search("Suggested Assessment Rubric s")
    assert rubric_tables._HEADING.search("Suggested Assessment Rubrics")
    assert rubric_tables._HEADING.search("Suggested Formative Assessment Rubric")

    extractor = (BACKEND / "app/services/curriculum_extractor.py").read_text()
    assert "Formative\\\\s+)?Assessment" in extractor or "(?:Formative" in extractor


def test_rubric_pages_are_found_between_the_sub_strands_they_measure():
    """A rubric table is on its own page, after the sub-strands it covers, so
    it is inside nobody's body text and no per-sub-strand extractor finds it."""
    harvest = rubric_tables.harvest(DESIGN, SUBS)
    assert harvest.pages_read == [207]


def test_each_row_reaches_the_sub_strand_whose_outcome_it_measures():
    harvest = rubric_tables.harvest(DESIGN, SUBS)
    got = {r.matched_sub_strand: r.indicator for r in harvest.rows}

    assert "Our God" in got and "qualities of God" in got["Our God"]
    assert "God our Creator" in got and "things created by God" in got["God our Creator"]


def test_a_wrapped_indicator_does_not_shift_every_level_by_one():
    """"Ability to identify three / qualities of God." is one indicator across
    two lines. Reading the second line as the first cell put "more than three"
    under Meeting and left Below empty."""
    row = next(r for r in rubric_tables.harvest(DESIGN, SUBS).rows
               if r.matched_sub_strand == "Our God")

    assert row.indicator == "Ability to identify three qualities of God."
    assert row.exceeding.startswith("Identifies more than three")
    assert row.meeting.startswith("Identifies three")
    assert row.approaching.startswith("Identifies two")
    assert row.below.startswith("Identifies one")


def test_the_lost_space_after_a_verb_is_repaired():
    """"Identifiestwo", "Namesthree", "Demonstratestwo" all appear in one
    design — the PDF drops the space, and a teacher reads the cell."""
    row = next(r for r in rubric_tables.harvest(DESIGN, SUBS).rows
               if r.matched_sub_strand == "God our Creator")

    assert "Namesthree" not in row.meeting
    assert "Namestwo" not in row.approaching
    assert row.meeting.startswith("Names three")
    assert row.approaching.startswith("Names two")


def test_a_row_matching_nothing_is_reported_rather_than_filed():
    """Filing it anyway is how a rubric for the Holy Bible ended up under the
    birth of Jesus."""
    harvest = rubric_tables.harvest(DESIGN, [
        {"sub_strand_name": "Photosynthesis", "sub_strand_id": "1.1",
         "slos": ["describe the process of photosynthesis"]},
    ])

    assert harvest.rows == []
    assert len(harvest.unmatched) == 2


def test_an_incomplete_row_is_not_offered_as_a_rubric():
    """A table the PDF destroyed beyond repair should fall through to an
    honestly labelled generated rubric, not a half-empty one."""
    partial = DESIGN + "207:27  Ability to do something else.\n207:28  Identifies it.\n"
    harvest = rubric_tables.harvest(partial, SUBS)
    for rows in (harvest.for_sub_strand("Our God"),):
        for row in rows:
            assert all(row[k] for k in ("exceeding", "meeting", "approaching", "below"))


# ── checking what came out ──────────────────────────────────────────────────


def _rubric(**kw):
    base = {"indicator": "", "exceeding": "", "meeting": "",
            "approaching": "", "below": ""}
    base.update(kw)
    return base


def test_a_level_lifted_from_another_strands_table_is_refused():
    """The real one: "Identifies the Holy Bible from other books" arrived as the
    Meeting level for the birth of Jesus, from the rubric two pages earlier. A
    teacher would assess the nativity by whether the child can pick out the
    Bible."""
    findings = rubric_integrity.check_one(
        "The Birth of Jesus Christ",
        ["identify the parents of Jesus Christ from a chart",
         "tell the story of the birth of Jesus Christ"],
        _rubric(
            indicator="Ability to identify the parents of Jesus Christ from pictures.",
            exceeding="Identifies the parents of Jesus pictures with ease.",
            meeting="Identifies the Holy Bible from other books when prompted.",
            approaching="Identifies one parent of Jesus from drawn pictures when prompted.",
            below="Identifies one parent of Jesus from drawn pictures with guidance.",
        ),
    )

    foreign = [f for f in findings if f.check == "foreign_concept"]
    assert foreign and foreign[0].level == "meeting"
    assert foreign[0].severity == "error"


def test_meeting_below_the_outcome_is_refused():
    """The Wise Men asks for TWO ways; its rubric put Meeting at one and
    Exceeding at two, so a child doing exactly what the outcome asks is marked
    as exceeding it."""
    findings = rubric_integrity.check_one(
        "The Wise Men",
        ["identify two ways the wise men celebrated the birth of Jesus"],
        _rubric(
            indicator="Ability to identify two ways the wise men celebrated the birth of Jesus.",
            exceeding="Identifies two ways the wise men celebrated the birth of Jesus with ease.",
            meeting="Identifies one way the wise men celebrated the birth of Jesus.",
            approaching="Identifies one way the wise men celebrated the birth of Jesus with guidance.",
            below="Identifies one way the wise men celebrated the birth of Jesus with continued support.",
        ),
    )

    assert any(f.check == "meeting_below_outcome" and f.severity == "error"
               for f in findings)


def test_a_scale_that_does_not_climb_is_refused():
    findings = rubric_integrity.check_one(
        "Counting",
        ["count three objects"],
        _rubric(indicator="Ability to count three objects.",
                exceeding="Counts two objects.", meeting="Counts three objects.",
                approaching="Counts two objects with help.", below="Counts one object."),
    )
    assert any(f.check == "scale_inverted" for f in findings)


def test_two_levels_a_teacher_cannot_tell_apart_are_refused():
    findings = rubric_integrity.check_one(
        "Sharing", ["share items with the needy"],
        _rubric(indicator="Ability to share items.",
                exceeding="Shares many items.", meeting="Shares one item.",
                approaching="Shares one item.", below="Does not share."),
    )
    assert any(f.check == "levels_identical" for f in findings)


def test_the_designs_own_contradiction_is_named_rather_than_repaired():
    """Sub-strand 5.1's outcome says "state ONE difference" and its rubric
    indicator says "tell THREE differences". That is KICD's inconsistency, and
    a teacher meets it in the classroom either way."""
    findings = rubric_integrity.check_one(
        "A House of God",
        ["state one difference between the church and other buildings"],
        _rubric(
            indicator="Ability to tell three differences between the church and other buildings.",
            exceeding="Tells more than three differences between the church and other buildings.",
            meeting="Tells three differences between the church and other buildings.",
            approaching="Tells two differences between the church and other buildings.",
            below="Tells one difference between the church and other buildings.",
        ),
    )

    defects = [f for f in findings if f.check == "outcome_rubric_disagree"]
    assert defects and defects[0].severity == "design_defect"
    # Reported, not corrected — picking a side would be doing it on KICD's behalf.
    assert not [f for f in findings if f.severity == "error"]


def test_a_sound_rubric_passes_untouched():
    findings = rubric_integrity.check_one(
        "Our God", ["identify three qualities of God"],
        _rubric(indicator="Ability to identify three qualities of God.",
                exceeding="Identifies more than three qualities of God.",
                meeting="Identifies three qualities of God.",
                approaching="Identifies two qualities of God.",
                below="Identifies one quality of God."),
    )
    assert findings == []


def test_a_wrong_rubric_is_dropped_so_the_filler_can_replace_it():
    """A wrong rubric is worse than an absent one: the filler writes an honest
    labelled replacement for an absent one, and cannot tell that a present one
    is wrong."""
    subs = [{
        "sub_strand_name": "The Birth of Jesus Christ",
        "slos": ["identify the parents of Jesus Christ from a chart"],
        "assessment_rubrics": [_rubric(
            indicator="Ability to identify the parents of Jesus Christ from pictures.",
            exceeding="Identifies the parents of Jesus with ease.",
            meeting="Identifies the Holy Bible from other books when prompted.",
            approaching="Identifies one parent of Jesus when prompted.",
            below="Identifies one parent of Jesus with guidance.",
        )],
    }]
    report = rubric_integrity.drop_unsound(subs)

    assert report.errors
    assert subs[0]["assessment_rubrics"] == []


# ── page numbers ────────────────────────────────────────────────────────────


def test_pages_are_resolved_from_the_document_not_guessed():
    """The model guessed "this page plus the next", which put three of twelve
    sub-strands on a neighbour's page — and page addresses are what every
    citation in this system resolves against."""
    subs = [
        {"sub_strand_name": "Our God", "sub_strand_id": "1.1", "source_pages": [202, 203]},
        {"sub_strand_name": "God our Creator", "sub_strand_id": "1.2",
         "source_pages": [205, 206]},
    ]
    changed = source_pages.apply(DESIGN, subs)

    assert changed == 2
    # 206 was 1.3's page, not 1.2's. 207 is the rubric that measures it.
    assert subs[1]["source_pages"] == [202, 205, 207]
    assert 206 not in subs[1]["source_pages"]


def test_the_summary_and_rubric_pages_are_both_counted_as_sources():
    resolved = source_pages.resolve(DESIGN, SUBS)
    assert 202 in resolved["Our God"], "the summary table lists every sub-strand"
    assert 207 in resolved["Our God"], "the rubric page measures it"


def test_an_unlocatable_sub_strand_keeps_what_it_had():
    """An unresolved sub-strand is a gap in this resolver, not proof the
    model's guess was wrong."""
    subs = [{"sub_strand_name": "Nowhere In This Document",
             "sub_strand_id": "9.9", "source_pages": [42]}]
    source_pages.apply(DESIGN, subs)
    assert subs[0]["source_pages"] == [42]


# ── the extractor is no longer shaped like one subject ──────────────────────


def test_visual_discovery_is_not_an_agriculture_keyword_list():
    """It scanned every learning area for "drip irrigation", "zai pit",
    "scarecrow", "compost", "nursery bed" and "soil profile"."""
    source = (BACKEND / "app/services/curriculum_extractor.py").read_text()
    # Comments explaining what was removed name the terms; the CODE must not.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    for agricultural in ("zai pit", "scarecrow", "drip irrigation",
                         "nursery bed", "container garden", "seedbed"):
        assert agricultural not in code, agricultural


def test_the_pipeline_grounds_rubrics_before_the_filler_decides():
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    fn = source[source.index("def _ground_substrands"):]
    fn = fn[: fn.index("@router.post")]

    assert "rubric_tables.harvest" in fn
    assert "rubric_integrity.drop_unsound" in fn
    assert "source_pages_service.apply" in fn
    # Order matters: read, then check, then the filler replaces what was
    # dropped.
    assert fn.index("harvest") < fn.index("drop_unsound")


# ── the defects the first real regeneration exposed ─────────────────────────


def _row(indicator: str, page: int = 0) -> rubric_tables.RubricRow:
    return rubric_tables.RubricRow(indicator=indicator, page=page)


def test_assessment_verbs_alone_cannot_match_a_rubric_to_a_sub_strand():
    """"Ability to identify three qualities of God" scored 0.5 against "A Holy
    Book" purely on "identify" and "three" — which is how one strand's rubric
    reached four other sub-strands at once."""
    name, score = rubric_tables._match_to_sub_strand(
        _row("Ability to identify three qualities of God."),
        [{"sub_strand_name": "A Holy Book",
          "slos": ["identify the Holy Bible from other books",
                   "demonstrate three ways of handling the Bible"]}],
    )
    assert name == ""
    assert score < rubric_tables._MATCH_FLOOR


def test_an_indicator_with_no_topic_words_is_not_filed_anywhere():
    """"Ability to name three things" belongs to whichever sub-strand the page
    says, and word matching cannot tell."""
    name, _ = rubric_tables._match_to_sub_strand(
        _row("Ability to name three things."),
        [{"sub_strand_name": "God our Creator",
          "slos": ["mention three things created by God"]}],
    )
    assert name == ""


def test_a_row_that_fits_two_sub_strands_equally_is_filed_against_neither():
    rows = rubric_tables._match_to_sub_strand(
        _row("Ability to identify three ways loving God."),
        [{"sub_strand_name": "Love for God",
          "slos": ["identify three ways of loving God"]},
         {"sub_strand_name": "God our Loving Father",
          "slos": ["tell three ways God shows His love to us"]}],
    )
    assert rows[0] == ""


def test_a_rubric_from_another_strands_page_is_rejected():
    """KICD prints one rubric table per strand. Word overlap cannot separate
    "identify three ways loving God" (page 217) from "God our Loving Father",
    and this resolver runs one strand at a time so the wrong one has no
    competitor to lose to. The page settles it."""
    import app.routes.curriculum as routes

    design = (
        "[PAGE 202]\n202:5  Summary of Strands and Sub-Strands\n"
        "[PAGE 206]\n206:9  1.3\n206:10  God our\n206:11  Loving\n206:12  Father\n"
        "[PAGE 207]\n207:2  Suggested Assessment Rubric s\n"
        "207:8  Ability to identify three\n207:9  qualities of God.\n"
        "207:10  Identifies more than three qualities of God.\n"
        "207:11  Identifies three qualities of God.\n"
        "207:12  Identifies two qualities of God.\n"
        "207:13  Identifies one quality of God.\n"
        "[PAGE 217]\n217:2  Suggested Assessment Rubric\n"
        "217:10  Ability to identify\n217:11  three ways loving God.\n"
        "217:12  Identifies more than three ways of loving God.\n"
        "217:13  Identifies three ways of loving God.\n"
        "217:14  Identifies two ways of loving God.\n"
        "217:15  Identifies one way of loving God.\n"
    )
    subs = [{"sub_strand_name": "God our Loving Father", "sub_strand_id": "1.3",
             "slos": ["tell three ways God shows His love to us"]}]

    report = routes._ground_substrands(subs, design)

    assert report["rubric_tables"]["rejected_off_page"] >= 1
    assert not subs[0].get("assessment_rubrics")


def test_a_level_that_is_only_a_wrapped_fragment_fails_the_row():
    """"shows His love to them." and "David and Goliath." both arrived as
    rubric levels. They read as levels and measure nothing."""
    row = rubric_tables.RubricRow(
        indicator="Ability to tell three ways God shows His love to them.",
        exceeding="Tells more than three ways God shows His love to them.",
        meeting="shows His love to them.",
        approaching="Tells two ways God shows His love to them.",
        below="Tells one way God shows His love to them.",
    )
    assert not row.complete


def test_a_sub_strand_does_not_span_the_rest_of_the_document():
    """Called with one strand's sub-strands, the last of them had no next
    opening and claimed every remaining page: "God our Loving Father" came back
    with thirteen source pages."""
    design = "".join(
        f"[PAGE {n}]\n{n}:1  1.3\n{n}:2  God our\n{n}:3  Loving\n{n}:4  Father\n"
        if n == 206 else f"[PAGE {n}]\n{n}:1  filler text for page {n}\n"
        for n in range(202, 222)
    )
    subs = [{"sub_strand_name": "God our Loving Father", "sub_strand_id": "1.3",
             "source_pages": []}]
    source_pages.apply(design, subs)

    assert len(subs[0]["source_pages"]) <= 4, subs[0]["source_pages"]
    assert 221 not in subs[0]["source_pages"]


def test_the_models_own_rubric_is_dropped_in_favour_of_the_designs():
    """The generator returns its own rubric under the singular key, so a
    sub-strand carried two sets with nothing saying which to follow — and the
    model's was the worse: for "A Holy Book" it put "Identifies the Holy Bible
    from other books" at Meeting and "Demonstrates one way of handling the holy
    Bible" at Below, welding two indicators into one scale."""
    import app.routes.curriculum as routes

    subs = [{
        "sub_strand_name": "A Holy Book", "sub_strand_id": "2.1",
        "slos": ["identify the Holy Bible from other books"],
        "assessment_rubric": {"indicator": "the model's own guess"},
    }]
    report = routes._ground_substrands(subs, "")

    assert "assessment_rubric" not in subs[0]
    assert report["model_rubrics_dropped"] == 1


def test_a_cell_kicd_cut_off_is_named_rather_than_hidden():
    """"Identifies three", "Names one thing", "Tells three" — the words are
    KICD's and the sentence is not finished."""
    row = rubric_tables.RubricRow(
        indicator="Ability to identify three qualities of God.",
        exceeding="Identifies more than three qualities of God.",
        meeting="Identifies three",
        approaching="Identifies two qualities of",
        below="Identifies one quality of God.",
    )
    assert row.truncated_levels == ["meeting", "approaching"]
    assert row.to_dict()["truncated_levels"] == ["meeting", "approaching"]
    # Still usable: a partial rubric from the design beats a generated one.
    assert row.complete


def test_a_span_stops_where_another_strand_begins():
    """This resolver runs on one strand at a time, so the last sub-strand had
    no sibling after it and ran on into the following strand: "God our Loving
    Father" claimed page 208, which is where The Holy Bible starts."""
    design = (
        "[PAGE 202]\n202:5  Summary of Strands and Sub-Strands\n"
        "[PAGE 206]\n206:9  1.3\n206:10  God our\n206:11  Loving\n206:12  Father\n"
        "[PAGE 207]\n207:2  Suggested Assessment Rubric s\n"
        "207:8  Ability to tell three ways God shows His love.\n"
        "[PAGE 208]\n208:5  STRAND 2.0: THE HOLY BIBLE\n208:13  2.1 A Holy\n208:14  Book\n"
    )
    subs = [{"sub_strand_name": "God our Loving Father", "sub_strand_id": "1.3",
             "source_pages": []}]
    source_pages.apply(design, subs)

    assert subs[0]["source_pages"] == [202, 206, 207]
    assert 208 not in subs[0]["source_pages"]


def test_a_meets_cell_the_pdf_stripped_of_its_verb_fails_the_row():
    """Page 210's Meets cell for David and Goliath is literally "David and
    Goliath." — the verb was lost in extraction. A generated rubric that says
    so beats a level a teacher cannot act on."""
    design = (
        "[PAGE 209]\n209:9  2.2 Bible\n209:10  Story:\n209:11  David and\n209:12  Goliath\n"
        "[PAGE 210]\n210:2  Suggested Assessment Rubric\n"
        "210:31  Ability to narrate the\n210:32  story of David and\n210:33  Goliath.\n"
        "210:34  Narrates the story of\n210:35  David and Goliath\n210:36  with actions.\n"
        "210:37  David and Goliath.\n"
        "210:38  Partly narrates the story of\n"
        "210:39  Narrates the story\n210:40  of David and Goliath\n210:41  with prompts.\n"
    )
    harvest = rubric_tables.harvest(
        design,
        [{"sub_strand_name": "Bible Story: David and Goliath", "sub_strand_id": "2.2",
          "slos": ["retell the story of David and Goliath"]}],
    )
    row = harvest.rows[0]

    assert row.meeting == "David and Goliath."
    assert not row.complete
    assert harvest.for_sub_strand("Bible Story: David and Goliath") == []


# ── finishing what KICD's PDF cut off ───────────────────────────────────────


def test_a_truncated_cell_is_completed_from_the_indicators_own_words():
    """Half of KICD's rubric cells arrive cut off — "Identifies three", "Tells
    three", "Names one thing". A teacher cannot mark against those."""
    assert rubric_tables.complete_cell(
        "Identifies three", "Ability to identify three qualities of God."
    ) == "Identifies three qualities of God."

    assert rubric_tables.complete_cell(
        "Tells three", "Ability to tell three differences between the church and other buildings."
    ) == "Tells three differences between the church and other buildings."

    assert rubric_tables.complete_cell(
        "Names one thing", "Ability to name three things created by God."
    ) == "Names one thing created by God.", "singular/plural must not block the join"


def test_completion_is_a_join_and_never_a_guess():
    """Where the cell's words cannot be located in the indicator there is
    nothing to join to, and inventing the rest is how a wrong rubric that reads
    plausibly gets into a classroom."""
    assert rubric_tables.complete_cell(
        "Something else entirely", "Ability to identify three qualities of God."
    ) == "Something else entirely"

    # A cell ending on a function word still has an anchor once that word is
    # stripped: "way" locates it, and only what follows is appended — the verb
    # is not swallowed along with it.
    assert rubric_tables.complete_cell(
        "Identifies one way of", "Ability to identify three ways loving God."
    ) == "Identifies one way of loving God."

    # And a cell stating a different count of the same thing is completed from
    # the object the indicator names, without repeating its number.
    assert rubric_tables.complete_cell(
        "Identifies one to two", "Ability to tell four activities they do in church."
    ) == "Identifies one to two activities they do in church."


def test_a_completed_cell_is_never_completed_silently():
    design = (
        "[PAGE 203]\n203:10  1.1\n203:11  Our God\n"
        "[PAGE 207]\n207:2  Suggested Assessment Rubric s\n"
        "207:8  Ability to identify three\n207:9  qualities of God.\n"
        "207:10  Identifies more than\n207:11  three qualities of\n207:12  God.\n"
        "207:13  Identifies three\n207:14  Identifiestwo qualities of\n"
        "207:15  Identifies one quality\n207:16  of God.\n"
    )
    row = rubric_tables.harvest(design, [
        {"sub_strand_name": "Our God", "sub_strand_id": "1.1",
         "slos": ["identify three qualities of God"]},
    ]).rows[0]

    assert row.meeting == "Identifies three qualities of God."
    assert row.completed_levels == ["meeting", "approaching"]
    assert row.truncated_levels == [], "nothing left cut off"
    assert row.to_dict()["completed_levels"] == ["meeting", "approaching"]


def test_one_field_has_one_shape():
    """The generator returned link_to_other_learning_areas as a string for
    eleven sub-strands and a list for the twelfth, so every reader has to
    handle both — and the one that forgets fails on whichever differs."""
    import app.routes.curriculum as routes

    subs = [
        {"sub_strand_name": "A", "link_to_other_learning_areas": ["one", "two"]},
        {"sub_strand_name": "B", "link_to_other_learning_areas": "plain string"},
    ]
    routes._ground_substrands(subs, "")

    assert subs[0]["link_to_other_learning_areas"] == "one two"
    assert subs[1]["link_to_other_learning_areas"] == "plain string"

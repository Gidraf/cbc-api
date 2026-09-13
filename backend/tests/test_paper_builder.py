"""A paper composed from the bank, printed as the booklet a school buys.

The bank is a pile of items; the exam builder held zero exams because
composing one by hand from four hundred items is work nobody does. And the
printed bank paper handed the renderer rows as they came out of the table,
found no `question_text` on top of any, and printed empty stems.
"""
from __future__ import annotations

from app.services import paper_builder, question_paper, question_rows


def _row(qid: str, sub_strand: str, q_type: str, text: str, marks: int, *,
         status: str = "approved", slo: str = "s1", difficulty: float = 0.5,
         parts: int = 0, options: bool = False) -> dict:
    content = {"question_type": q_type, "question_text": text, "stimulus_context": "",
               "model_answer": "x", "marking_scheme": "x = x (1 mark)"}
    if options:
        content["options"] = [{"id": "A", "text": "1", "is_correct": True},
                              {"id": "B", "text": "2"}, {"id": "C", "text": "3"}, {"id": "D", "text": "4"}]
        content["correct_answer"] = "A"
    if parts:
        content["structured_parts"] = [
            {"part_id": f"({chr(97 + i)})", "sub_question": f"Part {i + 1} of {text}",
             "marks": marks // parts, "model_answer": "y"} for i in range(parts)]
    return {
        "question_id": qid, "display_label": qid.upper(), "status": status,
        "curriculum_link": {"grade": "grade-9", "subject": "Mathematics", "strand": "Numbers",
                            "sub_strand": sub_strand, "slo_id": slo},
        "pedagogical_dna": {"max_marks": marks, "difficulty_index": difficulty,
                            "question_type": q_type, "bloom_level": "Application"},
        "content": content,
    }


def _bank() -> list[dict]:
    rows = []
    for n in range(1, 13):
        rows.append(_row(f"int-mcq-{n}", "Integers", "multiple_choice",
                         f"Work out $({-n}) \\times 3 + {n}$.", 1, options=True,
                         slo=f"s{n % 3}", difficulty=n / 12))
    for n in range(1, 7):
        rows.append(_row(f"int-calc-{n}", "Integers", "quantitative_calculation",
                         f"Evaluate $[{n} - 9] \\div (-3) + {n} \\times (-2)$.", 3, slo=f"s{n % 2}"))
    for n in range(1, 4):
        rows.append(_row(f"int-str-{n}", "Integers", "structured_scenario",
                         f"A trader's balance changes {n} times in a day.", 6, parts=3))
    for n in range(1, 7):
        rows.append(_row(f"frac-mcq-{n}", "Fractions", "multiple_choice",
                         f"Which fraction equals $\\frac{{{n}}}{{{n + 1}}}$?", 1, options=True))
    for n in range(1, 4):
        rows.append(_row(f"frac-calc-{n}", "Fractions", "short_answer",
                         f"Simplify $\\frac{{{2 * n}}}{{{6 * n}}}$.", 2))
    return rows


ARGS = dict(grade="grade-9", subject="Mathematics", strand="Numbers")
SCHOOL = dict(ARGS, format_key="school")


def test_the_bank_rows_reach_the_renderer_with_their_text() -> None:
    """The row keeps the item under `content`; the renderer reads the top."""
    items = question_rows.flatten_all(_bank()[:1])
    html = question_paper.render_html(items, grade="grade-9", subject="Mathematics")

    assert "Work out" in html
    assert items[0]["pedagogy"]["max_marks"] == 1
    assert items[0]["curriculum"]["sub_strand"] == "Integers"


def test_a_topical_paper_has_sections_that_add_up() -> None:
    items = question_rows.flatten_all(_bank())
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=30, **SCHOOL)

    assert paper.title == "Topical Test: Integers"
    assert [s.letter for s in paper.sections] == ["A", "B", "C"]
    assert paper.total_marks == 30, paper.to_dict()
    assert sum(s.marks for s in paper.sections) == paper.total_marks
    assert all((q.get("curriculum") or {}).get("sub_strand") == "Integers" for q in paper.items)
    assert paper.time_allowed == "45 minutes"
    assert not paper.shortfall


def test_a_strand_paper_is_dealt_across_its_sub_strands() -> None:
    items = question_rows.flatten_all(_bank())
    paper = paper_builder.compose(items, kind="strand", marks=40, **SCHOOL)

    assert paper.title == "End of Strand Assessment: Numbers"
    assert set(paper.covers) == {"Integers", "Fractions"}
    assert paper.covers["Fractions"] >= 4, paper.covers


def test_within_a_section_the_items_run_easy_to_hard() -> None:
    items = question_rows.flatten_all(_bank())
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=30, **SCHOOL)

    section_a = paper.sections[0]
    difficulties = [q["pedagogy"]["difficulty_index"] for q in section_a.items]
    assert difficulties == sorted(difficulties)


def test_the_same_request_composes_the_same_paper_and_a_seed_deals_another() -> None:
    items = question_rows.flatten_all(_bank())
    one = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=30, **SCHOOL)
    two = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=30, **SCHOOL)
    other = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=30,
                                  seed="stream-b", **SCHOOL)

    assert one.to_dict()["question_ids"] == two.to_dict()["question_ids"]
    assert other.to_dict()["question_ids"] != one.to_dict()["question_ids"]
    assert other.total_marks == 30


def test_the_same_task_under_two_ids_is_set_once() -> None:
    rows = _bank()
    rows.append(_row("int-mcq-copy", "Integers", "multiple_choice",
                     "Work out $(-1) \\times 3 + 1$.", 1, options=True))
    items = question_rows.flatten_all(rows)
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=40, **SCHOOL)

    ids = paper.to_dict()["question_ids"]
    assert not ("int-mcq-copy" in ids and "int-mcq-1" in ids)


def test_drafts_are_kept_out_unless_asked_and_stamp_the_page_when_let_in() -> None:
    rows = _bank()
    for row in rows:
        if row["question_id"].startswith("frac"):
            row["status"] = "draft"
    items = question_rows.flatten_all(rows)

    strict = paper_builder.compose(items, kind="strand", marks=30, allow_drafts=False, **SCHOOL)
    loose = paper_builder.compose(items, kind="strand", marks=30, allow_drafts=True, **SCHOOL)

    assert "Fractions" not in strict.covers and not strict.has_drafts
    assert "Fractions" in loose.covers and loose.has_drafts
    assert "DRAFT" in question_paper.render_paper(loose)
    assert "DRAFT" not in question_paper.render_paper(strict)


def test_a_bank_too_small_for_the_marks_says_so() -> None:
    items = question_rows.flatten_all(_bank()[:3])
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=50, **SCHOOL)

    assert paper.total_marks == 3
    assert "3 of the 50 marks" in paper.shortfall
    assert "Incomplete" in question_paper.render_paper(paper)


def test_a_section_with_nothing_in_the_bank_gives_its_marks_to_the_others() -> None:
    items = question_rows.flatten_all([r for r in _bank() if "str" not in r["question_id"]])
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", marks=24, **SCHOOL)

    assert [s.letter for s in paper.sections] == ["A", "B"]
    assert paper.total_marks == 24


def test_the_booklet_prints_the_paper_then_the_scheme_with_the_key_up_front() -> None:
    items = question_rows.flatten_all(_bank())
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", count=20,
                                  series="Step Flyer Series", **ARGS)
    paper.scheme_url = "https://papers.example.co.ke/api/v1/exams/exam-1/scheme?token=abc"

    learner = question_paper.render_paper(paper)
    scheme = question_paper.render_paper(paper, answers=True)
    booklet = question_paper.render_paper(paper, with_scheme=True)

    # The masthead the national paper carries.
    assert "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT" in learner
    assert "GRADE 9 – YEAR" in learner and "'subject'>MATHEMATICS<" in learner and "Step Flyer Series" in learner
    assert "(i) Your name" in learner and "READ THESE INSTRUCTIONS CAREFULLY" in learner
    assert "For official use only" in learner, "Section B marks table"
    assert "SECTION A" in learner and "SECTION B" in learner
    # The scheme is reached from the paper, never printed on it.
    assert "<svg" in learner.split("class='qr'")[1][:2000], "a QR code on the paper"
    assert "papers.example.co.ke/api/v1/exams/exam-1/scheme" in learner
    assert "Correct option" not in learner and "MARKING SCHEME" not in learner
    assert "MARKING SCHEME" in scheme and "class='keygrid'" in scheme
    assert "(i) Your name" not in scheme
    assert booklet.count("class='mast'") == 2 and "break-before: page" in booklet
    # Continuous numbering across sections.
    assert "<span class='n'>1.</span>" in learner
    assert f"<span class='n'>{len(paper.items)}.</span>" in learner


def test_a_grade_6_paper_is_kpsea_shaped_and_a_grade_9_paper_kjsea() -> None:
    rows = [dict(r, curriculum_link={**r["curriculum_link"], "grade": "grade-6"}) for r in _bank()]
    items = question_rows.flatten_all(rows)

    six = paper_builder.compose(items, kind="strand", count=30, grade="grade-6",
                                subject="Mathematics", strand="Numbers")
    nine = paper_builder.compose(question_rows.flatten_all(_bank()), kind="strand", count=40, **ARGS)

    assert six.format["key"] == "kpsea"
    assert [s.letter for s in six.sections] == [""], "one section, all multiple choice"
    assert all(q.get("options") for q in six.items)
    assert six.masthead["assessment"] == "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT"
    assert nine.format["key"] == "kjsea"
    assert [s.letter for s in nine.sections] == ["A", "B"]
    assert all(q.get("options") for q in nine.sections[0].items)
    assert not any(q.get("options") for q in nine.sections[1].items)
    assert nine.time_allowed == "1 hour 40 minutes"


def test_items_on_one_figure_sit_together_and_the_figure_prints_once() -> None:
    rows = _bank()
    for n in range(1, 4):
        rows.append({**rows[0], "question_id": f"map-{n}",
                     "content": {**rows[0]["content"], "question_text": f"Which town is on the coast? ({n})",
                                 "diagram": {"diagram_id": "kenya-map", "diagram_title": "Sketch map of Kenya"}}})
    items = question_rows.flatten_all(rows)
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", count=30, **ARGS)

    ids = [q["question_id"] for q in paper.sections[0].items]
    positions = [ids.index(f"map-{n}") for n in range(1, 4)]
    assert max(positions) - min(positions) == 2, "the three map items are consecutive"

    html = question_paper.render_paper(paper, assets={"kenya-map": {"svg_markup": "<svg><text>x</text></svg>",
                                                                    "scene_document": {}}})
    first = min(positions) + 1
    assert html.count("Study the map below") == 1
    assert f"answer questions {first} to {first + 2}" in html


def test_a_frozen_paper_thaws_to_the_same_paper() -> None:
    items = question_rows.flatten_all(_bank())
    paper = paper_builder.compose(items, kind="topical", sub_strand="Integers", count=20, **ARGS)
    snapshot = {**paper.to_dict(),
                "sections": [{**s.to_dict(), "instructions": s.instructions} for s in paper.sections],
                "time_allowed": paper.time_allowed, "instructions": paper.instructions}

    again = paper_builder.thaw(snapshot, items)

    assert again.to_dict()["question_ids"] == paper.to_dict()["question_ids"]
    assert [s.letter for s in again.sections] == [s.letter for s in paper.sections]
    assert again.format == paper.format and again.masthead == paper.masthead
    assert again.total_marks == paper.total_marks


def test_the_freeze_and_public_scheme_routes_exist() -> None:
    import inspect

    from app.routes import exams, questions

    q = inspect.getsource(questions)
    e = inspect.getsource(exams)
    assert '@router.post("/paper/freeze")' in q and "share_token" in q
    assert "secrets.token_urlsafe" in q
    assert '@router.get("/exams/{exam_id}/scheme")' in e
    scheme = e[e.index("def public_marking_scheme("):]
    assert "Depends(require_roles" not in scheme[:600], "the QR link needs no sign-in"
    assert "hmac.compare_digest" in scheme
    assert '@router.get("/exams/{exam_id}/paper.html")' in e


def test_the_generator_is_told_what_paper_its_items_are_for() -> None:
    import inspect

    from app.routes import questions
    from app.services import assessment_format

    assert "assessment_format.prompt_block(payload.grade, payload.batch_count)" in inspect.getsource(questions)
    block = assessment_format.prompt_block("grade-6", 50)
    assert "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT" in block
    assert "Nothing a Grade 3 learner could answer" in block
    assert "50 items" in block
    assert assessment_format.for_grade("grade-8").key == "kjsea"
    assert assessment_format.for_grade("grade-2").key == "lower_primary"
    assert assessment_format.for_grade("grade-11").key == "senior"


def test_a_diagram_question_prints_its_figure_blank_for_the_learner_and_labelled_for_the_marker() -> None:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 100'>"
           "<g data-layer='labels'><text id='p1' x='10' y='20'>Nucleus</text></g>"
           "<circle id='shape' cx='100' cy='50' r='30'/></svg>")
    question = {
        "question_id": "d1", "question_type": "diagram_based", "question_text": "Name the part labelled A.",
        "model_answer": "Nucleus", "marking_scheme": "Nucleus (1 mark)",
        "pedagogy": {"max_marks": 1}, "curriculum": {"sub_strand": "Cells"},
        "diagram": {"diagram_id": "diag-1", "diagram_title": "The cell", "hide_layers": ["labels"],
                    "binding_method": "authored", "variant_mode": "label_blanks"},
    }
    assets = {"diag-1": {"svg_markup": svg, "scene_document": {"parts": [], "regions": []}}}

    learner = question_paper.render_html([question], answers=False, assets=assets)
    marker = question_paper.render_html([question], answers=True, assets=assets)

    assert "figure-inline" in learner and "figure-inline" in marker
    assert "Nucleus" not in learner.split("class='stem'")[0], "the label is on the learner's copy"
    assert "Nucleus" in marker


def test_the_composed_paper_routes_exist_and_flatten_the_bank() -> None:
    import inspect

    from app.routes import questions

    source = inspect.getsource(questions)
    assert '@router.get("/paper/exam.html")' in source
    assert '@router.get("/paper/exam.pdf")' in source
    assert '@router.get("/paper/exam.json")' in source
    assert source.count("question_rows.flatten_all(") >= 3, "the bank paper must flatten its rows"
    assert "question_paper.figures_for(" in source


def test_a_batch_of_fifty_is_written_in_chunks_that_see_each_other() -> None:
    from app.routes.questions import _generate_in_chunks

    class Usage:
        def __init__(self):
            self.prompt_tokens, self.completion_tokens, self.total_tokens = 10, 5, 15

    class Resp:
        def __init__(self, items):
            self.content, self.usage, self.model = {"questions": items}, Usage(), "m"

    seen = []

    class Client:
        def generate(self, config, messages, temperature=0.0):
            seen.append(messages[-1]["content"])
            n = len(seen)
            return Resp([{"question_text": f"chunk {n} item {i}"} for i in range(25 if n == 1 else 25)])

    resp, items = _generate_in_chunks(Client(), object(), [{"role": "system", "content": "s"},
                                                            {"role": "user", "content": "directive"}], 50)

    assert len(seen) == 2 and len(items) == 50
    assert "CHUNK 2 OF 2" in seen[1] and "chunk 1 item 3" in seen[1], "the second chunk sees the first"
    assert "ALREADY WRITTEN" not in seen[0]
    assert resp.usage.total_tokens == 30


def test_the_paper_is_headed_with_knecs_own_name_for_the_grade() -> None:
    """A paper headed "Junior Secondary" is a paper from a different system,
    and a head teacher sees it at once."""
    from app.services import assessment_format as af

    assert af.assessment_name("grade-9") == "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT"
    assert af.assessment_name("grade-7") == "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT"
    assert af.assessment_name("grade-6") == "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT"
    assert af.assessment_name("grade-4") == "KENYA PRIMARY SCHOOL EDUCATION ASSESSMENT"
    assert af.assessment_name("grade-3") == "KENYA EARLY YEARS ASSESSMENT"
    assert af.assessment_name("grade-1") == "SCHOOL BASED ASSESSMENT"
    assert "SECONDARY" not in " ".join(af.ASSESSMENT_NAMES.values())

    head = af.masthead("grade-9", "Mathematics", year=2026, kind="term", term=2)
    assert head["assessment"] == "KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT"
    assert head["grade_line"] == "GRADE 9 – YEAR 2026"
    assert head["subject"] == "MATHEMATICS"
    assert head["kind_line"] == "END OF TERM 2 EXAMINATION 2026"
    assert af.masthead("grade-6", "Mathematics", kind="topical", scope="Integers")["kind_line"] \
        == "TOPICAL ASSESSMENT: INTEGERS"

    items = question_rows.flatten_all(_bank())
    paper = paper_builder.compose(items, kind="strand", count=20, year=2026, **ARGS)
    html = question_paper.render_paper(paper)
    order = [html.index(x) for x in ("KENYA JUNIOR SCHOOL EDUCATION ASSESSMENT", "GRADE 9 – YEAR 2026",
                                     "'subject'>MATHEMATICS<", "END OF STRAND ASSESSMENT: NUMBERS")]
    assert order == sorted(order), "assessment, grade and year, subject, then the paper's kind"

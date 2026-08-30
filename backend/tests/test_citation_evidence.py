"""A reviewer must not have to guess whether a citation is real.

Layer 2 scored factual_correctness 70 and raised a HIGH issue — "fabricated
citations such as '203:26' and '203:33'" — on a guide whose citations all
resolve. Our own check had verified six of six at 100%.

The reviewer was given a SUMMARY of the design and then told to flag any
address "not in the excerpt". There was no excerpt. It followed the instruction
the only way it could.
"""
from __future__ import annotations

import pathlib

from app.services import citation_evidence, document_index

BACKEND = pathlib.Path(__file__).resolve().parents[1]

DESIGN = """[PAGE 203]
203:25  The learner is guided to:
203:26  • say the name of God in their mother tongue or
203:27  language of catchment area,
203:33  • in turns, say what they know about God ( loving,
203:34  creator, and provider),
"""


# ── the parsing bug underneath it ───────────────────────────────────────────


def test_a_rendered_address_survives_being_parsed_back():
    """Stripping the address and then counting positionally made rendering and
    parsing one-way: "203:26" came back as line 2 of page 203, so every address
    resolved against re-parsed text pointed at the wrong line."""
    pages = document_index.parse_pages(DESIGN)
    numbers = [l.line for l in pages[0].lines]

    assert numbers == [25, 26, 27, 33, 34]
    assert pages[0].lines[1].text.startswith("• say the name of God")


def test_a_line_with_no_address_still_gets_one():
    pages = document_index.parse_pages(
        "[PAGE 7]\nfirst line with no address\nsecond line\n"
    )
    assert [l.line for l in pages[0].lines] == [1, 2]


def test_rendering_and_parsing_are_inverses():
    """The property the whole citation substrate rests on."""
    pages = document_index.parse_pages(DESIGN)
    rendered = "\n".join(
        f"[PAGE {p.number}]\n" + "\n".join(f"{l.page}:{l.line}  {l.text}" for l in p.lines)
        for p in pages
    )
    again = document_index.parse_pages(rendered)

    assert [(l.page, l.line, l.text) for l in again[0].lines] == \
           [(l.page, l.line, l.text) for l in pages[0].lines]


# ── the evidence the reviewer is given ──────────────────────────────────────


def _artifact(refs: list[str]) -> dict:
    return {"modules": [{"citations": [{"ref": r, "claim": f"cited for {r}"}]}
                        for r in refs]}


def test_a_real_address_resolves_and_shows_what_the_design_says():
    evidence = citation_evidence.resolve(_artifact(["203:26"]), DESIGN)
    row = evidence["citations"][0]

    assert row["status"] == "VERIFIED"
    assert any("say the name of God" in s for s in row["design_says"])


def test_an_invented_address_is_reported_as_such():
    evidence = citation_evidence.resolve(_artifact(["999:1", "203:88"]), DESIGN)
    statuses = {r["ref"]: r["status"] for r in evidence["citations"]}

    assert statuses["999:1"] == "PAGE NOT IN THE DESIGN"
    assert statuses["203:88"] == "LINE NOT ON THAT PAGE"


def test_the_exact_citations_the_reviewer_called_fabricated_verify():
    """203:26 and 203:33 — the two it named."""
    evidence = citation_evidence.resolve(_artifact(["203:26", "203:33"]), DESIGN)

    assert evidence["verified"] == 2
    assert all(r["status"] == "VERIFIED" for r in evidence["citations"])


def test_with_no_design_the_reviewer_is_told_not_to_guess():
    """The failure mode was guessing. Silence about it is what produced the
    false accusation."""
    rendered = citation_evidence.render(
        citation_evidence.resolve(_artifact(["203:26"]), "")
    )
    assert "CANNOT judge" in rendered
    assert "Do not guess" in rendered
    assert "do not report a citation as fabricated" in rendered


def test_the_block_still_asks_the_reviewer_to_judge_the_claim():
    """An address can resolve and still be cited for something it does not
    say — which is a real defect this pipeline has produced."""
    rendered = citation_evidence.render(
        citation_evidence.resolve(_artifact(["203:26"]), DESIGN)
    )
    assert "whether the quoted line actually supports the claim" in rendered


# ── wiring ──────────────────────────────────────────────────────────────────


def test_the_reviewer_receives_the_resolved_citations():
    from app.services import review_layers

    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "Creation", "sub_strand_name": "Our God", "version": 1,
        "content": _artifact(["203:26", "301:9"]),
    })()
    messages = review_layers.build_messages(artifact, 2, design_source_text=DESIGN)
    user = messages[1]["content"]

    assert "=== CITATIONS IN THIS ARTIFACT, ALREADY RESOLVED ===" in user
    assert "203:26  [VERIFIED]" in user
    assert "301:9  [PAGE NOT IN THE DESIGN]" in user


def test_the_instruction_no_longer_asks_for_the_impossible():
    from app.services import review_layers

    artifact = type("A", (), {"kind": "notes", "grade": "grade-pp1",
                              "subject": "CRE", "strand_name": "",
                              "sub_strand_name": "", "version": 1,
                              "content": {}})()
    system = review_layers.build_messages(artifact, 2)[0]["content"]

    assert "a page:line address that is not in the excerpt" not in system
    assert "the resolution block below marks as NOT found" in system
    assert "false accusation" in system


def test_the_review_route_loads_the_page_addressed_design():
    source = (BACKEND / "app/routes/artifacts.py").read_text()
    route = source[source.index("def review_artifact"):]
    route = route[: route.index("@router.post", 10)]

    assert "design_source.resolve(artifact.grade, artifact.subject)" in route
    assert "design_source_text=design_source_text" in route


# ── a real address lending its authority to an invented sentence ────────────

OUR_GOD = """[PAGE 203]
203:10  1.1
203:11  Our God
203:12  (7 lessons)
203:19  God,
203:20  b) practice saying
203:21  short prayers,
203:22  c) appreciate God
203:23  as a loving
203:24  heavenly father.
"""


def _quoted(ref: str, quote: str) -> dict:
    return {"modules": [{"citations": [
        {"ref": ref, "claim": "a claim", "quote": quote}]}]}


def test_a_quote_that_is_not_at_the_address_is_caught():
    """The guide cited 203:11 — a line reading "Our God" — for the sentence
    "By the end of the sub-strand, the learner should be able to: identify
    three qualities of God." The address resolved, so the reviewer called the
    citation correct and scored factual_correctness 95.

    This is the one fabrication that survives being checked."""
    evidence = citation_evidence.resolve(
        _quoted("203:11", "By the end of the sub-strand, the learner should be "
                          "able to: identify three qualities of God."),
        OUR_GOD,
    )
    row = evidence["citations"][0]

    assert row["status"] == "ADDRESS REAL, QUOTE NOT THERE"
    assert evidence["misquoted"] == 1


def test_a_quote_wrapped_across_design_lines_still_verifies():
    """KICD pages break mid-sentence: "b) practice saying" / "short prayers,"
    is one outcome over two lines. Flagging that as invented would restart the
    false-accusation loop this module exists to end."""
    evidence = citation_evidence.resolve(
        _quoted("203:20", "practice saying short prayers."), OUR_GOD)

    assert evidence["citations"][0]["status"] == "VERIFIED"


def test_a_quote_running_past_the_displayed_window_still_verifies():
    """203:22 shows only "c) appreciate God"; the sentence finishes two lines
    later. Matching uses a wider window than is displayed for exactly this."""
    evidence = citation_evidence.resolve(
        _quoted("203:22", "appreciate God as a loving heavenly father."),
        OUR_GOD)

    assert evidence["citations"][0]["status"] == "VERIFIED"


def test_a_short_quote_is_not_judged_either_way():
    evidence = citation_evidence.resolve(_quoted("203:11", "Our God"), OUR_GOD)

    assert evidence["citations"][0]["status"] == "VERIFIED"
    assert "quote_support" not in evidence["citations"][0]


def test_the_block_shows_the_invented_sentence_beside_the_real_line():
    rendered = citation_evidence.render(citation_evidence.resolve(
        _quoted("203:11", "By the end of the sub-strand, the learner should be "
                          "able to: identify three qualities of God."),
        OUR_GOD,
    ))

    assert "the artifact quotes:" in rendered
    assert "203:11  Our God" in rendered
    assert "The quote was written, not copied." in rendered
    assert "ADDRESS REAL, QUOTE NOT THERE" in rendered


# ── a quote that is real but cited at the wrong line ────────────────────────

SHIFTED = """[PAGE 203]
203:40  The learner is guided to:
203:41  • say the name of God in their mother tongue or
203:42  language of catchment area,
[PAGE 205]
205:12  • take a nature walk to observe things created by God
"""


def test_a_quote_found_elsewhere_is_not_called_a_fabrication():
    """The reviewer and the generator do not always read the same rendering of
    the design — a re-extraction can shift every line on a page — and a
    citation three lines out is a wrong address, not a written sentence.
    Saying "the quote was written, not copied" about text that is demonstrably
    in the document is the same false accusation this module was built to stop,
    one level further down."""
    evidence = citation_evidence.resolve(
        _quoted("203:41", "take a nature walk to observe things created by God"),
        SHIFTED)
    row = evidence["citations"][0]

    assert row["status"] == "QUOTE IS REAL, AT 205:12"
    assert row["found_at"] == "205:12"
    assert evidence["misquoted"] == 0
    assert evidence["misaddressed"] == 1


def test_a_small_drift_still_verifies_outright():
    """A citation one or two lines out is absorbed by the matching window; it
    is not worth reporting at all."""
    drifted = """[PAGE 203]
203:27  The learner is guided to:
203:28  • say the name of God in their mother tongue or
203:29  language of catchment area,
"""
    evidence = citation_evidence.resolve(
        _quoted("203:26",
                "say the name of God in their mother tongue or language of "
                "catchment area"),
        drifted)

    assert evidence["citations"][0]["status"] == "VERIFIED"


def test_a_sentence_nowhere_in_the_design_is_still_a_fabrication():
    evidence = citation_evidence.resolve(
        _quoted("203:41",
                "the learner shall recite the Nicene Creed from memory"),
        SHIFTED)

    assert evidence["citations"][0]["status"] == "ADDRESS REAL, QUOTE NOT THERE"
    assert evidence["misquoted"] == 1


def test_the_reviewer_is_told_the_two_are_different_defects():
    """The difference between a wrong page number and a written quotation is
    the whole of what factual_correctness measures."""
    rendered = citation_evidence.render(citation_evidence.resolve(
        _quoted("203:41", "take a nature walk to observe things created by God"),
        SHIFTED))

    assert "The quote is real and the address is wrong" in rendered
    assert "is NOT a fabrication" in rendered
    assert "do NOT let it drag factual_correctness down" in rendered


def test_the_search_looks_at_the_cited_page_before_the_rest():
    """A quote that appears twice should be reported where it was most nearly
    cited, not at the first page that happens to contain it."""
    twice = """[PAGE 203]
203:5  • sing songs about God in groups
203:60  • sing songs about God in groups
[PAGE 205]
205:3  • sing songs about God in groups
"""
    evidence = citation_evidence.resolve(
        _quoted("203:58", "sing songs about God in groups, all together"), twice)
    row = evidence["citations"][0]

    assert row.get("found_at", "").startswith("203:")


# ── design rows that are dicts, not strings ─────────────────────────────────


def test_a_design_row_that_is_a_dict_is_read_as_its_text():
    """`slos` come back as {"id": …, "text": …}, and str() on one produced a
    scheme of work whose outcome read "{'id': 'grade-pp1-Chr-1.1-1', 'text':
    'identify three qualities of God'}"."""
    from app.routes.curriculum import _plain

    assert _plain({"id": "x", "text": "identify three qualities of God"}) == \
        "identify three qualities of God"
    assert _plain("already a string") == "already a string"


def test_the_notes_station_normalises_design_rows_before_using_them():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert "slos=[_plain(s) for s in (slos or [])]" in source
    assert "design_experiences=[_plain(e) for e in (design_experiences or [])]" in source

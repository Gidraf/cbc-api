"""One JSON contract, whatever the document looks like.

The regex extractor reads the designs it was written against and returns
nothing for the rest — a Grade 9 Agriculture design came back with zero
sub-strands because its PDF reader flattened the four-column table. An empty
design is indistinguishable, in the console, from one nobody has run.
"""
from __future__ import annotations

from app.services import design_agent


def test_every_promised_key_is_present_however_thin_the_answer() -> None:
    """The consumer of this JSON is code, and it must not have to ask whether a
    key exists."""
    out = design_agent.shape({"subject": "Agriculture"})

    assert set(out) == {
        "subject", "subject_code", "grade", "level", "essence_statement",
        "general_learning_outcomes", "naming", "citations", "strands",
        "unreadable", "gaps",
    }
    assert out["naming"] == {"design_word": "", "uses_themes": False}
    assert out["strands"] == [] and out["gaps"] == []

    # And nothing a model can return blows it up.
    for junk in (None, "not a dict", [], 7, {"strands": "no"}):
        assert design_agent.shape(junk)["strands"] == []


def test_a_sub_strand_always_carries_the_same_fourteen_fields() -> None:
    out = design_agent.shape({"strands": [{
        "strand_name": "1.0 Conservation of Resources",
        "sub_strands": [{"sub_strand_name": "1.1 Conserving Animal Feed: Hay"}],
    }]})
    sub = out["strands"][0]["sub_strands"][0]

    assert sub["slos"] == [] and sub["citations"] == []
    assert sub["theme"] == "" and sub["allocated_time"] == ""
    assert len(sub) == 14


def test_a_nameless_sub_strand_is_dropped_not_kept_as_a_blank() -> None:
    out = design_agent.shape({"strands": [{
        "strand_name": "1.0 Conservation",
        "sub_strands": [{"sub_strand_name": "  "}, {"slos": ["x"]},
                        {"sub_strand_name": "1.1 Real"}],
    }]})
    names = [s["sub_strand_name"] for s in out["strands"][0]["sub_strands"]]
    assert names == ["1.1 Real"]


DOCUMENT = """[PAGE 12]
12:1  SUMMARY OF STRANDS AND SUB-STRANDS
12:4  1.0 Conservation of Resources 1.1 Conserving Animal Feed: Hay 12
12:5  1.2 Conserving Leftover Food 11
"""


def test_a_citation_that_does_not_resolve_is_dropped() -> None:
    """An address that does not resolve is worse than none: a reviewer clicks
    it, sees a page, and assumes the fact was read off it."""
    design = design_agent.shape({
        "subject": "Agriculture",
        "citations": [
            {"ref": "12:4", "quote": "1.0 Conservation of Resources", "claim": "the spine"},
            {"ref": "99:1", "quote": "invented", "claim": "nothing"},
        ],
        "strands": [{"strand_name": "1.0 Conservation of Resources", "sub_strands": [
            {"sub_strand_name": "1.1 Conserving Animal Feed: Hay",
             "citations": [{"ref": "12:5", "quote": "1.2 Conserving Leftover Food"},
                           {"ref": "40:9", "quote": "not in this document"}]},
        ]}],
    })

    reading = design_agent.verify(design, DOCUMENT)

    assert reading.citations_checked == 4
    assert reading.citations_resolved == 2
    assert reading.citation_percentage == 50
    assert [d["ref"] for d in reading.dropped] == ["99:1", "40:9"]
    # The surviving citations stay on the fact they belong to.
    assert [c["ref"] for c in reading.design["citations"]] == ["12:4"]
    sub = reading.design["strands"][0]["sub_strands"][0]
    assert [c["ref"] for c in sub["citations"]] == ["12:5"]
    assert "were dropped" in reading.findings[0]


def test_the_agent_only_runs_where_the_patterns_came_up_short() -> None:
    """Reading every design with a model costs a call per document for designs
    the patterns already read correctly."""
    import inspect

    from app.services.curriculum_extractor import CurriculumExtractorService

    source = inspect.getsource(CurriculumExtractorService._read_with_agent_if_thin)
    assert "if found and (not expected or found >= expected):" in source
    assert "return" in source
    # Additive only: a sub-strand the regex read keeps its SLOs.
    assert "name.lower() in have" in source
    assert "design_agent_enabled" in source


def test_a_failed_reading_keeps_what_the_patterns_found() -> None:
    import inspect

    from app.services.curriculum_extractor import CurriculumExtractorService

    source = inspect.getsource(CurriculumExtractorService._read_with_agent_if_thin)
    assert "except Exception" in source
    assert "Keeping the %d" in source


# ── the prompt, which is the actual contract ────────────────────────────────


def test_the_prompt_says_what_kicd_calls_these_at_each_level() -> None:
    """KICD does not call them the same thing at every level, and a teacher
    searching for what the cover says must find it."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["curriculum-extractor"].split())

    assert "LEARNING AREA OR SUBJECT — USE THE DESIGN'S OWN WORD" in prompt
    assert "activity area" in prompt
    assert "naming.design_word" in prompt
    assert "Never report a theme as if it were a strand" in prompt


def test_the_prompt_describes_the_document_it_will_actually_get() -> None:
    """The flattened four-column table is the failure this exists for."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["curriculum-extractor"].split())

    assert "FLATTENED" in prompt
    assert "1.1 Conserving Animal Feed: Hay" in prompt
    assert "SUMMARY TABLE IS THE SPINE" in prompt
    assert "Never return fewer sub-strands than the summary names" in prompt
    # Every key, every time.
    assert "EVERY KEY, EVERY TIME" in prompt
    assert "never absent, never null" in prompt


def test_the_prompt_requires_a_page_line_address_for_every_fact() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = " ".join(SEED_AGENT_PROMPTS["curriculum-extractor"].split())

    assert "CITE EVERYTHING, BY PAGE AND LINE" in prompt
    assert '{"ref": "12:4"' in prompt
    assert "an address that does not resolve is worse than none" in prompt


def test_the_prompt_is_written_to_langfuse_under_its_folder() -> None:
    """Edited where every other prompt is edited, and versioned the same way."""
    from app.services.prompt_sync import _all_prompts

    prompts = _all_prompts()
    assert "curriculum-extractor" in prompts
    assert "extract/curriculum" in prompts
    assert prompts["curriculum-extractor"] == prompts["extract/curriculum"]


# ── an ingest that writes nothing must not report success ───────────────────


def test_a_design_is_read_back_after_it_is_written() -> None:
    """An INSERT that ran without raising is not the same fact as a row being
    there — and every way those come apart looked like a successful ingest with
    no design at the end of it. Sixteen documents read, zero designs, no error
    anywhere.
    """
    import inspect

    from app.services.curriculum_extractor import CurriculumExtractorService

    source = inspect.getsource(CurriculumExtractorService._persist_to_db)
    write = source.index("INSERT INTO curriculum_designs")
    read_back = source.index("SELECT design_id, grade FROM curriculum_designs")
    assert write < read_back, "read it back AFTER writing it"
    assert "is not there when read back" in source
    assert "failed ingest rather than a quiet one" in source


def test_the_ingest_says_what_it_did_at_each_step() -> None:
    """"Read but no design" was diagnosed across four sessions by inference,
    because an ingest ran twenty seconds and said nothing about what it did."""
    import inspect

    from app.services.curriculum_extractor import CurriculumExtractorService

    source = inspect.getsource(CurriculumExtractorService._ingest_one)
    for narrated in ("Read the cover", "Read the structure", "Design stored",
                     "Filed to Langfuse"):
        assert f'step(\n            "{narrated}"' in source or f'step("{narrated}"' in source, narrated

    # The two that matter most say what was actually read, not that it ran.
    assert "no learning area" in source and "NO GRADE" in source
    assert "sub-strand(s) across" in source


def test_the_check_is_not_implemented_twice() -> None:
    """The one at the write is the one that can say WHICH design failed to
    land."""
    import inspect

    from app.services import dataset_ingest

    source = inspect.getsource(dataset_ingest.process_item)
    assert "reported a successful ingest and" not in source
    assert "lives in `_persist_to_db`" in source

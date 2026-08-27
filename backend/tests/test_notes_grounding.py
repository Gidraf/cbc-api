"""The note generator has to be shown the design and what the design says.

It read the stored document under the keys "raw_text"/"text"/"output". The
extractor writes it under "source_text", so the lookup always missed and every
note ever generated was written without the design in front of it — while the
prompt slot read "(Syllabus design context attached)", which said the opposite.
"""
from __future__ import annotations

import re

from app.services import design_source


def test_the_notes_route_no_longer_spells_the_lookup_itself() -> None:
    """Five copies of this query drifted apart; the fifth is why notes were
    ungrounded. One resolver, so a sixth spelling cannot appear here."""
    source = open("app/routes/curriculum.py").read()
    notes = source[source.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    assert 'raw_payload.get("raw_text")' not in notes, (
        "the design is stored under 'source_text'; this key never matched"
    )
    assert "design_source.resolve" in notes


def test_every_key_the_extractor_writes_is_read_back() -> None:
    """The contract between what ingest writes and what generation reads."""
    extractor = open("app/services/curriculum_extractor.py").read()
    written = set(re.findall(r'"(source_text|raw_text|text|output)":', extractor))

    assert "source_text" in written, "the extractor stopped writing source_text"
    assert written <= set(design_source._TEXT_KEYS), (
        f"the resolver does not read {written - set(design_source._TEXT_KEYS)}"
    )


def test_the_notes_prompt_is_handed_the_designs_own_sub_strand_detail() -> None:
    """Learning experiences, values, PCIs and the rubric were stored and then
    dropped. For pre-primary the suggested experiences ARE the lesson."""
    source = open("app/routes/curriculum.py").read()
    notes = source[source.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    for field in (
        "learning_experiences", "core_competencies", "values",
        "pertinent_contemporary_issues", "link_to_other_learning_areas",
        "assessment_rubrics",
    ):
        assert f'substrand_row.get("{field}")' in notes, f"{field} is not passed"
    assert '"design_extract"' in notes


def test_the_agriculture_worked_example_is_gone() -> None:
    """A four-hour soil-pH-and-lime-tonnage module was shown to every subject
    and grade as the model of what to produce, out-massing the level register."""
    source = open("app/routes/curriculum.py").read()
    notes = source[source.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]
    body = "\n".join(
        line for line in notes.split("\n") if not line.strip().startswith("#")
    )

    for leak in ("soil pH", "lime", "agroforestry", "GDP", "Embu County", "CaCO3"):
        assert leak.lower() not in body.lower(), f"{leak!r} still steers every subject"


def test_the_module_count_comes_from_the_design_not_from_four() -> None:
    source = open("app/routes/curriculum.py").read()
    notes = source[source.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    assert "time_allocation.parse" in notes
    assert "allocation.modules" in notes
    assert "240 instructional minutes" not in notes, "60-minute hours were hardcoded"

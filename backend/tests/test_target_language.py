"""A language lesson has to contain the language.

A Grade 6 Arabic lesson came back with the teacher saying "The first phrase is
'My name is...'. Now, say it with me: 'My name is...'". The learners repeat
English and learn no Arabic. It was substantial, on topic, at the right
register and grounded in the design — every check passed. It simply was not
the lesson.
"""
from __future__ import annotations

from app.services import target_language as tl


def test_the_language_areas_are_known_however_they_are_named() -> None:
    for spelling in ("Arabic", "Arabic Language", "ARABIC LANGUAGE"):
        assert tl.for_subject(spelling).name == "Arabic", spelling
    assert tl.for_subject("Mandarin").name == "Mandarin"
    assert tl.for_subject("KSL").name == "Kenya Sign Language"
    # Kiswahili and the indigenous languages are taught in themselves too.
    assert tl.for_subject("Kiswahili").name == "Kiswahili"
    # And a subject is not a language.
    assert tl.for_subject("Mathematics") is None
    assert tl.for_subject("Integrated Science") is None


def test_the_instruction_asks_for_all_three_parts() -> None:
    """The script alone cannot be read aloud by every teacher; the
    transliteration alone teaches a spelling that does not exist."""
    block = tl.block_for("Arabic Language")

    assert "the Arabic alphabet" in block
    assert "transliteration" in block
    assert "what it means" in block
    assert "Two of the three is not enough" in block
    # The failure is quoted, so the model is told the exact shape to avoid.
    assert "Now say it with me: 'My name is'" in block
    # English keeps the instructions around the language.
    # Wrapped in the source, so match the halves rather than the line.
    assert "English is for the INSTRUCTIONS around the language" in block
    assert "it is Arabic." in block


def test_a_signed_language_is_not_asked_for_a_script() -> None:
    """Kenya Sign Language has none, and a lesson that "writes out the sign" is
    describing a photograph."""
    block = tl.block_for("Kenya Sign Language")

    assert "no written script" in block
    assert "handshape" in block
    assert "transliteration" not in block


def test_a_subject_gets_no_block_at_all() -> None:
    assert tl.block_for("Mathematics") == ""
    assert tl.block_for("Christian Religious Education") == ""


# ── the check, against the run that prompted it ─────────────────────────────

PIECES = [
    {"title": "Introduction to Arabic Sounds", "module_number": 1,
     "say": "For example, the letter 'أ' (alif) sounds like 'a' in 'apple'. "
            "Repeat after me: 'أ' (alif)."},
    {"title": "Identifying Introduction Phrases", "module_number": 2,
     "say": "The first phrase is 'My name is...'. Now, say it with me: "
            "'My name is...'. Good. The next phrase is 'This is my friend...'."},
    {"title": "Role-Playing Introductions", "module_number": 2,
     "say": "When you introduce yourself, remember to say, 'Hello, my name is "
            "[your name].'"},
]


def _plan(n: int):
    from app.services.lesson_material import Directive, Plan
    return Plan(modules=2, directives=[
        Directive(index=i, module_number=1, module_title="L", topic=str(i),
                  instruction="write it", minutes=10) for i in range(1, n + 1)])


def test_the_check_is_per_piece_not_per_document() -> None:
    """One lesson had 'أ' (alif) in its first part and pure English three parts
    later. A document-level check passes that, because the script IS there."""
    from app.services.lesson_material import check

    report = check({"material": PIECES}, _plan(3), grade="grade-6",
                   subject="Arabic Language")

    assert len(report.unscripted) == 2
    assert {u["title"] for u in report.unscripted} == {
        "Identifying Introduction Phrases", "Role-Playing Introductions"}
    # The part that DOES carry the script is not flagged.
    assert all(u["title"] != "Introduction to Arabic Sounds" for u in report.unscripted)


def test_it_fires_only_where_it_is_decidable() -> None:
    """A French lesson written entirely in English looks, to a pattern, exactly
    like a French lesson — that one the prompt has to carry."""
    from app.services.lesson_material import check

    for subject in ("Mathematics", "French", "Kiswahili", "Kenya Sign Language"):
        report = check({"material": PIECES}, _plan(3), grade="grade-6", subject=subject)
        assert report.unscripted == [], subject


def test_the_loop_is_told_what_to_write() -> None:
    from app.services.lesson_material import check, gate_of

    gate = gate_of(check({"material": PIECES}, _plan(3), grade="grade-6",
                         subject="Arabic Language"))

    assert gate["passed"] is False
    assert any(f["aspect"] == "target_language" and f["status"] == "fail"
               for f in gate["reviewer"]["feedback"])
    directive = next(a for a in gate["next_actions"] if "English" in a)
    assert "Write every phrase they say in Arabic" in directive
    assert "transliteration and its meaning" in directive


def test_both_authoring_prompts_carry_the_slot() -> None:
    """The plan must NAME the phrases, or the material is written from
    "practise greetings" and has to invent them."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    for name in ("note-generator", "material-generator"):
        assert "{{ target_language }}" in SEED_AGENT_PROMPTS[name], name

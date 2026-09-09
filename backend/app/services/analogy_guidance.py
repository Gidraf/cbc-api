"""How to reach for an everyday example, at THIS grade and in THIS subject.

The plan prompt carried one paragraph of analogy advice for every subject and
every grade, and it was written for pre-primary Christian Religious Education:

    "A four-year-old understands God as provider through the food on their own
     table... 'God cares for you the way your mother does when she gives you
     food' is exactly the right kind of teaching, and this guide should be full
     of it."
    "Draw those analogies from the child's own world: self, family, home,
     neighbourhood, school. Not farms, industry, counties or national
     development."
    "NEVER cite a scripture reference the design does not name."

A Grade 9 Mathematics prompt was being primed with "four-year-old", "song or
story" and scripture — and the last line directly contradicted the register
three paragraphs above it, which says Grade 9 works in "school, community,
county and national contexts".

So the scope comes from the register, which already states it per level, and
the scripture rule appears only where a faith is actually in scope.
"""
from __future__ import annotations


_GENERAL = """Reach for real-life analogies and everyday examples. An idea a learner can picture is an idea they keep, and a definition they cannot picture is one they memorise and lose.

Draw them from the world this learner actually moves in: {{ world }}"""

_SCRIPTURE = """  - NEVER cite a scripture reference the design does not name. The design names its own; use those and no others. An invented chapter and verse is indistinguishable from a real one and a teacher will read it aloud to a class.
"""


def block_for(grade: str | None, subject: str = "") -> str:
    """The analogy guidance for this grade, scoped by its own register."""
    from .level_register import register_for_grade
    from .prompt_store import render

    register = register_for_grade(grade)
    world = (register.scenario_world or "").strip()
    if not world:
        world = "the learner's own school, home and community."
    return render("analogy-guidance", _GENERAL, world=world)


def scripture_rule(subject: str) -> str:
    """The scripture rule, and only where a faith is in scope.

    Telling a Mathematics prompt never to invent a chapter and verse is telling
    it about scripture, which is the one thing it had no reason to think about.
    """
    from .faith_scope import scope_for
    from .prompt_store import stored_or

    if scope_for(subject) is None:
        return ""
    return stored_or("analogy-scripture-rule", _SCRIPTURE)


def seed_prompts() -> dict[str, str]:
    return {"analogy-guidance": _GENERAL,
            "analogy-scripture-rule": _SCRIPTURE}

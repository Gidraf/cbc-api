"""No prompt is written in Python.

A prompt built in code is the one prompt nobody can read or improve without a
deploy — and the two that were built that way were the material station, whose
output a child hears verbatim, and the diagram-question agent, which writes the
questions on a printed paper.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def test_the_material_station_reads_its_prompt_from_langfuse() -> None:
    from app.services.lesson_material import AGENT, prompt_for, Directive
    from app.services.langfuse_context import langfuse_context_service
    from app.services.prompt_sync import _all_prompts

    assert AGENT == "material-generator"
    prompts = _all_prompts()
    assert AGENT in prompts
    assert langfuse_context_service.FOLDERS[AGENT] == "generate/lesson-material"
    assert "generate/lesson-material" in prompts

    directive = Directive(index=1, module_number=1, module_title="Lesson 1",
                          topic="Sounds", instruction="Model each sound.", minutes=10)
    filled = prompt_for(
        directive, register="AUDIENCE: Upper-primary learners — Grade 6.",
        faith="", language="LANGUAGE: short sentences.", notation="",
        sub_strand="Pronunciation", slos=["articulate target sounds"],
    )
    # Every slot resolved, and the register actually arrived.
    assert "{{" not in filled
    assert "Grade 6" in filled and "Pronunciation" in filled
    assert "articulate target sounds" in filled


def test_the_diagram_question_agent_reads_its_prompt_from_langfuse() -> None:
    from app.services.diagram_question_agent import AGENT, build_agent_prompt
    from app.services.prompt_sync import _all_prompts

    assert AGENT == "diagram-question-agent"
    assert AGENT in _all_prompts()
    assert "generate/diagram-questions" in _all_prompts()

    out = build_agent_prompt(
        {"scene_document": {"parts": [{"label": "Stem", "function": "supports"}]}},
        {"removed_facts": [{"slot": "A", "label": "Stem", "function": "supports"}],
         "retained_parts": [{"label": "Root"}]},
        {"grade": "grade-6", "subject": "Integrated Science",
         "strand": "Plants", "sub_strand": "Parts"},
    )
    assert "{{" not in out
    # It was written with no statement of who is answering, so a Grade 2
    # diagram and a Grade 11 one were asked about in the same words.
    assert "AUDIENCE:" in out
    assert "the part labelled A" in out


def test_no_service_assembles_a_prompt_out_of_string_literals() -> None:
    """The shape to catch: a long multi-line string that instructs a model,
    built where nobody can edit it."""
    offenders: list[str] = []
    # `=== ` anchored to a line start: that is how a prompt writes a section
    # header. Unanchored it also matched JavaScript strict equality — a
    # `display === 'true'` inside the notes renderer's KaTeX loader was
    # reported as an unseeded prompt.
    instruction = re.compile(
        r"you are (a|an|the|writing)|return only valid json|^=== ",
        re.I | re.M)

    for path in (APP / "services").rglob("*.py"):
        # These ARE the prompt store: their text is seeded to Langfuse, so it
        # is readable and editable there. Living in Python is how it gets
        # PUBLISHED, not where it hides.
        if path.name in {"langfuse_seed.py", "prompt_fragments.py", "notation.py"}:
            continue
        # A repair directive is assembled from what the last run actually
        # produced — the modules that came back thin, by name and length, and
        # the design steps nobody used. There is no fixed text to seed: every
        # sentence in it names a specific failure of a specific guide.
        if path.name == "notes_repair.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if len(text) > 400 and instruction.search(text):
                offenders.append(f"{path.name}:{node.lineno}  {text[:60]!r}")

    assert not offenders, (
        "a prompt written in Python cannot be read or improved without a "
        "deploy — seed it and load it through get_agent_prompt:\n  "
        + "\n  ".join(offenders)
    )


def test_every_seeded_prompt_reaches_langfuse_under_a_folder() -> None:
    """Nineteen prompts in a flat list is a list nobody edits."""
    from app.services.langfuse_context import langfuse_context_service
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS
    from app.services.prompt_sync import _all_prompts

    prompts = _all_prompts()
    for name in SEED_AGENT_PROMPTS:
        assert name in prompts, name
        foldered = langfuse_context_service.FOLDERS.get(name)
        assert foldered, f"{name} has no folder"
        assert prompts[foldered] == prompts[name], name

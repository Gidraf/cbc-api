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


# Which files hold the store was a hand-kept list, and a hand-kept list is a
# list that goes stale: every module that grew a `seed_prompts()` had to be
# remembered here, and one that was forgotten reported working machinery as a
# defect. The question is not WHICH FILE a literal is in. It is whether the
# literal reaches Langfuse — text that is seeded is published, wherever it is
# written, and text that is not is hidden, wherever it is written.
def _seeded_text() -> str:
    from app.services.prompt_sync import _all_prompts

    return "\n\n".join(_all_prompts().values())


# The ones that are not prompts at all.
_NOT_A_PROMPT = {
    # A repair directive is assembled from what the last run actually produced
    # — the modules that came back thin, by name and length. There is no fixed
    # text to seed: every sentence names a specific failure of a specific guide.
    "notes_repair.py",
    # A README written INTO an export bundle, read by a person unpacking a zip.
    "prompt_bundle.py",
    "export_bundle.py",
    # The master context a fresh deployment falls back to when no prompt store
    # is configured at all. Seeding it is what it is a fallback FOR.
    "langfuse_context.py",
}


def _instruction_literals(root: pathlib.Path) -> list[str]:
    """Long strings that instruct a model, excluding docstrings.

    Docstrings were counted before, so the scan reported nine module docstrings
    describing prompts alongside the prompts themselves — and a check whose
    output is mostly false alarms is a check nobody reads to the end of.
    """
    instruction = re.compile(
        r"you are (a|an|the|writing)|return only valid json|^=== |"
        r"^(WRITE|DO NOT|NEVER|ALWAYS|YOUR TASK|RULES)\b|\byou must\b",
        re.I | re.M)
    found: list[str] = []
    published = _seeded_text()
    for path in root.rglob("*.py"):
        if path.name in _NOT_A_PROMPT:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        docs = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) and body \
                    and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
        for node in ast.walk(tree):
            # An F-STRING is measured whole. This is where thirteen prompts
            # hid, including the 6,000-character directive that generates every
            # question: an f-string is a JoinedStr of many short Constants, so
            # a 6,000-character instruction built from forty 90-character
            # pieces passed a scan that measured each piece on its own.
            if isinstance(node, ast.JoinedStr):
                text = "".join(v.value for v in node.values
                               if isinstance(v, ast.Constant))
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                text = node.value
            else:
                continue
            if len(text) <= 200:
                continue
            # Seeded text is published text, whatever file it is written in.
            if text.strip() in published:
                continue
            if instruction.search(text):
                found.append(f"{path.relative_to(APP.parent)}:{node.lineno}  "
                             f"{text[:60]!r}")
    return found


def test_no_service_assembles_a_prompt_out_of_string_literals() -> None:
    """The shape to catch: a long multi-line string that instructs a model,
    built where nobody can edit it."""
    offenders = _instruction_literals(APP / "services")

    assert not offenders, (
        "a prompt written in Python cannot be read or improved without a "
        "deploy — seed it and load it through get_agent_prompt or "
        "prompt_store:\n  " + "\n  ".join(offenders)
    )


def test_no_ROUTE_assembles_a_prompt_out_of_string_literals() -> None:
    """The services were scanned and the routes were not, so the longest single
    instruction in the system — the note generator's production rules, six
    thousand characters of it — sat in `curriculum.py` and was the one prompt
    nobody could change a sentence in without a deploy."""
    offenders = _instruction_literals(APP / "routes")

    assert not offenders, (
        "prompt text in a route is prompt text nobody can edit:\n  "
        + "\n  ".join(offenders)
    )


def test_the_register_and_the_teacher_band_are_editable_without_a_deploy() -> None:
    """The two blocks a head of department is most likely to disagree with —
    what a level's learners can do, and what a teacher at that level can be
    assumed to know — needed a code change to correct."""
    from app.services.prompt_sync import _all_prompts

    prompts = _all_prompts()
    for level in ("pre-primary", "lower-primary", "upper-primary",
                  "junior-school", "senior-school"):
        assert f"register/{level}" in prompts, level
        assert f"teacher/{level}" in prompts, level


def test_the_grade_facts_inside_a_register_are_not_editable() -> None:
    """An edit that replaced them would put PP1's ages on a Grade 9 page and
    nothing would show it had happened."""
    from app.services.level_register import seed_prompts, register_block

    seeded = seed_prompts()["register/junior-school"]
    block = register_block("grade-9")

    assert "14-15 years old" in block
    assert "14-15 years old" not in seeded, "an age is a fact about the grade"
    assert "Grade 9" not in seeded, "the grade is not a property of the band"


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


def test_the_house_conventions_reach_the_prompt_store() -> None:
    """The four subject notation blocks were seeded and the house block was
    not, so the sentence forbidding PEMDAS existed only in the repository. A
    running system that had never been redeployed had never been told it —
    which is exactly what a reviewer found in the output."""
    from app.services import notation
    from app.services.prompt_sync import _all_prompts

    assert notation.HOUSE_NAME in _all_prompts()
    assert "BODMAS" in notation.for_prompt("Mathematics", grade="grade-9")
    assert "Never PEMDAS" in notation.for_prompt("Mathematics", grade="grade-9")


def test_a_blank_edit_never_removes_a_rule() -> None:
    """Blanking a prompt is almost always an accident or a half-finished edit,
    and honouring it removes the rules silently, at generation time, from every
    station at once."""
    from app.services import prompt_store

    assert prompt_store.stored_or("nothing-is-stored-here", "the default") \
        == "the default"


def test_the_scan_asks_whether_a_literal_is_PUBLISHED_not_where_it_lives() -> None:
    """A hand-kept list of store files goes stale: every module that grows a
    `seed_prompts()` has to be remembered in it, and one that is forgotten
    reports working machinery as a defect."""
    import inspect

    source = inspect.getsource(_instruction_literals)

    assert "published" in source
    assert "_IS_THE_STORE" not in source

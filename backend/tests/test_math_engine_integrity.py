"""What the maths engine must never do again.

Every test here corresponds to a defect that shipped: an engine that reported
"Solved" over a step that was the question read back, a verifier that certified
"banana", a Grade 1 formula list made of quadratics, and narration synthesised
on the request thread.
"""
from __future__ import annotations

import re

import pytest

from app.services.math_engine import solve_math_problem, verify_solution
from app.services.math_engine.formula_registry import (
    get_formulas_for_context,
    search_formulas,
)
from app.services.math_engine.latex_input import to_plain
from app.services.grade_order import normalize_grade


# ── the dispatcher actually reaches the solvers ─────────────────────────────

@pytest.mark.parametrize(
    "problem, expect",
    [
        (r"Work out: $\frac{2}{3} + \frac{1}{4}$", "11"),
        (r"Find the area of a triangle with a base of $8\text{ cm}$ "
         r"and a perpendicular height of $6\text{ cm}$.", "24"),
        (r"Solve for x: $3x + 4 = 19$", "5"),
        (r"Solve for $x$: $4(2x - 1) = 28$", "4"),
        (r"Find the GCD of 24 and 36.", "12"),
        (r"Calculate $20\%$ of 150.", "30"),
    ],
)
def test_the_latex_the_console_sends_reaches_a_real_solver(problem: str, expect: str) -> None:
    """These are the exact shapes the UI posts. Every one of them used to fall
    through to a stub, because the patterns were written for plain text and the
    console has always sent LaTeX."""
    trace = solve_math_problem(problem)

    assert not trace.unsolved, f"{problem!r} fell through to the fallback"
    assert trace.steps, "a solved problem shows its working"
    assert expect in trace.final_answer, trace.final_answer


@pytest.mark.parametrize(
    "problem",
    [
        "Name three properties of a rhombus.",
        "Explain why the sky is blue.",
        "Describe two uses of a magnet in the home.",
    ],
)
def test_a_problem_no_solver_recognises_says_so(problem: str) -> None:
    """It used to answer "Solved", with one step whose latex was the question,
    and verified=True. A narrated walkthrough was then built on top of it."""
    trace = solve_math_problem(problem)

    assert trace.unsolved
    assert trace.verified is False
    assert trace.steps == []
    assert trace.final_answer == ""
    assert trace.unsolved_reason, "an unsolved problem must explain itself"


def test_to_plain_leaves_the_mathematics_and_drops_the_markup() -> None:
    assert to_plain(r"$\frac{2}{3} + \frac{1}{4}$") == "2/3 + 1/4"
    assert to_plain(r"a base of $8\text{ cm}$") == "a base of 8 cm"
    assert to_plain(r"$5 \times 4$") == "5 * 4"
    assert to_plain(r"$\sqrt{16}$") == "sqrt(16)"
    assert to_plain("") == ""


# ── the verifier does not pass what it cannot read ──────────────────────────

@pytest.mark.parametrize(
    "problem, answer",
    [
        ("Find the area of a triangle with base 8 cm and height 6 cm", "A = 500 cm^2"),
        ("Work out 2/3 + 1/4", "banana"),
        ("Give the mean of the data", ""),
    ],
)
def test_an_answer_that_cannot_be_checked_is_not_verified(problem: str, answer: str) -> None:
    """The fallback returned verified=True with "Verified by inspection", which
    printed on the teacher's marking scheme as a checked answer."""
    result = verify_solution(problem, answer)

    assert result["verified"] is False
    assert result["method"] == "unverified"
    assert "human" in result["message"].lower() or "could not verify" in result["message"].lower()


def test_a_correct_substitution_still_verifies() -> None:
    """The fix must not make the verifier useless — real checks still pass."""
    assert verify_solution("3*x + 4 = 19", "x = 5")["verified"] is True
    assert verify_solution("3*x + 4 = 19", "x = 7")["verified"] is False


# ── grade filtering ─────────────────────────────────────────────────────────

def test_a_grade_never_receives_another_grades_formulas() -> None:
    """`"grade-1" in "grade-10"` handed Grade 1 the quadratic formula and the
    n-th term of an arithmetic progression, and withheld fraction addition."""
    for grade in ("grade-1", "Grade 1", "grade-2", "grade-9", "Grade 6", "grade-12"):
        wanted = normalize_grade(grade)
        for formula in search_formulas(grade=grade):
            tagged = {normalize_grade(g) for g in formula["grades"]}
            assert wanted in tagged, f"{grade} was offered {formula['name']}"


@pytest.mark.parametrize("grade", ["Grade 6", "grade-6", "GRADE-6", "grade 6"])
def test_every_spelling_of_a_grade_finds_the_same_formulas(grade: str) -> None:
    """The console sends "Grade 6"; the tags say "grade-6". Neither matched."""
    assert len(search_formulas(grade=grade)) == len(search_formulas(grade="grade-6"))
    assert search_formulas(grade=grade), "Grade 6 has formulas"


def test_no_formulas_for_a_grade_means_no_formulas() -> None:
    """It used to return the ENTIRE registry when the filter matched nothing,
    so a PP1 lesson was offered compound interest and the quadratic formula."""
    everything = len(search_formulas())

    for grade in ("grade-pp1", "PP1", "grade-1"):
        got = get_formulas_for_context(grade=grade)
        assert len(got) != everything, f"{grade} fell back to the whole registry"
        assert got == [], f"{grade} has no formulas tagged, so it gets none"


# ── the print renderer cannot be made to run script ─────────────────────────

def test_a_supplied_figure_cannot_carry_script() -> None:
    from app.services.math_engine.document_renderer import _safe_svg

    hostile = ('<svg onload="alert(1)"><script>alert(2)</script>'
               '<a xlink:href="javascript:alert(3)"/><circle r="5"/></svg>')
    cleaned = _safe_svg(hostile)

    assert "<script" not in cleaned.lower()
    assert "onload" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "<circle" in cleaned, "the figure itself survives"


def test_latex_keeps_its_inequalities_but_cannot_open_a_tag() -> None:
    from app.services.math_engine.document_renderer import _latex

    assert "<" not in _latex("a < b")
    assert "\\lt" in _latex("a < b")
    assert "<" not in _latex("</script><img src=x onerror=alert(1)>")


# ── narration is queued, not synthesised in the request ─────────────────────

def test_building_a_walkthrough_never_calls_the_tts_provider(monkeypatch) -> None:
    """Inline synthesis held the request open for up to 25 seconds per step."""
    from app.services.math_engine import simulation_builder
    from app.services.math_engine.objects import SolutionStep, SolutionTrace

    calls: list[str] = []
    monkeypatch.setattr(simulation_builder, "enqueue_audio",
                        lambda *a, **k: calls.append("queued") or "job_1")
    monkeypatch.setattr(simulation_builder, "execute", lambda *a, **k: None)

    def explode(*a, **k):  # pragma: no cover - the point is that it is not hit
        raise AssertionError("TTS must not run on the request thread")

    from app.services.math_engine.tts_service import tts_service
    monkeypatch.setattr(tts_service, "synthesize_step_audio", explode)

    trace = SolutionTrace(
        problem="p", final_answer="x = 5",
        steps=[SolutionStep(1, "Divide", "3x=15", "x=5", "x = 5", "Divide both sides.")],
    )
    track = simulation_builder.build_simulation_track(
        problem="p", solution_trace=trace,
        curriculum_link={"grade": "grade-6", "subject": "Mathematics"},
    )

    assert calls == ["queued"], "narration must go to the worker"
    assert track.steps[0].audio_url is None
    assert track.steps[0].duration_ms > 0, "the player needs a fallback timing"


# ── the prompts live in Langfuse ────────────────────────────────────────────

def test_the_narration_prompts_are_not_built_in_python() -> None:
    """Every prompt in this system is editable without a deploy. These two were
    the exception."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/services/math_engine/narration_agent.py").read_text()

    assert 'get_agent_prompt' in source or '_prompt(' in source
    for smell in ("Return a JSON object with key", "You are a warm, encouraging"):
        assert smell not in source, f"prompt text still hardcoded: {smell!r}"


def test_both_maths_prompts_are_seeded_and_foldered() -> None:
    from app.services.langfuse_context import langfuse_context_service
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    for agent in ("math-equation-extractor", "math-narrator"):
        assert agent in SEED_AGENT_PROMPTS
        assert "/" in langfuse_context_service.FOLDERS[agent]
        # Slots the engine actually fills.
        assert "{{ grade }}" in SEED_AGENT_PROMPTS[agent]
        assert "{{ level_register }}" in SEED_AGENT_PROMPTS[agent]


# ── the assessment audit reports what it could not check ────────────────────

def test_an_unverified_question_is_named_in_the_audit() -> None:
    from app.services.math_engine import AssessmentValidator

    report = AssessmentValidator.validate_assessment_document({
        "document_id": "doc_1",
        "questions": [
            {"question_number": 1, "marks": 3, "marking_scheme": "M1 A1 B1",
             "solution_trace": {"steps": [{"step_number": 1}], "verified": False}},
            {"question_number": 2, "marks": 3, "marking_scheme": "M1 A1 B1",
             "solution_trace": {"steps": [], "unsolved": True}},
        ],
    })

    assert not report.is_valid
    blob = " ".join(report.discrepancies)
    assert "could not be verified" in blob
    assert "not solved by any deterministic solver" in blob


def test_a_heading_level_cannot_smuggle_an_attribute() -> None:
    """`tag = f"h{level}"` put the payload straight into the tag name."""
    from app.services.math_engine.document_renderer import render_educational_document_html

    html = render_educational_document_html({
        "title": "T", "curriculum": {},
        "blocks": [{"block_type": "heading",
                    "payload": {"level": '1 onmouseover=alert(1)', "text": "Hi"}}],
    })

    assert "onmouseover" not in html
    assert "<h2>Hi</h2>" in html


def test_a_walkthrough_is_removed_when_its_grade_is_reset() -> None:
    """math_simulations was a private table no cleanup knew about, so a reset
    deleted the questions and left their walkthroughs pointing at nothing."""
    from app.services.factory_reset import DERIVED

    by_table = {t.table: t for t in DERIVED}
    target = by_table.get("math_simulations")

    assert target is not None, "walkthroughs must be resettable"
    assert target.grade_json, "and scopable to one grade"

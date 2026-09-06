"""Does the content serve the outcomes, and is it pitched at the right person?

Two prompts seeded since the beginning that nothing ever called. Both answer a
question the mechanical gates cannot:

  `slo-aligner`    counts say how much was produced; only outcome coverage says
                   whether the curriculum was taught. Ten questions all testing
                   one outcome look identical to ten covering the sub-strand
                   until somebody checks.
  `layer-reviewer` whether it is pitched for the learner it names AND for the
                   teacher who has to read it.
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.services import content_fit


class _Response:
    def __init__(self, payload):
        self.content = json.dumps(payload)


@pytest.fixture
def agents(monkeypatch):
    seen: list[str] = []

    def _ask(agent, variables, resolved):
        seen.append(agent)
        if agent == content_fit.ALIGNER:
            return {"coverage": [{"slo": "perform basic operations",
                                  "covered": True, "strength": "full"}],
                    "uncovered": ["appreciate the use of integers"],
                    "unattached": [], "coverage_percentage": 50}
        return {"score": 88, "status": "approved",
                "feedback": [{"aspect": "pitch", "score": 0.9,
                              "status": "pass", "comment": "Right for Grade 9."}],
                "risk_flags": []}

    monkeypatch.setattr(content_fit, "_ask", _ask)
    return seen


def _check(**over):
    return content_fit.check(
        {"modules": []}, grade=over.pop("grade", "grade-9"),
        subject="Mathematics", strand="Numbers", sub_strand="Integers",
        slos=over.pop("slos", ["perform basic operations",
                               "appreciate the use of integers"]),
        resolved=object(), **over)


def test_it_reports_the_outcomes_nothing_serves(agents) -> None:
    """A false cover is worse than a known hole, because nobody goes back for
    it."""
    fit = _check()

    assert fit.uncovered == ["appreciate the use of integers"]
    assert fit.coverage_percentage == 50
    assert "have nothing serving them" in fit.summary()


def test_it_reports_whether_the_pitch_landed(agents) -> None:
    fit = _check()

    assert fit.level_score == 88
    assert fit.level_status == "approved"
    assert fit.level_feedback[0]["aspect"] == "pitch"
    assert "Pitch: approved at 88/100" in fit.summary()


def test_it_carries_the_teacher_band_it_judged_against(agents) -> None:
    """The band is the half nothing described before, and a reviewer reading
    the verdict needs to see what it was measured against."""
    fit = _check()

    assert "subject-trained junior-school teacher" in fit.teacher_band
    assert "which key on a calculator is the minus sign" in fit.teacher_band


def test_a_substrand_with_no_outcomes_says_so_rather_than_scoring_zero(agents) -> None:
    """Zero coverage and nothing to cover are different facts."""
    fit = _check(slos=[])

    assert fit.coverage_percentage == 0
    assert any("carries no learning outcomes" in e for e in fit.errors)
    assert content_fit.ALIGNER not in agents, "nothing to ask it"


def test_one_check_failing_does_not_lose_the_other(monkeypatch) -> None:
    def _ask(agent, variables, resolved):
        if agent == content_fit.ALIGNER:
            raise RuntimeError("provider down")
        return {"score": 91, "status": "approved"}

    monkeypatch.setattr(content_fit, "_ask", _ask)
    fit = _check()

    assert fit.level_score == 91
    assert any("Outcome coverage could not be measured" in e for e in fit.errors)


def test_both_failing_says_neither_ran(monkeypatch) -> None:
    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(content_fit, "_ask", _boom)
    fit = _check()

    assert not fit.ran
    assert "Neither check could be run" in fit.summary()


# ── the console ─────────────────────────────────────────────────────────────


def test_the_factory_shows_who_the_content_is_written_for() -> None:
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    factory = " ".join((frontend / "src/views/ContentFactory.tsx").read_text().split())
    panel = " ".join((frontend / "src/ui/TeacherProfile.tsx").read_text().split())

    assert "TeacherProfile" in factory
    assert "THE LEARNER" in panel and "THE TEACHER READING IT" in panel
    assert "Check the fit" in panel


def test_a_grade_with_no_band_is_told_nothing_rather_than_a_guess() -> None:
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    panel = " ".join((frontend / "src/ui/TeacherProfile.tsx").read_text().split())

    assert "rather than told a guess" in panel


def test_the_review_box_is_where_the_guide_is_read() -> None:
    """A reviewer who has just read a guide had to go and find the versions
    drawer to write a note about it."""
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    factory = " ".join((frontend / "src/views/ContentFactory.tsx").read_text().split())

    assert "ReviewerNote artifactId={newest.artifact_id}" in factory


def test_the_route_reads_the_outcomes_from_the_design() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_fit_check)

    assert "_blueprint_for(" in source
    assert 'blueprint.get("slos")' in source

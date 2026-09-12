"""The guide's own checks outrank the measured criteria.

A page read "Notes gate passed at 95/100" beside "Checks this guide did not
pass — 40/100". The gate measured words per sentence and term coverage and
never looked at what the remediation loop had found and failed to clear.
"""
from __future__ import annotations

from app.services import quality_gate as qg


class _Reviewer:
    def __init__(self):
        self.passed = True
        self.score = 95
        self.feedback = []
        self.risk_flags = []


class _Verdict:
    verdict = "approved"
    score = 95


def _gate(monkeypatch, content):
    svc = qg.QualityGateService()
    monkeypatch.setattr(svc, "_run_reviewer", lambda *a, **k: _Reviewer())
    monkeypatch.setattr(svc, "_run_approver_1", lambda *a, **k: _Verdict())
    monkeypatch.setattr(svc, "_run_approver_2", lambda *a, **k: _Verdict())
    return svc.run_layer_gate("notes", content, {}, object())


def test_a_guide_with_outstanding_findings_does_not_pass_the_gate(monkeypatch) -> None:
    out = _gate(monkeypatch, {"modules": [], "self_check": {
        "score": 40.1, "clean": False, "outstanding": ["Lesson 3 repeats lesson 1."]}})

    assert out.passed is False
    assert out.overall_score <= 40
    assert "could not clear" in out.summary_message


def test_a_clean_guide_passes_as_before(monkeypatch) -> None:
    out = _gate(monkeypatch, {"modules": [], "self_check": {"score": 100, "clean": True, "outstanding": []}})
    assert out.passed is True and out.overall_score == 95

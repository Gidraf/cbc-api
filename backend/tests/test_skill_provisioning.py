"""Deriving a teaching skill from the parent context when none exists yet."""
from __future__ import annotations

import pytest

from app.services import skill_provisioning as sp


class Skill:
    def __init__(self, subject="Agriculture", grade="grade-dte"):
        self.subject, self.grade = subject, grade
        self.persona = "A specialist"


@pytest.fixture
def classifier(monkeypatch):
    """Stand in for the profile store and the generator."""
    import app.services.content_type_classifier as ctc

    state = {"stored": None, "generated_with": None}
    monkeypatch.setattr(ctc, "get_profile_from_db", lambda s, g="all": state["stored"])

    def generate(**kwargs):
        state["generated_with"] = kwargs
        return Skill(kwargs["subject"], kwargs["grade"])

    monkeypatch.setattr(ctc, "ai_generate_profile_from_dataset", generate)
    return state


def stub_design(monkeypatch, row):
    monkeypatch.setattr(sp, "_design_context", lambda grade, subject: row)


def test_an_existing_skill_is_used_and_nothing_is_generated(classifier, monkeypatch):
    classifier["stored"] = Skill()
    stub_design(monkeypatch, {})

    skill, how = sp.ensure_skill("Agriculture", "grade-dte")
    assert how["status"] == sp.EXISTING
    assert classifier["generated_with"] is None, "an existing skill must not be regenerated"
    assert skill is not None


def test_a_missing_skill_is_derived_from_the_design(classifier, monkeypatch):
    stub_design(monkeypatch, {
        "design_id": "cd_dte_agri", "level": "Diploma",
        "essence_statement": "Agriculture underpins the Kenyan economy.",
        "general_learning_outcomes": ["apply agricultural knowledge", "rear domestic animals"],
    })

    skill, how = sp.ensure_skill("Agriculture", "grade-dte")
    assert how["status"] == sp.DERIVED
    assert skill is not None
    assert classifier["generated_with"]["essence_statement"].startswith("Agriculture underpins")
    assert classifier["generated_with"]["general_learning_outcomes"] == [
        "apply agricultural knowledge", "rear domestic animals",
    ]
    assert classifier["generated_with"]["save_to_db"] is True, "derive once, reuse thereafter"


def test_context_the_caller_already_holds_is_preferred_over_a_lookup(classifier, monkeypatch):
    stub_design(monkeypatch, {"essence_statement": "from the database", "general_learning_outcomes": ["db"]})

    sp.ensure_skill(
        "Agriculture", "grade-dte",
        essence_statement="from the caller",
        general_learning_outcomes=["caller outcome"],
    )
    assert classifier["generated_with"]["essence_statement"] == "from the caller"


def test_nothing_is_invented_when_there_is_nothing_to_derive_from(classifier, monkeypatch):
    """A persona conjured from a subject name is grounded in nothing."""
    stub_design(monkeypatch, {})

    skill, how = sp.ensure_skill("Agriculture", "grade-dte")
    assert skill is None
    assert how["status"] == sp.UNAVAILABLE
    assert "Ingest the design" in how["reason"]
    assert classifier["generated_with"] is None


def test_deriving_can_be_declined(classifier, monkeypatch):
    stub_design(monkeypatch, {"essence_statement": "something", "general_learning_outcomes": ["x"]})

    skill, how = sp.ensure_skill("Agriculture", "grade-dte", derive=False)
    assert skill is None
    assert how["status"] == sp.UNAVAILABLE
    assert classifier["generated_with"] is None


def test_a_derived_skill_is_flagged_as_unreviewed(classifier, monkeypatch):
    stub_design(monkeypatch, {"essence_statement": "something", "general_learning_outcomes": ["x"]})

    _skill, how = sp.ensure_skill("Agriculture", "grade-dte")
    assert "not been reviewed" in how["review_note"]
    assert how["derived_from"]["outcome_count"] == 1


def test_a_failure_to_derive_is_reported_not_raised(classifier, monkeypatch):
    import app.services.content_type_classifier as ctc

    stub_design(monkeypatch, {"essence_statement": "something", "general_learning_outcomes": ["x"]})
    monkeypatch.setattr(ctc, "ai_generate_profile_from_dataset",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("provider down")))

    skill, how = sp.ensure_skill("Agriculture", "grade-dte")
    assert skill is None
    assert how["status"] == sp.UNAVAILABLE
    assert "provider down" in how["reason"]


def test_a_subject_is_required(classifier):
    skill, how = sp.ensure_skill("", "grade-4")
    assert skill is None and how["status"] == sp.UNAVAILABLE

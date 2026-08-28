"""What must be true of a prompt before it serves production traffic.

Every prompt carried all five labels, so `production` and `dev` always pointed
at the same version: a bad edit was live the instant it was written and the
version history recorded no moment at which anyone could have caught it.
"""
from __future__ import annotations

import pytest

from app.services import prompt_bindings
from app.services.prompt_sync import _all_prompts
from app.services.prompt_validators import validate, validate_all

_AUTHORING = (
    "You author KICD content.\n{{ level_register }}\n{{ faith_scope }}\n"
    "Grade: {{ grade }} Subject: {{ subject }}\n" + ("Detail. " * 40) + "\nReturn ONLY valid JSON."
)


def test_every_seeded_prompt_is_promotable() -> None:
    """The suite is the gate. A prompt that cannot pass it cannot go live, so a
    failure here is a prompt that would be stuck in staging on the next deploy."""
    reports = validate_all(_all_prompts())
    blocked = {
        name: [f.message for f in r.errors]
        for name, r in reports.items() if not r.promotable
    }
    assert not blocked, f"prompts that cannot be promoted: {blocked}"


def test_an_authoring_prompt_without_a_register_is_blocked() -> None:
    """Without it the prompt's own examples set the register — this is how a
    pre-primary sub-strand came back demanding a flowchart from a child who
    cannot read."""
    report = validate("note-generator", _AUTHORING.replace("{{ level_register }}", ""))

    assert not report.promotable
    assert any(f.check == "missing_register" for f in report.errors)


def test_an_authoring_prompt_without_faith_scope_is_blocked() -> None:
    """CRE, IRE and HRE authored from one undifferentiated pool is how content
    from one faith reaches another."""
    report = validate("note-generator", _AUTHORING.replace("{{ faith_scope }}", ""))

    assert any(f.check == "missing_faith_scope" for f in report.errors)


def test_a_variable_nothing_supplies_is_blocked(monkeypatch) -> None:
    """It renders as an empty string and whatever depended on it disappears —
    silently, which is why it survived eight call sites."""
    monkeypatch.setattr(prompt_bindings, "bindings_for",
                        lambda name: {"level_register", "faith_scope", "grade", "subject"})

    report = validate("note-generator", _AUTHORING + "\n{{ design_extract }}")

    assert not report.promotable
    assert any("design_extract" in f.message for f in report.errors)


def test_an_unbalanced_placeholder_is_blocked() -> None:
    """"{{ foo }" renders literally into the model's context."""
    report = validate("note-generator", _AUTHORING + "\n{{ strand }")

    assert any(f.check == "malformed_placeholder" for f in report.errors)


def test_one_subjects_worked_example_cannot_reach_every_subject() -> None:
    """A four-hour TVET agriculture module was the model of what to produce for
    every grade and learning area."""
    report = validate(
        "note-generator",
        _AUTHORING + "\nHour 4: soil pH testing and agricultural lime requirement.",
    )

    assert not report.promotable
    assert any(f.check == "subject_bleed" for f in report.errors)


def test_another_countrys_values_are_blocked() -> None:
    """The master context once listed Care and Compassion and Understanding and
    Tolerance — Australian values, not the Kenyan eight."""
    report = validate("note-generator", _AUTHORING + "\nValues: Care and Compassion.")

    assert any(f.check == "foreign_values" for f in report.errors)


def test_a_hardcoded_hour_count_is_blocked() -> None:
    """Pre-primary allocates 30-minute lessons, and a fabricated figure is
    indistinguishable afterwards from one KICD published."""
    report = validate(
        "question-generator",
        _AUTHORING.replace("Return ONLY valid JSON.", "Allocated: 4 hours. Return ONLY valid JSON."),
    )

    assert any(f.check == "hardcoded_hours" for f in report.errors)


def test_an_extraction_prompt_needs_its_source() -> None:
    """Without it the agent reports what it recalls rather than what the
    document says — and reports it as grounded."""
    report = validate("curriculum-extractor", "Extract the curriculum blueprint. Return JSON.")

    assert any(f.check == "missing_source" for f in report.errors)


@pytest.mark.parametrize("slot", ["raw_text", "source_material_text", "document_text"])
def test_any_reasonable_name_counts_as_the_source(slot) -> None:
    report = validate("curriculum-extractor", f"Extract from {{{{ {slot} }}}}. Return ONLY valid JSON.")

    assert not any(f.check == "missing_source" for f in report.errors)


# ── Bindings are read from the code, not kept by hand ────────────────────────

def test_bindings_follow_a_local_variable() -> None:
    """Most call sites build the variables into a local first. Reading only
    inline dicts reported the note generator as binding six of its eighteen."""
    bound = prompt_bindings.bindings_for("note-generator")

    assert "design_extract" in bound
    assert "time_allocation" in bound
    assert "level_register" in bound


def test_the_context_assemblers_own_arguments_count_as_bound() -> None:
    """assemble_agent_context injects grade and subject before merging the call
    site's variables; missing that made every authoring prompt look broken."""
    bound = prompt_bindings.bindings_for("substrand-generator")

    assert {"grade", "subject", "subject_context"} <= bound


def test_a_prompt_nothing_reads_is_named() -> None:
    """layer-reviewer was pushed to Langfuse on every deploy, edited by nobody,
    and read by nothing."""
    unused = prompt_bindings.unused_agents(sorted(_all_prompts()))

    assert "BECF" not in unused, "the master context is read by its own reader"
    assert "note-generator" not in unused

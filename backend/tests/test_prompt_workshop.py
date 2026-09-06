"""Turning a complaint about the OUTPUT into a change to the PROMPT.

A reviewer writes "this explains which key on the calculator is the minus
sign". That is a defect in the prompt, not the guide — every future guide does
it again — and the route from that sentence to the prompt ran through somebody
who knew which of twenty-two prompts to open.

It proposes and stops. A prompt is the behaviour of every generator downstream
of it, and a model rewriting one on a single complaint is how a system loses a
rule nobody remembers adding.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from app.services import prompt_improver
from app.services.langfuse_seed import SEED_AGENT_PROMPTS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"
REAL = SEED_AGENT_PROMPTS["note-generator"]


# ── what a revision may not do ──────────────────────────────────────────────


def test_a_revision_that_drops_a_slot_is_refused() -> None:
    """A renamed slot binds to nothing and renders empty. The prompt still
    looks complete and the instruction is simply gone."""
    valid, problems = prompt_improver.validate(
        "note-generator", REAL, REAL.replace("{{ teacher_band }}", ""))

    assert not valid
    assert "drops teacher_band" in problems[0]
    assert "vanish with no error" in problems[0]


def test_a_revision_that_invents_a_slot_is_refused() -> None:
    valid, problems = prompt_improver.validate(
        "note-generator", REAL, REAL + "\nAlso consider {{ invented_thing }}.")

    assert not valid
    assert "nothing supplies" in problems[0]


def test_a_real_improvement_passes() -> None:
    better = REAL.replace(
        "Return ONLY valid JSON",
        "Never explain how to use a calculator.\n\nReturn ONLY valid JSON", 1)

    valid, problems = prompt_improver.validate("note-generator", REAL, better)

    assert valid, problems


def test_an_empty_revision_is_refused() -> None:
    valid, problems = prompt_improver.validate("note-generator", REAL, "   ")

    assert not valid and "empty" in problems[0]


def test_only_errors_block_a_revision() -> None:
    """A warning is a note about a prompt that will still work. Refusing over
    one would stop every improvement that made a prompt longer."""
    source = inspect.getsource(prompt_improver.validate)

    assert "report.errors" in source
    assert "would stop every improvement" in source


# ── what it asks for ────────────────────────────────────────────────────────


def test_the_improvers_own_prompt_is_not_written_in_python() -> None:
    """It was — caught by the guard that says "a prompt written in Python
    cannot be read or improved without a deploy". The tool for editing prompts
    without a deploy had its own hardcoded."""
    assert "prompt-improver" in SEED_AGENT_PROMPTS

    source = inspect.getsource(prompt_improver)
    assert "langfuse_context_service.get_agent_prompt(AGENT)" in source
    assert 'RULES = """' not in source


def test_the_rules_forbid_the_four_ways_a_revision_breaks_a_pipeline() -> None:
    rules = " ".join(SEED_AGENT_PROMPTS["prompt-improver"].split())

    assert "Never remove or rename a slot" in rules
    assert "Never add a slot" in rules
    assert "Never drop a rule you were not asked about" in rules
    assert "Never change the output schema" in rules
    # And the smallest change that fixes it, not a rewrite.
    assert "smallest change that will actually fix it" in rules


def test_it_may_say_the_prompt_already_covers_the_complaint() -> None:
    """An instruction repeated three times is a prompt nobody reads to the
    end."""
    rules = " ".join(SEED_AGENT_PROMPTS["prompt-improver"].split())

    assert "already_covered" in rules
    assert "restating it louder" in rules


def test_a_meta_prompt_is_not_given_a_learner_register() -> None:
    """It edits a prompt rather than authoring anything, so describing an
    audience it does not have would be describing nothing."""
    text = SEED_AGENT_PROMPTS["prompt-improver"]

    assert "{{ level_register }}" not in text
    assert "{{ faith_scope }}" not in text


# ── proposing, never applying ───────────────────────────────────────────────


def test_it_asks_every_provider_that_was_chosen(monkeypatch) -> None:
    """Two vendors disagree usefully: one adds a rule where the other rewrites
    a section, and the difference says which kind of fault it was."""
    asked: list[str] = []

    class _Model:
        def __init__(self, name):
            self.model = name

    def _generate(resolved, messages, **kwargs):
        asked.append(resolved.model)
        class _R:
            content = json.dumps({"revised": REAL, "changes": []})
        return _R()

    from app.services import llm_client as module
    from app.services.langfuse_context import langfuse_context_service as ctx

    monkeypatch.setattr(module.llm_client, "generate", _generate)
    monkeypatch.setattr(ctx, "get_agent_prompt",
                        lambda a: SEED_AGENT_PROMPTS.get(a, REAL))

    out = prompt_improver.propose(
        "note-generator", ["explains the calculator"],
        models=[_Model("gpt-4o-mini"), _Model("gemini-2.0-flash")], current=REAL)

    assert asked == ["gpt-4o-mini", "gemini-2.0-flash"]
    assert [p.model for p in out] == ["gpt-4o-mini", "gemini-2.0-flash"]


def test_one_provider_failing_does_not_lose_the_other(monkeypatch) -> None:
    class _Model:
        def __init__(self, name):
            self.model = name

    def _generate(resolved, messages, **kwargs):
        if resolved.model == "broken":
            raise RuntimeError("provider down")
        class _R:
            content = json.dumps({"revised": REAL, "changes": []})
        return _R()

    from app.services import llm_client as module
    from app.services.langfuse_context import langfuse_context_service as ctx

    monkeypatch.setattr(module.llm_client, "generate", _generate)
    monkeypatch.setattr(ctx, "get_agent_prompt", lambda a: REAL)

    out = prompt_improver.propose("note-generator", ["x"],
                                  models=[_Model("broken"), _Model("fine")],
                                  current=REAL)

    assert out[0].error and not out[1].error


def test_nothing_to_act_on_is_said_rather_than_guessed() -> None:
    out = prompt_improver.propose("note-generator", [], current=REAL)

    assert out[0].error == "No reviewer notes to act on."


# ── saving, without a deploy ────────────────────────────────────────────────


def test_saving_is_two_steps() -> None:
    from app.routes import pipelines

    source = inspect.getsource(pipelines.save_prompt)

    assert 'payload.confirm.strip().upper() != "APPLY"' in source
    assert '"written": False' in source


def test_an_invalid_revision_is_saved_but_not_promoted() -> None:
    """Refusing the write outright would lose the editing; promoting it would
    ship a prompt whose slots no longer bind."""
    from app.routes import pipelines

    source = inspect.getsource(pipelines.save_prompt)

    assert "promote=valid" in source
    assert "still serving the previous version" in source


def test_it_takes_effect_without_a_deploy() -> None:
    from app.routes import pipelines

    source = inspect.getsource(pipelines.save_prompt)

    assert "No deploy" in source
    assert "prompt_sync.push_one(" in source


# ── the console ─────────────────────────────────────────────────────────────


def test_the_workshop_sits_on_the_station_that_runs_the_prompt() -> None:
    factory = " ".join((FRONTEND / "src/views/ContentFactory.tsx").read_text().split())

    assert "STATION_AGENT" in factory
    assert '"note-generator"' in factory and '"question-generator"' in factory
    assert "Fix the prompt behind this" in factory


def test_it_offers_the_reviewer_notes_it_already_has() -> None:
    panel = " ".join((FRONTEND / "src/ui/PromptWorkshop.tsx").read_text().split())

    assert "useReviewerNotes" in panel
    assert "What reviewers said about what it produced" in panel


def test_it_can_ask_more_than_one_vendor() -> None:
    panel = " ".join((FRONTEND / "src/ui/PromptWorkshop.tsx").read_text().split())

    assert '["openai", "gemini", "anthropic"]' in panel


def test_saving_is_a_second_press_and_says_what_it_does() -> None:
    panel = " ".join((FRONTEND / "src/ui/PromptWorkshop.tsx").read_text().split())

    assert "Show what would change" in panel
    assert "Save it — live on the next run" in panel
    assert "Nothing is changed until you save." in panel

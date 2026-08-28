"""Prompt text is deployed code, so it ships like a migration.

The note generator gained {{ design_extract }} and {{ time_allocation }}, and
every generation served them stripped until somebody remembered to press Seed.
Nothing failed loudly: the notes were simply written without the design's own
detail, and read fine.
"""
from __future__ import annotations

import pytest

from app.services import prompt_sync


class Created:
    def __init__(self, version: int):
        self.version = version


class FakeClient:
    def __init__(self, failing: set[str] | None = None):
        self.written: list[tuple[str, list[str]]] = []
        self.failing = failing or set()

    def create_prompt(self, name, prompt, labels, **kwargs):
        if name in self.failing:
            raise RuntimeError("langfuse rejected it")
        self.written.append((name, labels))
        return Created(version=len(self.written))


@pytest.fixture
def wired(monkeypatch):
    state = {"applied": {}, "recorded": [], "client": FakeClient()}

    monkeypatch.setattr(prompt_sync, "_applied", lambda: dict(state["applied"]))
    monkeypatch.setattr(prompt_sync, "_record",
                        lambda name, digest, version: state["recorded"].append((name, digest)))
    # Prompt text that passes validation, because validation now gates
    # promotion: a prompt that fails is written to staging and production keeps
    # serving the previous version.
    valid = (
        "You are authoring KICD curriculum content.\n"
        "=== WHO THIS IS FOR ===\n{{ level_register }}\n{{ faith_scope }}\n"
        "Grade: {{ grade }}\nSubject: {{ subject }}\n"
        + "Write what the design supports and nothing it does not. " * 8
        + "\nReturn ONLY valid JSON."
    )
    monkeypatch.setattr(prompt_sync, "_all_prompts",
                        lambda: {"note-generator": valid, "strand-generator": valid})
    state["valid_text"] = valid

    settings = type("S", (), {"langfuse_public_key": "pk", "langfuse_secret_key": "sk",
                              "langfuse_host": "http://langfuse"})()
    monkeypatch.setattr("app.settings.settings", settings, raising=False)

    import sys, types
    module = types.ModuleType("langfuse")
    module.Langfuse = lambda **kwargs: state["client"]
    monkeypatch.setitem(sys.modules, "langfuse", module)
    return state


def test_a_changed_prompt_is_pushed(wired) -> None:
    report = prompt_sync.sync_prompts()

    assert report.status == "ok"
    assert len(report.pushed) == 2
    assert [n for n, _ in wired["client"].written] == ["note-generator", "strand-generator"]


def test_an_unchanged_prompt_is_not_rewritten(wired) -> None:
    """Pushing all fifteen every boot would add fifteen versions a day and make
    the version history useless."""
    wired["applied"] = {
        "note-generator": prompt_sync.content_hash(wired["valid_text"]),
        "strand-generator": prompt_sync.content_hash(wired["valid_text"]),
    }

    report = prompt_sync.sync_prompts()

    assert report.pushed == []
    assert sorted(report.unchanged) == ["note-generator", "strand-generator"]
    assert wired["client"].written == []


def test_only_the_prompt_that_changed_is_pushed(wired) -> None:
    wired["applied"] = {"strand-generator": prompt_sync.content_hash(wired["valid_text"])}

    report = prompt_sync.sync_prompts()

    assert [n for n, _ in wired["client"].written] == ["note-generator"]
    assert report.unchanged == ["strand-generator"]


def test_every_label_the_resolver_tries_is_written(wired) -> None:
    """get_prompt tries "production" and "latest" BEFORE "prod", so a version
    missing them stays invisible however new it is."""
    prompt_sync.sync_prompts()

    _, labels = wired["client"].written[0]
    for label in ("production", "latest", "prod", "staging", "dev"):
        assert label in labels, f"{label} is a label the resolver tries"
    assert set(labels) >= {"production", "latest", "prod", "staging", "dev"}


def test_a_failed_push_is_reported_not_recorded(wired) -> None:
    """Recording it as pushed is how a rewritten prompt silently keeps serving
    the old text."""
    wired["client"].failing = {"note-generator"}

    report = prompt_sync.sync_prompts()

    assert report.status == "error"
    assert report.failed[0]["prompt"] == "note-generator"
    assert "note-generator" not in [n for n, _ in wired["recorded"]]
    assert "NOT taken effect" in report.to_dict()["message"]


def test_force_rewrites_everything(wired) -> None:
    wired["applied"] = {"note-generator": prompt_sync.content_hash("NOTES v1")}

    report = prompt_sync.sync_prompts(force=True)

    assert len(report.pushed) == 2


def test_missing_credentials_skip_rather_than_fail(wired, monkeypatch) -> None:
    monkeypatch.setattr("app.settings.settings",
                        type("S", (), {"langfuse_public_key": "", "langfuse_secret_key": ""})())

    report = prompt_sync.sync_prompts()

    assert report.status == "skipped"
    assert report.pushed == []


def test_every_seeded_prompt_is_covered() -> None:
    """A prompt the sync does not know about never ships."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    covered = prompt_sync._all_prompts()
    assert set(SEED_AGENT_PROMPTS) <= set(covered)
    assert {"BECF", "cbc-master-context"} <= set(covered)


def test_a_prompt_that_fails_validation_is_staged_not_promoted(wired, monkeypatch) -> None:
    """Every prompt used to carry all five labels, so `production` and `dev`
    always pointed at the same version and a bad edit was live the instant it
    was written. There was no moment at which it could have been caught."""
    monkeypatch.setattr(
        prompt_sync, "_all_prompts",
        lambda: {"note-generator": "Write some notes about the topic. Return JSON."},
    )

    report = prompt_sync.sync_prompts()

    assert report.status == "staged"
    assert report.pushed == []
    assert len(report.staged) == 1

    _, labels = wired["client"].written[0]
    assert "staging" in labels and "dev" in labels
    assert "production" not in labels, "a prompt that failed validation went live"
    assert "prod" not in labels


def test_a_staged_prompt_says_production_is_still_the_old_text(wired, monkeypatch) -> None:
    """Reporting "ok" for a prompt that did not go live is how a rewritten
    prompt silently keeps serving the old text."""
    monkeypatch.setattr(
        prompt_sync, "_all_prompts",
        lambda: {"note-generator": "Too short to be an agent prompt."},
    )

    message = prompt_sync.sync_prompts().to_dict()["message"]

    assert "NOT promoted" in message
    assert "previous version" in message


def test_the_validation_report_travels_with_the_sync(wired, monkeypatch) -> None:
    """An operator who is told a prompt was staged needs to know why."""
    monkeypatch.setattr(
        prompt_sync, "_all_prompts", lambda: {"note-generator": "Short."},
    )

    detail = prompt_sync.sync_prompts().to_dict()["validation"]["note-generator"]

    assert detail["promotable"] is False
    assert any("level_register" in e["message"] for e in detail["errors"])


def test_seeding_no_longer_writes_a_version_per_press() -> None:
    """note-generator reached version 78 because every press of Seed rewrote all
    fifteen prompts whether or not a character had changed."""
    seed = open("app/services/langfuse_seed.py").read()

    body = seed[seed.index("def seed_langfuse"):]
    assert "client.create_prompt(" not in body, (
        "seeding must go through the hash-gated sync, not write directly"
    )
    assert "sync_prompts()" in body

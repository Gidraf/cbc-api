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
    monkeypatch.setattr(prompt_sync, "_all_prompts",
                        lambda: {"note-generator": "NOTES v1", "strand-generator": "STRANDS v1"})

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
        "note-generator": prompt_sync.content_hash("NOTES v1"),
        "strand-generator": prompt_sync.content_hash("STRANDS v1"),
    }

    report = prompt_sync.sync_prompts()

    assert report.pushed == []
    assert sorted(report.unchanged) == ["note-generator", "strand-generator"]
    assert wired["client"].written == []


def test_only_the_prompt_that_changed_is_pushed(wired) -> None:
    wired["applied"] = {"strand-generator": prompt_sync.content_hash("STRANDS v1")}

    report = prompt_sync.sync_prompts()

    assert [n for n, _ in wired["client"].written] == ["note-generator"]
    assert report.unchanged == ["strand-generator"]


def test_every_label_the_resolver_tries_is_written(wired) -> None:
    """get_prompt tries "production" and "latest" BEFORE "prod", so a version
    missing them stays invisible however new it is."""
    prompt_sync.sync_prompts()

    _, labels = wired["client"].written[0]
    assert labels[:2] == ["production", "latest"]
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

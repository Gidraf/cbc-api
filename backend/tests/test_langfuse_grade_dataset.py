"""Behaviour of get_grade_dataset when a grade's dataset is absent.

The strict branch had no coverage, so calling a property as a method got past
every test and only surfaced as a 500 in the running container.
"""
from __future__ import annotations

import pytest

from app.services import langfuse_context as lc


@pytest.fixture
def service(monkeypatch):
    svc = lc.langfuse_context_service
    svc._cache = {}
    # No client → the "dataset not found" path, which is what production hits
    # before any curriculum has been uploaded.
    monkeypatch.setattr(svc, "_client", None)
    return svc


def test_is_strict_is_a_property_not_a_method():
    """Guards the exact mistake that produced 'bool' object is not callable."""
    assert isinstance(type(lc.langfuse_context_service).__dict__["_is_strict"], property)


def test_strict_returns_nothing_rather_than_inventing_curriculum(service, monkeypatch):
    monkeypatch.setattr(lc.settings, "langfuse_env", "prod")
    assert service.get_grade_dataset("grade-pp1") == []


def test_non_strict_returns_a_flagged_placeholder(service, monkeypatch):
    monkeypatch.setattr(lc.settings, "langfuse_env", "dev")
    items = service.get_grade_dataset("grade-pp1")
    assert len(items) == 1
    # Tagged so nothing downstream mistakes the development stand-in for real
    # curriculum — dataset_ingest refuses to queue it.
    assert items[0]["is_placeholder"] is True


def test_every_grade_on_the_ladder_survives_a_missing_dataset(service, monkeypatch):
    """PP1 through DTE must all return cleanly, not raise."""
    from app.services.curriculum_catalogue import all_grade_slugs

    monkeypatch.setattr(lc.settings, "langfuse_env", "prod")
    for slug in all_grade_slugs():
        service._cache = {}
        assert service.get_grade_dataset(slug) == []

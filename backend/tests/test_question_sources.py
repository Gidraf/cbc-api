"""Every generated question is filed with who wrote it, and the bank can be
read by source — what an agent wrote beside what a provider wrote."""
from __future__ import annotations

from types import SimpleNamespace

from app.routes import questions as qr
from app.services import byom
from app.services import question_dna as qd


def test_source_fields_name_the_writer():
    assert qd._source_fields(None) == {}
    assert qd._source_fields({"provider": "openai", "model": "gpt-4.1"}) == {
        "provider": "openai", "model": "gpt-4.1", "written_by": "openai · gpt-4.1"}
    out = qd._source_fields({"provider": "agent", "model": "ollama/llama3.1",
                             "agent_task": "t1", "agent_key": "kit-antigravity", "station": "questions"})
    assert out["written_by"] == "agent · ollama/llama3.1"
    assert out["agent_task"] == "t1" and out["agent_key"] == "kit-antigravity"
    assert qd._source_label("", "") == "unrecorded"
    assert qd._source_label("agent", "agent") == "agent"


def test_written_by_reads_the_provider_response(monkeypatch):
    monkeypatch.setattr(byom, "current", lambda: None)
    resp = SimpleNamespace(provider="gemini", model="gemini-2.5-pro")
    assert qr._written_by(resp) == {"provider": "gemini", "model": "gemini-2.5-pro"}


def test_written_by_names_the_agent_task_when_one_is_driving(monkeypatch):
    task = SimpleNamespace(task_id="task_9", created_by="kit-claude", station="questions",
                           steps=[SimpleNamespace(model_used="claude-sonnet (replayed)")])
    monkeypatch.setattr(byom, "current", lambda: task)
    out = qr._written_by(SimpleNamespace(provider="agent", model="agent"))
    assert out == {"provider": "agent", "model": "claude-sonnet", "agent_task": "task_9",
                   "agent_key": "kit-claude", "station": "questions"}


def test_list_filters_by_source(monkeypatch):
    seen = {}

    def fetch_all(sql, params):
        seen["sql"], seen["params"] = sql, params
        return []
    monkeypatch.setattr(qd, "fetch_all", fetch_all)
    qd.question_dna_service.list_questions(source="agent")
    assert "provenance->>'provider' = :source" in seen["sql"]
    assert seen["params"]["source"] == "agent" and seen["params"]["source_like"] == "%agent%"


def test_sources_summary_groups_by_writer_and_status(monkeypatch):
    def fetch_all(sql, params):
        if "GROUP BY status" in sql:
            return [{"status": "draft", "n": 30}, {"status": "approved", "n": 12}]
        if "GROUP BY provider, model, status" in sql:
            return [{"provider": "agent", "model": "ollama/llama3.1", "status": "draft", "n": 20},
                    {"provider": "openai", "model": "gpt-4.1", "status": "draft", "n": 10},
                    {"provider": "openai", "model": "gpt-4.1", "status": "approved", "n": 12}]
        return [{"grade": "grade-9", "subject": "Mathematics", "n": 42}]
    monkeypatch.setattr(qd, "fetch_all", fetch_all)
    out = qd.question_dna_service.sources(grade="grade-9")
    assert out["total"] == 42 and out["by_status"] == {"draft": 30, "approved": 12}
    assert [s["label"] for s in out["sources"]] == ["openai · gpt-4.1", "agent · ollama/llama3.1"]
    assert out["sources"][0]["by_status"] == {"draft": 10, "approved": 12}
    assert out["by_grade_subject"] == [{"grade": "grade-9", "subject": "Mathematics", "n": 42}]


def test_sources_route_is_not_shadowed_by_the_question_id_route():
    from app.main import app

    seen_id = False
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.endswith("/questions/{question_id}/dna"):
            seen_id = True
        if path.endswith("/questions/sources"):
            assert not seen_id

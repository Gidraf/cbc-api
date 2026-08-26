"""The author-from-diagram endpoint, with the database and the model stubbed."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import ApiError
from app.routes import questions as questions_route
from app.services.auth import AuthContext, get_auth_context
from app.services.diagram_scene import build_scene_from_svg

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
<rect x="0" y="0" width="400" height="300" fill="#ffffff"/>
<text x="200" y="40" font-size="14">Stigma</text>
<text x="200" y="150" font-size="14">Ovary</text>
<text x="120" y="220" font-size="14">Petal</text>
</svg>"""

MODEL_SCENE = {"parts": [
    {"label": "Stigma", "function": "receives pollen during pollination", "assessable": True},
    {"label": "Ovary", "function": "contains the ovules that become seeds", "assessable": True},
    {"label": "Petal", "function": "attracts insect pollinators", "assessable": True},
]}


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(questions_route.router)

    @app.exception_handler(ApiError)
    async def _api_error(_request, exc: ApiError):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})

    # require_roles() builds a fresh dependency on every call, so overriding it
    # by identity never matches the one the route captured. Override the context
    # it depends on instead.
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(
        subject="tester", role="admin", auth_type="jwt"
    )

    row = {
        "diagram_id": "diag_flower_01",
        "title": "Parts of a flower",
        "svg_markup": SVG,
        "scene_document": build_scene_from_svg(SVG, "Parts of a flower", MODEL_SCENE),
        "storage_url": "",
        "grade": "Grade 4",
        "subject": "Science",
    }

    import app.infra.db as db
    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: dict(row))

    class _Resolved:
        provider = "openai"
        model = "gpt-4o"

    # The route imports these at call time, so patch them at their source.
    import app.services.pipeline as pipeline_module
    monkeypatch.setattr(
        pipeline_module.pipeline_orchestrator.router, "resolve_for_stage", lambda _stage: _Resolved()
    )
    return TestClient(app), monkeypatch, row


def _stub_llm(monkeypatch, payload):
    import app.services.llm_client as llm_module

    class _Resp:
        content = payload
        usage = type("U", (), {"prompt_tokens": 0, "completion_tokens": 0})()
        model = "stub"

    monkeypatch.setattr(llm_module.llm_client, "generate", lambda *a, **k: _Resp())


def test_route_returns_paper_and_marking_copies(client):
    tc, monkeypatch, _row = client
    _stub_llm(monkeypatch, {"questions": [{
        "question_text": "Study the diagram and answer the questions.",
        "slots_tested": ["A"],
        "structured_parts": [
            {"part_id": "(a)", "sub_question": "Name the part labelled A.", "marks": 1},
        ],
    }]})

    resp = tc.post("/api/v1/questions/factory/author-from-diagram", json={
        "diagram_id": "diag_flower_01", "grade": "Grade 4", "subject": "Science", "max_blanks": 1,
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["accepted"] == 1
    hidden = body["removed_facts"][0]["label"]
    assert hidden not in body["paper_svg"]
    assert hidden in body["answer_svg"]
    assert body["questions"][0]["structured_parts"][0]["model_answer"] == hidden


def test_route_reports_a_corrected_answer(client):
    tc, monkeypatch, _row = client
    _stub_llm(monkeypatch, {"questions": [{
        "question_text": "Study the diagram.",
        "slots_tested": ["A"],
        "structured_parts": [
            {"part_id": "(a)", "sub_question": "Name the part labelled A.",
             "marks": 1, "model_answer": "Anther"},
        ],
    }]})

    body = tc.post("/api/v1/questions/factory/author-from-diagram", json={
        "diagram_id": "diag_flower_01", "max_blanks": 1,
    }).json()

    assert body["counts"]["answers_corrected"] == 1
    assert "used the diagram" in body["answer_corrections"][0]


def test_route_422s_when_nothing_can_be_blanked(client, monkeypatch):
    tc, mp, row = client
    _stub_llm(mp, {"questions": []})
    import app.infra.db as db
    mp.setattr(db, "fetch_one", lambda *a, **k: {**row, "scene_document": {"parts": []}})

    resp = tc.post("/api/v1/questions/factory/author-from-diagram", json={"diagram_id": "diag_flower_01"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "UNPROCESSABLE_DIAGRAM"


def test_route_404s_for_an_unknown_diagram(client, monkeypatch):
    tc, mp, _row = client
    import app.infra.db as db
    mp.setattr(db, "fetch_one", lambda *a, **k: None)

    resp = tc.post("/api/v1/questions/factory/author-from-diagram", json={"diagram_id": "nope"})
    assert resp.status_code == 404

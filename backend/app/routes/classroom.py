"""A teacher's or parent's classroom: their own questions, online tests, the
video plan — and the public pages a student opens with a test code."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/classroom", tags=["Classroom"])
public = APIRouter(prefix="/api/v1/tests", tags=["Online tests (students)"])
watch = APIRouter(prefix="/api/v1/watch", tags=["Video streaming"])

MEMBER = require_roles("admin", "operator", "reviewer", "developer", "user")


# ── the video plan ───────────────────────────────────────────────────────────

@router.get("/plan")
def plan(auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import entitlements

    return entitlements.plan_status(auth.subject, auth.role)


@router.post("/plan")
def subscribe(auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    """Pay one period of the video plan from the wallet."""
    from ..services import billing, entitlements

    try:
        return entitlements.subscribe(auth.subject, auth.role)
    except billing.PaymentRequired as exc:
        raise_api_error("PAYMENT_REQUIRED", str(exc), detail=exc.detail())
    return {}


# ── own questions ────────────────────────────────────────────────────────────

class OwnQuestion(BaseModel):
    question_text: str
    question_type: str = "short_answer"
    stimulus_context: str = ""
    options: list[dict[str, Any]] = Field(default_factory=list)
    correct_answer: str = ""
    marking_scheme: str = ""
    model_answer: str = ""
    marks: float = 1
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""


@router.get("/questions")
def my_questions(grade: str = Query(""), subject: str = Query(""), auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import user_questions

    return {"items": user_questions.list_for(auth.subject, grade=grade, subject=subject)}


@router.post("/questions")
def add_question(payload: OwnQuestion, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import user_questions

    return user_questions.create(auth.subject, payload.model_dump())


@router.put("/questions/{question_id}")
def edit_question(question_id: str, payload: OwnQuestion, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import user_questions

    return user_questions.update(auth.subject, question_id, payload.model_dump())


@router.delete("/questions/{question_id}")
def remove_question(question_id: str, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import user_questions

    user_questions.delete(auth.subject, question_id)
    return {"ok": True}


class AddToPaper(BaseModel):
    draft_id: str
    question_ids: list[str]


@router.post("/questions/to-paper")
def add_to_paper(payload: AddToPaper, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    """Put some of your own questions on one of your papers (at the end)."""
    from ..services import exam_drafts, user_questions

    for qid in payload.question_ids:
        user_questions.get(auth.subject, qid)          # yours, or refused
    row = exam_drafts.get(payload.draft_id, f"{auth.role}:{auth.subject}")
    ids = [str(i.get("question_id")) for i in (row.get("items") or []) if isinstance(i, dict)]
    out = exam_drafts.reorder(payload.draft_id, ids + [q for q in payload.question_ids if q not in ids],
                              owner=f"{auth.role}:{auth.subject}")
    return {"draft_id": payload.draft_id, "items": len(out.get("items") or [])}


# ── online tests: the teacher ────────────────────────────────────────────────

class NewTest(BaseModel):
    draft_id: str
    title: str = ""
    per_student: int = Field(default=0, ge=0, le=200, description="Questions each student gets (0 = all)")
    minutes: int = Field(default=0, ge=0, le=600, description="Time allowed (0 = no limit)")
    show_answers: str = Field(default="after_submit", pattern="^(after_submit|after_close|never)$")
    shuffle_options: bool = True
    days_open: int = Field(default=14, ge=1, le=180)


@router.get("/tests")
def tests(auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import online_tests

    return {"tests": online_tests.list_for(auth.subject)}


@router.post("/tests")
def new_test(payload: NewTest, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    """A test from one of your bought papers: share its code or link with the class."""
    from ..services import online_tests

    return online_tests.create(owner=auth.subject, role=auth.role, draft_id=payload.draft_id, title=payload.title,
                               per_student=payload.per_student, minutes=payload.minutes, show=payload.show_answers,
                               shuffle_options=payload.shuffle_options, days_open=payload.days_open)


@router.get("/tests/{test_id}/results")
def test_results(test_id: str, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import online_tests

    out = online_tests.results(auth.subject, test_id)
    out["questions"] = online_tests.to_mark_detail(auth.subject, test_id)
    return out


class MarkRequest(BaseModel):
    attempt_id: str
    question_id: str
    score: float = Field(ge=0, le=100)


@router.post("/tests/{test_id}/mark")
def mark(test_id: str, payload: MarkRequest, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import online_tests

    return online_tests.mark_written(auth.subject, test_id, payload.attempt_id, payload.question_id, payload.score)


class StatusRequest(BaseModel):
    status: str = Field(pattern="^(open|closed)$")


@router.post("/tests/{test_id}/status")
def test_status(test_id: str, payload: StatusRequest, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    from ..services import online_tests

    return online_tests.set_status(auth.subject, test_id, payload.status)


@router.delete("/tests/{test_id}")
def delete_test(test_id: str, auth: AuthContext = Depends(MEMBER)) -> dict[str, Any]:
    """The test and every student's answers and name with it."""
    from ..services import online_tests

    online_tests.delete(auth.subject, test_id)
    return {"ok": True}


# ── online tests: the student (no account; the code, then the attempt's token) ─

class Start(BaseModel):
    name: str = Field(max_length=60)


class Submit(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


@public.get("/{code}")
def test_info(code: str, request: Request) -> dict[str, Any]:
    from ..infra.db import fetch_one
    from ..services import rate_limit

    rate_limit.hit("test_code_ip", rate_limit.client_ip(request))
    row = fetch_one("SELECT title, per_student, minutes, status, closes_at FROM online_tests WHERE code = :c",
                    {"c": code.strip().upper()[:12]})
    if not row:
        raise_api_error("NOT_FOUND", "No test has that code. Check it with your teacher.")
    return {"title": row["title"], "questions": row["per_student"], "minutes": row["minutes"],
            "open": row["status"] == "open"}


@public.post("/{code}/start")
def test_start(code: str, payload: Start, request: Request) -> dict[str, Any]:
    from ..services import online_tests, rate_limit

    rate_limit.hit("test_start_ip", rate_limit.client_ip(request))
    return online_tests.start(code[:12], payload.name)


@public.get("/attempts/{token}")
def attempt(token: str) -> dict[str, Any]:
    from ..services import online_tests

    return online_tests.resume(token[:64])


@public.post("/attempts/{token}/submit")
def attempt_submit(token: str, payload: Submit) -> dict[str, Any]:
    from ..services import online_tests

    if len(payload.answers) > 300:
        raise_api_error("VALIDATION_FAILED", "Too many answers.")
    return online_tests.submit(token[:64], payload.answers)


@public.get("/attempts/{token}/walkthrough/{question_id}", response_class=HTMLResponse)
def attempt_walkthrough(token: str, question_id: str) -> HTMLResponse:
    """The animated, narrated walkthrough of one question the student was dealt."""
    from ..services import online_tests, play_engine
    from .play import walkthrough_html

    q = online_tests.walkthrough_question(token[:64], question_id)
    data = play_engine.walkthrough(q, grade=str((q.get("curriculum") or {}).get("grade") or ""))
    return HTMLResponse(walkthrough_html(data, title=str(q.get("question_text") or "")[:80], voice="en-KE", autoplay=False))


# ── streaming a video ────────────────────────────────────────────────────────

@watch.get("/{token}")
def watch_stream(token: str, request: Request) -> Any:
    """A video, streamed: inline, uncached, by a short-lived link."""
    from fastapi.responses import Response

    from ..services import streaming

    claims = streaming.read(token)
    if not claims:
        return Response(status_code=403)
    out = streaming.stream(str(claims["obj"]), request.headers.get("range", ""))
    return out if out is not None else Response(status_code=404)

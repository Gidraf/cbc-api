"""The exam builder: a paper built step by step, previewed as it will print.

Open to every signed-in role, the `user` a signup gets included — this is
the product a school buys. A user sees their own drafts; staff see all.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

logger = logging.getLogger("cbc-exam-builder")
router = APIRouter(prefix="/api/v1/builder", tags=["Exam Builder"])

ANY = require_roles("admin", "operator", "reviewer", "developer", "user")
STAFF = {"admin", "operator"}


def _owner(auth: AuthContext) -> str:
    return f"{auth.role}:{auth.subject}"


class DraftCreate(BaseModel):
    grade: str
    subject: str
    kind: str = "topical"
    title: str = ""
    term: int | None = Field(default=None, ge=1, le=3)
    scope: dict[str, Any] = Field(default_factory=lambda: {"mode": "smart"})
    settings: dict[str, Any] | None = None


class DraftPatch(BaseModel):
    title: str | None = None
    kind: str | None = None
    grade: str | None = None
    subject: str | None = None
    term: int | None = Field(default=None, ge=1, le=3)
    scope: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


class FillRequest(BaseModel):
    count: int = Field(default=30, ge=1, le=120)
    diagram_count: int | None = Field(default=None, ge=0, le=60)
    seed: str = ""
    format: str = "auto"


class GenerateRequest(BaseModel):
    count: int = Field(default=30, ge=1, le=120)
    # One sub-strand, there and then — the row's own button.
    sub_strand: str = ""
    difficulty: str = "mixed"          # easy | medium | hard | mixed
    figures: int | None = Field(default=None, ge=0, le=60)


class OverrideRequest(BaseModel):
    fields: dict[str, Any]


class ReorderRequest(BaseModel):
    question_ids: list[str]


class ReviewRequest(BaseModel):
    provider: str = ""
    model: str = ""
    fix: bool = True


@router.get("/kinds")
def kinds(_: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts, print_settings

    return {"kinds": exam_drafts.KINDS,
            "print_presets": {k: v.to_dict() for k, v in print_settings.PRESETS.items()}}


@router.get("/drafts")
def list_drafts(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return {"drafts": exam_drafts.list_for(_owner(auth), everyone=auth.role in STAFF)}


@router.post("/drafts")
def create_draft(payload: DraftCreate, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return exam_drafts.create(owner=_owner(auth), grade=payload.grade, subject=payload.subject,
                              kind=payload.kind, title=payload.title, term=payload.term,
                              scope=payload.scope, settings=payload.settings)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    row = exam_drafts.get(draft_id, _owner(auth))
    row["scope_sub_strands"] = exam_drafts.scope_sub_strands(row)
    return row


@router.patch("/drafts/{draft_id}")
def patch_draft(draft_id: str, payload: DraftPatch, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return exam_drafts.update(draft_id, payload.model_dump(exclude_unset=True), owner=_owner(auth))


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    exam_drafts.delete(draft_id, owner=_owner(auth))
    return {"deleted": draft_id}


@router.post("/drafts/{draft_id}/duplicate")
def duplicate_draft(draft_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return exam_drafts.duplicate(draft_id, owner=_owner(auth))


@router.get("/drafts/{draft_id}/bank")
def draft_bank(draft_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """What the bank holds for each sub-strand in scope, so the builder
    can choose between picking and generating."""
    from ..services import exam_drafts

    row = exam_drafts.get(draft_id, _owner(auth))
    return {"sub_strands": exam_drafts.bank_summary(row)}


@router.post("/drafts/{draft_id}/fill")
def fill_draft(draft_id: str, payload: FillRequest, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return exam_drafts.fill(draft_id, count=payload.count, diagram_count=payload.diagram_count,
                            seed=payload.seed, format_key=payload.format, owner=_owner(auth))


@router.post("/drafts/{draft_id}/generate")
def generate_for_draft(draft_id: str, payload: GenerateRequest, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Queue the questions the scope lacks. Spends the platform's provider
    tokens; a user account may do it only if the platform allows it."""
    from ..services import exam_drafts, platform_settings

    if auth.role == "user" and not platform_settings.get("users_may_generate", False):
        raise_api_error("FORBIDDEN", "Generating new questions is not enabled for user accounts on this platform; "
                                     "choose from the bank, or ask the operator.")
    return exam_drafts.generate(draft_id, count=payload.count, sub_strand=payload.sub_strand,
                                difficulty=payload.difficulty, figures=payload.figures,
                                owner=_owner(auth), queued_by=auth.subject)


@router.get("/drafts/{draft_id}/live")
def live(draft_id: str, sub_strand: str = Query(...), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """What is happening for one sub-strand right now: the job's narration,
    the figures as each is filed, the questions as they land."""
    from ..services import exam_drafts

    row = exam_drafts.get(draft_id, _owner(auth))
    return exam_drafts.live(row, sub_strand)


@router.get("/drafts/{draft_id}/items")
def draft_items(draft_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    row = exam_drafts.get(draft_id, _owner(auth))
    return {"items": exam_drafts.items_detail(row)}


@router.put("/drafts/{draft_id}/items/{question_id}")
def override_item(draft_id: str, question_id: str, payload: OverrideRequest,
                  auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return exam_drafts.set_override(draft_id, question_id, payload.fields, owner=_owner(auth))


@router.post("/drafts/{draft_id}/order")
def reorder_items(draft_id: str, payload: ReorderRequest, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts

    return exam_drafts.reorder(draft_id, payload.question_ids, owner=_owner(auth))


@router.get("/drafts/{draft_id}/candidates")
def candidates(draft_id: str, sub_strand: str = Query(""), limit: int = Query(200, ge=1, le=500),
               auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Bank items the builder can add by hand, for one sub-strand in scope."""
    from ..services import exam_drafts, question_rows
    from ..services.question_dna import question_dna_service

    row = exam_drafts.get(draft_id, _owner(auth))
    on_paper = {str(i.get("question_id")) for i in (row.get("items") or []) if isinstance(i, dict)}
    rows = question_dna_service.list_questions(grade=str(row["grade"]), subject=str(row["subject"]),
                                               sub_strand=sub_strand or None, limit=limit)
    items = [q for q in question_rows.flatten_all(rows)
             if str(q.get("status") or "") not in ("needs_review", "rejected", "superseded")
             and str(q.get("question_id")) not in on_paper]
    return {"items": items}


@router.get("/drafts/{draft_id}/preview.html")
def preview_html(draft_id: str, request: Request, answers: bool = Query(False), with_scheme: bool = Query(False),
                 answer_sheet: bool = Query(False), auth: AuthContext = Depends(ANY)) -> Any:
    from ..services import exam_drafts, print_settings

    row = exam_drafts.get(draft_id, _owner(auth))
    # The query string wins over the saved settings, so the builder can
    # try a knob without saving it.
    merged = {**(row.get("settings") or {}), **dict(request.query_params)}
    return HTMLResponse(exam_drafts.render(row, answers=answers, with_scheme=with_scheme,
                                           answer_sheet=answer_sheet,
                                           settings=print_settings.from_params(merged)))


@router.get("/drafts/{draft_id}/preview.pdf")
def preview_pdf(draft_id: str, request: Request, answers: bool = Query(False), with_scheme: bool = Query(False),
                answer_sheet: bool = Query(False), auth: AuthContext = Depends(ANY)) -> Any:
    from ..services import exam_drafts, pdf, print_settings

    row = exam_drafts.get(draft_id, _owner(auth))
    merged = {**(row.get("settings") or {}), **dict(request.query_params)}
    html = exam_drafts.render(row, answers=answers, with_scheme=with_scheme, answer_sheet=answer_sheet,
                              settings=print_settings.from_params(merged))
    from .exams import finish_pdf, page_selection

    try:
        body = finish_pdf(pdf.from_html(html), page_selection(request))
    except pdf.PdfUnavailable as exc:
        raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", str(exc))
    name = (str(row.get("title") or draft_id).lower().replace(" ", "-")) + ("-booklet" if with_scheme else "") + ".pdf"
    return Response(content=body, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.post("/drafts/{draft_id}/review")
def review_draft(draft_id: str, payload: ReviewRequest, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts, platform_settings

    if auth.role == "user" and not platform_settings.get("users_may_generate", False):
        raise_api_error("FORBIDDEN", "AI review spends the platform's tokens and is not enabled for user "
                                     "accounts here; ask the operator.")
    return exam_drafts.queue_review(draft_id, provider=payload.provider, model=payload.model, fix=payload.fix,
                                    owner=_owner(auth), queued_by=auth.subject)


@router.post("/drafts/{draft_id}/freeze")
def freeze_draft(draft_id: str, request: Request, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import exam_drafts, platform_settings

    return exam_drafts.freeze(draft_id, created_by=auth.subject, base=platform_settings.public_base_url(request),
                              owner=_owner(auth))

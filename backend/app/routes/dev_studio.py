"""The developer studio's routes: projects (admin), the poster's LinkedIn
queue, and each project's test link — /p/<id>/ with its keyless ./cbc/ data."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/dev", tags=["Developer studio"])
demo = APIRouter(prefix="/p", tags=["Developer studio"], include_in_schema=False)
ADMIN = require_roles("admin")
POSTER = require_roles("admin", "poster")


class NewProject(BaseModel):
    idea: str = Field("", max_length=600)
    category: Literal["productivity", "games", "visualisation", "animations", "android"] = "productivity"
    provider: str = Field("", max_length=40, description="anthropic, openai, gemini, ollama, or agent (Claude Code / Codex / Antigravity through Agent tasks); empty: the default")
    model: str = Field("", max_length=80)


@router.get("/projects")
def projects(auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..services import dev_studio

    return {"projects": dev_studio.listing(), "ideas": dev_studio.IDEAS}


@router.post("/projects")
def new_project(payload: NewProject, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..services import dev_studio

    return dev_studio.create(payload.idea, category=payload.category, provider=payload.provider, model=payload.model,
                             by=str(auth.subject or ""))


@router.get("/projects/{project_id}")
def project(project_id: str, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..services import dev_studio

    try:
        return dev_studio.one(project_id)
    except ValueError as exc:
        raise_api_error("NOT_FOUND", str(exc))
    return {}


@router.post("/projects/{project_id}/retry")
def retry(project_id: str, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..services import dev_studio, job_queue

    dev_studio.one(project_id)
    job = job_queue.enqueue(dev_studio.JOB_KIND, "", "", {"artifact_id": project_id, "project_id": project_id},
                            queued_by=str(auth.subject or ""))
    job_queue.dispatch(job.job_id)
    return {"job_id": job.job_id}


@router.post("/projects/{project_id}/linkedin")
def to_linkedin(project_id: str, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..services import dev_studio

    return {"queued": dev_studio.queue_linkedin(project_id)}


@router.get("/linkedin/next")
def linkedin_next(poster_id: str = Query(""), auth: AuthContext = Depends(POSTER)) -> dict[str, Any]:
    """The next LinkedIn post — only for the active poster (with two Macs, one posts)."""
    from ..services import dev_studio, social_export

    why = social_export.standing_by(poster_id)
    if why:
        return {"post": None, "reason": why}
    return {"post": dev_studio.linkedin_next()}


class LinkedinDone(BaseModel):
    ok: bool
    url: str = ""
    error: str = ""


@router.post("/linkedin/{post_id}/done")
def linkedin_done(post_id: str, payload: LinkedinDone, auth: AuthContext = Depends(POSTER)) -> dict[str, Any]:
    from ..services import dev_studio

    dev_studio.linkedin_done(post_id, payload.ok, url=payload.url, error=payload.error)
    return {"ok": True}


# ── the test link ────────────────────────────────────────────────────────────

def _demo_limit(request: Request) -> None:
    from ..services import rate_limit

    rate_limit.hit("devdemo_ip", rate_limit.client_ip(request))


OPEN = {"Access-Control-Allow-Origin": "*"}     # the sandboxed page has an origin of its own


@demo.get("/{project_id}/cbc/curriculum")
def demo_curriculum(project_id: str, request: Request) -> JSONResponse:
    from ..services import content_api

    _demo_limit(request)
    return JSONResponse({"items": content_api.curriculum()}, headers=OPEN)


@demo.get("/{project_id}/cbc/questions")
def demo_questions(project_id: str, request: Request, grade: str = "", subject: str = "", strand: str = "",
                   sub_strand: str = "", type: str = "", limit: int = Query(10, ge=1, le=10)) -> JSONResponse:
    from ..services import content_api

    _demo_limit(request)
    rows, total = content_api.search({"grade": grade, "subject": subject, "strand": strand, "sub_strand": sub_strand,
                                      "question_type": type, "figures": "any"}, limit=limit, offset=0)
    return JSONResponse({"items": [content_api.public(r) for r in rows], "total": total}, headers=OPEN)


@demo.get("/{project_id}/cbc/questions/{question_id}")
def demo_question(project_id: str, question_id: str, request: Request) -> Any:
    from ..services import content_api

    _demo_limit(request)
    row = content_api.one(question_id)
    if not row:
        return JSONResponse({"error": "No such question."}, status_code=404, headers=OPEN)
    return JSONResponse(content_api.public(row), headers=OPEN)


@demo.get("/{project_id}")
def demo_root(project_id: str) -> RedirectResponse:
    return RedirectResponse(f"/p/{project_id}/", status_code=307)


@demo.get("/{project_id}/{path:path}")
def demo_file(project_id: str, path: str) -> Response:
    from ..services import dev_studio

    got = dev_studio.served_file(project_id, path or "index.html")
    if not got:
        return Response("Not found", status_code=404, media_type="text/plain")
    body, kind = got
    headers = {"Cache-Control": "public, max-age=300"}
    if kind == "text/html":
        # Model-written code, on the console's own address: sandboxed into an
        # origin of its own, so it can never read a signed-in console's token.
        headers["Content-Security-Policy"] = "sandbox allow-scripts allow-forms allow-popups allow-modals; frame-ancestors 'none'"
    return Response(body, media_type=kind, headers=headers)

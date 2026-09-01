"""Exam composition and the public question API.

Two audiences:

* **Operators** compose an exam from approved questions. Composition freezes a
  snapshot of the exact question versions, so reprinting next term produces the
  same paper even if the source questions have since been revised.
* **The exam builder** reads questions through ``/api/v1/public/questions``,
  authenticated by API key, filtered in SQL, and ordered along the CBC
  progression from PP1 upward rather than newest-first.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..models import now_iso
from ..services.auth import AuthContext, require_roles
from ..services.exam_renderer import DEFAULT_INSTRUCTIONS, render_html, render_markdown
from ..services.grade_order import GRADE_SEQUENCE, describe, grade_label, grade_ordinal, normalize_grade
from ..services.ids import mint_exam_id
from ..services.question_dna import question_dna_service
from ..services import diagram_svg

logger = logging.getLogger("cbc-exams")

router = APIRouter(prefix="/api/v1", tags=["Exam Builder"])


class ExamComposeRequest(BaseModel):
    title: str = "Competency-Based Assessment"
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str = ""
    time_allowed: str = "1 hour 30 minutes"
    instructions: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)


def _load_questions(question_ids: list[str]) -> list[dict[str, Any]]:
    """Load questions preserving the caller's ordering."""
    if not question_ids:
        return []
    rows = fetch_all(
        "SELECT * FROM question_dna WHERE question_id = ANY(:ids)",
        {"ids": question_ids},
    )
    by_id = {r["question_id"]: r for r in rows}
    missing = [qid for qid in question_ids if qid not in by_id]
    if missing:
        raise_api_error(
            "QUESTIONS_NOT_FOUND",
            f"{len(missing)} question(s) could not be found: {', '.join(missing[:5])}",
        )
    return [by_id[qid] for qid in question_ids]


def _load_diagrams(questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fetch every diagram the paper needs, in one query."""
    diagram_ids: set[str] = set()
    for question in questions:
        content = question.get("content") or {}
        binding = content.get("diagram") or question.get("diagram")
        if isinstance(binding, dict) and binding.get("diagram_id"):
            diagram_ids.add(str(binding["diagram_id"]))

    if not diagram_ids:
        return {}

    rows = fetch_all(
        """
        SELECT diagram_id, title, svg_markup, scene_document, storage_url, alt_text
        FROM diagram_registry WHERE diagram_id = ANY(:ids)
        """,
        {"ids": list(diagram_ids)},
    )
    # The markup lives in MinIO; the row carries the link to it.
    found = {r["diagram_id"]: diagram_svg.with_svg(r) for r in rows}

    for missing in diagram_ids - set(found):
        logger.warning("Exam references diagram %s which is not in the registry", missing)

    return found


def _exam_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "exam_id": row["exam_id"],
        "title": row["title"],
        "grade": row["grade"],
        "grade_label": grade_label(row["grade"]),
        "subject": row["subject"],
        "strand": row.get("strand", ""),
        "sub_strand": row.get("sub_strand", ""),
        "time_allowed": row.get("time_allowed", ""),
        "total_marks": row.get("total_marks", 0),
        "instructions": row.get("instructions") or DEFAULT_INSTRUCTIONS,
        "question_ids": row.get("question_ids") or [],
        "created_at": str(row.get("created_at", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/exams")
def compose_exam(
    payload: ExamComposeRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Compose a paper from approved questions and freeze its contents."""
    if not payload.question_ids:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "An exam needs at least one question.")

    questions = _load_questions(payload.question_ids)

    unapproved = [q["question_id"] for q in questions if q.get("status") != "approved"]
    if unapproved:
        raise_api_error(
            "QUESTIONS_NOT_APPROVED",
            f"{len(unapproved)} question(s) are not approved and cannot be printed: "
            f"{', '.join(unapproved[:5])}",
        )

    total_marks = sum(int((q.get("pedagogical_dna") or {}).get("max_marks", 1) or 1) for q in questions)
    grade_slug = normalize_grade(payload.grade)
    exam_id = mint_exam_id(grade_slug, payload.subject)

    # The snapshot is what makes a reprint reproducible: it records the exact
    # question versions composed today, independent of later edits.
    snapshot = {
        "frozen_at": now_iso(),
        "questions": [
            {
                "question_id": q["question_id"],
                "version": q.get("version", 1),
                "universal_id": q.get("universal_id", ""),
            }
            for q in questions
        ],
    }

    execute(
        """
        INSERT INTO exams (
            exam_id, title, grade, grade_ordinal, subject, strand, sub_strand,
            time_allowed, total_marks, instructions, question_ids, snapshot, created_by
        )
        VALUES (
            :exam_id, :title, :grade, :grade_ordinal, :subject, :strand, :sub_strand,
            :time_allowed, :total_marks, CAST(:instructions AS jsonb),
            CAST(:question_ids AS jsonb), CAST(:snapshot AS jsonb), :created_by
        )
        """,
        {
            "exam_id": exam_id,
            "title": payload.title,
            "grade": grade_slug,
            "grade_ordinal": grade_ordinal(grade_slug),
            "subject": payload.subject,
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "time_allowed": payload.time_allowed,
            "total_marks": total_marks,
            "instructions": to_json(payload.instructions or DEFAULT_INSTRUCTIONS),
            "question_ids": to_json(payload.question_ids),
            "snapshot": to_json(snapshot),
            "created_by": auth.subject,
        },
    )

    return {
        "exam_id": exam_id,
        "total_marks": total_marks,
        "question_count": len(questions),
        "render_urls": {
            "question_paper": f"/api/v1/exams/{exam_id}/render?format=html",
            "full_paper_with_scheme": f"/api/v1/exams/{exam_id}/render?format=html&include_answers=true",
            "markdown": f"/api/v1/exams/{exam_id}/render?format=markdown&include_answers=true",
        },
    }


@router.get("/exams")
def list_exams(
    grade: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if grade:
        conditions.append("grade = :grade")
        params["grade"] = normalize_grade(grade)
    if subject:
        conditions.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject

    rows = fetch_all(
        f"""
        SELECT * FROM exams WHERE {' AND '.join(conditions)}
        ORDER BY grade_ordinal ASC, subject ASC, created_at DESC
        LIMIT :limit
        """,
        params,
    )
    return {"total": len(rows), "items": [_exam_payload(r) for r in rows]}


@router.get("/exams/{exam_id}")
def get_exam(
    exam_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM exams WHERE exam_id = :eid", {"eid": exam_id})
    if not row:
        raise_api_error("NOT_FOUND", f"No exam with id {exam_id}")
    return _exam_payload(row)


@router.get("/exams/{exam_id}/render")
def render_exam(
    exam_id: str,
    format: Literal["html", "markdown", "json"] = Query(default="html"),
    include_answers: bool = Query(default=False),
    download: bool = Query(default=False),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> Any:
    """Render a frozen exam.

    HTML is print-ready A4 — the browser's own print-to-PDF produces the final
    document, with diagrams inlined so nothing depends on fetching an asset.
    """
    row = fetch_one("SELECT * FROM exams WHERE exam_id = :eid", {"eid": exam_id})
    if not row:
        raise_api_error("NOT_FOUND", f"No exam with id {exam_id}")

    exam = _exam_payload(row)
    questions = _load_questions(exam["question_ids"])
    diagrams = _load_diagrams(questions)

    if format == "json":
        return {
            "exam": exam,
            "questions": [
                {
                    "question_id": q["question_id"],
                    "universal_id": q.get("universal_id"),
                    "curriculum": q.get("curriculum_link"),
                    "pedagogy": q.get("pedagogical_dna"),
                    "content": q.get("content") if include_answers else _strip_answers(q.get("content") or {}),
                }
                for q in questions
            ],
            "diagrams": {k: {"title": v.get("title"), "svg": v.get("svg_markup")} for k, v in diagrams.items()},
        }

    if format == "markdown":
        parts = render_markdown(exam, questions, diagrams)
        body = parts["question_paper"] + (
            "\n\n<!-- PAGE BREAK -->\n\n" + parts["marking_scheme"] if include_answers else ""
        )
        media_type = "text/markdown; charset=utf-8"
        extension = "md"
    else:
        body = render_html(exam, questions, diagrams, include_answers=include_answers)
        media_type = "text/html; charset=utf-8"
        extension = "html"

    headers = {}
    if download:
        suffix = "with-scheme" if include_answers else "paper"
        headers["Content-Disposition"] = f'attachment; filename="{exam_id}-{suffix}.{extension}"'

    return Response(content=body, media_type=media_type, headers=headers)


def _strip_answers(content: dict[str, Any]) -> dict[str, Any]:
    """Question-paper view: options without the key, no model answer."""
    stripped = {k: v for k, v in content.items() if k not in {"correct_answer", "model_answer", "marking_scheme", "rubric"}}
    if isinstance(content.get("options"), list):
        stripped["options"] = [
            {"id": o.get("id"), "text": o.get("text")}
            for o in content["options"]
            if isinstance(o, dict)
        ]
    if isinstance(content.get("structured_parts"), list):
        stripped["structured_parts"] = [
            {k: v for k, v in p.items() if k != "model_answer"}
            for p in content["structured_parts"]
            if isinstance(p, dict)
        ]
    return stripped


# ─────────────────────────────────────────────────────────────────────────────
# Public read API for the exam builder
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/public/grades")
def public_list_grades(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """The CBC progression, lowest grade first, with the ordinal to sort by."""
    return {"grades": [describe(slug) for slug, _, _ in GRADE_SEQUENCE]}


@router.get("/public/questions")
def public_list_questions(
    grade: str | None = Query(default=None, description="Grade slug, e.g. grade-7"),
    subject: str | None = Query(default=None),
    strand: str | None = Query(default=None),
    sub_strand: str | None = Query(default=None),
    slo_id: str | None = Query(default=None),
    question_type: str | None = Query(default=None),
    include_answers: bool = Query(default=True, description="Include keys, model answers and rubrics"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Approved questions in curriculum order, lowest grade first.

    Ordering runs PP1 → Grade 12 → DTE, then subject, strand, sub-strand, SLO and
    ascending difficulty, which is the order a paper is assembled in. Superseded
    versions are excluded so a caller always gets the current text.
    """
    rows = question_dna_service.list_questions(
        grade=grade,
        subject=subject,
        strand=strand,
        sub_strand=sub_strand,
        slo_id=slo_id,
        question_type=question_type,
        status="approved",
        limit=limit,
        offset=offset,
        order="curriculum",
    )

    items = []
    for row in rows:
        content = row.get("content") or {}
        curriculum = row.get("curriculum_link") or {}
        item = {
            "question_id": row["question_id"],
            "universal_id": row.get("universal_id"),
            "version": row.get("version", 1),
            "display_label": row.get("display_label", ""),
            "curriculum": {
                **curriculum,
                "grade_label": grade_label(curriculum.get("grade")),
                "grade_ordinal": row.get("grade_ordinal", 999),
            },
            "pedagogy": row.get("pedagogical_dna") or {},
            "content": content if include_answers else _strip_answers(content),
            "dna": {
                "scores": (row.get("review_audit") or {}).get("scores", {}),
                "mean_score": (row.get("review_audit") or {}).get("mean_score"),
            },
            "provenance": row.get("provenance") or {},
            "updated_at": str(row.get("updated_at", "")),
        }
        items.append(item)

    return {
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if len(items) == limit else None,
        "ordering": "grade_ordinal ASC, subject, strand, sub_strand, slo_id, difficulty ASC",
        "items": items,
    }


@router.get("/public/questions/{question_id}")
def public_get_question(
    question_id: str,
    include_answers: bool = Query(default=True),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    row = question_dna_service.get_question(question_id)
    content = row.get("content") or {}
    return {
        "question_id": row["question_id"],
        "universal_id": row.get("universal_id"),
        "version": row.get("version", 1),
        "superseded_by": row.get("superseded_by"),
        "curriculum": row.get("curriculum_link") or {},
        "pedagogy": row.get("pedagogical_dna") or {},
        "content": content if include_answers else _strip_answers(content),
        "review_audit": row.get("review_audit") or {},
        "provenance": row.get("provenance") or {},
    }


@router.get("/public/diagrams/{diagram_id}/render")
def public_render_diagram(
    diagram_id: str,
    region_id: str | None = Query(default=None, description="Crop to a named region"),
    hide_layers: str = Query(default="", description="Comma-separated layer ids to strip, e.g. labels"),
    highlight: str = Query(default="", description="Comma-separated part ids to emphasise"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> Response:
    """Render a diagram variant as SVG.

    ``hide_layers=labels`` gives the unlabelled copy for a question paper; the
    same diagram without it gives the labelled copy for the marking scheme.
    """
    from ..services.diagram_scene import render_svg

    row = fetch_one(
        "SELECT diagram_id, title, svg_markup, storage_url, scene_document "
        "FROM diagram_registry WHERE diagram_id = :did",
        {"did": diagram_id},
    )
    if not row:
        raise_api_error("NOT_FOUND", f"No diagram with id {diagram_id}")

    svg = render_svg(
        diagram_svg.svg_for(row),
        row.get("scene_document") or {},
        hide_layers=[h.strip() for h in hide_layers.split(",") if h.strip()],
        region_id=region_id,
        highlight_part_ids=[h.strip() for h in highlight.split(",") if h.strip()],
    )
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/public/diagrams/{diagram_id}")
def public_get_diagram(
    diagram_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """The diagram's structure — its layers, addressable parts and regions."""
    row = fetch_one(
        """
        SELECT diagram_id, title, alt_text, tactile_description, storage_url,
               scene_document, grade, subject, reuse_count
        FROM diagram_registry WHERE diagram_id = :did
        """,
        {"did": diagram_id},
    )
    if not row:
        raise_api_error("NOT_FOUND", f"No diagram with id {diagram_id}")

    scene = row.get("scene_document") or {}
    return {
        "diagram_id": row["diagram_id"],
        "title": row.get("title", ""),
        "grade": row.get("grade", ""),
        "subject": row.get("subject", ""),
        "accessibility": {
            "alt_text": row.get("alt_text", ""),
            "tactile_description": row.get("tactile_description", ""),
        },
        "reuse_count": row.get("reuse_count", 1),
        "layers": scene.get("layers", []) if isinstance(scene, dict) else [],
        "parts": [
            {k: v for k, v in p.items() if k != "bbox"} | {"bbox": p.get("bbox")}
            for p in (scene.get("parts", []) if isinstance(scene, dict) else [])
        ],
        "regions": scene.get("regions", []) if isinstance(scene, dict) else [],
        "render_url": f"/api/v1/public/diagrams/{diagram_id}/render",
    }

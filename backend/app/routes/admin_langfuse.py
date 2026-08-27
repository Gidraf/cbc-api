from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles
from ..services.langfuse_context import langfuse_context_service
from ..services.validation import validate_grade_dataset

router = APIRouter(prefix="/api/v1/admin/langfuse", tags=["Admin Langfuse Datasets"])


class UploadContextRequest(BaseModel):
    subject: str
    subject_code: str = ""
    essence_statement: str = ""
    strands: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}


class PreviewContextRequest(BaseModel):
    grade: str
    subject: str
    agent_name: str = "note-generator"
    template_vars: dict[str, Any] = {}


class UpdateMasterContextRequest(BaseModel):
    text: str


# ── Dataset & Subject Discovery ──────────────────────────────────────────────


@router.get("/datasets")
def list_datasets(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict[str, Any]:
    datasets = langfuse_context_service.list_datasets()
    return {"datasets": datasets}


@router.get("/datasets/{grade}")
def get_grade_dataset(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(grade)
    items = langfuse_context_service.get_grade_dataset(grade_slug)
    return {"grade": grade_slug, "items": items}


class ProcessItemsRequest(BaseModel):
    item_ids: list[str] = []
    # Un-ingest only: also delete notes, diagrams, activities and questions
    # generated from the design. Off by default — that is real token spend.
    purge_generated: bool = False
    # Replace what a previous run produced instead of refusing. Off by default
    # so re-processing is always a deliberate act.
    force: bool = False


@router.get("/datasets/{grade}/diagnostics")
def grade_diagnostics(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """What is actually stored for this grade, table by table.

    Coverage and the content factory read sub-strands, so a design that ingests
    "successfully" but produces no sub-strand rows looks like nothing happened.
    This reports each table separately, and the grade each row is filed under,
    so the gap is visible instead of inferred.
    """
    from ..infra.db import fetch_all

    grade_slug = validate_grade_dataset(grade)
    alt_grade = grade_slug.replace("grade-", "")

    designs = fetch_all(
        """
        SELECT d.design_id, d.subject, d.grade, d.level, d.review_status,
               (SELECT COUNT(*) FROM curriculum_substrands s
                 WHERE s.design_id = d.design_id) AS substrand_count
        FROM curriculum_designs d
        WHERE d.grade = :grade OR d.grade = :alt_grade
        ORDER BY d.subject
        """,
        {"grade": grade_slug, "alt_grade": alt_grade},
    )

    substrands = fetch_all(
        """
        SELECT subject, strand_name, COUNT(*) AS n
        FROM curriculum_substrands
        WHERE grade = :grade OR grade = :alt_grade
        GROUP BY subject, strand_name
        ORDER BY subject, strand_name
        """,
        {"grade": grade_slug, "alt_grade": alt_grade},
    )

    # Sub-strands whose design says one grade while the row says another: the
    # symptom of a cover parsed differently from the queue it was launched from.
    orphans = fetch_all(
        """
        SELECT s.grade AS substrand_grade, d.grade AS design_grade, COUNT(*) AS n
        FROM curriculum_substrands s
        JOIN curriculum_designs d ON d.design_id = s.design_id
        WHERE (d.grade = :grade OR d.grade = :alt_grade) AND s.grade <> d.grade
        GROUP BY s.grade, d.grade
        """,
        {"grade": grade_slug, "alt_grade": alt_grade},
    )

    tracked = fetch_all(
        """
        SELECT item_id, source_item_id, status, title, resolved_subject, design_id
        FROM dataset_ingest_status WHERE grade = :grade ORDER BY title
        """,
        {"grade": grade_slug},
    )

    def count(table: str, column: str) -> int:
        rows = fetch_all(
            f"SELECT COUNT(*) AS n FROM {table} "
            f"WHERE LOWER({column}->>'grade') IN (LOWER(:grade), LOWER(:alt_grade))",
            {"grade": grade_slug, "alt_grade": alt_grade},
        )
        return int((rows[0] if rows else {}).get("n") or 0)

    return {
        "grade": grade_slug,
        "also_matching": alt_grade,
        "curriculum_designs": {"count": len(designs), "rows": designs},
        "curriculum_substrands": {
            "total": sum(int(r["n"]) for r in substrands),
            "by_subject_and_strand": substrands,
        },
        "grade_mismatches": orphans,
        "generated": {
            "substrand_resources": count("substrand_resources", "curriculum"),
            "question_dna": count("question_dna", "curriculum_link"),
        },
        "tracked_items": tracked,
        "reads_substrands_from": "curriculum_substrands WHERE grade = :grade OR grade = :alt_grade",
    }


@router.post("/datasets/{grade}/sync")
def sync_grade_dataset(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Register this grade's Langfuse dataset items for tracking."""
    from ..services.dataset_ingest import list_grade, sync_grade

    grade_slug = validate_grade_dataset(grade)
    result = sync_grade(grade_slug)
    return {"grade": grade_slug, **result, **list_grade(grade_slug)}


@router.get("/datasets/{grade}/ingest-status")
def get_grade_ingest_status(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Every tracked item for this grade and how far each has got."""
    from ..services.dataset_ingest import list_grade

    return list_grade(validate_grade_dataset(grade))


@router.post("/datasets/{grade}/select")
def select_grade_items(
    grade: str,
    payload: ProcessItemsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Mark items as queued for processing without starting them."""
    from ..services.dataset_ingest import PENDING, SELECTED, list_grade, set_status

    grade_slug = validate_grade_dataset(grade)
    for item_id in payload.item_ids:
        set_status(item_id, SELECTED)
    if not payload.item_ids:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "No item_ids given to select.")
    return {"grade": grade_slug, "selected": len(payload.item_ids), **list_grade(grade_slug)}


@router.post("/datasets/{grade}/process")
def process_grade_items(
    grade: str,
    payload: ProcessItemsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Ingest the named items, one at a time.

    Deliberately manual and sequential: a bad extraction should stop at one
    document rather than propagate across a grade. Each item reports its own
    outcome, so one failure does not discard the successes before it.
    """
    from ..services.dataset_ingest import AlreadyIngested, list_grade, process_item

    grade_slug = validate_grade_dataset(grade)
    if not payload.item_ids:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "No item_ids given to process.")

    results = []
    for item_id in payload.item_ids:
        try:
            outcome = process_item(item_id, force=payload.force)
            results.append({
                "item_id": item_id,
                "ok": True,
                "replaced": payload.force,
                "subject": outcome.get("subject"),
                "grade": outcome.get("grade"),
                "design_id": outcome.get("design_id"),
            })
        except AlreadyIngested as exc:
            # Not a failure: the work is already done. Reported separately so
            # the caller can offer to replace rather than showing an error.
            results.append({
                "item_id": item_id, "ok": False, "already_ingested": True, "error": str(exc),
            })
        except Exception as exc:  # noqa: BLE001
            results.append({"item_id": item_id, "ok": False, "error": str(exc)[:300]})

    return {
        "grade": grade_slug,
        "processed": sum(1 for r in results if r["ok"]),
        "skipped_already_ingested": sum(1 for r in results if r.get("already_ingested")),
        "failed": sum(1 for r in results if not r["ok"] and not r.get("already_ingested")),
        "results": results,
        **list_grade(grade_slug),
    }


@router.post("/datasets/{grade}/uningest")
def uningest_grade_items(
    grade: str,
    payload: ProcessItemsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Remove what these items produced and return them to pending."""
    from ..services.dataset_ingest import list_grade, uningest_item

    grade_slug = validate_grade_dataset(grade)
    if not payload.item_ids:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "No item_ids given to un-ingest.")

    results = []
    for item_id in payload.item_ids:
        try:
            results.append({"item_id": item_id, "ok": True,
                            **uningest_item(item_id, purge_generated=payload.purge_generated)})
        except Exception as exc:  # noqa: BLE001
            results.append({"item_id": item_id, "ok": False, "error": str(exc)[:300]})

    totals: dict[str, int] = {}
    for r in results:
        for key, value in (r.get("removed") or {}).items():
            totals[key] = totals.get(key, 0) + int(value)

    return {
        "grade": grade_slug,
        "uningested": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "removed": totals,
        "results": results,
        **list_grade(grade_slug),
    }


@router.post("/datasets/{grade}/retry")
def retry_failed_items(
    grade: str,
    payload: ProcessItemsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Return failed items to pending so they can be run again."""
    from ..services.dataset_ingest import FAILED, PENDING, list_grade, set_status

    grade_slug = validate_grade_dataset(grade)
    state = list_grade(grade_slug)
    targets = payload.item_ids or [
        row["item_id"] for row in state["items"] if row["status"] == FAILED
    ]
    for item_id in targets:
        set_status(item_id, PENDING, error="")
    return {"grade": grade_slug, "reset": len(targets), **list_grade(grade_slug)}


@router.get("/datasets/{grade}/subjects")
def get_grade_subjects(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Subjects KICD publishes for this grade, each marked ingested or missing."""
    grade_slug = validate_grade_dataset(grade)
    summary = langfuse_context_service.get_grade_subject_summary(grade_slug)
    return {"grade": grade_slug, **summary}


@router.get("/datasets/{grade}/{subject}")
def get_subject_context(
    grade: str,
    subject: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(grade)
    context = langfuse_context_service.get_subject_context(grade_slug, subject)
    return {"grade": grade_slug, "subject": subject, "context": context}


@router.get("/datasets/{grade}/{subject}/strands")
@router.get("/datasets/{grade}/subjects/{subject}/strands")
def get_subject_strands(
    grade: str,
    subject: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Returns the strands and sub-strands tree for a subject in a grade."""
    grade_slug = validate_grade_dataset(grade)
    strands = langfuse_context_service.get_strands_for_subject(grade_slug, subject)
    return {"grade": grade_slug, "subject": subject, "strands": strands}


@router.get("/datasets/{grade}/{subject}/strands/{strand}/{sub_strand}/slos")
@router.get("/datasets/{grade}/subjects/{subject}/strands/{strand}/substrands/{sub_strand}/slos")
def get_substrand_slos(
    grade: str,
    subject: str,
    strand: str,
    sub_strand: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Returns SLO IDs for a specific sub-strand."""
    grade_slug = validate_grade_dataset(grade)
    slos = langfuse_context_service.get_slos_for_substrand(grade_slug, subject, strand, sub_strand)
    return {
        "grade": grade_slug,
        "subject": subject,
        "strand": strand,
        "sub_strand": sub_strand,
        "slos": slos,
    }


# ── Subject Context Upload ───────────────────────────────────────────────────


@router.post("/datasets/{grade}")
def upload_subject_context(
    grade: str,
    payload: UploadContextRequest,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(grade)
    result = langfuse_context_service.upload_dataset_item(grade_slug, payload.model_dump())
    return result


# ── Global Master Context ────────────────────────────────────────────────────


@router.get("/context/master")
def get_master_context(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Returns the current Global BECF Context with metadata."""
    try:
        metadata = langfuse_context_service.get_master_context_metadata()
        return metadata
    except Exception:  # noqa: BLE001
        text = langfuse_context_service.get_master_context()
        return {"text": text, "prompt_name": "cbc-master-context", "prompt_version": "unknown", "prompt_label": "unknown"}


@router.put("/context/master")
def update_master_context(
    payload: UpdateMasterContextRequest,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Update the Global BECF Context in Langfuse."""
    result = langfuse_context_service.update_master_context(payload.text)
    return result


@router.get("/context/master-preview")
def preview_master_context(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    master = langfuse_context_service.get_master_context()
    return {"master_context": master}


# ── Prompt Preview & Assembly ────────────────────────────────────────────────


@router.post("/context/preview")
def preview_assembled_context(
    payload: PreviewContextRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(payload.grade)
    compiled = langfuse_context_service.assemble_agent_context(
        agent_name=payload.agent_name,
        grade_slug=grade_slug,
        subject=payload.subject,
        template_vars=payload.template_vars,
    )
    return {
        "prompt_name": compiled.prompt_name,
        "prompt_version": compiled.prompt_version,
        "prompt_label": compiled.prompt_label,
        "prompt_hash": compiled.prompt_hash,
        "messages": compiled.messages,
    }


# ── Langfuse Seed ────────────────────────────────────────────────────────────


@router.post("/seed")
def trigger_langfuse_seed(
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Seed Langfuse with initial prompts and empty grade datasets."""
    from ..services.langfuse_seed import seed_langfuse

    result = seed_langfuse()
    return result


@router.post("/sync-prompts")
def trigger_prompt_sync(
    force: bool = False,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Push prompts whose text has changed since they were last written.

    This runs at startup on its own, keyed on the content hash — the same way
    schema migrations run. It is here for the case where a deploy could not
    reach Langfuse and the sync has to be retried without a restart.

    `force=true` rewrites every prompt regardless of hash.
    """
    from ..services.prompt_sync import sync_prompts

    return sync_prompts(force=force).to_dict()


@router.get("/prompt-status")
def read_prompt_status(
    _: AuthContext = Depends(require_roles("admin", "operator", "developer")),
) -> dict[str, Any]:
    """Which prompts are current, and which are waiting to be pushed."""
    from ..infra.db import fetch_all
    from ..services.prompt_sync import _all_prompts, content_hash

    try:
        rows = fetch_all("SELECT name, content_hash, remote_version, applied_at "
                         "FROM prompt_versions") or []
    except Exception:  # noqa: BLE001
        rows = []
    applied = {str(r["name"]): r for r in rows}

    prompts = []
    for name, text in sorted(_all_prompts().items()):
        record = applied.get(name)
        prompts.append({
            "name": name,
            "current": bool(record) and record["content_hash"] == content_hash(text),
            "remote_version": (record or {}).get("remote_version"),
            "applied_at": (record or {}).get("applied_at"),
        })
    return {
        "prompts": prompts,
        "pending": [p["name"] for p in prompts if not p["current"]],
        "all_current": all(p["current"] for p in prompts),
    }


# ── Dataset Clearing & Cascading Children Removal ───────────────────────────


class ClearDatasetRequest(BaseModel):
    clear_mode: str = "cascade_all"  # "datasets_only" | "cascade_all"
    subject: str | None = None
    strand: str | None = None


@router.get("/datasets/{grade}/inspect-deletion")
def inspect_dataset_deletion(
    grade: str,
    subject: str | None = None,
    strand: str | None = None,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Inspects and counts all children (strands, substrands, 4-hour notes, visuals, practicals, questions) before deletion."""
    from ..infra.db import fetch_all, fetch_one
    from ..services.validation import validate_grade_dataset

    grade_slug = validate_grade_dataset(grade)
    alt_grade = grade_slug.replace("grade-", "")

    # 1. Inspect curriculum substrands
    query = "SELECT strand_name, sub_strand_name, subject FROM curriculum_substrands WHERE (grade = :grade OR grade = :alt_grade)"
    params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        query += " AND LOWER(subject) = LOWER(:subject)"
        params["subject"] = subject.strip()
    if strand:
        query += " AND LOWER(strand_name) = LOWER(:strand)"
        params["strand"] = strand.strip()

    ss_rows = fetch_all(query, params)
    subjects_set: set[str] = set()
    strands_set: set[str] = set()
    substrands_list: list[dict[str, str]] = []
    for r in ss_rows:
        if r.get("subject"):
            subjects_set.add(r["subject"])
        if r.get("strand_name"):
            strands_set.add(r["strand_name"])
        if r.get("sub_strand_name"):
            substrands_list.append({
                "subject": r.get("subject", ""),
                "strand": r.get("strand_name", ""),
                "sub_strand": r["sub_strand_name"],
            })

    # 2. Inspect generated substrand_resources
    res_query = "SELECT bundle_id, curriculum, notes, diagrams, activities, questions, status FROM substrand_resources WHERE (LOWER(curriculum->>'grade') = LOWER(:grade) OR LOWER(curriculum->>'grade') = LOWER(:alt_grade))"
    res_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        res_query += " AND LOWER(curriculum->>'subject') = LOWER(:subject)"
        res_params["subject"] = subject.strip()
    if strand:
        res_query += " AND LOWER(curriculum->>'strand') = LOWER(:strand)"
        res_params["strand"] = strand.strip()

    res_rows = fetch_all(res_query, res_params)
    total_notes_hours = 0
    total_visuals = 0
    total_activities = 0
    total_questions = 0
    generated_bundles: list[dict[str, Any]] = []

    for r in res_rows:
        notes_data = r.get("notes") or {}
        h_mods = notes_data.get("hour_modules") or notes_data.get("key_concepts") or []
        hours_count = len(h_mods) if isinstance(h_mods, list) and len(h_mods) > 0 else (4 if notes_data.get("full_lecture_notes") else 0)
        total_notes_hours += hours_count

        diagrams_list = r.get("diagrams") or []
        total_visuals += len(diagrams_list) if isinstance(diagrams_list, list) else 0

        activities_list = r.get("activities") or []
        total_activities += len(activities_list) if isinstance(activities_list, list) else 0

        questions_list = r.get("questions") or []
        total_questions += len(questions_list) if isinstance(questions_list, list) else 0

        curr = r.get("curriculum") or {}
        generated_bundles.append({
            "bundle_id": r.get("bundle_id"),
            "subject": curr.get("subject", ""),
            "strand": curr.get("strand", ""),
            "sub_strand": curr.get("sub_strand", ""),
            "hours_count": hours_count,
            "visuals_count": len(diagrams_list) if isinstance(diagrams_list, list) else 0,
            "activities_count": len(activities_list) if isinstance(activities_list, list) else 0,
            "questions_count": len(questions_list) if isinstance(questions_list, list) else 0,
            "status": r.get("status", "draft"),
        })

    # 3. Inspect standalone question_dna
    q_count_row = fetch_one(
        """
        SELECT COUNT(*) AS total FROM question_dna
        WHERE (LOWER(curriculum_link->>'grade') = LOWER(:grade) OR LOWER(curriculum_link->>'grade') = LOWER(:alt_grade))
        """,
        {"grade": grade_slug, "alt_grade": alt_grade},
    )
    standalone_questions_count = q_count_row.get("total", 0) if q_count_row else 0

    return {
        "grade": grade_slug,
        "filter_subject": subject or "All Subjects",
        "filter_strand": strand or "All Strands",
        "dataset_children": {
            "subjects_count": len(subjects_set),
            "subjects_list": sorted(list(subjects_set)),
            "strands_count": len(strands_set),
            "strands_list": sorted(list(strands_set)),
            "substrands_count": len(substrands_list),
            "substrands_list": substrands_list[:50],
        },
        "generations_children": {
            "bundles_count": len(res_rows),
            "total_notes_hours": total_notes_hours,
            "total_visuals": total_visuals,
            "total_activities": total_activities,
            "total_questions": total_questions + standalone_questions_count,
            "generated_bundles": generated_bundles,
        },
    }


@router.post("/datasets/{grade}/clear")
def clear_grade_dataset(
    grade: str,
    payload: ClearDatasetRequest,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Clears dataset definitions only or cascades to delete all generated lesson notes, visuals, activities, and questions."""
    from ..infra.db import execute
    from ..services.validation import validate_grade_dataset

    grade_slug = validate_grade_dataset(grade)
    alt_grade = grade_slug.replace("grade-", "")
    subject = payload.subject.strip() if payload.subject else None
    strand = payload.strand.strip() if payload.strand else None

    # Clear dataset definitions
    cs_query = "DELETE FROM curriculum_substrands WHERE (grade = :grade OR grade = :alt_grade)"
    cs_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        cs_query += " AND LOWER(subject) = LOWER(:subject)"
        cs_params["subject"] = subject
    if strand:
        cs_query += " AND LOWER(strand_name) = LOWER(:strand)"
        cs_params["strand"] = strand
    execute(cs_query, cs_params)

    cd_query = "DELETE FROM curriculum_designs WHERE (grade = :grade OR grade = :alt_grade)"
    cd_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        cd_query += " AND LOWER(subject) = LOWER(:subject)"
        cd_params["subject"] = subject
    execute(cd_query, cd_params)

    # Clear memory cache in langfuse_context_service
    langfuse_context_service._cache.clear()

    deleted_generations = False
    if payload.clear_mode == "cascade_all":
        # Delete generated resources
        res_query = "DELETE FROM substrand_resources WHERE (LOWER(curriculum->>'grade') = LOWER(:grade) OR LOWER(curriculum->>'grade') = LOWER(:alt_grade))"
        res_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
        if subject:
            res_query += " AND LOWER(curriculum->>'subject') = LOWER(:subject)"
            res_params["subject"] = subject
        if strand:
            res_query += " AND LOWER(curriculum->>'strand') = LOWER(:strand)"
            res_params["strand"] = strand
        execute(res_query, res_params)

        # Delete standalone questions
        q_query = "DELETE FROM question_dna WHERE (LOWER(curriculum_link->>'grade') = LOWER(:grade) OR LOWER(curriculum_link->>'grade') = LOWER(:alt_grade))"
        q_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
        if subject:
            q_query += " AND LOWER(curriculum_link->>'subject') = LOWER(:subject)"
            q_params["subject"] = subject
        execute(q_query, q_params)
        deleted_generations = True

    return {
        "status": "success",
        "grade": grade_slug,
        "clear_mode": payload.clear_mode,
        "deleted_generations": deleted_generations,
        "message": f"Successfully cleared {payload.clear_mode} for {grade_slug}" + (f" (Subject: {subject})" if subject else ""),
    }


# ── Hierarchical Generation Progress & Dataset Dashboard ────────────────────


@router.get("/datasets/{grade}/progress")
def get_dataset_progress_report(
    grade: str,
    subject: str | None = None,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Computes comprehensive multi-level progress percentage (Grade -> Subject -> Strand -> Sub-strand -> 4-Hour Notes -> Diagrams -> Practicals -> Questions) with actionable focus recommendations."""
    from ..infra.db import fetch_all
    from ..services.coverage import WEIGHTS, compute_substrand_coverage, next_action, weighted_rollup
    from ..services.grade_order import grade_label, grade_ordinal
    from ..services.validation import validate_grade_dataset

    grade_slug = validate_grade_dataset(grade)
    alt_grade = grade_slug.replace("grade-", "")

    # 1. Fetch generated resources from substrand_resources
    res_query = """
        SELECT bundle_id, curriculum, notes, diagrams, activities, questions, status, updated_at
        FROM substrand_resources
        WHERE (LOWER(curriculum->>'grade') = LOWER(:grade) OR LOWER(curriculum->>'grade') = LOWER(:alt_grade))
    """
    res_rows = fetch_all(res_query, {"grade": grade_slug, "alt_grade": alt_grade})

    # Index generated resources by (subject.lower(), substrand.lower()) and (subject.lower(), strand.lower(), substrand.lower())
    res_index: dict[tuple[str, str], dict] = {}
    for r in res_rows:
        c = r.get("curriculum") or {}
        s_key = c.get("subject", "").strip().lower()
        ss_key = c.get("sub_strand", "").strip().lower()
        if s_key and ss_key:
            res_index[(s_key, ss_key)] = r

    # 2. Discover all curriculum sub-strands from multiple sources
    discovered_nodes: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def add_node(subj: str, st: str, ss: str, hours: str = "", slos: list = None, diagrams: list = None, exps: list = None):
        subj_clean = (subj or "General Subject").strip()
        st_clean = (st or "General Strand").strip()
        ss_clean = (ss or "General Sub-strand").strip()
        key = (subj_clean.lower(), st_clean.lower(), ss_clean.lower())
        if key not in seen_keys:
            seen_keys.add(key)
            discovered_nodes.append({
                "subject": subj_clean,
                "strand_name": st_clean,
                "sub_strand_name": ss_clean,
                "allocated_hours": hours or "",
                "slos": slos or [],
                "required_diagrams": diagrams or [],
                "experiments": exps or [],
            })

    # Source A: curriculum_substrands table
    cs_query = """
        SELECT subject, strand_name, sub_strand_name, allocated_hours, required_diagrams, experiments, slos
        FROM curriculum_substrands
        WHERE (grade = :grade OR grade = :alt_grade)
    """
    cs_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        cs_query += " AND LOWER(subject) = LOWER(:subject)"
        cs_params["subject"] = subject.strip()
    cs_rows = fetch_all(cs_query, cs_params)
    for r in cs_rows:
        add_node(
            r.get("subject", ""),
            r.get("strand_name", ""),
            r.get("sub_strand_name", ""),
            r.get("allocated_hours", ""),
            r.get("slos", []),
            r.get("required_diagrams", []),
            r.get("experiments", []),
        )

    # Source B: curriculum_designs table (ingested & approved blueprints)
    cd_query = """
        SELECT subject, metadata, raw_payload
        FROM curriculum_designs
        WHERE (grade = :grade OR grade = :alt_grade)
    """
    cd_params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        cd_query += " AND LOWER(subject) = LOWER(:subject)"
        cd_params["subject"] = subject.strip()
    cd_rows = fetch_all(cd_query, cd_params)
    for dr in cd_rows:
        d_subj = dr.get("subject") or "Subject"
        meta = dr.get("metadata") or {}
        raw = dr.get("raw_payload") or {}
        strands_list = meta.get("strands") or raw.get("strands") or []
        for st in strands_list:
            st_name = st.get("name") or st.get("strand_name") or "Strand"
            for ss in st.get("sub_strands") or []:
                ss_name = ss if isinstance(ss, str) else (ss.get("sub_strand_name") or ss.get("name") or ss.get("title"))
                ss_hours = (ss.get("allocated_time") or ss.get("allocated_hours") or ss.get("hours") or "") if isinstance(ss, dict) else ""
                ss_slos = (ss.get("slos") or []) if isinstance(ss, dict) else []
                ss_diagrams = (ss.get("required_diagrams") or []) if isinstance(ss, dict) else []
                ss_exps = (ss.get("experiments") or []) if isinstance(ss, dict) else []
                if ss_name:
                    add_node(d_subj, st_name, ss_name, ss_hours, ss_slos, ss_diagrams, ss_exps)

    # Source C: Also register any generated substrand_resources that may not be in tables
    for r in res_rows:
        c = r.get("curriculum") or {}
        r_subj = c.get("subject")
        r_st = c.get("strand")
        r_ss = c.get("sub_strand")
        if r_subj and r_st and r_ss:
            if not subject or r_subj.lower() == subject.strip().lower():
                add_node(r_subj, r_st, r_ss)

    # Source D: Fallback to Langfuse dataset items if still empty
    if not discovered_nodes:
        dataset_items = langfuse_context_service.get_grade_dataset(grade_slug)
        for item in dataset_items:
            meta = item.get("metadata", {})
            inp = item.get("input", {})
            d_subj = inp.get("subject") if isinstance(inp, dict) else (meta.get("subject") or "General")
            for st in meta.get("strands") or []:
                st_name = st.get("name") or "Strand"
                for ss in st.get("sub_strands") or []:
                    ss_name = ss if isinstance(ss, str) else (ss.get("sub_strand_name") or ss.get("name"))
                    if ss_name:
                        add_node(d_subj, st_name, ss_name)

    # 3. Build hierarchical tree: Subject -> Strand -> Sub-strands
    #
    # Requirements come from each sub-strand's own blueprint (allocated hours,
    # required diagrams, experiments, SLOs) rather than fixed constants, and
    # roll-ups are weighted by teaching hours so a 10-hour sub-strand counts for
    # more than a 2-hour one.
    subjects_tree: dict[str, dict[str, list[dict]]] = {}
    focus_recommendations: list[dict[str, Any]] = []

    for node in discovered_nodes:
        s_name = node["subject"]
        st_name = node["strand_name"]
        ss_name = node["sub_strand_name"]

        subjects_tree.setdefault(s_name, {}).setdefault(st_name, [])

        gen_res = res_index.get((s_name.lower(), ss_name.lower()))
        report = compute_substrand_coverage(node, gen_res)
        dims = report["dimensions"]

        is_approved = bool(
            gen_res
            and (
                gen_res.get("status") == "published"
                or (isinstance(gen_res.get("notes"), dict) and gen_res.get("notes", {}).get("approved"))
            )
        )

        action = next_action(report)
        if action:
            focus_recommendations.append({
                **action,
                "subject": s_name,
                "strand": st_name,
                "sub_strand": ss_name,
                "percentage": report["overall_percentage"],
                "message": f"{action['message']} for '{ss_name}' ({s_name}).",
            })
        else:
            focus_recommendations.append({
                "type": "ready",
                "priority": "ready",
                "action": "open_questions_factory",
                "subject": s_name,
                "strand": st_name,
                "sub_strand": ss_name,
                "percentage": 100,
                "message": f"'{ss_name}' ({s_name}) is complete and ready to publish.",
            })

        h_mods = []
        if gen_res and isinstance(gen_res.get("notes"), dict):
            h_mods = gen_res["notes"].get("hour_modules") or gen_res["notes"].get("key_concepts") or []
        diagrams_list = (gen_res.get("diagrams") or []) if gen_res else []
        activities_raw = (gen_res.get("activities") or []) if gen_res else []
        activities_list = (
            (activities_raw.get("activities") or []) if isinstance(activities_raw, dict) else activities_raw
        )

        subjects_tree[s_name][st_name].append({
            "sub_strand_name": ss_name,
            "allocated_hours": report["allocated_hours"],
            "weight_hours": report["weight_hours"],
            "estimated": report["estimated"],
            # Legacy key names kept so existing dashboards keep rendering.
            "notes": {
                "generated_hours": dims["notes"]["generated"],
                "required_hours": dims["notes"]["required"],
                "remaining_hours": dims["notes"]["remaining"],
                "percentage": dims["notes"]["percentage"],
                "estimated": dims["notes"]["estimated"],
                "hour_modules": [
                    {
                        "hour_number": hm.get("hour_number", h_idx + 1),
                        "hour_title": hm.get("hour_title", f"Hour {h_idx + 1}"),
                        "has_notes": bool(hm.get("full_lecture_notes") or hm.get("content")),
                        "visuals_count": len([
                            v for v in diagrams_list
                            if isinstance(v, dict) and v.get("hour_index") == (h_idx + 1)
                        ]),
                        "activities_count": len([
                            a for a in activities_list
                            if isinstance(a, dict) and a.get("hour_index") == (h_idx + 1)
                        ]),
                    }
                    for h_idx, hm in enumerate(h_mods)
                    if isinstance(hm, dict)
                ],
            },
            "visuals": {
                "generated_count": dims["visuals"]["generated"],
                "required_count": dims["visuals"]["required"],
                "remaining_count": dims["visuals"]["remaining"],
                "percentage": dims["visuals"]["percentage"],
                "estimated": dims["visuals"]["estimated"],
            },
            "practicals": {
                "generated_count": dims["practicals"]["generated"],
                "required_count": dims["practicals"]["required"],
                "remaining_count": dims["practicals"]["remaining"],
                "percentage": dims["practicals"]["percentage"],
                "estimated": dims["practicals"]["estimated"],
            },
            "questions": {
                "generated_count": dims["questions"]["generated"],
                "required_count": dims["questions"]["required"],
                "remaining_count": dims["questions"]["remaining"],
                "percentage": dims["questions"]["percentage"],
                "estimated": dims["questions"]["estimated"],
            },
            "slo_coverage": {
                "generated_count": dims["slo_coverage"]["generated"],
                "required_count": dims["slo_coverage"]["required"],
                "remaining_count": dims["slo_coverage"]["remaining"],
                "percentage": dims["slo_coverage"]["percentage"],
                "estimated": dims["slo_coverage"]["estimated"],
            },
            "overall_percentage": report["overall_percentage"],
            "production_ready": report["production_ready"],
            "approved": is_approved,
            "bundle_id": gen_res.get("bundle_id") if gen_res else None,
        })

    # 4. Roll up by Strand, Subject and Grade, weighted by teaching hours.
    DIMENSION_KEYS = {
        "notes": ("generated_hours", "required_hours"),
        "visuals": ("generated_count", "required_count"),
        "practicals": ("generated_count", "required_count"),
        "questions": ("generated_count", "required_count"),
        "slo_coverage": ("generated_count", "required_count"),
    }

    def _sum_dimensions(items: list[dict]) -> dict[str, dict[str, int]]:
        totals: dict[str, dict[str, int]] = {}
        for dim, (gen_key, req_key) in DIMENSION_KEYS.items():
            generated = sum(item[dim][gen_key] for item in items)
            required = sum(item[dim][req_key] for item in items)
            totals[dim] = {
                "generated": generated,
                "required": required,
                "remaining": max(0, required - generated),
                "percentage": min(100, round((generated / required) * 100)) if required else 0,
            }
        return totals

    subject_reports: list[dict[str, Any]] = []
    all_substrands: list[dict[str, Any]] = []

    for s_name, strands_dict in subjects_tree.items():
        strand_reports: list[dict[str, Any]] = []
        subject_substrands: list[dict[str, Any]] = []

        for st_name, ss_list in strands_dict.items():
            if not ss_list:
                continue
            strand_totals = _sum_dimensions(ss_list)
            strand_reports.append({
                "strand_name": st_name,
                "total_substrands": len(ss_list),
                "completed_substrands": sum(1 for i in ss_list if i["production_ready"]),
                "remaining_substrands": sum(1 for i in ss_list if not i["production_ready"]),
                "production_ready_substrands": sum(1 for i in ss_list if i["production_ready"]),
                "strand_percentage": weighted_rollup(ss_list),
                "estimated": any(i["estimated"] for i in ss_list),
                "notes_summary": strand_totals["notes"],
                "visuals_summary": strand_totals["visuals"],
                "practicals_summary": strand_totals["practicals"],
                "questions_summary": strand_totals["questions"],
                "slo_coverage_summary": strand_totals["slo_coverage"],
                "substrands": ss_list,
            })
            subject_substrands.extend(ss_list)

        if not subject_substrands:
            continue

        subject_totals = _sum_dimensions(subject_substrands)
        subject_reports.append({
            "subject": s_name,
            "total_substrands": len(subject_substrands),
            "completed_substrands": sum(1 for i in subject_substrands if i["production_ready"]),
            "remaining_substrands": sum(1 for i in subject_substrands if not i["production_ready"]),
            "production_ready_substrands": sum(1 for i in subject_substrands if i["production_ready"]),
            "subject_percentage": weighted_rollup(subject_substrands),
            "estimated": any(i["estimated"] for i in subject_substrands),
            "notes_summary": subject_totals["notes"],
            "visuals_summary": subject_totals["visuals"],
            "practicals_summary": subject_totals["practicals"],
            "questions_summary": subject_totals["questions"],
            "slo_coverage_summary": subject_totals["slo_coverage"],
            "strands": strand_reports,
        })
        all_substrands.extend(subject_substrands)

    subject_reports.sort(key=lambda s: s["subject"].lower())

    grade_totals = _sum_dimensions(all_substrands) if all_substrands else {
        dim: {"generated": 0, "required": 0, "remaining": 0, "percentage": 0} for dim in DIMENSION_KEYS
    }
    grade_pct = weighted_rollup(all_substrands)
    production_ready_count = sum(1 for i in all_substrands if i["production_ready"])

    priority_order = {"high": 0, "medium": 1, "low": 2, "ready": 3}
    focus_recommendations.sort(
        key=lambda x: (priority_order.get(x.get("priority", "low"), 2), x.get("percentage", 0))
    )

    estimated_count = sum(1 for i in all_substrands if i["estimated"])

    return {
        "grade": grade_slug,
        "grade_label": grade_label(grade_slug),
        "grade_ordinal": grade_ordinal(grade_slug),
        "overall_grade_percentage": grade_pct,
        "rollup_method": "weighted_by_allocated_hours",
        "weights": WEIGHTS,
        "total_substrands": len(all_substrands),
        "completed_substrands": production_ready_count,
        "remaining_substrands": max(0, len(all_substrands) - production_ready_count),
        "production_ready_substrands": production_ready_count,
        "is_all_production_ready": bool(all_substrands) and production_ready_count == len(all_substrands),
        "measurement_confidence": {
            "substrands_with_estimated_requirements": estimated_count,
            "substrands_measured_from_blueprint": len(all_substrands) - estimated_count,
            "note": (
                "Estimated sub-strands had no allocated hours, required diagrams, "
                "experiments or SLOs in their curriculum design, so a fallback "
                "requirement was used. Ingest a fuller design to measure them."
            ) if estimated_count else "All requirements derived from curriculum blueprints.",
        },
        "notes_totals": {
            "generated_hours": grade_totals["notes"]["generated"],
            "required_hours": grade_totals["notes"]["required"],
            "remaining_hours": grade_totals["notes"]["remaining"],
            "percentage": grade_totals["notes"]["percentage"],
        },
        "visuals_totals": {
            "generated_count": grade_totals["visuals"]["generated"],
            "required_count": grade_totals["visuals"]["required"],
            "remaining_count": grade_totals["visuals"]["remaining"],
            "percentage": grade_totals["visuals"]["percentage"],
        },
        "practicals_totals": {
            "generated_count": grade_totals["practicals"]["generated"],
            "required_count": grade_totals["practicals"]["required"],
            "remaining_count": grade_totals["practicals"]["remaining"],
            "percentage": grade_totals["practicals"]["percentage"],
        },
        "questions_totals": {
            "generated_count": grade_totals["questions"]["generated"],
            "required_count": grade_totals["questions"]["required"],
            "remaining_count": grade_totals["questions"]["remaining"],
            "percentage": grade_totals["questions"]["percentage"],
        },
        "slo_coverage_totals": {
            "generated_count": grade_totals["slo_coverage"]["generated"],
            "required_count": grade_totals["slo_coverage"]["required"],
            "remaining_count": grade_totals["slo_coverage"]["remaining"],
            "percentage": grade_totals["slo_coverage"]["percentage"],
        },
        "focus_recommendations": focus_recommendations[:15],
        "subjects": subject_reports,
    }



from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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


@router.get("/datasets/{grade}/subjects")
def get_grade_subjects(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Returns all subjects available in a grade dataset, with their metadata."""
    grade_slug = validate_grade_dataset(grade)
    subjects = langfuse_context_service.get_available_subjects(grade_slug)
    return {"grade": grade_slug, "subjects": subjects}


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
    """Computes comprehensive multi-level progress percentage (Grade -> Subject -> Strand -> Sub-strand -> 4-Hour Notes -> Diagrams -> Practicals -> Questions)."""
    from ..infra.db import fetch_all
    from ..services.validation import validate_grade_dataset

    grade_slug = validate_grade_dataset(grade)
    alt_grade = grade_slug.replace("grade-", "")

    # 1. Fetch all curriculum sub-strands for this grade
    query = """
        SELECT subject, strand_name, sub_strand_name, allocated_hours, required_diagrams, experiments
        FROM curriculum_substrands
        WHERE (grade = :grade OR grade = :alt_grade)
    """
    params: dict[str, Any] = {"grade": grade_slug, "alt_grade": alt_grade}
    if subject:
        query += " AND LOWER(subject) = LOWER(:subject)"
        params["subject"] = subject.strip()
    query += " ORDER BY subject ASC, strand_name ASC, sub_strand_id ASC"

    ss_rows = fetch_all(query, params)

    # 2. Fetch all generated substrand_resources for this grade
    res_query = """
        SELECT bundle_id, curriculum, notes, diagrams, activities, questions, status
        FROM substrand_resources
        WHERE (LOWER(curriculum->>'grade') = LOWER(:grade) OR LOWER(curriculum->>'grade') = LOWER(:alt_grade))
    """
    res_rows = fetch_all(res_query, {"grade": grade_slug, "alt_grade": alt_grade})

    # Index generated resources by (subject.lower(), substrand.lower())
    res_index: dict[tuple[str, str], dict] = {}
    for r in res_rows:
        c = r.get("curriculum") or {}
        s_key = c.get("subject", "").strip().lower()
        ss_key = c.get("sub_strand", "").strip().lower()
        if s_key and ss_key:
            res_index[(s_key, ss_key)] = r

    # 3. Build hierarchical tree: Subject -> Strand -> Sub-strands
    subjects_tree: dict[str, dict[str, list[dict]]] = {}
    for r in ss_rows:
        s_name = r.get("subject") or "General"
        st_name = r.get("strand_name") or "Strand"
        ss_name = r.get("sub_strand_name") or "Sub-strand"

        if s_name not in subjects_tree:
            subjects_tree[s_name] = {}
        if st_name not in subjects_tree[s_name]:
            subjects_tree[s_name][st_name] = []

        # Check generation status
        gen_res = res_index.get((s_name.lower(), ss_name.lower()))
        notes_data = gen_res.get("notes") if gen_res else None
        h_mods = (notes_data.get("hour_modules") or notes_data.get("key_concepts") or []) if isinstance(notes_data, dict) else []
        notes_hours_gen = len(h_mods) if isinstance(h_mods, list) and len(h_mods) > 0 else (4 if notes_data and notes_data.get("full_lecture_notes") else 0)
        required_hours = 4
        remaining_hours = max(0, required_hours - notes_hours_gen)
        notes_pct = min(100, round((notes_hours_gen / required_hours) * 100))

        diagrams_list = (gen_res.get("diagrams") or []) if gen_res else []
        visuals_gen = len(diagrams_list) if isinstance(diagrams_list, list) else 0
        required_visuals = 8  # 2 per hour
        remaining_visuals = max(0, required_visuals - visuals_gen)
        visuals_pct = min(100, round((visuals_gen / required_visuals) * 100))

        activities_list = (gen_res.get("activities") or []) if gen_res else []
        activities_gen = len(activities_list) if isinstance(activities_list, list) else 0
        required_activities = 4  # 1 per hour
        remaining_activities = max(0, required_activities - activities_gen)
        activities_pct = min(100, round((activities_gen / required_activities) * 100))

        questions_list = (gen_res.get("questions") or []) if gen_res else []
        questions_gen = len(questions_list) if isinstance(questions_list, list) else 0
        required_questions = 10
        remaining_questions = max(0, required_questions - questions_gen)
        questions_pct = min(100, round((questions_gen / required_questions) * 100))

        overall_ss_pct = round((notes_pct * 0.25) + (visuals_pct * 0.25) + (activities_pct * 0.25) + (questions_pct * 0.25))
        is_approved = gen_res.get("status") == "published" or (isinstance(gen_res.get("notes"), dict) and gen_res.get("notes", {}).get("approved")) if gen_res else False
        is_production_ready = notes_hours_gen >= 4 and visuals_gen >= 2 and activities_gen >= 1 and questions_gen >= 3

        subjects_tree[s_name][st_name].append({
            "sub_strand_name": ss_name,
            "allocated_hours": r.get("allocated_hours") or "4 hours",
            "notes": {
                "generated_hours": notes_hours_gen,
                "required_hours": required_hours,
                "remaining_hours": remaining_hours,
                "percentage": notes_pct,
                "hour_modules": [
                    {
                        "hour_number": hm.get("hour_number", h_idx + 1),
                        "hour_title": hm.get("hour_title", f"Hour {h_idx + 1}"),
                        "has_notes": bool(hm.get("full_lecture_notes") or hm.get("content")),
                        "visuals_count": len([v for v in diagrams_list if v.get("hour_index") == (h_idx + 1)]),
                        "activities_count": len([a for a in activities_list if a.get("hour_index") == (h_idx + 1)]),
                    }
                    for h_idx, hm in enumerate(h_mods[:4])
                ] if len(h_mods) > 0 else [],
            },
            "visuals": {
                "generated_count": visuals_gen,
                "required_count": required_visuals,
                "remaining_count": remaining_visuals,
                "percentage": visuals_pct,
            },
            "practicals": {
                "generated_count": activities_gen,
                "required_count": required_activities,
                "remaining_count": remaining_activities,
                "percentage": activities_pct,
            },
            "questions": {
                "generated_count": questions_gen,
                "required_count": required_questions,
                "remaining_count": remaining_questions,
                "percentage": questions_pct,
            },
            "overall_percentage": overall_ss_pct,
            "production_ready": is_production_ready,
            "approved": is_approved,
            "bundle_id": gen_res.get("bundle_id") if gen_res else None,
        })

    # 4. Roll up metrics by Strand, Subject, and Grade
    total_grade_substrands = 0
    completed_grade_substrands = 0
    production_ready_grade_substrands = 0
    subject_reports: list[dict[str, Any]] = []

    for s_name, strands_dict in subjects_tree.items():
        total_sub_count = 0
        completed_sub_count = 0
        prod_ready_sub_count = 0
        strand_reports: list[dict[str, Any]] = []

        for st_name, ss_list in strands_dict.items():
            st_total = len(ss_list)
            st_completed = sum(1 for item in ss_list if item["overall_percentage"] >= 90)
            st_prod_ready = sum(1 for item in ss_list if item["production_ready"])
            st_pct = round(sum(item["overall_percentage"] for item in ss_list) / st_total) if st_total > 0 else 0

            strand_reports.append({
                "strand_name": st_name,
                "total_substrands": st_total,
                "completed_substrands": st_completed,
                "remaining_substrands": max(0, st_total - st_completed),
                "production_ready_substrands": st_prod_ready,
                "strand_percentage": st_pct,
                "substrands": ss_list,
            })

            total_sub_count += st_total
            completed_sub_count += st_completed
            prod_ready_sub_count += st_prod_ready

        sub_pct = round(sum(str_rep["strand_percentage"] for str_rep in strand_reports) / len(strand_reports)) if strand_reports else 0
        subject_reports.append({
            "subject": s_name,
            "total_substrands": total_sub_count,
            "completed_substrands": completed_sub_count,
            "remaining_substrands": max(0, total_sub_count - completed_sub_count),
            "production_ready_substrands": prod_ready_sub_count,
            "subject_percentage": sub_pct,
            "strands": strand_reports,
        })

        total_grade_substrands += total_sub_count
        completed_grade_substrands += completed_sub_count
        production_ready_grade_substrands += prod_ready_sub_count

    grade_pct = round(sum(s["subject_percentage"] for s in subject_reports) / len(subject_reports)) if subject_reports else 0

    return {
        "grade": grade_slug,
        "overall_grade_percentage": grade_pct,
        "total_substrands": total_grade_substrands,
        "completed_substrands": completed_grade_substrands,
        "remaining_substrands": max(0, total_grade_substrands - completed_grade_substrands),
        "production_ready_substrands": production_ready_grade_substrands,
        "is_all_production_ready": production_ready_grade_substrands > 0 and production_ready_grade_substrands == total_grade_substrands,
        "subjects": subject_reports,
    }


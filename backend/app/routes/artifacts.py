"""Versioned artifacts, layered review, and the approved label.

Every generation is a version rather than an overwrite; every version can be
reviewed by three layers; only the third can apply `approved`. A regeneration
is reviewed as a diff against the version it came from.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services import artifact_registry as registry
from ..services import review_context, review_layers, review_vendors
from ..services.auth import AuthContext, require_roles
from ..services.faith_scope import prompt_block as faith_prompt_block
from ..services.level_register import register_block

logger = logging.getLogger("cbc-artifacts-api")

router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifact Versions & Layered Review"])


class CreateArtifactRequest(BaseModel):
    kind: str
    grade: str
    subject: str
    content: dict[str, Any]
    strand: str = ""
    sub_strand: str = ""
    title: str = ""
    parent_artifact_id: str = ""
    provenance: dict[str, Any] = {}
    labels: list[str] = []


class UpdateArtifactRequest(BaseModel):
    content: dict[str, Any]


class LabelRequest(BaseModel):
    label: str
    # Approval is a person's decision and is recorded as one. Coverage counts
    # approved work, so this is the signature under a claim that a grade is
    # taught-ready.
    reviewed_by_me: bool = False
    note: str = ""


class CommentRequest(BaseModel):
    body: str
    dimension: str = ""


class RegenerateRequest(BaseModel):
    artifact_id: str
    extra_instructions: str = ""


class ReviewRequest(BaseModel):
    artifact_id: str
    layer: int = 2
    provider: str = ""
    model: str = ""
    compare_with: str = ""
    custom_instructions: str = ""


# ── CRUD ────────────────────────────────────────────────────────────────────

@router.post("")
def create_artifact(
    payload: CreateArtifactRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Record one generation as a new version of its artifact."""
    artifact = registry.create_version(
        payload.kind, payload.grade, payload.subject, payload.content,
        strand=payload.strand, sub_strand=payload.sub_strand, title=payload.title,
        parent_artifact_id=payload.parent_artifact_id,
        provenance=payload.provenance, created_by=getattr(auth, "subject", ""),
        labels=payload.labels,
    )
    return artifact.to_dict()


@router.get("")
def list_artifacts(
    grade: str = Query(""),
    subject: str = Query(""),
    kind: str = Query(""),
    sub_strand: str = Query(""),
    label: str = Query("", description="Only versions holding this label"),
    limit: int = Query(200, ge=1, le=1000),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    rows = registry.search(grade, subject, kind, sub_strand, label, limit)
    return {"artifacts": rows, "count": len(rows), "kinds": list(registry.KINDS),
            "labels": list(registry.LABELS)}


@router.get("/versions")
def list_versions(
    artifact_key: str = Query(..., description="The natural identity, not one version"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Every attempt at one thing, with its labels and review verdicts."""
    rows = registry.versions(artifact_key)
    return {"artifact_key": artifact_key, "versions": rows, "count": len(rows)}


@router.get("/{artifact_id}")
def read_artifact(
    artifact_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    artifact = registry.get(artifact_id)
    return {
        **artifact.to_dict(),
        "reviews": review_layers.reviews_for(artifact_id),
        "comments": registry.comments_for(artifact_id),
        "approval": review_layers.approval_state(artifact_id),
    }


@router.put("/{artifact_id}")
def edit_artifact(
    artifact_id: str,
    payload: UpdateArtifactRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """A human edit creates the next version rather than overwriting this one.

    Editing in place would make an approved version mean whatever it was last
    edited into, which is exactly what versioning exists to prevent.
    """
    return registry.update_content(
        artifact_id, payload.content, edited_by=getattr(auth, "subject", "")
    ).to_dict()


@router.delete("/{artifact_id}")
def delete_artifact(
    artifact_id: str,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    return registry.delete_version(artifact_id)


# ── Labels ──────────────────────────────────────────────────────────────────

@router.post("/{artifact_id}/label")
def apply_label(
    artifact_id: str,
    payload: LabelRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Point a label at this version.

    `approved` is gated: it may only be applied where the layered review
    actually supports it, so the label means the same thing everywhere.
    """
    if payload.label == "approved":
        state = review_layers.approval_state(artifact_id)
        if not state["can_approve"]:
            raise_api_error(
                "VALIDATION_FAILED",
                "This version cannot be approved yet: "
                + "; ".join(state["blockers"]) + ".",
                detail=state,
            )
        if not payload.reviewed_by_me:
            raise_api_error(
                "VALIDATION_FAILED",
                "Approval needs a person to say they have read this version. The "
                "review layers narrow what reaches you; they do not replace you, and "
                "coverage counts approved work as taught-ready. Send "
                '"reviewed_by_me": true to sign for it.',
                detail=state,
            )
        if payload.note:
            registry.add_comment(
                artifact_id, payload.note,
                author=getattr(auth, "subject", ""), dimension="approval",
            )

    return registry.set_label(artifact_id, payload.label,
                              moved_by=getattr(auth, "subject", ""))


@router.delete("/{artifact_id}/label/{label}")
def clear_label(
    artifact_id: str, label: str,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    return registry.remove_label(artifact_id, label)


# ── Diff ────────────────────────────────────────────────────────────────────

@router.get("/{artifact_id}/diff")
def read_diff(
    artifact_id: str,
    against: str = Query("", description="Defaults to this version's parent"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    current = registry.get(artifact_id)
    previous_id = against or current.parent_artifact_id
    if not previous_id:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Version {current.version} has no parent to compare against. "
            "Pass ?against=<artifact_id> to compare with a specific version.",
        )
    return registry.diff(registry.get(previous_id), current)


# ── Comments ────────────────────────────────────────────────────────────────

@router.post("/{artifact_id}/comments")
def comment_on_artifact(
    artifact_id: str,
    payload: CommentRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    return registry.add_comment(
        artifact_id, payload.body, author=getattr(auth, "subject", ""),
        dimension=payload.dimension,
    )


@router.post("/comments/{comment_id}/resolve")
def resolve_artifact_comment(
    comment_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    return registry.resolve_comment(comment_id)


# ── Review ──────────────────────────────────────────────────────────────────

@router.get("/review/vendors")
def list_review_vendors(
    configured_only: bool = Query(False),
    generator_provider: str = Query("", description="Suggest a vendor unlike this one"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Who can review, and which choice would be a genuine second opinion."""
    return {
        "vendors": review_vendors.catalogue(configured_only),
        "dimensions": {
            name: {"weight": meta["weight"], "question": meta["question"]}
            for name, meta in review_layers.DIMENSIONS.items()
        },
        "layers": review_layers.LAYERS,
        "suggested": review_vendors.suggest(generator_provider),
        "independent_of": review_vendors.independent_of(generator_provider),
    }


@router.post("/review")
def review_artifact(
    payload: ReviewRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Run one review layer over one version, scored per dimension.

    Layer 2 defaults to a vendor different from the one that generated the
    content: two models from one vendor share failure modes, so that pairing is
    one opinion asked twice rather than a second opinion.
    """
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    if payload.layer not in review_layers.LAYERS:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Layer must be one of {sorted(review_layers.LAYERS)}.",
        )

    artifact = registry.get(payload.artifact_id)
    generator_provider = str(artifact.provenance.get("provider") or "")

    provider = (payload.provider or "").lower()
    model = payload.model
    if not provider:
        if payload.layer == 1:
            provider, model = generator_provider, str(artifact.provenance.get("model") or "")
        else:
            suggested = review_vendors.suggest(generator_provider)
            if not suggested:
                raise_api_error(
                    "MODEL_CREDENTIAL_MISSING",
                    "No configured vendor other than the one that generated this. "
                    "Independent review needs a second vendor — add credentials for "
                    "Anthropic, Gemini or a local Ollama.",
                )
            provider, model = suggested["provider"], suggested["model"]

    if provider and not review_vendors.is_known(provider):
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{provider}' is not a known review vendor. "
            f"Known: {', '.join(review_vendors.REVIEW_MODELS)}.",
        )
    if payload.layer >= 2 and provider == generator_provider and generator_provider:
        logger.warning(
            "Layer %d review of %s uses the generating vendor '%s' — that is one "
            "opinion asked twice, and approval will refuse it.",
            payload.layer, artifact.artifact_id, provider,
        )

    # A regeneration is judged on what changed, not re-read from scratch.
    diff_summary: dict[str, Any] = {}
    compared_with = payload.compare_with or artifact.parent_artifact_id
    if compared_with:
        try:
            diff_summary = registry.diff(registry.get(compared_with), artifact)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not diff against %s: %s", compared_with, exc)
            compared_with = ""

    # This used the sub-strand lookup for every kind. A strand artifact has no
    # sub_strand_name, so the query matched nothing, returned "", and the miss
    # was logged at DEBUG and swallowed — strand reviews have been scoring
    # curriculum_alignment against an empty comparison and reporting a number
    # for it. Each kind now gets the comparison it can actually be judged by.
    grounding = review_context.for_artifact(artifact)
    if not grounding.found:
        logger.warning(
            "Review of %s (%s) has no design to judge against: %s",
            artifact.artifact_id, artifact.kind, grounding.missing_reason,
        )

    prior = [r for r in review_layers.reviews_for(artifact.artifact_id)
             if int(r["layer"]) < payload.layer]
    human = [str(c.get("body") or "") for c in registry.comments_for(artifact.artifact_id)
             if not c.get("resolved")]

    # The page-addressed source, so citations can be resolved rather than
    # guessed at. Without it a reviewer was told to flag any address "not in
    # the excerpt" when it had never been given an excerpt.
    design_source_text = ""
    try:
        from ..services import design_source

        found = design_source.resolve(artifact.grade, artifact.subject)
        design_source_text = found.text or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not load the design for %s (%s); citations will be reported "
            "as unresolvable rather than guessed at: %s",
            artifact.artifact_id, artifact.kind, exc,
        )

    messages = review_layers.build_messages(
        artifact, payload.layer,
        design_extract=grounding.text,
        design_source_text=design_source_text,
        missing_design=grounding.missing_reason,
        descendants=grounding.descendants,
        register=register_block(artifact.grade),
        faith=faith_prompt_block(artifact.subject),
        prior_reviews=prior, human_comments=human,
        diff_summary=diff_summary or None,
    )
    if payload.custom_instructions:
        messages.append({"role": "user", "content": payload.custom_instructions})

    resolved = pipeline_orchestrator.router.resolve_for_stage(
        "notes_generation", provider=provider or None, model=model or None,
    )
    response = llm_client.generate(resolved, messages, temperature=0.1)
    content = response.content if isinstance(response.content, dict) else {}

    verdict = review_layers.from_response(
        content, artifact, payload.layer, resolved.provider, resolved.model
    )
    verdict.compared_with = compared_with
    verdict.diff_summary = {"counts": diff_summary.get("counts", {})} if diff_summary else {}
    verdict.usage = review_layers.normalise_usage(response.usage)
    review_layers.save(verdict)

    if artifact.status == "draft":
        from ..infra.db import execute

        execute(
            "UPDATE artifacts SET status = 'in_review', updated_at = NOW() "
            "WHERE artifact_id = :id AND status = 'draft'",
            {"id": artifact.artifact_id},
        )

    return {
        **verdict.to_dict(),
        "approval": review_layers.approval_state(artifact.artifact_id),
        "reviewed_a_diff": bool(diff_summary),
        # What the reviewer was actually shown, so a verdict can be checked
        # against its inputs rather than taken on trust.
        "inputs": {
            "grounding": grounding.to_dict(),
            "artifact_chars": len(json.dumps(artifact.content, default=str)),
            "truncated": len(json.dumps(artifact.content, default=str))
                         > review_layers.MAX_ARTIFACT_CHARS,
            "prior_reviews": len(prior),
            "human_comments": len(human),
            "prompt_chars": sum(len(m.get("content", "")) for m in messages),
            "messages": messages,
        },
    }


# ── Regenerate with the review's own findings ───────────────────────────────

# Which generator produces each kind, and how its payload is shaped. A kind
# absent here cannot be regenerated from a review yet, and says so rather than
# silently doing nothing.
_REGENERATORS: dict[str, dict[str, Any]] = {
    "strand": {"endpoint": "factory_generate_strands", "scope": "strand_list"},
    "sub_strand": {"endpoint": "factory_generate_substrands", "scope": "strand"},
    "notes": {"endpoint": "factory_generate_notes", "scope": "sub_strand"},
    "diagram": {"endpoint": "factory_plan_visuals", "scope": "sub_strand"},
    "activity": {"endpoint": "factory_plan_activities", "scope": "sub_strand"},
    "photo_prompt": {"endpoint": "factory_generate_media_prompts", "scope": "sub_strand"},
    "video_prompt": {"endpoint": "factory_generate_media_prompts", "scope": "sub_strand"},
}


@router.post("/regenerate")
def regenerate_artifact(
    payload: RegenerateRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Generate the next version, carrying the reviewers' findings into it.

    A review that says what is wrong and then leaves a person to retype it into
    a custom-instructions box is a review most of whose value is lost in
    transit. The findings are already structured, so they are handed to the
    generator directly — and the new version records this one as its parent, so
    the next review reads the diff rather than the whole thing again.
    """
    from . import curriculum as curriculum_routes
    from ..services.revision_directives import build as build_directives

    artifact = registry.get(payload.artifact_id)
    plan = _REGENERATORS.get(artifact.kind)
    if not plan:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{artifact.kind}' has no regeneration path yet. Regenerate it from its "
            f"own station in the factory. Kinds that can: "
            f"{', '.join(sorted(_REGENERATORS))}.",
        )

    reviews = review_layers.reviews_for(artifact.artifact_id)
    if not reviews:
        raise_api_error(
            "VALIDATION_FAILED",
            "This version has not been reviewed, so there are no findings to "
            "regenerate from. Run a review first, or regenerate from the station "
            "to start fresh.",
        )

    revision = build_directives(
        reviews, registry.comments_for(artifact.artifact_id),
        measured=_measured_defects(artifact),
    )
    if not revision["directives"]:
        raise_api_error(
            "VALIDATION_FAILED",
            "Every reviewer passed this version with no issues raised, so a "
            "regeneration would be told to change nothing. Approve it instead.",
        )

    instructions = revision["directives"]
    if payload.extra_instructions:
        instructions += f"\n\nALSO: {payload.extra_instructions}"

    common = {
        "grade": artifact.grade,
        "subject": artifact.subject,
        "custom_instructions": instructions,
    }
    scope = plan["scope"]
    if scope == "strand":
        common["strand_name"] = artifact.strand_name
    elif scope == "sub_strand":
        common["strand"] = artifact.strand_name
        common["sub_strand"] = artifact.sub_strand_name

    handler = getattr(curriculum_routes, plan["endpoint"])
    # The SAME resolver the queue uses. curriculum.py opens with
    # `from __future__ import annotations`, so every annotation in it is a
    # string — and reading it raw from here produced
    # "'str' object has no attribute 'model_fields'", the identical failure
    # that was fixed in the queue and left standing in this path.
    try:
        model_cls = curriculum_routes._payload_model(handler, plan["endpoint"])
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))

    # Fields the generator needs that this artifact does not carry are left to
    # the model's own defaults rather than guessed at here.
    allowed = set(model_cls.model_fields)
    result = handler(model_cls(**{k: v for k, v in common.items() if k in allowed}), auth)

    # The generator files its own version; attribute it to this one so the diff
    # review has a parent to compare against.
    filed = result.get("artifact") if isinstance(result, dict) else None
    if isinstance(filed, dict) and filed.get("artifact_id"):
        from ..infra.db import execute, to_json

        execute(
            "UPDATE artifacts SET parent_artifact_id = :parent, "
            "provenance = provenance || CAST(:extra AS jsonb), updated_at = NOW() "
            "WHERE artifact_id = :id AND parent_artifact_id = ''",
            {
                "parent": artifact.artifact_id,
                "id": filed["artifact_id"],
                "extra": to_json({
                    "regenerated_from": artifact.artifact_id,
                    "addressed_issues": len(revision["issues"]),
                    "requested_by": getattr(auth, "subject", ""),
                }),
            },
        )

    return {
        "status": "regenerated",
        "from_artifact_id": artifact.artifact_id,
        "from_version": artifact.version,
        "new_artifact": filed,
        "addressed": {
            "issues": revision["issues"],
            "weak_dimensions": revision["weak_dimensions"],
            "human_comments": revision["human_comments"],
        },
        "directives": instructions,
        "result": result,
    }


@router.get("/{artifact_id}/revision-directives")
def _measured_defects(artifact: Any) -> list[str]:
    """Defects found by comparison rather than by opinion.

    These reach a regeneration whether or not a reviewer noticed them, because
    the ones reviewers miss are consistently the ones only visible by
    comparison — a lesson that is a copy of the lesson four pages earlier reads
    perfectly well where it sits.
    """
    from ..services import redundancy_check

    try:
        report = redundancy_check.inspect(getattr(artifact, "content", None) or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not compare the lessons in %s: %s",
                       getattr(artifact, "artifact_id", "?"), exc)
        return []
    return report.get("findings") or []


def read_revision_directives(
    artifact_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """What a regeneration would be told, without running one.

    Copyable, so the same instruction can be pasted into another model or into
    a station's own custom-instructions box by hand.
    """
    from ..services.revision_directives import build as build_directives

    artifact = registry.get(artifact_id)
    revision = build_directives(
        review_layers.reviews_for(artifact_id), registry.comments_for(artifact_id),
        measured=_measured_defects(artifact),
    )
    return {
        "artifact_id": artifact_id,
        "kind": artifact.kind,
        "regeneratable": artifact.kind in _REGENERATORS,
        **revision,
    }

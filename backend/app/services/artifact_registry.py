"""Versioned, labelled storage for everything the factory generates.

Prompts are versioned in Langfuse and a label decides which version is served.
Content was not: every generation overwrote the last, so there was no way to
compare two attempts, to keep a good version while trying a better one, or to
say which version is the approved one. This gives content the same discipline.

``artifact_key`` is the natural identity — "the notes for this sub-strand". An
``artifact_id`` is one version of it. A label points at exactly one version, so
"approved" is a fact about a specific version rather than about a topic.

A regeneration records its parent. That is what makes a diff review possible:
the second opinion on attempt 4 should be about what changed since attempt 3,
not a fresh read of the whole thing as though nothing came before.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger("cbc-artifacts")

# Everything the factory produces, in the order it is produced.
KINDS: tuple[str, ...] = (
    "ingest",
    "strand",
    "sub_strand",
    "notes",
    # The words themselves, written from the plan above it. `notes` is a plan:
    # "choose a simple song", "tell a story". This is the song and the story.
    "material",
    "hour_module",
    "diagram",
    "photo_prompt",
    "video_prompt",
    "simulation",
    "experiment",
    "activity",
    "question",
    "answer",
)

# Labels move; versions do not. "approved" is the one the third layer applies,
# and the one every consumer should read.
LABELS: tuple[str, ...] = ("approved", "production", "staging", "test", "dev", "rejected")

# A label that means "this is the live copy". Applying it moves it off whatever
# held it before.
EXCLUSIVE_LABELS = frozenset(LABELS)

STATUSES = ("draft", "in_review", "approved", "rejected", "superseded")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def artifact_key(
    kind: str, grade: str, subject: str,
    strand: str = "", sub_strand: str = "", title: str = "",
) -> str:
    """The identity a version belongs to, stable across regenerations."""
    parts = [kind, grade, subject, strand, sub_strand, title]
    return ":".join(_slug(p) for p in parts).rstrip(":")


def content_hash(content: Any) -> str:
    canonical = json.dumps(content, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


@dataclass(slots=True)
class Artifact:
    artifact_id: str = ""
    artifact_key: str = ""
    kind: str = ""
    version: int = 1
    grade: str = ""
    subject: str = ""
    strand_name: str = ""
    sub_strand_name: str = ""
    title: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    parent_artifact_id: str = ""
    status: str = "draft"
    provenance: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id, "artifact_key": self.artifact_key,
            "kind": self.kind, "version": self.version, "grade": self.grade,
            "subject": self.subject, "strand_name": self.strand_name,
            "sub_strand_name": self.sub_strand_name, "title": self.title,
            "content": self.content, "content_hash": self.content_hash,
            "parent_artifact_id": self.parent_artifact_id, "status": self.status,
            "provenance": self.provenance, "created_by": self.created_by,
            "labels": self.labels,
        }


# ── Writing ─────────────────────────────────────────────────────────────────

def _next_version(key: str) -> int:
    from ..infra.db import fetch_one

    row = fetch_one(
        "SELECT COALESCE(MAX(version), 0) AS v FROM artifacts WHERE artifact_key = :key",
        {"key": key},
    )
    return int((row or {}).get("v") or 0) + 1


def create_version(
    kind: str, grade: str, subject: str, content: dict[str, Any], *,
    strand: str = "", sub_strand: str = "", title: str = "",
    parent_artifact_id: str = "", provenance: dict[str, Any] | None = None,
    created_by: str = "", labels: list[str] | None = None,
) -> Artifact:
    """Record one attempt. An identical re-run returns the version it matches.

    Storing a byte-identical regeneration as a new version would fill the
    history with noise and make "what changed since the approved one" harder to
    answer, not easier.
    """
    from ..errors import raise_api_error
    from ..infra.db import execute, fetch_one, to_json

    if kind not in KINDS:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{kind}' is not a known artifact kind. Known: {', '.join(KINDS)}.",
        )

    key = artifact_key(kind, grade, subject, strand, sub_strand, title)
    digest = content_hash(content)

    existing = fetch_one(
        "SELECT * FROM artifacts WHERE artifact_key = :key AND content_hash = :hash "
        "ORDER BY version DESC LIMIT 1",
        {"key": key, "hash": digest},
    )
    if existing:
        logger.info("Identical content already stored as %s.", existing["artifact_id"])
        return _hydrate(existing)

    version = _next_version(key)
    artifact_id = f"art_{_slug(kind)}_{hashlib.sha256(f'{key}:{version}'.encode()).hexdigest()[:16]}"

    execute(
        """
        INSERT INTO artifacts (
            artifact_id, artifact_key, kind, version, grade, subject, strand_name,
            sub_strand_name, title, content, content_hash, parent_artifact_id,
            status, provenance, created_by, updated_at
        )
        VALUES (
            :artifact_id, :artifact_key, :kind, :version, :grade, :subject, :strand_name,
            :sub_strand_name, :title, CAST(:content AS jsonb), :content_hash,
            :parent_artifact_id, :status, CAST(:provenance AS jsonb), :created_by, NOW()
        )
        """,
        {
            "artifact_id": artifact_id, "artifact_key": key, "kind": kind,
            "version": version, "grade": grade, "subject": subject,
            "strand_name": strand, "sub_strand_name": sub_strand, "title": title,
            "content": to_json(content), "content_hash": digest,
            "parent_artifact_id": parent_artifact_id, "status": "draft",
            "provenance": to_json(provenance or {}), "created_by": created_by,
        },
    )

    artifact = Artifact(
        artifact_id=artifact_id, artifact_key=key, kind=kind, version=version,
        grade=grade, subject=subject, strand_name=strand, sub_strand_name=sub_strand,
        title=title, content=content, content_hash=digest,
        parent_artifact_id=parent_artifact_id, provenance=provenance or {},
        created_by=created_by,
    )
    for label in labels or []:
        set_label(artifact_id, label, moved_by=created_by)
    artifact.labels = labels_of(artifact_id)
    return artifact


def update_content(
    artifact_id: str, content: dict[str, Any], *, edited_by: str = "",
) -> Artifact:
    """A human edit creates the NEXT version, never a silent overwrite.

    Editing in place would make an approved version mean whatever it was last
    edited into, which is the problem versioning exists to prevent.
    """
    current = get(artifact_id)
    return create_version(
        current.kind, current.grade, current.subject, content,
        strand=current.strand_name, sub_strand=current.sub_strand_name,
        title=current.title, parent_artifact_id=artifact_id,
        provenance={**current.provenance, "edited_from": artifact_id, "source": "human"},
        created_by=edited_by,
    )


def delete_version(artifact_id: str) -> dict[str, Any]:
    """Remove one version. Refused while a label points at it."""
    from ..errors import raise_api_error
    from ..infra.db import execute, fetch_all

    held = fetch_all(
        "SELECT label FROM artifact_labels WHERE artifact_id = :id", {"id": artifact_id}
    ) or []
    if held:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Cannot delete: this version holds the label(s) "
            f"{', '.join(str(h['label']) for h in held)}. Move the label to another "
            f"version first, so nothing silently loses its approved copy.",
        )

    execute("DELETE FROM artifact_reviews WHERE artifact_id = :id", {"id": artifact_id})
    execute("DELETE FROM artifact_comments WHERE artifact_id = :id", {"id": artifact_id})
    execute("DELETE FROM artifacts WHERE artifact_id = :id", {"id": artifact_id})
    return {"status": "deleted", "artifact_id": artifact_id}


# ── Labels ──────────────────────────────────────────────────────────────────

def set_label(artifact_id: str, label: str, *, moved_by: str = "") -> dict[str, Any]:
    """Point a label at this version, taking it off whatever held it."""
    from ..errors import raise_api_error
    from ..infra.db import execute, fetch_one

    if label not in LABELS:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{label}' is not a known label. Known: {', '.join(LABELS)}.",
        )

    row = fetch_one(
        "SELECT artifact_key FROM artifacts WHERE artifact_id = :id", {"id": artifact_id}
    )
    if not row:
        raise_api_error("DATASET_ITEM_NOT_FOUND", f"No artifact '{artifact_id}'.")

    previous = fetch_one(
        "SELECT artifact_id FROM artifact_labels WHERE artifact_key = :key AND label = :label",
        {"key": row["artifact_key"], "label": label},
    )
    execute(
        """
        INSERT INTO artifact_labels (artifact_key, label, artifact_id, moved_by, moved_at)
        VALUES (:key, :label, :id, :by, NOW())
        ON CONFLICT (artifact_key, label) DO UPDATE SET
            artifact_id = EXCLUDED.artifact_id,
            moved_by = EXCLUDED.moved_by,
            moved_at = NOW()
        """,
        {"key": row["artifact_key"], "label": label, "id": artifact_id, "by": moved_by},
    )
    if label == "approved":
        execute(
            "UPDATE artifacts SET status = 'approved', updated_at = NOW() WHERE artifact_id = :id",
            {"id": artifact_id},
        )
        if previous and previous["artifact_id"] != artifact_id:
            execute(
                "UPDATE artifacts SET status = 'superseded', updated_at = NOW() "
                "WHERE artifact_id = :id",
                {"id": previous["artifact_id"]},
            )
    return {
        "status": "labelled", "label": label, "artifact_id": artifact_id,
        "moved_from": (previous or {}).get("artifact_id", ""),
    }


def remove_label(artifact_key_or_id: str, label: str) -> dict[str, Any]:
    from ..infra.db import execute

    execute(
        "DELETE FROM artifact_labels WHERE label = :label AND "
        "(artifact_key = :ref OR artifact_id = :ref)",
        {"label": label, "ref": artifact_key_or_id},
    )
    return {"status": "removed", "label": label}


def labels_of(artifact_id: str) -> list[str]:
    from ..infra.db import fetch_all

    rows = fetch_all(
        "SELECT label FROM artifact_labels WHERE artifact_id = :id ORDER BY label",
        {"id": artifact_id},
    ) or []
    return [str(r["label"]) for r in rows]


# ── Reading ─────────────────────────────────────────────────────────────────

def _hydrate(row: dict[str, Any]) -> Artifact:
    artifact = Artifact(
        artifact_id=str(row.get("artifact_id") or ""),
        artifact_key=str(row.get("artifact_key") or ""),
        kind=str(row.get("kind") or ""),
        version=int(row.get("version") or 1),
        grade=str(row.get("grade") or ""),
        subject=str(row.get("subject") or ""),
        strand_name=str(row.get("strand_name") or ""),
        sub_strand_name=str(row.get("sub_strand_name") or ""),
        title=str(row.get("title") or ""),
        content=row.get("content") if isinstance(row.get("content"), dict) else {},
        content_hash=str(row.get("content_hash") or ""),
        parent_artifact_id=str(row.get("parent_artifact_id") or ""),
        status=str(row.get("status") or "draft"),
        provenance=row.get("provenance") if isinstance(row.get("provenance"), dict) else {},
        created_by=str(row.get("created_by") or ""),
    )
    artifact.labels = labels_of(artifact.artifact_id)
    return artifact


def get(artifact_id: str) -> Artifact:
    from ..errors import raise_api_error
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM artifacts WHERE artifact_id = :id", {"id": artifact_id})
    if not row:
        raise_api_error("DATASET_ITEM_NOT_FOUND", f"No artifact '{artifact_id}'.")
    return _hydrate(row)


def versions(key: str) -> list[dict[str, Any]]:
    """Every attempt at one thing, newest first, with its labels and verdicts."""
    from ..infra.db import fetch_all

    rows = fetch_all(
        """
        SELECT a.artifact_id, a.version, a.status, a.content_hash, a.parent_artifact_id,
               a.created_by, a.created_at, a.provenance,
               COALESCE(
                   (SELECT json_agg(l.label ORDER BY l.label)
                    FROM artifact_labels l WHERE l.artifact_id = a.artifact_id),
                   '[]'::json
               ) AS labels,
               (SELECT json_agg(json_build_object(
                        'layer', r.layer, 'verdict', r.verdict,
                        'confidence', r.overall_confidence,
                        'provider', r.provider, 'model', r.model)
                        ORDER BY r.layer)
                FROM artifact_reviews r WHERE r.artifact_id = a.artifact_id) AS reviews
        FROM artifacts a
        WHERE a.artifact_key = :key
        ORDER BY a.version DESC
        """,
        {"key": key},
    ) or []
    for row in rows:
        row["reviews"] = row.get("reviews") or []
    return rows


def by_label(key: str, label: str = "approved") -> Artifact | None:
    """The version a label points at, or None. Never raises: a consumer asking
    for the approved copy of something not yet approved needs an answer, not an
    exception."""
    from ..infra.db import fetch_one

    row = fetch_one(
        """
        SELECT a.* FROM artifacts a
        JOIN artifact_labels l ON l.artifact_id = a.artifact_id
        WHERE l.artifact_key = :key AND l.label = :label
        """,
        {"key": key, "label": label},
    )
    return _hydrate(row) if row else None


def search(
    grade: str = "", subject: str = "", kind: str = "",
    sub_strand: str = "", label: str = "", limit: int = 200,
) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": max(1, min(limit, 1000))}
    if grade:
        # Normalised on BOTH sides, because the same grade is written four
        # ways across this system: "PP1", "pp1", "grade-pp1", "Grade-PP1".
        #
        # This comparison was case-sensitive and only stripped `grade-` from
        # the value passed IN, never from the value stored. The board counts
        # artifacts with LOWER() and so showed the lesson plan as built, while
        # this search — the one the material and diagram stations ask before
        # they will run — found nothing and reported "no lesson plan filed for
        # this sub-strand". A plan that visibly exists, reviewed and scored,
        # and every station downstream of it locked.
        conditions.append(
            "REPLACE(LOWER(a.grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')"
        )
        params["grade"] = grade
    if subject:
        conditions.append("LOWER(a.subject) = LOWER(:subject)")
        params["subject"] = subject
    if kind:
        conditions.append("a.kind = :kind")
        params["kind"] = kind
    if sub_strand:
        conditions.append("LOWER(a.sub_strand_name) = LOWER(:sub_strand)")
        params["sub_strand"] = sub_strand
    join = ""
    if label:
        join = "JOIN artifact_labels l ON l.artifact_id = a.artifact_id AND l.label = :label"
        params["label"] = label

    return fetch_all(
        f"""
        SELECT a.artifact_id, a.artifact_key, a.kind, a.version, a.grade, a.subject,
               a.strand_name, a.sub_strand_name, a.title, a.status, a.created_at,
               -- The gate score this version was filed with. Without it the
               -- console has to fetch every version separately to say whether
               -- the work that is saved was any good.
               a.provenance
        FROM artifacts a {join}
        WHERE {' AND '.join(conditions)}
        ORDER BY a.updated_at DESC
        LIMIT :limit
        """,
        params,
    ) or []


# ── Diff ────────────────────────────────────────────────────────────────────

def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            flat.update(_flatten(item, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flat.update(_flatten(item, f"{prefix}[{index}]"))
    else:
        flat[prefix or "."] = value
    return flat


def diff(previous: Artifact, current: Artifact) -> dict[str, Any]:
    """Field-level change between two versions.

    A second opinion on attempt 4 should be about what changed since attempt 3.
    Re-reading the whole thing invites a different answer for the same content,
    which makes the review look unstable when it is the reading that moved.
    """
    before = _flatten(previous.content)
    after = _flatten(current.content)

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        path for path in set(before) & set(after) if before[path] != after[path]
    )

    def sample(paths: list[str], source: dict[str, Any], other: dict[str, Any] | None = None):
        out = []
        for path in paths[:40]:
            entry = {"path": path, "value": str(source.get(path))[:300]}
            if other is not None:
                entry["was"] = str(other.get(path))[:300]
            out.append(entry)
        return out

    return {
        "previous_artifact_id": previous.artifact_id,
        "previous_version": previous.version,
        "current_artifact_id": current.artifact_id,
        "current_version": current.version,
        "identical": not (added or removed or changed),
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
        "added": sample(added, after),
        "removed": sample(removed, before),
        "changed": sample(changed, after, before),
    }


def diff_by_id(previous_id: str, current_id: str) -> dict[str, Any]:
    return diff(get(previous_id), get(current_id))


# ── Comments ────────────────────────────────────────────────────────────────

def add_comment(
    artifact_id: str, body: str, *, author: str = "", dimension: str = "",
) -> dict[str, Any]:
    """A person's note on a version, beside the models' scores.

    A reviewer who disagrees with a 94% needs somewhere to say so that the next
    approver will actually read.
    """
    from ..errors import raise_api_error
    from ..infra.db import execute

    if not body.strip():
        raise_api_error("VALIDATION_FAILED", "A comment needs a body.")

    artifact = get(artifact_id)
    comment_id = f"cmt_{hashlib.sha256(f'{artifact_id}{body}{datetime.utcnow()}'.encode()).hexdigest()[:16]}"
    execute(
        """
        INSERT INTO artifact_comments (comment_id, artifact_id, artifact_key, author, body, dimension)
        VALUES (:comment_id, :artifact_id, :artifact_key, :author, :body, :dimension)
        """,
        {"comment_id": comment_id, "artifact_id": artifact_id,
         "artifact_key": artifact.artifact_key, "author": author,
         "body": body.strip(), "dimension": dimension},
    )
    return {"status": "added", "comment_id": comment_id}


def comments_for(artifact_id: str) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    return fetch_all(
        "SELECT * FROM artifact_comments WHERE artifact_id = :id ORDER BY created_at DESC",
        {"id": artifact_id},
    ) or []


def resolve_comment(comment_id: str) -> dict[str, Any]:
    from ..infra.db import execute

    execute(
        "UPDATE artifact_comments SET resolved = TRUE WHERE comment_id = :id",
        {"id": comment_id},
    )
    return {"status": "resolved", "comment_id": comment_id}

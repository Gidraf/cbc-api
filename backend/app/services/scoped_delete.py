"""Remove ONE strand or ONE sub-strand, with everything derived from it.

The only tool for getting rid of generated curriculum was the factory reset,
which clears a whole grade or a whole learning area. That is the right
instrument for "the pipeline has changed, start again" and the wrong one for
"this sub-strand came out badly, do it again" — and having only the second
means an operator either lives with a bad sub-strand or throws away eleven good
ones with it.

What makes this more than a DELETE is what hangs off a sub-strand. Its notes,
diagrams, media briefs, simulations, activities, questions, every artifact
version, every review verdict and every label all reference it by name. Left
behind they are orphans: they still count toward coverage, they still appear in
the question bank, and the sub-strand they describe no longer exists. So this
deletes children before parents, in the same order the reset does, and reports
what went.

It is a dry run unless told otherwise, for the same reason the reset is: the
counts should be visible before anything is irreversible.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-scoped-delete")


@dataclass(slots=True)
class Scoped:
    """One table, and how to narrow it to a strand or sub-strand by name."""

    table: str
    what: str
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    # Where the scope lives inside JSONB rather than in its own column.
    grade_json: str = ""
    subject_json: str = ""
    strand_json: str = ""
    sub_strand_json: str = ""
    # Rows reachable only through another table's key.
    via_artifacts: str = ""
    # Which LAYER of the sub-strand's content this table holds — so an
    # operator can clear the lesson notes and keep the dataset, or the other
    # way round. One of LAYERS below.
    layer: str = "notes"
    # For the artifacts table and the tables hanging off it: only these
    # artifact kinds. The same table holds the notes, the diagrams, the
    # questions and the dataset's own strand and sub-strand records.
    kinds: tuple[str, ...] = ()

    def clause(self, grade: str, subject: str, strand: str, sub_strand: str
               ) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        parts: list[str] = []

        def kinds_clause(alias: str) -> str:
            if not self.kinds:
                return ""
            names = ", ".join(f":kind_{i}" for i in range(len(self.kinds)))
            for i, kind in enumerate(self.kinds):
                params[f"kind_{i}"] = kind
            return f"{alias}kind IN ({names})"

        if self.via_artifacts:
            # These tables carry an artifact_id and no curriculum scope of
            # their own, so the whole narrowing happens in the subquery.
            # Running the column checks first found no grade column and bailed
            # out with an empty clause — which meant review verdicts, labels
            # and comments were never deleted, leaving exactly the orphans this
            # module exists to prevent.
            inner = ["1=1"]
            if grade:
                inner.append("(REPLACE(LOWER(a.grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))")
                params["grade"] = grade
                params["alt_grade"] = grade.replace("grade-", "")
            if subject:
                inner.append("LOWER(a.subject) = LOWER(:subject)")
                params["subject"] = subject
            if strand:
                inner.append("LOWER(a.strand_name) = LOWER(:strand)")
                params["strand"] = strand
            if sub_strand:
                inner.append("LOWER(a.sub_strand_name) = LOWER(:sub_strand)")
                params["sub_strand"] = sub_strand
            by_kind = kinds_clause("a.")
            if by_kind:
                inner.append(by_kind)
            clause = (
                f"{self.via_artifacts} IN (SELECT a.artifact_id FROM artifacts a "
                f"WHERE {' AND '.join(inner)})"
            )
            return clause, params

        def add(column: str, json_path: str, value: str, name: str) -> bool:
            if not value:
                return True
            target = column or json_path
            if not target:
                return False
            parts.append(f"LOWER({target}) = LOWER(:{name})")
            params[name] = value
            return True

        if grade:
            target = self.grade or self.grade_json
            if not target:
                return "", {}
            # Normalised on both sides, matching the artifact clause above.
            # A bare `=` is case-sensitive, so a row filed as "Grade-9"
            # survived a delete of "grade-9": nothing removed, success
            # reported, and the content back on the next read.
            parts.append(
                f"(REPLACE(LOWER({target}), 'grade-', '') "
                f"= REPLACE(LOWER(:grade), 'grade-', ''))")
            params["grade"] = grade
            params["alt_grade"] = grade.replace("grade-", "")

        for column, json_path, value, name in (
            (self.subject, self.subject_json, subject, "subject"),
            (self.strand, self.strand_json, strand, "strand"),
            (self.sub_strand, self.sub_strand_json, sub_strand, "sub_strand"),
        ):
            if not add(column, json_path, value, name):
                return "", {}

        by_kind = kinds_clause("")
        if by_kind:
            parts.append(by_kind)

        return (" AND ".join(parts) if parts else "1=1"), params


# The layers a sub-strand's content comes in. An operator who wants the
# lesson notes written again does not want the dataset gone with them, and one
# who has re-ingested a design does not want the questions gone with it.
LAYERS: dict[str, str] = {
    "notes": "lesson notes and material",
    "diagrams": "diagrams, figures and media briefs",
    "activities": "activities, experiments and simulations",
    "questions": "questions and their events",
    "jobs": "queued and failed jobs",
    "dataset": "the sub-strands and designs themselves",
}
GENERATED: tuple[str, ...] = ("notes", "diagrams", "activities", "questions", "jobs")
# What the console offers: a name and the layers it stands for.
PRESETS: dict[str, tuple[str, ...]] = {
    "all": tuple(LAYERS),
    "generated": GENERATED,
    "dataset": ("dataset",),
}

_NOTES_KINDS = ("notes", "material", "hour_module")
_DIAGRAM_KINDS = ("diagram", "photo_prompt", "video_prompt")
_ACTIVITY_KINDS = ("activity", "experiment", "simulation")
_QUESTION_KINDS = ("question", "answer")
_DATASET_KINDS = ("ingest", "strand", "sub_strand")

# Children before parents. Deleting the sub-strand first would leave its notes,
# its questions and its review verdicts pointing at a row that is gone.
DERIVED: tuple[Scoped, ...] = tuple(
    scoped
    for kinds, layer in (
        (_NOTES_KINDS, "notes"), (_DIAGRAM_KINDS, "diagrams"),
        (_ACTIVITY_KINDS, "activities"), (_QUESTION_KINDS, "questions"),
        (_DATASET_KINDS, "dataset"),
    )
    for scoped in (
        Scoped("artifact_comments", f"comments on {layer} versions",
               via_artifacts="artifact_id", layer=layer, kinds=kinds),
        Scoped("artifact_reviews", f"review verdicts on {layer}",
               via_artifacts="artifact_id", layer=layer, kinds=kinds),
        Scoped("artifact_labels", f"labels on {layer}",
               via_artifacts="artifact_id", layer=layer, kinds=kinds),
        Scoped("artifact_dna", f"content fingerprints of {layer}",
               via_artifacts="artifact_id", layer=layer, kinds=kinds),
        Scoped("artifacts", f"generated {layer} versions",
               grade="grade", subject="subject",
               strand="strand_name", sub_strand="sub_strand_name",
               layer=layer, kinds=kinds),
    )
) + (
    Scoped("substrand_media", "photo and video briefs",
           grade="grade", subject="subject",
           strand="strand_name", sub_strand="sub_strand_name", layer="diagrams"),
    # Drawn and uploaded figures. Deleting a sub-strand and leaving these
    # behind meant the next plan for it picked them straight back up: the book
    # attaches whatever is filed for a sub-strand, whether or not anything
    # currently asks for it.
    Scoped("uploaded_assets", "drawn diagrams and uploaded figures",
           grade="grade", subject="subject",
           strand="strand", sub_strand="sub_strand", layer="diagrams"),
    Scoped("material_drafts", "unfinished lesson-material runs",
           grade="grade", subject="subject",
           strand="strand", sub_strand="sub_strand", layer="notes"),
    Scoped("question_events", "generation, review and approval events",
           grade="grade", subject="subject",
           strand="strand", sub_strand="sub_strand", layer="questions"),
    # The published bundle — notes, diagrams, activities and questions in one
    # row. It belongs to the notes layer: it is what the notes station writes,
    # and it is what the book is printed from.
    Scoped("substrand_resources", "published lesson bundles",
           grade_json="curriculum->>'grade'", subject_json="curriculum->>'subject'",
           strand_json="curriculum->>'strand'",
           sub_strand_json="curriculum->>'sub_strand'", layer="notes"),
    Scoped("question_dna", "questions",
           grade_json="curriculum_link->>'grade'",
           subject_json="curriculum_link->>'subject'",
           strand_json="curriculum_link->>'strand'",
           sub_strand_json="curriculum_link->>'sub_strand'", layer="questions"),
    # Queued and failed work for a scope that no longer exists. A job left
    # behind is worse than an orphaned row: it still runs, and regenerates
    # content for a sub-strand nobody can see, which then reappears in the
    # console as if the delete had silently undone itself.
    Scoped("jobs", "queued and failed jobs",
           grade="grade", subject="subject",
           strand="strand", sub_strand="sub_strand", layer="jobs"),
    Scoped("curriculum_substrands", "the sub-strand itself",
           grade="grade", subject="subject",
           strand="strand_name", sub_strand="sub_strand_name", layer="dataset"),
)


def resolve_layers(requested: Any) -> tuple[str, ...]:
    """Layer names from what a caller sent: names, presets, or nothing (= all)."""
    if not requested:
        return PRESETS["all"]
    if isinstance(requested, str):
        requested = [part for part in requested.replace(";", ",").split(",")]
    chosen: list[str] = []
    for raw in requested:
        name = str(raw or "").strip().lower()
        if not name:
            continue
        for layer in PRESETS.get(name, (name,)):
            if layer not in LAYERS:
                from ..errors import raise_api_error

                raise_api_error(
                    "VALIDATION_FAILED",
                    f"'{name}' is not a layer. Layers: {', '.join(LAYERS)}; "
                    f"presets: {', '.join(PRESETS)}.")
            if layer not in chosen:
                chosen.append(layer)
    return tuple(chosen) or PRESETS["all"]


CONFIRMATION = "DELETE"


@dataclass(slots=True)
class DeleteReport:
    scope: dict[str, str] = field(default_factory=dict)
    dry_run: bool = True
    layers: tuple[str, ...] = ()
    tables: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    strand_removed: bool = False

    @property
    def total(self) -> int:
        return sum(int(t.get("rows", 0)) for t in self.tables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "dry_run": self.dry_run,
            "layers": list(self.layers),
            "total_rows": self.total,
            "tables": [t for t in self.tables if t.get("rows")],
            "failed": self.failed,
            "strand_removed_from_design": self.strand_removed,
            "confirmation_required": CONFIRMATION,
            "message": self._message(),
        }

    def _message(self) -> str:
        what = self.scope.get("sub_strand") or self.scope.get("strand") or "this selection"
        if not self.total and not self.strand_removed:
            return f"Nothing stored for {what}."
        if self.dry_run:
            return (
                f"{self.total} row(s) would be removed for {what}, including everything "
                f"generated from it. Nothing has been deleted — send "
                f'confirm="{CONFIRMATION}" to go ahead.'
            )
        return f"{what} and {self.total} derived row(s) removed."


def _count_and_delete(
    target: Scoped, grade: str, subject: str, strand: str, sub_strand: str,
    dry_run: bool,
) -> dict[str, Any] | None:
    from ..infra.db import execute, fetch_one

    clause, params = target.clause(grade, subject, strand, sub_strand)
    if not clause:
        # Not narrowable to this scope. Deleting it anyway would take rows
        # belonging to sub-strands the operator did not name.
        return None

    row = fetch_one(f"SELECT COUNT(*) AS n FROM {target.table} WHERE {clause}", params)
    rows = int((row or {}).get("n") or 0)
    if rows and not dry_run:
        execute(f"DELETE FROM {target.table} WHERE {clause}", params)
    return {"table": target.table, "what": target.what, "rows": rows}


def _remove_strand_from_design(
    grade: str, subject: str, strand: str, dry_run: bool
) -> bool:
    """Take one strand out of the design's metadata list.

    Strands are a JSONB array on `curriculum_designs`, not rows, so removing one
    is a rewrite of that list rather than a DELETE.
    """
    from ..infra.db import execute, fetch_one, to_json

    row = fetch_one(
        """
        SELECT design_id, metadata FROM curriculum_designs
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND LOWER(subject) = LOWER(:subject)
        ORDER BY updated_at DESC LIMIT 1
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""), "subject": subject},
    )
    if not row:
        return False

    metadata = dict(row.get("metadata") or {})
    strands = metadata.get("strands") or []
    kept = [
        s for s in strands
        if not (isinstance(s, dict)
                and str(s.get("strand_name") or s.get("name") or "").strip().lower()
                == strand.strip().lower())
    ]
    if len(kept) == len(strands):
        return False
    if dry_run:
        return True

    metadata["strands"] = kept
    execute(
        "UPDATE curriculum_designs SET metadata = CAST(:metadata AS jsonb), "
        "updated_at = NOW() WHERE design_id = :design_id",
        {"metadata": to_json(metadata), "design_id": row["design_id"]},
    )
    return True


# Artifacts whose sub-strand no longer exists in the curriculum. Matched on the
# normalised grade because artifacts store "grade-pp1" and the curriculum
# tables have carried both that and "pp1".
_ORPHAN_ARTIFACTS = """
    SELECT a.artifact_id, a.kind, a.grade, a.subject,
           a.strand_name, a.sub_strand_name, a.version
    FROM artifacts a
    WHERE a.sub_strand_name <> ''
      AND NOT EXISTS (
        SELECT 1 FROM curriculum_substrands c
        WHERE LOWER(c.subject) = LOWER(a.subject)
          AND LOWER(c.sub_strand_name) = LOWER(a.sub_strand_name)
          AND REPLACE(LOWER(c.grade), 'grade-', '')
              = REPLACE(LOWER(a.grade), 'grade-', '')
      )
"""


def _remove_designs(grade: str, subject: str, dry_run: bool) -> dict[str, Any]:
    """The design rows of a whole subject, or a whole grade."""
    from ..infra.db import execute, fetch_one

    clause = "(REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))"
    params: dict[str, Any] = {"grade": grade}
    if subject:
        clause += " AND LOWER(subject) = LOWER(:subject)"
        params["subject"] = subject
    row = fetch_one(f"SELECT COUNT(*) AS n FROM curriculum_designs WHERE {clause}", params)
    rows = int((row or {}).get("n") or 0)
    if rows and not dry_run:
        execute(f"DELETE FROM curriculum_designs WHERE {clause}", params)
    return {"table": "curriculum_designs", "what": "the designs themselves", "rows": rows}


def find_orphans(limit: int = 500) -> list[dict[str, Any]]:
    """Generated content whose sub-strand is gone.

    The delete endpoints the older console calls used to remove three tables
    and leave `artifacts` — with every review verdict, label and comment — in
    place. Anything deleted through them before that was fixed is still here,
    still counting toward coverage, still describing a sub-strand nobody can
    see. This finds it after the fact.
    """
    from ..infra.db import fetch_all

    return fetch_all(f"{_ORPHAN_ARTIFACTS} ORDER BY a.subject, a.sub_strand_name "
                     f"LIMIT :limit", {"limit": limit}) or []


def sweep_orphans(confirm: str = "") -> dict[str, Any]:
    """Remove orphaned artifacts and everything hanging off them."""
    from ..infra.db import execute, fetch_one

    found = find_orphans(limit=10_000)
    if confirm.strip().upper() != CONFIRMATION:
        by_scope: dict[str, int] = {}
        for row in found:
            key = (f"{row['grade']} / {row['subject']} / "
                   f"{row['strand_name'] or '—'} / {row['sub_strand_name']}")
            by_scope[key] = by_scope.get(key, 0) + 1
        return {
            "dry_run": True, "artifacts": len(found),
            "scopes": [{"scope": k, "versions": v}
                       for k, v in sorted(by_scope.items(), key=lambda i: -i[1])],
            "confirmation_required": CONFIRMATION,
            "message": (
                f"{len(found)} artifact version(s) describe a sub-strand that no "
                f"longer exists. Send confirm=\"{CONFIRMATION}\" to remove them "
                f"and their reviews, labels and comments."
            ),
        }

    removed: dict[str, int] = {}
    inner = f"SELECT artifact_id FROM ({_ORPHAN_ARTIFACTS}) o"
    for table in ("artifact_comments", "artifact_reviews", "artifact_labels"):
        try:
            row = fetch_one(
                f"SELECT COUNT(*) AS n FROM {table} WHERE artifact_id IN ({inner})")
            execute(f"DELETE FROM {table} WHERE artifact_id IN ({inner})")
            removed[table] = int((row or {}).get("n") or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not sweep %s: %s", table, exc)

    execute(f"DELETE FROM artifacts WHERE artifact_id IN ({inner})")
    removed["artifacts"] = len(found)
    logger.info("Swept %d orphaned artifact version(s).", len(found))
    return {"dry_run": False, "artifacts": len(found), "tables": removed,
            "message": f"Removed {len(found)} orphaned artifact version(s)."}


def delete(
    grade: str,
    subject: str,
    strand: str = "",
    sub_strand: str = "",
    *,
    confirm: str = "",
    keep_strand: bool = False,
    layers: Any = None,
    whole_subject: bool = False,
    whole_grade: bool = False,
) -> DeleteReport:
    """Remove a sub-strand, a strand, a subject or a grade — the layers named.

    `layers` is a list of layer names or presets ("all", "generated",
    "dataset"); nothing means everything. `keep_strand` deletes a strand's
    sub-strands and their content but leaves the strand itself in place —
    which is what "regenerate this strand's sub-strands" needs, since the
    strand is the thing being regenerated against.

    A whole subject or a whole grade has to be asked for by name. The old
    subject delete had its own list of four tables and left the versions,
    the reviews, the labels, the media and the queued jobs behind — and the
    console then showed the subject as still there.
    """
    from ..errors import raise_api_error

    if not grade:
        raise_api_error("VALIDATION_FAILED", "A grade is required.")
    if not subject and not whole_grade:
        raise_api_error("VALIDATION_FAILED", "A subject is required.")
    if not (strand or sub_strand) and not (whole_subject or whole_grade):
        raise_api_error(
            "VALIDATION_FAILED",
            "Name a strand or a sub-strand, or ask for the whole subject "
            "(whole_subject=true) or the whole grade (whole_grade=true).",
        )

    chosen = resolve_layers(layers)
    dry_run = confirm.strip().upper() != CONFIRMATION
    report = DeleteReport(
        scope={"grade": grade, "subject": subject,
               "strand": strand, "sub_strand": sub_strand},
        dry_run=dry_run,
        layers=chosen,
    )

    for target in DERIVED:
        if target.layer not in chosen:
            continue
        try:
            result = _count_and_delete(target, grade, subject, strand, sub_strand, dry_run)
        except Exception as exc:  # noqa: BLE001
            # A table that does not exist in this deployment is not a failure
            # worth aborting on; a real one is worth reporting.
            report.failed.append({"table": target.table, "error": str(exc)[:200]})
            continue
        if result:
            report.tables.append(result)

    # Only when the whole strand is going, and only after its children have.
    if "dataset" in chosen and strand and not sub_strand and not keep_strand:
        try:
            report.strand_removed = _remove_strand_from_design(
                grade, subject, strand, dry_run
            )
        except Exception as exc:  # noqa: BLE001
            report.failed.append({"table": "curriculum_designs", "error": str(exc)[:200]})

    # A whole subject or grade takes its design rows with it.
    if "dataset" in chosen and not strand and not sub_strand:
        try:
            report.tables.append(_remove_designs(grade, subject, dry_run))
        except Exception as exc:  # noqa: BLE001
            report.failed.append({"table": "curriculum_designs", "error": str(exc)[:200]})

    if not dry_run:
        logger.info(
            "Removed %s / %s (%s %s): %d row(s).",
            strand or "-", sub_strand or "-", subject, grade, report.total,
        )
    return report

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

    def clause(self, grade: str, subject: str, strand: str, sub_strand: str
               ) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}
        parts: list[str] = []

        if self.via_artifacts:
            # These tables carry an artifact_id and no curriculum scope of
            # their own, so the whole narrowing happens in the subquery.
            # Running the column checks first found no grade column and bailed
            # out with an empty clause — which meant review verdicts, labels
            # and comments were never deleted, leaving exactly the orphans this
            # module exists to prevent.
            inner = ["1=1"]
            if grade:
                inner.append("(a.grade = :grade OR a.grade = :alt_grade)")
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
            parts.append(f"({target} = :grade OR {target} = :alt_grade)")
            params["grade"] = grade
            params["alt_grade"] = grade.replace("grade-", "")

        for column, json_path, value, name in (
            (self.subject, self.subject_json, subject, "subject"),
            (self.strand, self.strand_json, strand, "strand"),
            (self.sub_strand, self.sub_strand_json, sub_strand, "sub_strand"),
        ):
            if not add(column, json_path, value, name):
                return "", {}

        return (" AND ".join(parts) if parts else "1=1"), params


# Children before parents. Deleting the sub-strand first would leave its notes,
# its questions and its review verdicts pointing at a row that is gone.
DERIVED: tuple[Scoped, ...] = (
    Scoped("artifact_comments", "comments on versions", via_artifacts="artifact_id"),
    Scoped("artifact_reviews", "review verdicts", via_artifacts="artifact_id"),
    Scoped("artifact_labels", "labels", via_artifacts="artifact_id"),
    Scoped("artifact_dna", "content fingerprints",
           grade_json="curriculum_link->>'grade'",
           subject_json="curriculum_link->>'subject'",
           strand_json="curriculum_link->>'strand'",
           sub_strand_json="curriculum_link->>'sub_strand'"),
    Scoped("artifacts", "generated versions",
           grade="grade", subject="subject",
           strand="strand_name", sub_strand="sub_strand_name"),
    Scoped("substrand_media", "photo and video briefs",
           grade="grade", subject="subject",
           strand="strand_name", sub_strand="sub_strand_name"),
    Scoped("substrand_resources", "notes, diagrams, activities",
           grade_json="curriculum->>'grade'", subject_json="curriculum->>'subject'",
           strand_json="curriculum->>'strand'",
           sub_strand_json="curriculum->>'sub_strand'"),
    Scoped("question_dna", "questions",
           grade_json="curriculum_link->>'grade'",
           subject_json="curriculum_link->>'subject'",
           strand_json="curriculum_link->>'strand'",
           sub_strand_json="curriculum_link->>'sub_strand'"),
    Scoped("curriculum_substrands", "the sub-strand itself",
           grade="grade", subject="subject",
           strand="strand_name", sub_strand="sub_strand_name"),
)

CONFIRMATION = "DELETE"


@dataclass(slots=True)
class DeleteReport:
    scope: dict[str, str] = field(default_factory=dict)
    dry_run: bool = True
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
        WHERE (grade = :grade OR grade = :alt_grade)
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


def delete(
    grade: str,
    subject: str,
    strand: str = "",
    sub_strand: str = "",
    *,
    confirm: str = "",
    keep_strand: bool = False,
) -> DeleteReport:
    """Remove one sub-strand, or one strand and everything under it.

    `keep_strand` deletes a strand's sub-strands and their content but leaves
    the strand itself in place — which is what "regenerate this strand's
    sub-strands" needs, since the strand is the thing being regenerated
    against.
    """
    from ..errors import raise_api_error

    if not (grade and subject):
        raise_api_error("VALIDATION_FAILED", "A grade and a subject are required.")
    if not (strand or sub_strand):
        raise_api_error(
            "VALIDATION_FAILED",
            "Name a strand or a sub-strand. Clearing a whole learning area is "
            "what POST /factory/reset is for, and it asks for a longer "
            "confirmation because it takes more.",
        )

    dry_run = confirm.strip().upper() != CONFIRMATION
    report = DeleteReport(
        scope={"grade": grade, "subject": subject,
               "strand": strand, "sub_strand": sub_strand},
        dry_run=dry_run,
    )

    for target in DERIVED:
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
    if strand and not sub_strand and not keep_strand:
        try:
            report.strand_removed = _remove_strand_from_design(
                grade, subject, strand, dry_run
            )
        except Exception as exc:  # noqa: BLE001
            report.failed.append({"table": "curriculum_designs", "error": str(exc)[:200]})

    if not dry_run:
        logger.info(
            "Removed %s / %s (%s %s): %d row(s).",
            strand or "-", sub_strand or "-", subject, grade, report.total,
        )
    return report

"""Clear generated content and start again from the dataset.

The dataset in Langfuse is the source of truth: it holds the KICD design
documents, and nothing here touches it. Everything in Postgres downstream of it
— designs, strands, sub-strands, notes, media, artifacts, reviews, questions —
is derived, reproducible, and safe to discard when the pipeline that produced it
has changed enough that the old output is not worth reconciling.

Three things this is careful about.

It never deletes configuration. Users, API keys, provider credentials, stage
bindings and the migration ledger are not curriculum content, and losing them
turns a content reset into an outage.

It is a dry run unless told otherwise. The counts come back first, so the
operator sees exactly what would go before anything does.

It deletes children before parents, in one transaction per table, so a partial
failure cannot leave sub-strands pointing at a design that no longer exists —
which is the state the incomplete per-subject delete used to produce.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-factory-reset")


@dataclass(slots=True)
class Target:
    """One table to clear, and how to narrow it to a grade or a subject."""

    table: str
    what: str
    grade_column: str = ""
    subject_column: str = ""
    # Where the scope lives inside a JSONB column instead of its own.
    grade_json: str = ""
    subject_json: str = ""
    # Rows reachable only through an artifact's key. These tables carry no
    # grade of their own, so a grade-scoped reset used to SKIP them — deleting
    # the artifacts and leaving their reviews, labels, comments and
    # fingerprints behind, pointing at rows that no longer exist. That is the
    # same orphaning the scoped delete was fixed for, still here.
    via_artifacts: str = ""

    def where(self, grade: str, subject: str) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}

        if self.via_artifacts:
            inner = ["1=1"]
            if grade:
                inner.append("(REPLACE(LOWER(a.grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))")
                params["grade"] = grade
                params["alt_grade"] = grade.replace("grade-", "")
            if subject:
                inner.append("LOWER(a.subject) = LOWER(:subject)")
                params["subject"] = subject
            return (
                f"{self.via_artifacts} IN (SELECT a.artifact_id FROM artifacts a "
                f"WHERE {' AND '.join(inner)})",
                params,
            )

        if grade:
            if self.grade_column:
                clauses.append(f"({self.grade_column} = :grade OR {self.grade_column} = :alt_grade)")
            elif self.grade_json:
                clauses.append(
                    f"(LOWER({self.grade_json}) = LOWER(:grade) "
                    f"OR LOWER({self.grade_json}) = LOWER(:alt_grade))"
                )
            else:
                # Not scoped by grade: a grade-limited reset must leave it alone
                # rather than delete the lot.
                return "", {}
            params["grade"] = grade
            params["alt_grade"] = grade.replace("grade-", "")

        if subject:
            if self.subject_column:
                clauses.append(f"LOWER({self.subject_column}) = LOWER(:subject)")
            elif self.subject_json:
                clauses.append(f"LOWER({self.subject_json}) = LOWER(:subject)")
            else:
                return "", {}
            params["subject"] = subject

        return (" AND ".join(clauses) if clauses else "1=1"), params


# Children first, parents last. A reset that removes designs before the
# sub-strands that reference them leaves rows nothing can resolve.
DERIVED: tuple[Target, ...] = (
    Target("artifact_comments", "comments on generated versions",
           via_artifacts="artifact_id"),
    Target("artifact_reviews", "layered review verdicts",
           via_artifacts="artifact_id"),
    Target("artifact_labels", "approved/production labels",
           via_artifacts="artifact_id"),
    Target("artifacts", "every generated version",
           grade_column="grade", subject_column="subject"),
    Target("substrand_media", "photo and video briefs and assets",
           grade_column="grade", subject_column="subject"),
    Target("substrand_resources", "generated notes, diagrams, activities, questions",
           grade_json="curriculum->>'grade'", subject_json="curriculum->>'subject'"),
    Target("question_dna", "question bank entries",
           grade_json="curriculum_link->>'grade'", subject_json="curriculum_link->>'subject'"),
    # Maths walkthroughs are keyed on curriculum_link exactly like question_dna.
    # Left out, a grade-scoped reset deleted the questions and left their
    # walkthroughs behind — orphans pointing at content that no longer exists,
    # and narration audio still sitting in MinIO.
    Target("math_simulations", "maths walkthroughs and their narration",
           grade_json="curriculum_link->>'grade'",
           subject_json="curriculum_link->>'subject'"),
    Target("diagram_registry", "rendered diagrams and their parts"),
    Target("artifact_dna", "content fingerprints",
           grade_json="curriculum_link->>'grade'",
           subject_json="curriculum_link->>'subject'"),
    # Queued work and the drafts it produced. Left behind, a "start again" left
    # every unaccepted sub-strand draft in place and a queue still holding jobs
    # for content that no longer exists — which then ran, and regenerated it.
    Target("jobs", "queued work and unaccepted drafts",
           grade_column="grade", subject_column="subject"),
    Target("curriculum_substrands", "sub-strands",
           grade_column="grade", subject_column="subject"),
    Target("curriculum_nodes", "curriculum tree nodes",
           grade_column="grade", subject_column="subject"),
    Target("grade_scope", "derived per-grade scope summaries",
           grade_column="grade", subject_column="subject"),
    Target("curriculum_designs", "ingested curriculum designs",
           grade_column="grade", subject_column="subject"),
    # Without this a grade cleared and re-ingested was reported as already
    # ingested, and the design never came back.
    Target("dataset_ingest_status", "which dataset items have been ingested",
           grade_column="grade"),
    Target("pipeline_runs", "pipeline run history"),
    Target("generation_costs", "token and cost records"),
    Target("data_repairs", "recorded repairs"),
    Target("idempotency_cache", "request de-duplication cache"),
)

# Not curriculum content. Losing these turns a content reset into an outage.
PROTECTED: tuple[str, ...] = (
    "app_users", "api_keys", "refresh_tokens", "provider_configs",
    "stage_bindings", "schema_migrations", "prompt_versions",
    "generation_targets", "subject_profiles", "audit_events", "milestone_events",
    "exams",
)

# What the caller must send to actually delete. A boolean is too easy to send by
# accident from a form or a retried request.
CONFIRMATION = "DELETE ALL GENERATED CONTENT"


@dataclass(slots=True)
class ResetReport:
    scope: dict[str, str] = field(default_factory=dict)
    dry_run: bool = True
    tables: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(int(t.get("rows", 0)) for t in self.tables)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "dry_run": self.dry_run,
            "total_rows": self.total,
            "tables": self.tables,
            "skipped": self.skipped,
            "failed": self.failed,
            "protected": list(PROTECTED),
            "confirmation_required": CONFIRMATION,
            "message": self._message(),
        }

    def _message(self) -> str:
        where = self.scope.get("subject") or self.scope.get("grade") or "every grade"
        if self.dry_run:
            return (
                f"{self.total:,} row(s) across {len(self.tables)} table(s) would be "
                f"deleted for {where}. Nothing has been deleted. Send "
                f'confirm="{CONFIRMATION}" to proceed. The Langfuse dataset is not '
                f"touched, so everything here can be produced again from it."
            )
        if self.failed:
            return (
                f"{self.total:,} row(s) deleted, but {len(self.failed)} table(s) "
                f"failed. The reset is INCOMPLETE and some content may reference "
                f"rows that are gone."
            )
        return (
            f"{self.total:,} row(s) deleted for {where}. Re-ingest from the dataset "
            f"to rebuild."
        )


def _count(table: str, where: str, params: dict[str, Any]) -> int:
    from ..infra.db import fetch_one

    row = fetch_one(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)
    return int((row or {}).get("n") or 0)


def run(
    grade: str = "",
    subject: str = "",
    confirm: str = "",
    include: list[str] | None = None,
) -> ResetReport:
    """Count, and delete only when the confirmation phrase is exact."""
    from ..infra.db import execute

    report = ResetReport(
        scope={k: v for k, v in (("grade", grade), ("subject", subject)) if v},
        dry_run=confirm != CONFIRMATION,
    )

    if subject and not grade:
        # A subject name is not unique across grades — "Mathematical Activities"
        # exists at every level — so clearing one by name alone would silently
        # take the others with it.
        report.failed.append({
            "table": "(scope)",
            "error": "A subject reset needs a grade too. Subject names repeat "
                     "across grades, so clearing one by name alone would take "
                     "every grade's copy with it.",
        })
        return report

    for target in DERIVED:
        if include and target.table not in include:
            continue

        where, params = target.where(grade, subject)
        if not where:
            report.skipped.append({
                "table": target.table,
                "why": f"not scoped by {'subject' if subject else 'grade'}; "
                       f"left untouched by a narrowed reset",
            })
            continue

        try:
            rows = _count(target.table, where, params)
        except Exception as exc:  # noqa: BLE001
            report.failed.append({"table": target.table, "error": str(exc)[:200]})
            continue

        entry = {"table": target.table, "what": target.what, "rows": rows}
        report.tables.append(entry)

        if report.dry_run or rows == 0:
            continue

        try:
            execute(f"DELETE FROM {target.table} WHERE {where}", params)
            logger.warning("Reset deleted %d row(s) from %s.", rows, target.table)
        except Exception as exc:  # noqa: BLE001
            entry["deleted"] = False
            report.failed.append({"table": target.table, "error": str(exc)[:200]})
        else:
            entry["deleted"] = True

    return report

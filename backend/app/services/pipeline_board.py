"""The pipeline as a board: what is built, what passed, what is stuck.

Everything needed to answer "where is this grade?" existed and was scattered
across five screens. Coverage said what percentage was generated; the queue
said what was running; the artifact list said what versions existed; the review
panel said what one version scored; nothing said, for one grade, which stage of
which subject is holding everything else up.

The shape people already know for this is a build board, so this is one:

    GRADE      is the project
    SUBJECT    is a branch of it
    STAGE      is a build step — strands, sub-strands, the lesson plan, the
               material, and the assets drawn from it
    REVIEWERS  are the step's tests, and the stage policy is what "passing"
               means for that step

A stage is red, amber or green for the same reason a build step is: what it
produced, whether its gate passed, and whether anything is failing. And the
board is read top-down — a subject is only as far along as its earliest
unfinished stage, because that is what is actually blocking it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import stage_policy

logger = logging.getLogger("cbc-pipeline-board")

# Which artifact kind each stage files. `ingest`, `strands` and `substrands`
# write curriculum rows rather than artifacts, so they are counted differently.
STAGE_KIND: dict[str, str] = {
    "notes": "notes",
    "material": "material",
    "diagram": "diagram",
    "media": "photo_prompt",
    "simulation": "simulation",
    "activity": "activity",
    "questions": "question",
}

# What a stage is called where a person reads it.
STAGE_LABEL: dict[str, str] = {
    "ingest": "Read the design",
    "strands": "Strands",
    "substrands": "Sub-strands",
    "notes": "Lesson plan",
    "material": "Lesson material",
    "diagram": "Diagrams",
    "media": "Photos & videos",
    "simulation": "Simulations",
    "activity": "Activities",
    "questions": "Questions",
}

# Amber rather than green: built, but not through its gate yet.
STATUSES = ("not_started", "running", "failing", "built", "reviewed",
            "approved", "blocked")


@dataclass(slots=True)
class Stage:
    stage: str
    label: str = ""
    status: str = "not_started"
    expected: int = 0
    built: int = 0
    reviewed: int = 0
    approved: int = 0
    running: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    last_run: str = ""
    # Why this stage is not green, in the words an operator would use.
    blocked_by: str = ""
    policy: dict[str, Any] = field(default_factory=dict)
    # Only on `ingest`: where the design came from, and whether it arrived.
    dataset: dict[str, Any] = field(default_factory=dict)
    # What would unblock it. A board that says "waiting on the lesson plan" and
    # makes you go and find the lesson plan has told you where to click, which
    # is not the same as letting you click it.
    remedy: list[dict[str, Any]] = field(default_factory=list)

    @property
    def percentage(self) -> int:
        if not self.expected:
            return 0
        return min(100, round(self.built / self.expected * 100))

    @property
    def files_versions(self) -> bool:
        """Whether there is anything here to review, approve or regenerate.

        `ingest`, `strands` and `substrands` write curriculum rows, not
        artifacts — nothing is filed with a version, a review or a label. The
        board offered Review on them anyway, enabled the moment they had built
        anything, and every press came back "there is nothing to review". A
        button that is enabled and always fails is worse than no button, so the
        board has to know this rather than find out from the server.
        """
        return bool(STAGE_KIND.get(self.stage))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "label": self.label, "status": self.status,
            "expected": self.expected, "built": self.built,
            "reviewed": self.reviewed, "approved": self.approved,
            "running": self.running, "failed": self.failed,
            "percentage": self.percentage,
            "files_versions": self.files_versions,
            "cost_usd": round(self.cost_usd, 4),
            "last_run": self.last_run, "blocked_by": self.blocked_by,
            "policy": self.policy, "dataset": self.dataset,
            "remedy": self.remedy,
        }


@dataclass(slots=True)
class Branch:
    subject: str
    stages: list[Stage] = field(default_factory=list)

    @property
    def blocking(self) -> Stage | None:
        """The earliest stage that is not finished — what is actually holding
        this subject up. A board that shows every red stage at once tells you
        ten things when one of them is the cause of the other nine."""
        for stage in self.stages:
            if stage.status in ("not_started", "running", "failing", "built",
                                "reviewed", "blocked"):
                return stage
        return None

    @property
    def status(self) -> str:
        blocking = self.blocking
        return blocking.status if blocking else "approved"

    @property
    def cost_usd(self) -> float:
        return round(sum(s.cost_usd for s in self.stages), 4)

    def to_dict(self) -> dict[str, Any]:
        blocking = self.blocking
        return {
            "subject": self.subject,
            "status": self.status,
            "blocking_stage": blocking.stage if blocking else "",
            "blocked_by": blocking.blocked_by if blocking else "",
            "cost_usd": self.cost_usd,
            "stages": [s.to_dict() for s in self.stages],
        }


@dataclass(slots=True)
class Project:
    grade: str
    label: str = ""
    branches: list[Branch] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(b.cost_usd for b in self.branches), 4)

    def to_dict(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for branch in self.branches:
            by_status[branch.status] = by_status.get(branch.status, 0) + 1
        return {
            "grade": self.grade, "label": self.label,
            "branches": len(self.branches),
            "by_status": by_status,
            "cost_usd": self.cost_usd,
            "subjects": [b.to_dict() for b in self.branches],
        }


def _rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    try:
        return fetch_all(sql, params) or []
    except Exception as exc:  # noqa: BLE001
        # A board that refuses to draw because one table is missing is less
        # useful than a board with one column empty.
        logger.warning("Board query failed (%s): %s", exc, sql.strip()[:80])
        return []


def _decide(stage: Stage, policy: stage_policy.Policy) -> None:
    """What colour this stage is, and why."""
    # The first stage answers a different question from the rest: not "has it
    # been built" but "has the design arrived". A grade with nothing in it
    # reads as "not started" either way, and those are different problems with
    # different next actions.
    if stage.stage == "ingest" and stage.dataset:
        state = stage.dataset.get("state")
        if state in ("not_imported", "imported", "failing", "running"):
            stage.status = {"not_imported": "not_started", "imported": "built",
                            "failing": "failing", "running": "running"}[state]
            stage.blocked_by = stage.dataset.get("note", "")
            return
    if stage.failed:
        stage.status = "failing"
        stage.blocked_by = (
            f"{stage.failed} job(s) failed. Read the error on the queue and "
            f"retry, or fix and re-run."
        )
        return
    if stage.running:
        stage.status = "running"
        stage.blocked_by = f"{stage.running} job(s) in flight."
        return
    if not stage.built:
        stage.status = "not_started"
        stage.blocked_by = (
            f"Nothing built yet"
            + (f" — {stage.expected} expected." if stage.expected else ".")
        )
        return
    if stage.expected and stage.built < stage.expected:
        stage.status = "built"
        stage.blocked_by = (
            f"{stage.built} of {stage.expected} built. Run the rest."
        )
        return
    if policy.required_layers and stage.reviewed < stage.built:
        stage.status = "built"
        stage.blocked_by = (
            f"{stage.built - stage.reviewed} of {stage.built} not reviewed. "
            f"This stage requires layer(s) "
            f"{', '.join(str(n) for n in policy.required_layers)}."
        )
        return
    if policy.requires_human and stage.approved < stage.built:
        stage.status = "reviewed"
        stage.blocked_by = (
            f"{stage.built - stage.approved} of {stage.built} awaiting a "
            f"person's approval. This stage does not move without one."
        )
        return
    stage.status = "approved"
    stage.blocked_by = ""


def _artifact_counts(grade: str, subject: str) -> dict[str, dict[str, int]]:
    """Built, reviewed and approved, per artifact kind, in one query."""
    rows = _rows(
        """
        SELECT a.kind,
               COUNT(DISTINCT a.artifact_key) AS built,
               COUNT(DISTINCT CASE WHEN r.artifact_id IS NOT NULL
                                   THEN a.artifact_key END) AS reviewed,
               COUNT(DISTINCT CASE WHEN l.label = 'approved'
                                   THEN a.artifact_key END) AS approved
        FROM artifacts a
        LEFT JOIN artifact_reviews r ON r.artifact_id = a.artifact_id
        LEFT JOIN artifact_labels l ON l.artifact_id = a.artifact_id
        -- LOWER on BOTH sides. The rows are written "grade-pp1"; a caller
        -- sending "PP1" derives "grade-PP1", which is not equal to it in
        -- Postgres — and the board then reports a grade with seven ingested
        -- designs as having no sub-strands at all. Fixed once already on the
        -- sub-strands endpoint, and reintroduced here.
        WHERE (LOWER(a.grade) = LOWER(:grade) OR LOWER(a.grade) = LOWER(:alt_grade))
          AND LOWER(a.subject) = LOWER(:subject)
        GROUP BY a.kind
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""),
         "subject": subject},
    )
    return {
        str(r["kind"]): {
            "built": int(r["built"] or 0),
            "reviewed": int(r["reviewed"] or 0),
            "approved": int(r["approved"] or 0),
        }
        for r in rows
    }


def _job_counts(grade: str, subject: str) -> dict[str, dict[str, Any]]:
    rows = _rows(
        """
        SELECT kind,
               COUNT(*) FILTER (WHERE status IN ('queued', 'running')) AS running,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed,
               COALESCE(SUM(cost_usd), 0) AS cost,
               MAX(finished_at) AS last_run
        FROM jobs
        WHERE (LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt_grade))
          AND LOWER(subject) = LOWER(:subject)
        GROUP BY kind
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""),
         "subject": subject},
    )
    return {
        str(r["kind"]): {
            "running": int(r["running"] or 0),
            "failed": int(r["failed"] or 0),
            "cost": float(r["cost"] or 0),
            "last_run": str(r["last_run"] or ""),
        }
        for r in rows
    }


def dataset_state(grade: str) -> dict[str, Any]:
    """Whether this grade's design has been imported and read in yet.

    The journey starts here and the board did not show it. `ingest` was drawn
    green the moment a design row existed, which says nothing about the dataset
    it came from — whether anything is waiting, whether an item failed, or
    whether the grade has simply never been imported. An operator looking at a
    grade with nothing in it could not tell "no design" from "not imported".
    """
    rows = _rows(
        """
        SELECT status, COUNT(*) AS n
        FROM dataset_ingest_status
        WHERE LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt)
        GROUP BY status
        """,
        {"grade": grade, "alt": grade.replace("grade-", "")},
    )
    counts = {str(r["status"]): int(r["n"] or 0) for r in rows}
    designs = _rows(
        "SELECT COUNT(*) AS n FROM curriculum_designs "
        "WHERE LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt)",
        {"grade": grade, "alt": grade.replace("grade-", "")},
    )
    filed = int((designs or [{}])[0].get("n") or 0)
    total = sum(counts.values())

    if not total and not filed:
        state, note = "not_imported", (
            "Nothing has been imported for this grade. The pipeline starts at "
            "the Langfuse dataset: import the design documents, then read them "
            "in."
        )
    elif counts.get("failed"):
        state, note = "failing", (
            f"{counts['failed']} dataset item(s) failed to read. Everything "
            f"below is built from what did read, so a failure here is a hole "
            f"in every stage after it."
        )
    elif counts.get("pending") or counts.get("running"):
        state, note = "running", (
            f"{counts.get('pending', 0) + counts.get('running', 0)} item(s) "
            f"still to read."
        )
    elif filed:
        state, note = "done", ""
    else:
        state, note = "imported", (
            f"{total} dataset item(s) imported and none read in yet."
        )

    return {"state": state, "note": note, "designs": filed,
            "items": total, "by_status": counts}


def _expected(grade: str, subject: str) -> dict[str, int]:
    """How many units each stage owes, from the design rather than from what
    was produced. Measuring completion against what exists means a stage that
    produced nothing is 100% complete."""
    alt = grade.replace("grade-", "")
    design = _rows(
        "SELECT metadata FROM curriculum_designs "
        "WHERE (LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt)) "
        "  AND LOWER(subject) = LOWER(:subject) LIMIT 1",
        {"grade": grade, "alt": alt, "subject": subject},
    )
    strands = 0
    if design:
        meta = design[0].get("metadata") or {}
        listed = meta.get("strands") if isinstance(meta, dict) else None
        strands = len(listed) if isinstance(listed, list) else 0

    substrands = _rows(
        "SELECT COUNT(*) AS n FROM curriculum_substrands "
        "WHERE (LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt)) "
        "  AND LOWER(subject) = LOWER(:subject)",
        {"grade": grade, "alt": alt, "subject": subject},
    )
    count = int((substrands or [{}])[0].get("n") or 0)

    return {
        "ingest": 1 if design else 0,
        "strands": 1 if design else 0,
        "substrands": strands,
        "notes": count, "material": count, "diagram": count,
        "media": count, "simulation": count, "activity": count,
        "questions": count,
    }


# What a stage's reset actually deletes, keyed by stage. `ingest` is not here:
# clearing the design a grade was built from is `factory/reset`, and doing it
# from a stage tile would be a very large action behind a very small button.
RESET_KINDS: dict[str, tuple[str, ...]] = {
    "notes": ("notes",),
    "material": ("material",),
    "diagram": ("diagram",),
    "media": ("photo_prompt", "video_prompt"),
    "simulation": ("simulation",),
    "activity": ("activity", "experiment"),
    "questions": ("question", "answer"),
}


def reset_stage(grade: str, subject: str, stage: str, *,
                confirm: str = "") -> dict[str, Any]:
    """Throw away one stage's output, so it can be built again.

    A stage-level reset because that is the unit an operator actually works in.
    Clearing a whole grade to re-run the diagrams costs the lesson plans that
    were fine, and clearing nothing means living with the first attempt.

    A dry run unless confirmed, like every other destructive path here: the
    counts should be visible before anything is irreversible.
    """
    from ..infra.db import execute, fetch_one

    kinds = RESET_KINDS.get(stage)
    if not kinds:
        return {"stage": stage, "supported": False,
                "reason": (
                    f"{stage} files no versions of its own, so there is nothing "
                    f"to reset. Clearing the design a grade was read from is "
                    f"the factory reset, not a stage."
                )}

    where = ["a.kind = ANY(:kinds)",
             "(LOWER(a.grade) = LOWER(:grade) OR LOWER(a.grade) = LOWER(:alt))"]
    params: dict[str, Any] = {
        "kinds": list(kinds), "grade": grade,
        "alt": grade.replace("grade-", ""),
    }
    if subject:
        where.append("LOWER(a.subject) = LOWER(:subject)")
        params["subject"] = subject
    clause = " AND ".join(where)
    inner = f"SELECT a.artifact_id FROM artifacts a WHERE {clause}"

    counted = fetch_one(f"SELECT COUNT(*) AS n FROM ({inner}) x", params) or {}
    versions = int(counted.get("n") or 0)

    # Queued work for a stage that is about to be deleted would run and rebuild
    # it, which reads as the reset silently undoing itself.
    job_where = ["kind = :stage",
                 "(LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt))"]
    job_params = {"stage": stage, "grade": grade,
                  "alt": grade.replace("grade-", "")}
    if subject:
        job_where.append("LOWER(subject) = LOWER(:subject)")
        job_params["subject"] = subject
    jobs_row = fetch_one(
        f"SELECT COUNT(*) AS n FROM jobs WHERE {' AND '.join(job_where)}",
        job_params) or {}
    jobs = int(jobs_row.get("n") or 0)

    if confirm.strip().upper() != "DELETE":
        return {
            "stage": stage, "supported": True, "dry_run": True,
            "versions": versions, "jobs": jobs,
            "message": (
                f"{versions} version(s) and {jobs} job(s) would be deleted for "
                f"{stage} in {subject or 'every subject'}. Nothing has been "
                f"deleted. Send confirm=\"DELETE\" to proceed — the lesson "
                f"plan and everything else stays."
            ),
        }

    # Children before parents, as everywhere else: a review pointing at a
    # version that is gone is an orphan nothing can resolve.
    for table in ("artifact_comments", "artifact_reviews", "artifact_labels"):
        try:
            execute(f"DELETE FROM {table} WHERE artifact_id IN ({inner})", params)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not clear %s for %s: %s", table, stage, exc)
    execute(f"DELETE FROM artifacts a WHERE {clause}", params)
    execute(f"DELETE FROM jobs WHERE {' AND '.join(job_where)}", job_params)

    logger.info("Reset %s for %s/%s: %d version(s), %d job(s).",
                stage, grade, subject or "every subject", versions, jobs)
    return {"stage": stage, "supported": True, "dry_run": False,
            "versions": versions, "jobs": jobs,
            "message": f"{versions} version(s) and {jobs} job(s) deleted. "
                       f"Run {stage} again to rebuild."}


def branch(grade: str, subject: str,
           policies: list[stage_policy.Policy] | None = None) -> Branch:
    """One subject, stage by stage."""
    policies = policies or stage_policy.all_policies()
    artifacts = _artifact_counts(grade, subject)
    jobs = _job_counts(grade, subject)
    expected = _expected(grade, subject)
    dataset = dataset_state(grade)

    out = Branch(subject=subject)
    for policy in policies:
        name = policy.stage
        stage = Stage(stage=name, label=STAGE_LABEL.get(name, name),
                      policy=policy.to_dict(),
                      expected=int(expected.get(name, 0)))

        kind = STAGE_KIND.get(name)
        if kind:
            counts = artifacts.get(kind, {})
            stage.built = counts.get("built", 0)
            stage.reviewed = counts.get("reviewed", 0)
            stage.approved = counts.get("approved", 0)
        elif name == "ingest":
            stage.built = stage.approved = stage.reviewed = expected.get("ingest", 0)
            stage.dataset = dataset
        elif name == "strands":
            stage.built = stage.approved = stage.reviewed = (
                1 if expected.get("substrands") else 0)
        elif name == "substrands":
            stage.built = stage.reviewed = stage.approved = expected.get("substrands", 0)

        # Job kinds and stage names mostly agree; where they do not, the queue
        # uses its own word.
        job = jobs.get(name) or jobs.get({"media": "media"}.get(name, name)) or {}
        stage.running = int(job.get("running", 0))
        stage.failed = int(job.get("failed", 0))
        stage.cost_usd = float(job.get("cost", 0.0))
        stage.last_run = str(job.get("last_run", ""))

        _decide(stage, policy)
        out.stages.append(stage)

    # A stage whose upstream blocks it is not "not started" — it is waiting,
    # and saying so is the difference between a board that explains itself and
    # one that shows ten reds for one cause.
    blocking_index = None
    for i, stage in enumerate(out.stages):
        policy = policies[i]
        if blocking_index is not None and stage.status == "not_started":
            upstream = out.stages[blocking_index]
            stage.status = "blocked"
            stage.blocked_by = (
                f"Waiting on {upstream.label.lower()}: {upstream.blocked_by}"
            )
            # Everything between here and what is blocking it, in the order it
            # has to be built. The board knows this already; the operator had
            # to work it out from ten red tiles with one cause.
            stage.remedy = _remedy_for(grade, subject, stage, out.stages[:i])
            continue
        if blocking_index is None and stage.status != "approved" and policy.blocks_downstream:
            blocking_index = i

    # A stage that is not blocked but has nothing in it is one press, and a
    # grade with no design at all is a different press entirely.
    for stage in out.stages:
        if stage.remedy:
            continue
        if stage.stage == "ingest" and dataset.get("state") == "not_imported":
            stage.remedy = remedies.as_payload(remedies.import_the_design(grade))
        elif stage.status == "not_started":
            stage.remedy = remedies.as_payload(
                remedies.run_this_stage(grade, subject, stage.stage)
            )
    return out


def _remedy_for(grade: str, subject: str, stage: Stage,
                earlier: list[Stage]) -> list[dict[str, Any]]:
    """The route from where this branch actually is to where this stage needs it.

    Built from what is already done rather than from the chain alone: proposing
    stages that have already run is how a remedy teaches an operator to ignore
    remedies.
    """
    have = {s.stage for s in earlier if s.status == "approved"}
    return remedies.as_payload(
        remedies.missing_upstream(grade, subject, stage.stage, have=have)
    )


def project(grade: str) -> Project:
    """One grade, every subject in it."""
    from .grade_order import grade_label

    subjects = _rows(
        "SELECT DISTINCT subject FROM curriculum_designs "
        "WHERE LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt) "
        "ORDER BY subject",
        {"grade": grade, "alt": grade.replace("grade-", "")},
    )
    policies = stage_policy.all_policies()
    out = Project(grade=grade, label=grade_label(grade))
    for row in subjects:
        name = str(row.get("subject") or "").strip()
        if name:
            out.branches.append(branch(grade, name, policies))
    return out


def projects() -> list[dict[str, Any]]:
    """Every grade there is, in curriculum order — not only the ingested ones.

    Listing only what has been started answers "what have I done" and hides the
    question actually being asked, which is "what is left". A grade with
    nothing in it is the most actionable row on the board: it is the one to
    start next. So the list comes from the curriculum's own sequence, and what
    exists is joined onto it.
    """
    from .grade_order import GRADE_SEQUENCE

    designs = {
        str(r["grade"]).lower(): r
        for r in _rows(
            """
            SELECT LOWER(grade) AS grade,
                   COUNT(DISTINCT subject) AS subjects
            FROM curriculum_designs GROUP BY LOWER(grade)
            """,
            {},
        )
    }
    substrands = {
        str(r["grade"]).lower(): int(r["n"] or 0)
        for r in _rows(
            """
            SELECT LOWER(REPLACE(grade, 'grade-', '')) AS grade, COUNT(*) AS n
            FROM curriculum_substrands GROUP BY LOWER(REPLACE(grade, 'grade-', ''))
            """,
            {},
        )
    }
    jobs = {
        str(r["grade"]).lower(): r
        for r in _rows(
            """
            SELECT LOWER(REPLACE(grade, 'grade-', '')) AS grade,
                   COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                   COUNT(*) FILTER (WHERE status IN ('queued','running')) AS running,
                   COALESCE(SUM(cost_usd), 0) AS cost
            FROM jobs GROUP BY LOWER(REPLACE(grade, 'grade-', ''))
            """,
            {},
        )
    }

    out = []
    for slug, label, level in GRADE_SEQUENCE:
        bare = slug.replace("grade-", "")
        design = designs.get(slug) or designs.get(bare) or {}
        counts = jobs.get(bare) or {}
        out.append({
            "grade": slug,
            "label": label,
            "level": level,
            "ingested": bool(design),
            "subjects": int(design.get("subjects") or 0),
            "sub_strands": substrands.get(bare, 0),
            "running": int(counts.get("running") or 0),
            "failed": int(counts.get("failed") or 0),
            "cost_usd": round(float(counts.get("cost") or 0), 4),
        })
    return out

"""Everything generated for a learning area, as a folder of JSON.

Content that only exists inside a console is content nobody can review
properly. A curriculum is a body of work — twelve sub-strands, their notes,
their diagrams, their media briefs, their questions and every review verdict —
and reviewing it means opening it in an editor, searching across it, and
diffing this week's against last week's.

So this writes a directory tree, one JSON file per thing, and zips it.

Two decisions make it reviewable rather than merely downloadable.

Keys are sorted and the indent is fixed, so two exports of the same content
produce byte-identical files and `git diff` between them shows what actually
changed rather than what happened to serialise in a different order.

Filenames are derived from the curriculum, not from database ids. A sub-strand
is `creation__our-god.json` in every export, on every machine, for ever — so a
diff pairs the right files, and a reviewer can find the one they mean without
consulting a lookup table.
"""
from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("cbc-export")

INDENT = 2


def slug(text: str) -> str:
    """A filename that survives every filesystem and sorts predictably."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return cleaned or "unnamed"


def _dump(value: Any) -> str:
    # sort_keys is what makes two exports diffable. Without it a re-export
    # rewrites every file and the diff is noise.
    return json.dumps(value, indent=INDENT, sort_keys=True, ensure_ascii=False, default=str) + "\n"


@dataclass(slots=True)
class ExportReport:
    grade: str = ""
    subject: str = ""
    files: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"grade": self.grade, "subject": self.subject,
                "file_count": len(self.files), "counts": self.counts,
                "files": self.files}


def _rows(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    try:
        return fetch_all(sql, params) or []
    except Exception as exc:  # noqa: BLE001
        # A table absent in this deployment is not a reason to fail the export.
        logger.warning("Export skipped a source: %s", exc)
        return []


def collect(grade: str, subject: str = "") -> dict[str, str]:
    """Every file the export contains, as path -> JSON text."""
    from .generation_version import VERSION

    params = {
        "grade": grade,
        "alt_grade": grade.replace("grade-", "") if grade.startswith("grade-") else f"grade-{grade}",
        "subject": subject,
    }
    scope = "(LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt_grade))"
    subject_clause = " AND (:subject = '' OR LOWER(subject) = LOWER(:subject))"

    files: dict[str, str] = {}
    counts: dict[str, int] = {}

    # ── the curriculum spine ────────────────────────────────────────────────
    substrands = _rows(
        f"""
        SELECT grade, subject, strand_id, strand_name, sub_strand_id,
               sub_strand_name, theme, allocated_hours, slos,
               learning_experiences, key_inquiry_questions, core_competencies,
               values, assessment_rubrics, pertinent_contemporary_issues,
               link_to_other_learning_areas, source_pages, updated_at
        FROM curriculum_substrands WHERE {scope}{subject_clause}
        ORDER BY subject, strand_id, sub_strand_id
        """,
        params,
    )
    counts["sub_strands"] = len(substrands)

    by_subject: dict[str, list[dict[str, Any]]] = {}
    for row in substrands:
        by_subject.setdefault(str(row.get("subject") or ""), []).append(dict(row))

    for subj, rows in by_subject.items():
        files[f"{slug(subj)}/curriculum/structure.json"] = _dump({
            "grade": grade, "subject": subj, "sub_strand_count": len(rows),
            "sub_strands": rows,
        })
        for row in rows:
            name = f"{slug(row.get('strand_name'))}__{slug(row.get('sub_strand_name'))}"
            files[f"{slug(subj)}/curriculum/sub-strands/{name}.json"] = _dump(row)

    # ── what each station produced ──────────────────────────────────────────
    resources = _rows(
        """
        SELECT bundle_id, curriculum, notes, diagrams, activities, questions,
               review_audit, status, updated_at
        FROM substrand_resources
        WHERE (LOWER(curriculum->>'grade') = LOWER(:grade)
               OR LOWER(curriculum->>'grade') = LOWER(:alt_grade))
          AND (:subject = '' OR LOWER(curriculum->>'subject') = LOWER(:subject))
        ORDER BY updated_at DESC
        """,
        params,
    )
    counts["bundles"] = len(resources)
    for row in resources:
        curriculum = row.get("curriculum") or {}
        subj = str(curriculum.get("subject") or "")
        name = f"{slug(curriculum.get('strand'))}__{slug(curriculum.get('sub_strand'))}"
        for station in ("notes", "diagrams", "activities", "questions"):
            payload = row.get(station)
            if not payload:
                continue
            files[f"{slug(subj)}/{station}/{name}.json"] = _dump(payload)

    # ── media briefs ────────────────────────────────────────────────────────
    media = _rows(
        f"""
        SELECT grade, subject, strand_name, sub_strand_name, kind, title,
               purpose, generation_prompt, negative_prompt, shot_list, spec,
               alt_text, narration
        FROM substrand_media WHERE {scope}{subject_clause}
        ORDER BY subject, strand_name, sub_strand_name, kind
        """,
        params,
    )
    counts["media_briefs"] = len(media)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in media:
        key = (f"{slug(row.get('subject'))}/media/"
               f"{slug(row.get('strand_name'))}__{slug(row.get('sub_strand_name'))}.json")
        grouped.setdefault(key, []).append(dict(row))
    for path, rows in grouped.items():
        files[path] = _dump(rows)

    # ── versions, reviews and approvals ─────────────────────────────────────
    artifacts = _rows(
        f"""
        SELECT artifact_id, artifact_key, kind, version, grade, subject,
               strand_name, sub_strand_name, title, status, provenance,
               created_at, updated_at
        FROM artifacts WHERE {scope}{subject_clause}
        ORDER BY artifact_key, version
        """,
        params,
    )
    counts["artifact_versions"] = len(artifacts)
    if artifacts:
        files["_versions/artifacts.json"] = _dump([dict(a) for a in artifacts])

    ids = [str(a.get("artifact_id")) for a in artifacts]
    if ids:
        reviews = _rows(
            "SELECT * FROM artifact_reviews WHERE artifact_id = ANY(:ids) "
            "ORDER BY artifact_id, layer",
            {"ids": ids},
        )
        counts["reviews"] = len(reviews)
        if reviews:
            files["_versions/reviews.json"] = _dump([dict(r) for r in reviews])

        labels = _rows(
            "SELECT * FROM artifact_labels WHERE artifact_id = ANY(:ids)",
            {"ids": ids},
        )
        counts["labels"] = len(labels)
        if labels:
            files["_versions/labels.json"] = _dump([dict(l) for l in labels])

    # ── the manifest, so an export explains itself ──────────────────────────
    files["manifest.json"] = _dump({
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "grade": grade,
        "subject": subject or "(all subjects in this grade)",
        "generator": VERSION,
        "counts": counts,
        "files": sorted(files),
        "note": (
            "Keys are sorted and the indent is fixed, so two exports of "
            "unchanged content are byte-identical and a diff shows only what "
            "actually changed. Filenames come from the curriculum, not from "
            "database ids, so the same sub-strand is the same path in every "
            "export."
        ),
    })

    files["README.md"] = (
        f"# {subject or grade} — generated content\n\n"
        f"Exported {datetime.now(timezone.utc).date().isoformat()} "
        f"by generator `{VERSION}`.\n\n"
        f"## Layout\n\n"
        f"- `manifest.json` — what is in here, and what produced it.\n"
        f"- `<subject>/curriculum/structure.json` — every strand and sub-strand.\n"
        f"- `<subject>/curriculum/sub-strands/<strand>__<sub-strand>.json` — one per sub-strand.\n"
        f"- `<subject>/notes/`, `diagrams/`, `activities/`, `questions/`, `media/` — what each station produced.\n"
        f"- `_versions/` — every version filed, its review verdicts and its labels.\n\n"
        f"## Reviewing it as a project\n\n"
        f"Put the folder under version control and export again after a run:\n\n"
        f"```bash\n"
        f"git init && git add -A && git commit -m 'baseline'\n"
        f"# ...regenerate, export again over the same folder...\n"
        f"git diff\n"
        f"```\n\n"
        f"Because keys are sorted and filenames are derived from the curriculum\n"
        f"rather than from database ids, the diff is the change — not the\n"
        f"serialisation order and not renamed files.\n\n"
        f"`rubric_source` on a sub-strand says whether its assessment rubric was\n"
        f"read from the KICD design or written from its outcomes. "
        f"`truncated_levels` names any rubric cell the source PDF cut off.\n"
    )
    return files


def to_zip(grade: str, subject: str = "") -> tuple[bytes, ExportReport]:
    """The whole export as a zip, ready to stream."""
    files = collect(grade, subject)
    report = ExportReport(grade=grade, subject=subject, files=sorted(files))
    try:
        report.counts = json.loads(files["manifest.json"])["counts"]
    except Exception:  # noqa: BLE001
        report.counts = {}

    root = f"cbc-{slug(grade)}" + (f"-{slug(subject)}" if subject else "")
    buffer = io.BytesIO()
    # Deflated and with a fixed date, so the same content produces the same
    # archive rather than one that differs by timestamp alone.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[path])

    logger.info("Exported %d file(s) for %s / %s.", len(files), grade, subject or "all")
    return buffer.getvalue(), report

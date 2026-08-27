"""Derive a grade's actual scope from its own design, small enough to inject.

The register can say what a PP1 learner may be asked because PP1's design was
read by hand: letter sounds only, nothing beyond 10, 30-minute lessons. Every
other grade says "read its own design", which is honest but not useful.

Doing the other fourteen by hand does not scale, and asking a model to
summarise a 296-page design in one call is the context-length failure this
system already hit. So the design is read in page-aligned chunks, each chunk
yields the bounded facts it can see, and those are reconciled into one summary.

The output is deliberately small. It goes into EVERY authoring prompt, so a
scope summary that runs to pages defeats its own purpose and re-creates the
problem it was built to solve. A fact that does not bound what may be asked —
"learners will enjoy the activities" — earns no space.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("cbc-grade-scope")

# What fits in every prompt without crowding out the design itself.
MAX_FACTS = 8
MAX_CHARS = 1_400
MAX_FACT_CHARS = 260

# A fact earns its place by bounding something: a count, a range, a limit, a
# ceiling. These are the words that mark one.
_BOUNDING = re.compile(
    r"\b(?:\d+|only|not|never|no\s|up to|beyond|maximum|minimum|limited|"
    r"lessons?|hours?|minutes?|per week|range|between|stops?|through)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ScopeFact:
    statement: str
    source_pages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"statement": self.statement, "source_pages": list(self.source_pages)}


@dataclass(slots=True)
class GradeScope:
    grade: str
    subject: str
    facts: list[ScopeFact] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def notes(self) -> list[str]:
        """The register-ready lines."""
        return [
            f"{f.statement} [{', '.join(f.source_pages)}]" if f.source_pages else f.statement
            for f in self.facts
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "subject": self.subject,
            "facts": [f.to_dict() for f in self.facts],
            "notes": self.notes,
            "fact_count": len(self.facts),
            "chars": sum(len(n) for n in self.notes),
            "trace": self.trace,
        }


def _normalise(statement: str) -> str:
    return " ".join(re.split(r"[^a-z0-9]+", statement.lower())).strip()


def _is_bounding(statement: str) -> bool:
    return bool(_BOUNDING.search(statement))


def compact(facts: list[dict[str, Any]]) -> list[ScopeFact]:
    """Cut the reconciled facts down to what fits in a prompt.

    Bounding facts first — a limit is what stops a generator overreaching, and
    "learners enjoy singing" stops nothing.
    """
    seen: set[str] = set()
    bounding: list[ScopeFact] = []
    rest: list[ScopeFact] = []

    for raw in facts:
        if not isinstance(raw, dict):
            continue
        statement = re.sub(r"\s+", " ", str(raw.get("statement") or "")).strip()
        if not statement:
            continue
        if len(statement) > MAX_FACT_CHARS:
            statement = statement[: MAX_FACT_CHARS - 1].rstrip() + "…"
        key = _normalise(statement)
        if not key or key in seen:
            continue
        seen.add(key)

        pages = raw.get("source_pages") or []
        fact = ScopeFact(
            statement=statement,
            source_pages=[str(p) for p in pages if str(p).strip()][:4],
        )
        (bounding if _is_bounding(statement) else rest).append(fact)

    kept: list[ScopeFact] = []
    budget = MAX_CHARS
    for fact in bounding + rest:
        if len(kept) >= MAX_FACTS:
            break
        cost = len(fact.statement) + 2
        if cost > budget:
            continue
        kept.append(fact)
        budget -= cost
    return kept


def derive_scope(
    grade: str,
    subject: str,
    document: str,
    generate_for_chunk: Callable[[Any], list[dict[str, Any]]],
    *,
    context_window_tokens: int = 128_000,
    overhead_tokens: int = 12_000,
) -> GradeScope:
    """Read the design in chunks and reconcile one small scope summary."""
    from .map_reduce import map_reduce_over_document

    if not document or not document.strip():
        return GradeScope(grade=grade, subject=subject, facts=[],
                          trace={"skipped": "no source document"})

    outcome = map_reduce_over_document(
        document,
        generate_for_chunk,
        context_window_tokens=context_window_tokens,
        overhead_tokens=overhead_tokens,
        identity_fields=("statement",),
    ).to_dict()

    facts = compact(outcome["items"])
    logger.info(
        "Scope for %s %s: %d fact(s) from %d chunk(s), %d chars.",
        grade, subject, len(facts),
        outcome["trace"]["chunks"].get("chunk_count", 0),
        sum(len(f.statement) for f in facts),
    )
    return GradeScope(grade=grade, subject=subject, facts=facts, trace=outcome["trace"])


# ── Storage ─────────────────────────────────────────────────────────────────
# Derived once per design, read on every generation, so it is stored rather
# than recomputed. A summary is only as current as the design it came from.

def save_scope(scope: GradeScope, design_id: str = "") -> None:
    from ..infra.db import execute, to_json

    execute(
        """
        INSERT INTO grade_scope (grade, subject, design_id, facts, updated_at)
        VALUES (:grade, :subject, :design_id, CAST(:facts AS jsonb), NOW())
        ON CONFLICT (grade, subject) DO UPDATE SET
            design_id = EXCLUDED.design_id,
            facts = EXCLUDED.facts,
            updated_at = NOW()
        """,
        {
            "grade": scope.grade,
            "subject": scope.subject,
            "design_id": design_id,
            "facts": to_json([f.to_dict() for f in scope.facts]),
        },
    )


def notes_for(grade: str, subject: str) -> list[str]:
    """The stored scope lines for a learning area, or [] when none is derived.

    Never raises: a missing scope must degrade to the register's own "read the
    design" note, not fail the generation that asked for it.
    """
    if not grade or not subject:
        return []
    try:
        from ..infra.db import fetch_one

        row = fetch_one(
            "SELECT facts FROM grade_scope WHERE grade = :grade AND LOWER(subject) = LOWER(:subject)",
            {"grade": grade, "subject": subject},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Scope lookup for %s %s unavailable: %s", grade, subject, exc)
        return []

    if not row:
        return []
    facts = row.get("facts") or []
    if isinstance(facts, str):
        try:
            facts = json.loads(facts)
        except ValueError:
            return []
    return GradeScope(grade=grade, subject=subject, facts=compact(facts)).notes

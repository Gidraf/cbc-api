"""Server-side artifact ID minting.

Generation models return positional labels — ``"Q1"``, ``"Q2"``, ``"vis_01"`` —
which are display ordering, not identity. Persisting them as primary keys makes
every batch collide with every other batch. IDs are always minted here, and the
model's label is preserved separately as a display label.
"""
from __future__ import annotations

import re
import secrets
import time

from .grade_order import normalize_grade

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str | None, max_len: int = 18, fallback: str = "x") -> str:
    if not value:
        return fallback
    slug = _SLUG_STRIP.sub("-", str(value).strip().lower()).strip("-")
    return (slug[:max_len].strip("-") or fallback)


def _suffix() -> str:
    """Time-ordered, collision-resistant suffix.

    Base-36 milliseconds keeps IDs roughly sortable by creation time; the random
    tail makes concurrent mints in the same millisecond safe.
    """
    ms = int(time.time() * 1000)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = ""
    while ms:
        ms, rem = divmod(ms, 36)
        encoded = digits[rem] + encoded
    return f"{encoded}{secrets.token_hex(3)}"


def subject_code(subject: str | None, explicit: str | None = None) -> str:
    """Short uppercase subject code, preferring the curriculum's own code."""
    if explicit and explicit.strip():
        return _SLUG_STRIP.sub("", explicit.strip().lower())[:6].upper() or "GEN"
    words = [w for w in re.split(r"[^A-Za-z]+", subject or "") if w]
    if not words:
        return "GEN"
    if len(words) == 1:
        return words[0][:4].upper()
    return "".join(w[0] for w in words[:4]).upper()


def mint_question_id(
    grade: str,
    subject: str,
    sub_strand: str,
    slo_id: str | None = None,
    subject_code_hint: str | None = None,
) -> str:
    """``q-grade-7-intsci-soil-profiles-slo-01-m8xk2a4f91``

    Globally unique. Never derived from anything the model returns.
    """
    parts = [
        "q",
        normalize_grade(grade) or "grade-unknown",
        subject_code(subject, subject_code_hint).lower(),
        slugify(sub_strand, 24, "substrand"),
        slugify(slo_id, 12, "slo"),
        _suffix(),
    ]
    return "-".join(p for p in parts if p)


def mint_universal_id(
    grade: str,
    subject: str,
    strand: str | None,
    sub_strand: str | None,
    slo_id: str | None,
    subject_code_hint: str | None = None,
) -> str:
    """The curriculum coordinate from master_agent_context.md §4.

    ``[LEVEL]-[GRADE]-[LEARNING_AREA]-[STRAND]-[SUBSTRAND]-[SLO_ID]``. Shared by
    every artifact sitting at the same point in the curriculum, so unlike the
    question ID this one is intentionally *not* unique.
    """
    parts = [
        (normalize_grade(grade) or "grade-unknown").upper(),
        subject_code(subject, subject_code_hint),
        slugify(strand, 16, "strand").upper(),
        slugify(sub_strand, 20, "substrand").upper(),
        slugify(slo_id, 12, "slo").upper(),
    ]
    return "-".join(parts)


def mint_diagram_id(subject: str | None = None, sub_strand: str | None = None) -> str:
    return f"diag-{slugify(subject, 10, 'gen')}-{slugify(sub_strand, 16, 'ss')}-{_suffix()}"


def mint_exam_id(grade: str, subject: str) -> str:
    return f"exam-{normalize_grade(grade) or 'grade-unknown'}-{subject_code(subject).lower()}-{_suffix()}"


def next_version_id(question_id: str) -> tuple[str, int]:
    """Derive the next immutable version of a question ID.

    ``q-grade-7-…-m8xk2a4f91`` → ``q-grade-7-…-m8xk2a4f91@v2``. Approved questions
    are frozen, so an edit mints a new version rather than mutating the row a
    printed paper already cited.
    """
    base, _, current = question_id.partition("@v")
    version = (int(current) if current.isdigit() else 1) + 1
    return f"{base}@v{version}", version

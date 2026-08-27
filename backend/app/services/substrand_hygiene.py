"""Refuse content that is raw source text wearing a sub-strand's clothes.

A chunk of a design that the model fails to parse comes back as the chunk
itself: page markers, line addresses and column debris packed into whatever
field the schema offered. One such entry saved as a sixth CRE strand called
"4.0 CHRISTIAN VALUES", holding a single sub-strand whose `values` list was two
hundred lines of pages 214–221. Its real content — 4.1, 4.2, 4.3 — had already
been extracted correctly by a different chunk, so nothing was lost and a
duplicate was gained.

Reconciliation did not catch it because it dedupes on the strand name, and
"4.0 CHRISTIAN VALUES" is not the string "Christian Values". Both problems are
general: any design, any grade, any subject. So both are fixed here rather than
in the one endpoint where they were noticed.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cbc-substrand-hygiene")

# "215:27  " — the line address the chunk renderer prefixes to every line it
# shows the model. Its presence in an answer means the answer is the question.
_LINE_ADDRESS = re.compile(r"\b\d{1,4}:\d{1,5}\s\s")

# "[PAGE 215]" and the page footers KICD prints — same story.
_PAGE_DEBRIS = re.compile(r"\[PAGE\s+\d{1,4}\]|\bPage\s+\d{1,4}\s+of\s+\d{1,4}\b", re.I)

# Column headers from the design's own table. A field that quotes the table's
# scaffolding is reproducing the layout, not reading it.
_TABLE_SCAFFOLD = (
    "strand sub-strand specific learning",
    "suggested learning experiences suggested",
    "by the end of the sub-strand, the learner",
    "core competencies to be developed",
    "link to pertinent and contemporary issues",
    "suggested assessment rubric",
)

# Leading design numbering: "4.0 ", "4.1 ", "STRAND 5.0:", "1.0. "
_NUMBERING = re.compile(r"^\s*(?:strand\s*)?\d{1,2}(?:\.\d{1,2})*[.:)]?\s*", re.I)

# How much of a field may be debris before the whole entry is refused.
_MAX_DEBRIS_VALUES = 0


def strand_key(name: str) -> str:
    """A strand's identity, independent of how the design numbered it.

    "4.0 CHRISTIAN VALUES", "4.0 Christian Values" and "Christian Values" are
    one strand. Treating them as three is what let a duplicate save.
    """
    stripped = _NUMBERING.sub("", str(name or ""))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def strip_numbering(name: str) -> str:
    """The display form: the design's own words, without its numbering."""
    stripped = _NUMBERING.sub("", str(name or "")).strip()
    return stripped or str(name or "").strip()


def _walk(value: Any) -> list[str]:
    """Every string anywhere in a nested payload."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _walk(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _walk(v)]
    return []


def debris_reason(value: Any) -> str:
    """Why this value is raw source rather than extracted content, or ""."""
    for text in _walk(value):
        if _LINE_ADDRESS.search(text):
            return "carries page:line addresses from the source document"
        if _PAGE_DEBRIS.search(text):
            return "carries page markers from the source document"
        lowered = text.lower()
        for scaffold in _TABLE_SCAFFOLD:
            if scaffold in lowered:
                return f"quotes the design's table headings ({scaffold!r})"
    return ""


def inspect(strand_name: str, substrand: dict[str, Any]) -> str:
    """Why this sub-strand must not be saved, or "" when it is sound."""
    name = str(substrand.get("sub_strand_name") or substrand.get("name") or "").strip()
    if not name:
        return "has no sub-strand name"

    if strand_key(name) == strand_key(strand_name):
        # A parse that failed at the table level names the block it could not
        # read — the strand — instead of the sub-strand inside it.
        return "repeats the strand name instead of naming a sub-strand"

    debris_fields: list[str] = []
    for field, value in substrand.items():
        reason = debris_reason(value)
        if reason:
            debris_fields.append(f"{field} {reason}")
    if len(debris_fields) > _MAX_DEBRIS_VALUES:
        return "; ".join(debris_fields[:3])

    return ""


def clean(
    strand_name: str, substrands: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a generated batch into what may be saved and what may not.

    Returns ``(kept, rejected)``; each rejection carries its reason so the
    console can say what was dropped instead of silently saving less.
    """
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in substrands:
        if not isinstance(entry, dict):
            rejected.append({"sub_strand_name": str(entry)[:80],
                             "reason": "is not a sub-strand object"})
            continue

        reason = inspect(strand_name, entry)
        if reason:
            rejected.append({
                "sub_strand_name": str(
                    entry.get("sub_strand_name") or entry.get("name") or "?"
                )[:80],
                "reason": reason,
            })
            continue

        name = str(entry.get("sub_strand_name") or entry.get("name") or "")
        key = strand_key(name)
        if key in seen:
            rejected.append({"sub_strand_name": name,
                             "reason": "duplicates another sub-strand in this batch"})
            continue
        seen.add(key)
        kept.append(entry)

    if rejected:
        logger.warning(
            "Refused %d of %d sub-strand(s) under '%s': %s",
            len(rejected), len(substrands), strand_name,
            "; ".join(f"{r['sub_strand_name']} — {r['reason']}" for r in rejected[:3]),
        )
    return kept, rejected


def clean_strands(
    strands: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The same for a generated strand list, collapsing numbering variants."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}

    for entry in strands:
        if not isinstance(entry, dict):
            rejected.append({"strand_name": str(entry)[:80],
                             "reason": "is not a strand object"})
            continue

        name = str(entry.get("strand_name") or entry.get("name") or "").strip()
        if not name:
            rejected.append({"strand_name": "", "reason": "has no strand name"})
            continue

        reason = debris_reason(entry)
        if reason:
            rejected.append({"strand_name": name[:80], "reason": reason})
            continue

        key = strand_key(name)
        if not key:
            rejected.append({"strand_name": name[:80], "reason": "has no strand name"})
            continue

        existing = by_key.get(key)
        if existing is None:
            by_key[key] = entry
            kept.append(entry)
            continue

        # Same strand, two spellings. Keep the fuller record rather than the
        # first one seen, and keep the name that is not shouted numbering.
        if len(str(entry.get("description") or "")) > len(str(existing.get("description") or "")):
            existing["description"] = entry.get("description")
        if not existing.get("strand_id") and entry.get("strand_id"):
            existing["strand_id"] = entry.get("strand_id")
        rejected.append({"strand_name": name[:80],
                         "reason": f"duplicates '{existing.get('strand_name')}' "
                                   "under different numbering"})

    if rejected:
        logger.warning(
            "Refused %d of %d strand(s): %s", len(rejected), len(strands),
            "; ".join(f"{r['strand_name']} — {r['reason']}" for r in rejected[:3]),
        )
    return kept, rejected

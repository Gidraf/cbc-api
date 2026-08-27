"""Generate across a document too large for one call, then reconcile.

Reading a design in pieces is only half the problem. Each piece yields its own
partial answer — strands found on pages 1-18, more on pages 19-36 — and those
have to be merged into one result without duplicating what appears twice or
losing what appears once.

Every step is recorded: which pages a call saw, how long it took, what it
returned, and what reconciliation did with it. When an output looks wrong, the
trace says which chunk produced it and which pages that chunk held, so the
question becomes "what does page 24 actually say" rather than "why did the model
do that".
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .document_chunking import Chunk, chunk_document, describe

logger = logging.getLogger("cbc-map-reduce")


@dataclass(slots=True)
class Step:
    index: int
    pages: str
    chars: int
    status: str
    duration_ms: int
    produced: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk": self.index, "pages": self.pages, "chars": self.chars,
            "status": self.status, "duration_ms": self.duration_ms,
            "produced": self.produced, "error": self.error,
        }


@dataclass(slots=True)
class MapReduceResult:
    items: list[dict[str, Any]]
    steps: list[Step] = field(default_factory=list)
    chunk_summary: dict[str, Any] = field(default_factory=dict)
    reconciliation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        succeeded = sum(1 for s in self.steps if s.status == "ok")
        return {
            "items": self.items,
            "trace": {
                "chunks": self.chunk_summary,
                "steps": [s.to_dict() for s in self.steps],
                "chunks_succeeded": succeeded,
                "chunks_failed": len(self.steps) - succeeded,
                "total_duration_ms": sum(s.duration_ms for s in self.steps),
                "reconciliation": self.reconciliation,
            },
        }


def _key(item: dict[str, Any], fields: tuple[str, ...]) -> str:
    for f in fields:
        value = str(item.get(f) or "").strip().lower()
        if value:
            # Labels drift between chunks — "2.0 Pre-Reading" in one, "Pre
            # Reading" in another — so compare on the words alone, dropping
            # numbering and punctuation.
            words = re.split(r"[^a-z0-9]+", value)
            return " ".join(w for w in words if w and not w.isdigit())
    return ""


def reconcile(
    partials: list[tuple[Chunk, list[dict[str, Any]]]],
    identity_fields: tuple[str, ...] = ("strand_name", "sub_strand_name", "name", "title"),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge per-chunk results into one list, keeping where each came from.

    An item seen in several chunks is kept once, with the fullest version of
    each field and the union of its source pages — a strand that spans pages
    12-40 should say so, not report only where it was first noticed.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    duplicates = 0
    unkeyed = 0

    for chunk, items in partials:
        for item in items:
            if not isinstance(item, dict):
                continue
            key = _key(item, identity_fields)
            if not key:
                unkeyed += 1
                key = f"__unkeyed_{len(order)}_{unkeyed}"

            pages = [chunk.page_range]
            if key in merged:
                duplicates += 1
                existing = merged[key]
                for field_name, value in item.items():
                    # Prefer the fuller answer; a later chunk often has more.
                    current = existing.get(field_name)
                    if isinstance(value, str) and isinstance(current, str):
                        if len(value.strip()) > len(current.strip()):
                            existing[field_name] = value
                    elif isinstance(value, list) and isinstance(current, list):
                        for v in value:
                            if v not in current:
                                current.append(v)
                    elif current in (None, "", [], {}):
                        existing[field_name] = value
                existing["source_pages"] = sorted(set(existing.get("source_pages", []) + pages))
            else:
                merged[key] = {**item, "source_pages": pages}
                order.append(key)

    return (
        [merged[k] for k in order],
        {
            "merged_from": len(partials),
            "items_before": sum(len(items) for _c, items in partials),
            "items_after": len(order),
            "duplicates_merged": duplicates,
            "items_without_identity": unkeyed,
        },
    )


def map_reduce_over_document(
    text: str,
    generate_for_chunk: Callable[[Chunk], list[dict[str, Any]]],
    *,
    context_window_tokens: int = 128_000,
    overhead_tokens: int = 12_000,
    identity_fields: tuple[str, ...] = ("strand_name", "sub_strand_name", "name", "title"),
    stop_on_error: bool = False,
) -> MapReduceResult:
    """Run a generator over every chunk of a document and reconcile the results.

    A chunk that fails does not abandon the run by default: one bad page should
    not cost the other thirty, and the trace records exactly which one failed.
    """
    chunks = chunk_document(text, context_window_tokens, overhead_tokens)
    steps: list[Step] = []
    partials: list[tuple[Chunk, list[dict[str, Any]]]] = []

    for chunk in chunks:
        started = time.monotonic()
        try:
            produced = generate_for_chunk(chunk) or []
            elapsed = int((time.monotonic() - started) * 1000)
            partials.append((chunk, produced))
            steps.append(Step(chunk.index, chunk.page_range, len(chunk.text), "ok", elapsed, len(produced)))
            logger.info(
                "Chunk %d (pages %s): %d item(s) in %dms.",
                chunk.index, chunk.page_range, len(produced), elapsed,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.monotonic() - started) * 1000)
            steps.append(Step(chunk.index, chunk.page_range, len(chunk.text), "failed", elapsed, 0, str(exc)[:300]))
            logger.warning("Chunk %d (pages %s) failed: %s", chunk.index, chunk.page_range, exc)
            if stop_on_error:
                break

    items, summary = reconcile(partials, identity_fields)
    return MapReduceResult(
        items=items,
        steps=steps,
        chunk_summary=describe(chunks),
        reconciliation=summary,
    )

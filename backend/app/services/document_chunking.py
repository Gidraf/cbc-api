"""Split a curriculum design into pieces a model can actually read.

A full design runs to 140,000 characters. Sent whole with the BECF master
context and a teaching skill on top, it exceeded a 128k-token window and the
request was rejected outright — so nothing was generated at all.

Chunks are cut on page boundaries, never inside one. That costs a little
packing efficiency and buys the thing that matters: every chunk still knows
which pages it holds, so anything generated from it can cite them, and a
reviewer can open those pages and check.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .document_index import Page, parse_pages

logger = logging.getLogger("cbc-document-chunking")

# Roughly four characters per token for English prose. Deliberately pessimistic:
# under-filling a chunk costs an extra call, over-filling costs the whole run.
CHARS_PER_TOKEN = 4

# What the model must have room for besides the document: the master context,
# the teaching skill, the instructions and the answer it has to write.
DEFAULT_OVERHEAD_TOKENS = 12_000


@dataclass(slots=True)
class Chunk:
    index: int
    pages: list[Page]
    text: str

    @property
    def first_page(self) -> int:
        return self.pages[0].number if self.pages else 0

    @property
    def last_page(self) -> int:
        return self.pages[-1].number if self.pages else 0

    @property
    def page_range(self) -> str:
        if not self.pages:
            return "—"
        return f"{self.first_page}" if self.first_page == self.last_page else f"{self.first_page}-{self.last_page}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "pages": self.page_range,
            "page_numbers": [p.number for p in self.pages],
            "chars": len(self.text),
            "estimated_tokens": len(self.text) // CHARS_PER_TOKEN,
        }


def budget_chars(context_window_tokens: int, overhead_tokens: int = DEFAULT_OVERHEAD_TOKENS) -> int:
    """How much document fits in one call."""
    usable = max(1_000, context_window_tokens - overhead_tokens)
    return usable * CHARS_PER_TOKEN


def _page_text(page: Page) -> str:
    header = f"[PAGE {page.number}]"
    body = "\n".join(f"{page.number}:{line.line}  {line.text}" for line in page.lines)
    return f"{header}\n{body}"


def chunk_document(
    text: str,
    context_window_tokens: int = 128_000,
    overhead_tokens: int = DEFAULT_OVERHEAD_TOKENS,
) -> list[Chunk]:
    """Page-aligned chunks that fit the window, each carrying its line addresses.

    Every line is prefixed with its ``page:line`` address so the model can cite
    what it read. A single page larger than the whole budget is emitted alone
    rather than split, because splitting it would break its citations — the
    caller sees an oversized chunk instead of a silently truncated one.
    """
    pages = parse_pages(text)
    if not pages:
        return []

    limit = budget_chars(context_window_tokens, overhead_tokens)
    chunks: list[Chunk] = []
    current: list[Page] = []
    current_len = 0

    for page in pages:
        rendered = _page_text(page)
        if current and current_len + len(rendered) > limit:
            chunks.append(Chunk(index=len(chunks), pages=current, text="\n\n".join(_page_text(p) for p in current)))
            current, current_len = [], 0
        current.append(page)
        current_len += len(rendered) + 2

    if current:
        chunks.append(Chunk(index=len(chunks), pages=current, text="\n\n".join(_page_text(p) for p in current)))

    oversized = [c for c in chunks if len(c.text) > limit]
    if oversized:
        logger.warning(
            "%d chunk(s) exceed the %d-character budget because a single page is larger than it. "
            "They are kept whole so citations stay valid.",
            len(oversized), limit,
        )
    return chunks


def describe(chunks: list[Chunk]) -> dict[str, Any]:
    return {
        "chunk_count": len(chunks),
        "total_chars": sum(len(c.text) for c in chunks),
        "chunks": [c.to_dict() for c in chunks],
    }

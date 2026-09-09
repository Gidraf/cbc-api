"""The pages of a design a sub-strand actually needs, and nothing else.

The notes prompt carried the whole 69-page Grade 9 Mathematics design — the
foreword, the preface, the acknowledgements, the ISBN, the table of contents,
and every other strand: Matrices, Trigonometry, Bearings, Probability, the
Community Service Learning appendix.

For a sub-strand that occupies four pages. Which the system already knew:

    "source_pages": [12, 13, 14, 20]

Ninety thousand characters of the 124,000-character prompt were pages the model
must not write about, sent to a model whose reasoning degrades under exactly
that load. It also explains content nobody asked for — a lesson on IT tools
appears when the ICT appendix is sitting in the context window.

WHAT IS KEPT BESIDES THE SUB-STRAND'S OWN PAGES. A guide needs the subject's
essence statement, the learning outcomes for the level, and the lesson
allocation, because the prompt quotes all three and a citation has to resolve
against something. Those are found by their headings rather than by page
number, because page numbers differ per document.

WHEN THE PAGES ARE NOT KNOWN the whole document is sent, unchanged. A design
nobody has indexed is not improved by guessing which quarter of it matters.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-design-scope")

# Front matter a guide genuinely quotes, found by heading rather than by page.
_ALWAYS = (
    "ESSENCE STATEMENT",
    "SUBJECT GENERAL LEARNING OUTCOMES",
    "LEARNING OUTCOMES FOR",
    "LESSON ALLOCATION",
)

# Pages that are the document's own furniture and are never taught from.
_NEVER = (
    "FOREWORD", "PREFACE", "ACKNOWLEDGEMENT", "TABLE OF CONTENTS",
    "All rights reserved", "ISBN",
)


@dataclass
class Trim:
    text: str = ""
    kept: list[int] = field(default_factory=list)
    dropped: int = 0
    total: int = 0
    reason: str = ""

    @property
    def trimmed(self) -> bool:
        return bool(self.dropped)

    def to_dict(self) -> dict[str, Any]:
        return {"kept": self.kept, "dropped": self.dropped, "total": self.total,
                "trimmed": self.trimmed, "reason": self.reason,
                "chars": len(self.text)}


def _page_text(page: Any) -> str:
    """A page's own words. `Page` carries `lines`, not `text`."""
    direct = getattr(page, "text", None)
    if isinstance(direct, str) and direct:
        return direct
    return "\n".join(str(getattr(line, "text", line) or "")
                     for line in (getattr(page, "lines", None) or []))


def _wanted(page: Any, pages_named: set[int]) -> bool:
    number = int(getattr(page, "number", 0) or 0)
    if number in pages_named:
        return True
    body = _page_text(page)
    head = body[:600].upper()
    if any(marker in head for marker in _NEVER):
        return False
    return any(marker in body.upper() for marker in _ALWAYS)


def for_sub_strand(text: str, source_pages: list[Any] | None,
                   sub_strand: str = "") -> Trim:
    """The design, cut down to what this sub-strand is written from."""
    from . import document_index

    named = {int(p) for p in (source_pages or [])
             if isinstance(p, (int, float)) or str(p).isdigit()}
    if not named:
        return Trim(text=text, total=0,
                    reason="the design's pages for this sub-strand are not "
                           "recorded, so all of it was sent")

    try:
        pages = document_index.parse_pages(text or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not page the design (%s); sending all of it", exc)
        return Trim(text=text, reason=f"could not be paged: {exc}")

    if not pages:
        return Trim(text=text, reason="no page markers were found")

    keep = [p for p in pages if _wanted(p, named)]
    if not keep:
        # Never send nothing. A trim that empties the design is worse than one
        # that does not happen.
        return Trim(text=text, total=len(pages),
                    reason="no page matched, so all of it was sent")

    kept_numbers = [int(getattr(p, "number", 0) or 0) for p in keep]
    body = "\n\n".join(_page_text(p) for p in keep)
    dropped = len(pages) - len(keep)
    note = (
        f"\n\n[This is the part of the design that covers "
        f"{sub_strand or 'this sub-strand'}: pages "
        f"{', '.join(str(n) for n in kept_numbers)} of {len(pages)}. "
        f"The other {dropped} page(s) cover other sub-strands and are not "
        f"shown, so nothing here belongs to them.]"
    )
    return Trim(text=body + note, kept=kept_numbers, dropped=dropped,
                total=len(pages),
                reason=f"kept {len(keep)} of {len(pages)} pages")

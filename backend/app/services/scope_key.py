"""One way of naming a (subject, sub-strand) scope, used on both sides of a join.

Coverage joins what the curriculum REQUIRES to what has been GENERATED, and
the two come from different places: the requirement from the design tree, the
generation from the artifacts table. Both were keyed by hand, and not
identically — one side stripped whitespace, the other did not.

A key that does not match produces no error. It produces a sub-strand whose
every station has run and which reports 0%, next to a board that locks the next
stage because "none exist yet". Grade 9 read 0% with strands, sub-strands,
lesson plans, notes and diagrams all filed.

So the key is built in one place, and a miss is reported rather than silently
scoring zero.
"""
from __future__ import annotations

import re
import unicodedata

# Curriculum names arrive from PDFs and from operators typing them. The same
# sub-strand appears as "Whole Numbers", "whole  numbers", "Whole Numbers ",
# and with a non-breaking space or a curly apostrophe in it.
_PUNCT = re.compile(r"[‘’“”`']")
_NOT_WORD = re.compile(r"[^a-z0-9]+")


def norm(value: object) -> str:
    """One name, reduced to what two spellings of it have in common."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = _PUNCT.sub("", text).lower()
    return _NOT_WORD.sub(" ", text).strip()


def key(subject: object, sub_strand: object) -> tuple[str, str]:
    """The scope key. Both sides of every coverage join build it with this."""
    return (norm(subject), norm(sub_strand))


def report_misses(required: set[tuple[str, str]],
                  generated: set[tuple[str, str]]) -> list[str]:
    """Generated work that matched no requirement, said out loud.

    This is the diagnosis that was missing. Work filed under a name the design
    tree does not use is invisible: it scores nothing, it unlocks nothing, and
    nothing anywhere says so. An operator sees 0% and assumes the run failed.
    """
    orphans = sorted(generated - required)
    if not orphans:
        return []
    lines = [
        f"{len(orphans)} generated sub-strand(s) matched no sub-strand in the "
        f"curriculum design, so none of that work is counted anywhere:"
    ]
    for subject, sub_strand in orphans[:8]:
        lines.append(f"  · {subject or '(no subject)'} — {sub_strand or '(no name)'}")
    if len(orphans) > 8:
        lines.append(f"  · and {len(orphans) - 8} more")
    lines.append(
        "Either the design was imported under different names, or the work was "
        "generated against a sub-strand that is not in it.")
    return lines

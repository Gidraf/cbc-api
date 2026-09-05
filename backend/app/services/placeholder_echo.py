"""Fields that came back holding the schema's own description of them.

Twice now a prompt has asked for a value and been handed its own instruction:

    "form": "one of: explanation, story, song, prayer, rhyme, dialogue, ..."
    "citation": {"ref": "202:14",
                 "quote": "The design's exact words at that address, verbatim."}

Both printed on the page in front of a class. The second is worse than a
cosmetic fault: every citation in the guide claimed page 202 line 14 of the
KICD design, which is a fabricated reference that survives inspection because
it LOOKS like a citation.

Rewriting the schema so the placeholder reads less like a value helps and does
not fix it — a model that copies one description will copy the next. So the
values are checked coming back. Nothing here needs the design text, so it runs
in the renderer as well as at the station, and a guide filed before this
existed still refuses to print a fabricated address.
"""
from __future__ import annotations

import re
from typing import Any

# Phrases that only ever appear in a schema's description of a field. Matched
# case-insensitively against the whole value, not as substrings of prose: a
# lesson may legitimately contain the word "verbatim".
_DESCRIPTIONS: tuple[str, ...] = (
    "the design's exact words at that address",
    "the exact words at that address",
    "empty where these words are your own",
    "verbatim from the source above",
    "what this piece of material is called",
    "the words the teacher speaks, verbatim",
    "what the learners do while this happens",
    "where these words come from",
    "one of:",
    "<the",
    "e.g.",
)

# The example address written into the schema. A citation carrying it is
# quoting the prompt, not the curriculum.
_EXAMPLE_REFS: frozenset[str] = frozenset({"202:14", "0:0", "1:1"})

_NORMALISE = re.compile(r"[^a-z0-9 ]+")


def _flat(value: Any) -> str:
    return _NORMALISE.sub(" ", str(value or "").lower()).strip()


def is_echo(value: Any) -> bool:
    """Whether this value is the schema's description of the field it fills."""
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    for phrase in _DESCRIPTIONS:
        if lowered.startswith(phrase) or phrase in lowered:
            return True
    return False


def is_example_ref(ref: Any) -> bool:
    """Whether this address is the one the prompt used as its example."""
    return str(ref or "").strip() in _EXAMPLE_REFS


def clean_citation(citation: Any) -> dict[str, str]:
    """A citation with anything copied from the prompt removed.

    Returns empty strings rather than dropping the keys, so a caller can tell
    "no citation was given" from "the citation was not usable".
    """
    if not isinstance(citation, dict):
        return {"ref": "", "quote": ""}

    ref = str(citation.get("ref") or "").strip()
    quote = str(citation.get("quote") or "").strip()

    if is_example_ref(ref):
        ref = ""
    if is_echo(quote):
        quote = ""
    # An address with nothing quoted at it cannot be checked by a reader, which
    # is the only thing a citation is for.
    if ref and not quote:
        return {"ref": "", "quote": ""}
    return {"ref": ref, "quote": quote}


def echoed_fields(piece: Any) -> list[str]:
    """Which fields of one piece came back holding their own description."""
    if not isinstance(piece, dict):
        return []

    found: list[str] = []
    for key in ("form", "title", "say", "learner_does", "attribution",
                "teacher_note", "notes_for_the_teacher"):
        if is_echo(piece.get(key)):
            found.append(key)

    citation = piece.get("citation")
    if isinstance(citation, dict):
        if is_example_ref(citation.get("ref")):
            found.append("citation.ref")
        if is_echo(citation.get("quote")):
            found.append("citation.quote")
    return found


def scan(material: Any) -> list[dict[str, Any]]:
    """Every piece that handed a description back, for the station's report."""
    pieces = material.get("material") if isinstance(material, dict) else None
    if not isinstance(pieces, list):
        return []

    out: list[dict[str, Any]] = []
    for piece in pieces:
        fields = echoed_fields(piece)
        if fields:
            out.append({
                "lesson": (piece or {}).get("module_number"),
                "topic": (piece or {}).get("topic") or (piece or {}).get("title"),
                "fields": fields,
            })
    return out

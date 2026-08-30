"""Resolve an artifact's citations before a reviewer is asked to judge them.

A layer-2 reviewer scored factual_correctness 70 and raised a HIGH issue —
"fabricated citations such as '203:26' and '203:33'" — on a guide whose
citations all resolve. Our own citation check had already verified six of six
at 100%.

The reviewer was not wrong to be suspicious. It was given a SUMMARY of the
design — the learning experiences, the competencies, the values — and never the
page-addressed document. Then it was told to flag "a page:line address that is
not in the excerpt", when there was no excerpt. It followed an instruction it
had no means to satisfy, and guessed.

A false accusation of fabrication is worse than a missed one: it drives a
regeneration that strips correct citations out of good content.

So the addresses are resolved mechanically first, and the reviewer is shown
what the design actually says at each one. It is not asked to check what it
cannot see.
"""
from __future__ import annotations

import logging
from typing import Any

from . import document_index

logger = logging.getLogger("cbc-citation-evidence")

# Enough of the page for a reviewer to judge the claim; not so much that the
# evidence block crowds out the artifact.
LINES_AROUND = 1
MAX_CITATIONS = 40


def _citations_in(content: Any, found: list[dict[str, Any]] | None = None
                  ) -> list[dict[str, Any]]:
    """Every citation anywhere in the artifact, in the order they appear."""
    out = found if found is not None else []
    if isinstance(content, dict):
        entries = content.get("citations")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and entry.get("ref"):
                    out.append(entry)
        for key, value in content.items():
            if key != "citations":
                _citations_in(value, out)
    elif isinstance(content, list):
        for item in content:
            _citations_in(item, out)
    return out


def resolve(content: Any, design_text: str) -> dict[str, Any]:
    """Each cited address, and what the design actually says there."""
    citations = _citations_in(content)
    # The same address cited from several modules is one address to check.
    seen: dict[str, dict[str, Any]] = {}
    for entry in citations:
        ref = str(entry.get("ref") or "").strip()
        if ref and ref not in seen:
            seen[ref] = entry

    if not design_text.strip():
        return {
            "checked": False,
            # How many there were to check, so a caller can stay silent about
            # an artifact that cites nothing rather than warning about it.
            "found": len(seen),
            "reason": "No design document was available to resolve against.",
            "citations": [],
        }

    pages = document_index.parse_pages(design_text)
    by_number = {p.number: p for p in pages}

    resolved: list[dict[str, Any]] = []
    for ref, entry in list(seen.items())[:MAX_CITATIONS]:
        parsed = document_index.parse_reference(ref)
        if not parsed:
            resolved.append({
                "ref": ref, "status": "MALFORMED",
                "claim": str(entry.get("claim") or "")[:160],
                "design_says": [],
            })
            continue

        _, page_number, line_number, _ = parsed
        page = by_number.get(page_number)
        if page is None:
            resolved.append({
                "ref": ref, "status": "PAGE NOT IN THE DESIGN",
                "claim": str(entry.get("claim") or "")[:160],
                "design_says": [],
            })
            continue

        lines = [l for l in page.lines
                 if abs(l.line - line_number) <= LINES_AROUND]
        if not lines:
            resolved.append({
                "ref": ref, "status": "LINE NOT ON THAT PAGE",
                "claim": str(entry.get("claim") or "")[:160],
                "design_says": [],
            })
            continue

        resolved.append({
            "ref": ref,
            "status": "VERIFIED",
            "claim": str(entry.get("claim") or "")[:160],
            "design_says": [f"{page_number}:{l.line}  {l.text}" for l in lines],
        })

    verified = sum(1 for r in resolved if r["status"] == "VERIFIED")
    return {
        "checked": True,
        "total": len(resolved),
        "verified": verified,
        "citations": resolved,
    }


def render(evidence: dict[str, Any]) -> str:
    """The block a reviewer reads instead of guessing."""
    if not evidence.get("checked"):
        return (
            "=== CITATIONS: NOT RESOLVED ===\n"
            f"{evidence.get('reason', 'No design document was available.')}\n"
            "You therefore CANNOT judge whether an address is real. Do not "
            "guess, and do not report a citation as fabricated — say under "
            "factual_correctness that citations could not be checked in this "
            "run.\n"
        )

    lines = [
        "=== CITATIONS IN THIS ARTIFACT, ALREADY RESOLVED ===",
        f"Every address below was looked up in the KICD design mechanically "
        f"before you saw it: {evidence['verified']} of {evidence['total']} "
        f"resolve to real lines.",
        "",
    ]
    for row in evidence.get("citations", []):
        lines.append(f"  {row['ref']}  [{row['status']}]")
        if row.get("claim"):
            lines.append(f"      cited for: {row['claim']}")
        for said in row.get("design_says", []):
            lines.append(f"      the design reads: {said}")
        lines.append("")

    lines += [
        "A citation marked VERIFIED is real. Do NOT report it as fabricated — "
        "it has been checked against the document, which you have not been "
        "shown in full.",
        "What IS worth your judgement: whether the quoted line actually "
        "supports the claim made from it. An address can resolve and still be "
        "cited for something it does not say.",
        "Report only the addresses marked MALFORMED, PAGE NOT IN THE DESIGN or "
        "LINE NOT ON THAT PAGE as fabricated.",
    ]
    return "\n".join(lines)

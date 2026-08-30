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

import difflib
import logging
from typing import Any

from . import document_index

logger = logging.getLogger("cbc-citation-evidence")

# Enough of the page for a reviewer to judge the claim; not so much that the
# evidence block crowds out the artifact.
LINES_AROUND = 1
MAX_CITATIONS = 40

# A quote is matched against a WIDER window than is displayed. KICD pages wrap
# mid-sentence — "b) practice saying" / "short prayers," is one outcome across
# two lines — so a quote that is honestly taken can still straddle the ±1 lines
# a reviewer is shown.
QUOTE_WINDOW = 3

# How much of the quote has to appear contiguously in the design at that
# address. Set low on purpose: the cost of a false "does not match" is the same
# false-accusation loop that this module exists to end, and a quote that shares
# half its length with the line is a quote, not an invention.
QUOTE_MATCH = 0.55

# Below this a quote is too short to judge — "God", "prayer" — and matching it
# proves nothing either way.
MIN_QUOTE_CHARS = 25


def _quote_support(quote: str, window: str) -> float:
    """How much of the quote actually appears at the cited address, 0 to 1."""
    a, b = _norm(quote), _norm(window)
    if not a or not b:
        return 0.0
    block = difflib.SequenceMatcher(None, a, b).find_longest_match(
        0, len(a), 0, len(b)
    )
    return block.size / len(a)


def _norm(text: str) -> str:
    import re as _re
    return _re.sub(r"[^a-z0-9 ]+", " ",
                   _re.sub(r"\s+", " ", text).strip().lower()).strip()


# How far either side of a line to sweep when looking for a quote that is not
# where it was cited. Wide enough to cover a re-extraction shifting a page, and
# narrow enough that the answer still means something.
SEARCH_SPAN = 25


def _sweep(quote: str, lines: list, centre: int | None = None) -> int:
    """The line where a run of `quote` actually starts, or 0."""
    for line in lines:
        if centre is not None and abs(line.line - centre) > SEARCH_SPAN:
            continue
        window = " ".join(
            l.text for l in lines if abs(l.line - line.line) <= QUOTE_WINDOW
        )
        if _quote_support(quote, window) >= QUOTE_MATCH:
            return line.line
    return 0


def _find(quote: str, page: Any, by_number: dict) -> str:
    """Where this quote really is: same page first, then the whole document."""
    if len(quote) < MIN_QUOTE_CHARS:
        return ""
    if page is not None:
        here = _sweep(quote, page.lines)
        if here:
            return f"{page.number}:{here}"
    for number in sorted(by_number):
        if page is not None and number == page.number:
            continue
        there = _sweep(quote, by_number[number].lines)
        if there:
            return f"{number}:{there}"
    return ""


def _unresolved(status: str, ref: str, entry: dict, page: Any,
                by_number: dict) -> dict[str, Any]:
    """A row for an address that did not resolve — and where its quote really is.

    Searched even here. An address that misses the page entirely can still
    carry a quotation lifted straight from the design, and calling that
    fabricated is the same false accusation as calling a two-line drift one.
    """
    quote = str(entry.get("quote") or "").strip()
    row = {"ref": ref, "status": status,
           "claim": str(entry.get("claim") or "")[:160], "design_says": []}
    found = _find(quote, page, by_number)
    if found:
        row["quote"] = quote[:200]
        row["found_at"] = found
        row["status"] = f"QUOTE IS REAL, AT {found}"
    elif quote:
        row["quote"] = quote[:200]
    return row


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
            resolved.append(_unresolved(
                "PAGE NOT IN THE DESIGN", ref, entry, None, by_number))
            continue

        lines = [l for l in page.lines
                 if abs(l.line - line_number) <= LINES_AROUND]
        if not lines:
            resolved.append(_unresolved(
                "LINE NOT ON THAT PAGE", ref, entry, page, by_number))
            continue

        row = {
            "ref": ref,
            "status": "VERIFIED",
            "claim": str(entry.get("claim") or "")[:160],
            "design_says": [f"{page_number}:{l.line}  {l.text}" for l in lines],
        }

        # The address being real is not the same as the quote being real. A
        # guide cited 203:11 — a line reading "Our God" — for the sentence
        # "By the end of the sub-strand, the learner should be able to:
        # identify three qualities of God." The address resolved, so the
        # reviewer called the citation correct and scored factual_correctness
        # 95. The quote was invented and attributed to a real line, which is
        # the one kind of fabrication that survives being checked.
        quote = str(entry.get("quote") or "").strip()
        if len(quote) >= MIN_QUOTE_CHARS:
            window = " ".join(
                l.text for l in page.lines
                if abs(l.line - line_number) <= QUOTE_WINDOW
            )
            support = _quote_support(quote, window)
            row["quote"] = quote[:200]
            row["quote_support"] = round(support, 2)
            if support < QUOTE_MATCH:
                # Before calling anything invented, look for it. The reviewer
                # and the generator do not always read the same rendering of
                # the design — a re-extraction can shift every line on a page
                # by two — and a citation that is three lines out is a wrong
                # address, not a written sentence. Saying "the quote was
                # written, not copied" about text that is demonstrably in the
                # document is the same false accusation this module was built
                # to stop, one level further down.
                found = _find(quote, page, by_number)
                if found:
                    row["status"] = f"QUOTE IS REAL, AT {found}"
                    row["found_at"] = found
                else:
                    row["status"] = "ADDRESS REAL, QUOTE NOT THERE"

        resolved.append(row)

    verified = sum(1 for r in resolved if r["status"] == "VERIFIED")
    misquoted = sum(1 for r in resolved
                    if r["status"] == "ADDRESS REAL, QUOTE NOT THERE")
    misaddressed = sum(1 for r in resolved if r.get("found_at"))
    return {
        "checked": True,
        "total": len(resolved),
        "verified": verified,
        "misquoted": misquoted,
        "misaddressed": misaddressed,
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
        if row.get("quote") and row["status"] != "VERIFIED":
            lines.append(f"      the artifact quotes: \"{row['quote']}\"")
        for said in row.get("design_says", []):
            lines.append(f"      the design reads: {said}")
        if row.get("found_at"):
            lines.append(
                f"      ^ that sentence IS in the design, at "
                f"{row['found_at']}. The quote is real and the address is "
                f"wrong. Not a fabrication — a citation to fix."
            )
        elif row["status"] == "ADDRESS REAL, QUOTE NOT THERE":
            lines.append(
                "      ^ the page and line exist, the sentence is not on them, "
                "and it is nowhere else in the design either. The quote was "
                "written, not copied."
            )
        lines.append("")

    lines += [
        "A citation marked VERIFIED is real. Do NOT report it as fabricated — "
        "it has been checked against the document, which you have not been "
        "shown in full.",
        "What IS worth your judgement: whether the quoted line actually "
        "supports the claim made from it. An address can resolve and still be "
        "cited for something it does not say.",
        "Report as fabricated the addresses marked MALFORMED, PAGE NOT IN THE "
        "DESIGN or LINE NOT ON THAT PAGE — and every one marked ADDRESS REAL, "
        "QUOTE NOT THERE. That last one is the worst case: a real address "
        "lends its authority to a sentence nobody wrote, and it passes every "
        "check a reader would think to make. Score factual_correctness low for "
        "it and name the quote.",
        "An address marked QUOTE IS REAL, AT … is NOT a fabrication. The "
        "sentence was found in the design at the address given after the "
        "comma; only the reference is off. Raise it as a low-severity citation "
        "fix and do NOT let it drag factual_correctness down as an invention "
        "would — the difference between a wrong page number and a written "
        "quotation is the whole of what this dimension measures.",
    ]
    return "\n".join(lines)

"""The pictures that actually exist, matched to the places the page keeps for them.

`notes_renderer.render_html` takes an `assets` map from "what the plan asked
for" to a URL. Neither route that renders a guide ever passed one — so the map
was always empty and EVERY figure printed as a hatched placeholder, including
the ones whose diagram had already been generated, reviewed and filed. The
production list said everything was outstanding.

Matching them is not a dictionary lookup either. The plan asks for

    "a number line diagram from -6 to +6 marked at every integer"

and the diagram station filed something titled

    "Number line showing integers from -6 to 6"

Those are the same picture and share not one identical string. So the match is
by overlapping content words, with a floor low enough to catch a rewording and
high enough that a lesson's photograph does not fill the slot kept for its
graph.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cbc-lesson-assets")

_STOP = frozenset("""
a an and are as at be by for from how in into is it its of on or that the their
then there these this to was were what when where which who will with your you
diagram picture image photo photograph video clip animation simulation showing
show shows illustrating illustrate labelled labeled drawing figure chart graph
""".split())

# Below this the two descriptions are simply about the same topic, which is not
# the same as being the same picture. "The respiratory system" covers half of
# "a labelled diagram of the human digestive system" on the word "system"
# alone — and showing one where the other was asked for is worse than showing
# a placeholder, because nobody checks a slot that looks filled.
_FLOOR = 0.6

# And one shared word is never enough on its own, whatever it scores.
_MIN_SHARED = 2


def _words(text: str) -> set[str]:
    from .figure_anchor import _stem

    found = re.findall(r"[a-z]{3,}", str(text or "").lower())
    return {_stem(w) for w in found if w not in _STOP}


def _score(wanted: str, candidate: str) -> float:
    """How much of what the plan asked for this candidate covers."""
    want, have = _words(wanted), _words(candidate)
    if not want or not have:
        return 0.0
    shared = want & have
    if len(shared) < min(_MIN_SHARED, len(want), len(have)):
        return 0.0
    # Against the SHORTER side: a long title that contains the whole request
    # should score high, and so should a terse title the request contains.
    return len(shared) / min(len(want), len(have))


def collect(grade: str, subject: str, sub_strand: str = "") -> list[dict[str, Any]]:
    """Everything filed for this sub-strand that can appear on a page.

    Failures are logged and swallowed: a guide that renders with placeholders
    is worth more than a guide that will not render.
    """
    found: list[dict[str, Any]] = []

    # Diagrams — the artifact carries the brief, the registry carries the SVG.
    try:
        from . import artifact_registry, diagram_svg

        for row in artifact_registry.search(grade=grade, subject=subject,
                                            sub_strand=sub_strand, kind="diagram"):
            content = row.get("content") or {}
            for diagram in (content.get("diagrams") or [content]):
                if not isinstance(diagram, dict):
                    continue
                title = str(diagram.get("title") or diagram.get("caption")
                            or diagram.get("what") or "").strip()
                url = str(diagram.get("storage_url") or diagram.get("url") or "")
                svg = ""
                try:
                    svg = diagram_svg.svg_for(diagram) or ""
                except Exception as exc:  # noqa: BLE001
                    logger.debug("No SVG for %s: %s", title[:60], exc)
                if title and (url or svg):
                    found.append({"kind": "diagram", "title": title,
                                  "url": url, "svg": svg,
                                  "alt": str(diagram.get("alt_text") or title)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not collect diagrams for %s/%s: %s", grade, subject, exc)

    # Photographs, video and audio.
    try:
        from . import media_registry

        for row in media_registry.list_for(grade, subject, sub_strand):
            title = str(row.get("title") or "").strip()
            url = str(row.get("storage_url") or row.get("asset_url") or "")
            if title and url:
                found.append({"kind": str(row.get("kind") or "image"),
                              "title": title, "url": url, "svg": "",
                              "alt": str(row.get("alt_text") or title)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not collect media for %s/%s: %s", grade, subject, exc)

    return found


def match(requirements: list[Any], available: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Which filed asset fills which requested figure, keyed by `what`.

    One asset fills at most one slot: two placeholders asking for slightly
    different diagrams must not both show the same picture, which would read
    as though both had been drawn.
    """
    if not requirements or not available:
        return {}

    pairs: list[tuple[float, int, int]] = []
    for r, req in enumerate(requirements):
        wanted = getattr(req, "what", "") or ""
        kind = getattr(req, "kind", "")
        for a, asset in enumerate(available):
            # A video never fills a slot kept for a diagram.
            if kind and asset.get("kind") and kind != asset["kind"]:
                continue
            score = _score(wanted, asset.get("title", ""))
            if score >= _FLOOR:
                pairs.append((score, r, a))

    pairs.sort(reverse=True)
    used_req: set[int] = set()
    used_asset: set[int] = set()
    out: dict[str, dict[str, Any]] = {}
    for score, r, a in pairs:
        if r in used_req or a in used_asset:
            continue
        used_req.add(r)
        used_asset.add(a)
        req = requirements[r]
        out[str(getattr(req, "what", "")).lower()] = {**available[a],
                                                      "match_score": round(score, 2)}
    return out


def for_notes(notes: dict[str, Any], grade: str, subject: str,
              sub_strand: str = "") -> dict[str, dict[str, Any]]:
    """The assets map `render_html` wants, built from what is actually filed."""
    try:
        from . import asset_requirements

        wanted = asset_requirements.read(notes).items
        return match(wanted, collect(grade, subject, sub_strand))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build the asset map: %s", exc)
        return {}

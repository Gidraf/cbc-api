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


# Two figure titles describing the same picture. Regenerating a diagram plan
# renames what it plans — "Number Line", then "Representation of Integers on a
# Number Line", then "Visual Representation of Integers on a Number Line" —
# and each new name filed a new asset beside the last, so one number line
# printed as three plates. Measured on those real titles: they score 0.67 and
# above against each other, and 0.00 against "Basic Operations on Integers",
# which is a genuinely different picture and must keep its own plate.
_SAME_SUBJECT = 0.6


def same_subject(one: str, other: str) -> bool:
    """Whether two figure titles are asking for the same picture."""
    one, other = str(one or "").strip(), str(other or "").strip()
    if not one or not other:
        return False
    if one.lower() == other.lower():
        return True
    return max(_score(one, other), _score(other, one)) >= _SAME_SUBJECT


def dedupe(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One asset per picture, keeping the first of each group.

    Callers pass them in preference order — newest first, a person's upload
    ahead of a station's older attempt — so "the first" is the one to keep.
    Only diagrams are collapsed: two photographs of the same thing are two
    photographs, and a video is never a duplicate of a drawing.

    Grouping is transitive, and it has to be. "Number Line" and "Visual
    Representation of Integers" share no words at all; they are the same
    picture only through "Representation of Integers on a Number Line", the
    name a regeneration in between them produced. So every pair is compared
    and the components are merged, rather than each title being tested against
    whichever member of a group happened to arrive first.
    """
    diagrams = [i for i, a in enumerate(assets) if a.get("kind") == "diagram"]
    parent = {i: i for i in diagrams}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(len(diagrams)):
        for b in range(a + 1, len(diagrams)):
            i, j = diagrams[a], diagrams[b]
            if same_subject(str(assets[i].get("title") or ""),
                            str(assets[j].get("title") or "")):
                parent[find(j)] = find(i)

    seen: set[int] = set()
    kept: list[dict[str, Any]] = []
    for i, asset in enumerate(assets):
        if asset.get("kind") != "diagram":
            kept.append(asset)
            continue
        root = find(i)
        if root in seen:
            continue
        seen.add(root)
        kept.append(asset)
    return kept


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
            # `visuals` is what the planner files and `diagrams` is what a
            # single render files. This read only the second, so every diagram
            # the station actually produced was invisible to the page and the
            # plate stayed hatched next to a diagram that existed.
            items = (content.get("visuals") or content.get("diagrams")
                     or [content])
            for diagram in items:
                if not isinstance(diagram, dict):
                    continue
                title = str(
                    diagram.get("title") or diagram.get("diagram_title")
                    or diagram.get("caption") or diagram.get("what") or ""
                ).strip()
                url = str(diagram.get("storage_url") or diagram.get("url") or "")
                # The generator's own key for the markup, before the stored one.
                svg = str(diagram.get("diagram_svg") or diagram.get("svg") or "")
                if not svg:
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

    # Anything a person supplied for a planned figure, and anything generated
    # on demand for one. Listed FIRST so that a file somebody chose beats a
    # station's older attempt at the same picture: an upload is a decision.
    try:
        from . import asset_uploads

        for row in asset_uploads.list_for(grade, subject, sub_strand):
            title = str(row.get("what") or row.get("title") or "").strip()
            if not title:
                continue
            url = str(row.get("storage_url") or "")
            svg = str(row.get("svg") or "")
            if url or svg:
                found.append({"kind": str(row.get("kind") or "diagram"),
                              "title": title, "url": url, "svg": svg,
                              "alt": str(row.get("alt_text") or title),
                              "source": str(row.get("source") or "upload")})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not collect uploads for %s/%s: %s", grade, subject, exc)

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

    # Newest and most deliberate first, then one per picture. Without this a
    # sub-strand redrawn four times printed four plates of the same figure.
    found.sort(key=lambda a: 0 if a.get("source") else 1)
    return dedupe(found)


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
            # An upload was filed against a requirement by name, so an exact
            # match on `what` is a decision a person made and outranks the
            # word-overlap score below.
            if asset.get("source") == "upload" and asset.get("title") == wanted:
                pairs.append((1.0, r, a))
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


def _best_module(title: str, modules: list[dict[str, Any]]) -> int:
    """Which lesson a drawing belongs beside, by what it is about.

    Falls back to the first lesson: a picture printed in the wrong lesson is a
    smaller failure than a picture the book never prints.
    """
    best, best_at = 0.0, 0
    for i, module in enumerate(modules):
        against = " ".join(str(module.get(k) or "") for k in
                           ("title", "topic", "teacher_exposition"))
        score = _score(title, against)
        if score > best:
            best, best_at = score, i
    return best_at


def with_drawn(plan: dict[str, Any], grade: str, subject: str,
               sub_strand: str = "") -> dict[str, Any]:
    """The plan, plus a visual entry for every diagram actually filed for it.

    A plate is reserved for what the PLAN asks for. So a diagram that had been
    planned by the diagram station, drawn, sanitised, stored in MinIO and
    scored 100/100 still printed as a hatched rectangle, because the lesson
    plan had happened to phrase its request as "charts" — and nothing binds
    "charts" to "Basic Operations on Integers".

    Whether the plan found the words for it is not the question. The drawing
    exists, it was made for this sub-strand, and the book should carry it. So
    anything filed and not already named by the plan is attached to the lesson
    it is about, and from there fills a plate like any other figure.
    """
    if not isinstance(plan, dict):
        return plan

    try:
        drawn = [a for a in collect(grade, subject, sub_strand)
                 if a.get("kind") == "diagram" and (a.get("svg") or a.get("url"))]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read what has been drawn for %s/%s: %s",
                       grade, sub_strand, exc)
        return plan
    if not drawn:
        return plan

    modules = plan.get("modules")
    if not isinstance(modules, list) or not modules:
        return plan
    modules = [m if isinstance(m, dict) else {} for m in modules]

    # What the plan already names, so a drawing is not attached twice and
    # printed twice.
    named: set[str] = set()
    for module in modules:
        for visual in (module.get("visuals") or module.get("diagrams") or []):
            if isinstance(visual, dict):
                named.add(str(visual.get("diagram_title") or visual.get("title")
                              or "").strip().lower())
            elif isinstance(visual, str):
                named.add(visual.strip().lower())

    out = [dict(m) for m in modules]
    added = 0
    for asset in drawn:
        title = str(asset.get("title") or "").strip()
        if not title or any(same_subject(title, seen) for seen in named):
            continue
        named.add(title.lower())
        at = _best_module(title, out)
        visuals = list(out[at].get("visuals") or [])
        visuals.append({"diagram_title": title,
                        "accessibility": {"alt_text": str(asset.get("alt") or title)},
                        "source": "drawn"})
        out[at]["visuals"] = visuals
        added += 1

    if not added:
        return plan
    return {**plan, "modules": out}

"""Where a figure goes on the page, and what to do when it does not exist yet.

The renderer used to emit every one of a lesson's figures in a block at the top
of the body and let them float. Two things went wrong with that.

The first is placement. A page reads "Integers can be illustrated on a number
line as shown below." — and the number line is three hundred words further up,
beside a different paragraph. "As shown below" is a promise the layout breaks.

The second is the empty plate. A lesson names a diagram nobody has drawn yet,
and the page prints a hatched box saying "diagram to be placed here". True, and
useless: the person looking at it now has to work out what the diagram was
supposed to show, in what style, at what level, before they can commission it.
Everything needed to write that brief is already in the plan.

So: figures are ANCHORED to the segment whose text calls for them, and an
unfilled one carries the prompt that would produce it, ready to copy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# "as shown below", "the diagram below", "see the figure" — an explicit promise
# that something appears at this point. These bind hardest.
_POINTS_HERE = re.compile(
    r"\b(?:as )?(?:shown|illustrated|represented|drawn|seen)\s+(?:below|here|above)\b"
    r"|\b(?:the |this )?(?:diagram|figure|picture|image|illustration|chart|graph|"
    r"table|number line|clip|video|animation|simulation)\s+(?:below|here|above|opposite)\b"
    r"|\b(?:look at|observe|study|examine)\s+(?:the|this)\s+"
    r"(?:diagram|figure|picture|image|illustration|chart|graph|video|clip)\b"
    r"|\bsee\s+(?:the\s+)?(?:diagram|figure|fig\.?|picture|illustration)\b",
    re.IGNORECASE,
)

_STOP = frozenset("""
a an and are as at be by for from how in into is it its of on or that the their
then there these this to was were what when where which who will with your you
learners learner teacher pupils children show shows showing using use used
""".split())


def _stem(word: str) -> str:
    """Crude singular. "integers" and "integer" are the same word here.

    Without this the number-line figure missed the paragraph that promised it:
    the requirement said "number line", the paragraph said "numbers" and
    "integers", and nothing matched.
    """
    for suffix, keep in (("ies", 3), ("ses", 2), ("xes", 2), ("shes", 2),
                         ("ches", 2), ("s", 1)):
        if word.endswith(suffix) and len(word) - keep >= 4:
            return word[: -keep] + ("y" if suffix == "ies" else "")
    return word


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", str(text or "").lower())
    return {_stem(w) for w in words if w not in _STOP}


@dataclass(slots=True)
class Anchor:
    """One figure, and the segment it belongs beside."""

    requirement: Any                 # asset_requirements.Requirement
    segment_index: int               # 1-based; 0 means "no segment matched"
    reason: str = ""                 # why it landed there, for the operator
    explicit: bool = False           # the text promised a figure at this point

    def to_dict(self) -> dict[str, Any]:
        return {"what": getattr(self.requirement, "what", ""),
                "kind": getattr(self.requirement, "kind", ""),
                "segment": self.segment_index,
                "reason": self.reason, "explicit": self.explicit}


def anchor(requirements: list[Any], segments: list[dict[str, Any]]) -> list[Anchor]:
    """Place each figure beside the segment that calls for it.

    Three rules, strongest first:

    1.  A segment whose text promises a figure ("as shown below") and whose
        words overlap the requirement takes it.
    2.  Otherwise the segment sharing the most vocabulary with the requirement.
    3.  Otherwise segment 0 — rendered at the top, as before. A figure with no
        home is still a figure the lesson asked for.

    Each segment takes at most one figure before any takes a second, so a
    lesson with four segments and four diagrams does not stack all four
    against the paragraph that happened to mention "diagram".
    """
    if not requirements:
        return []

    texts = [str(s.get("body") or "") for s in segments]
    keys = [_keywords(t) for t in texts]
    promises = [bool(_POINTS_HERE.search(t)) for t in texts]

    anchors: list[Anchor] = []
    taken: set[int] = set()

    for req in requirements:
        want = _keywords(getattr(req, "what", "")) | _keywords(getattr(req, "topic", ""))
        best_index, best_score, best_explicit = 0, 0.0, False

        for i, seg_keys in enumerate(keys, start=1):
            if not want:
                break
            overlap = len(want & seg_keys)
            if not overlap:
                continue
            score = overlap / len(want)
            # A promise doubles the pull, but only where the words also match:
            # "look at the diagram" in a segment about something else is not
            # this figure's home.
            if promises[i - 1]:
                score *= 2
            # Spread out before doubling up.
            if i in taken:
                score *= 0.4
            if score > best_score:
                best_index, best_score, best_explicit = i, score, promises[i - 1]

        if best_index:
            taken.add(best_index)
            reason = ("the text promises a figure here"
                      if best_explicit else "closest match in the teaching text")
        else:
            reason = "no segment named it — placed at the start of the lesson"

        anchors.append(Anchor(requirement=req, segment_index=best_index,
                              reason=reason, explicit=best_explicit))
    return anchors


def by_segment(anchors: list[Anchor]) -> dict[int, list[Anchor]]:
    out: dict[int, list[Anchor]] = {}
    for a in anchors:
        out.setdefault(a.segment_index, []).append(a)
    return out


# ── the brief for something that does not exist yet ─────────────────────────

_ASKS: dict[str, str] = {
    "diagram": "a labelled diagram",
    "image": "a photograph",
    "video": "a short video clip",
    "audio": "an audio recording",
    "simulation": "a small interactive simulation a learner can manipulate",
}

_STYLE: dict[str, str] = {
    "diagram": ("Line art, high contrast, labels in plain sans-serif large "
                "enough to survive a photocopy. Label only what the lesson "
                "names — an unlabelled part is a part the learner is not being "
                "asked about yet."),
    "image": ("A real photograph, Kenyan setting, people and objects a learner "
              "in this class would recognise. No stock-photo staging."),
    "video": ("Under 90 seconds. One idea. Wide, static shots at the seated eye "
              "level of this learner. Usable with the sound off."),
    "audio": ("Clear speech, no background music, at the pace this level reads."),
    "simulation": ("One control the learner changes, one thing they watch "
                   "change, and the relationship between them is the outcome. "
                   "Works on a small screen and with a slow connection."),
}


def brief_for(requirement: Any, *, grade_label: str = "", subject: str = "",
              strand: str = "", sub_strand: str = "", lesson_title: str = "",
              nearby_text: str = "") -> str:
    """The prompt that would produce this asset, ready to paste anywhere.

    Written to stand alone. Whoever fills this plate — a person, an image
    model, this platform's own diagram station — should not have to come back
    and ask what the picture was for.
    """
    kind = getattr(requirement, "kind", "diagram")
    what = str(getattr(requirement, "what", "") or "").strip()
    ask = _ASKS.get(kind, "an illustration")

    lines = [f"Produce {ask} for a Kenyan CBC lesson.", ""]

    where = " · ".join(x for x in (grade_label, subject, strand, sub_strand) if x)
    if where:
        lines += [f"CURRICULUM: {where}"]
    if lesson_title:
        lines += [f"LESSON: {lesson_title}"]
    topic = str(getattr(requirement, "topic", "") or "").strip()
    if topic:
        lines += [f"AT THIS POINT IN THE LESSON: {topic}"]

    lines += ["", f"WHAT IT MUST SHOW:", what or "(the plan did not say — check the lesson plan)"]

    if nearby_text:
        excerpt = re.sub(r"\s+", " ", nearby_text).strip()[:420]
        lines += ["", "THE TEXT IT SITS BESIDE — the figure must match this, "
                      "and must not introduce anything the text does not mention:",
                  f"\"{excerpt}\""]

    lines += ["", "STYLE:", _STYLE.get(kind, "Clear, simple, and legible in print.")]

    if grade_label:
        lines += ["", f"LEVEL: pitched at {grade_label}. Nothing in it should "
                      f"require knowledge this grade has not met."]

    return "\n".join(lines)

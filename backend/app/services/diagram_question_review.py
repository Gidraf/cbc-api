"""Reviewing a diagram question by doing to the diagram what the question does.

A diagram question is not text. "Name the part labelled A" is a claim about a
PICTURE that has had something taken out of it, and whether the question works
depends entirely on what the learner is left looking at. Reading the question
and the diagram separately — which is all a text reviewer can do — cannot see:

*   that the answer is still printed somewhere else on the page, so the
    question is free marks;
*   that the part it asks about was never removed, so the answer is simply
    there;
*   that two parts were blanked and the question asks about "the labelled
    part", so there is no single right answer;
*   that the region it points at is outside the viewBox, so the learner is
    looking at nothing.

So this applies the manipulation — the same call the paper uses — and inspects
the result. Everything here is mechanical: it is what a person does when they
cover the label with a thumb and asks whether the question still stands.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-diagram-question-review")

# Marks awarded for a question whose answer is visible on the paper.
LEAK = "answer_visible"
NOT_HIDDEN = "nothing_hidden"
AMBIGUOUS = "more_than_one_hidden"
OFF_CANVAS = "region_off_canvas"
NO_DIAGRAM = "no_diagram"


@dataclass(slots=True)
class Finding:
    code: str
    what: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "what": self.what, "detail": self.detail}


@dataclass(slots=True)
class Verdict:
    checked: bool = False
    findings: list[Finding] = field(default_factory=list)
    learner_view: str = ""
    marking_view: str = ""
    hidden_labels: list[str] = field(default_factory=list)

    @property
    def sound(self) -> bool:
        return self.checked and not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "sound": self.sound,
                "findings": [f.to_dict() for f in self.findings],
                "hidden_labels": self.hidden_labels,
                # The views themselves, so a reviewer can LOOK at what the
                # learner will see rather than take this on trust.
                "learner_view": self.learner_view,
                "marking_view": self.marking_view}


_TEXT = re.compile(r"<text\b[^>]*>(.*?)</text>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")


def visible_text(svg: str) -> list[str]:
    """Every word actually printed on the picture."""
    out: list[str] = []
    for chunk in _TEXT.findall(svg or ""):
        words = _TAGS.sub(" ", chunk)
        cleaned = " ".join(words.split())
        if cleaned:
            out.append(cleaned)
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _leaks(answer: str, shown: list[str]) -> str:
    """Whether the answer is readable on the learner's own copy.

    Matched whole, not as a substring: "Zero" must not be reported as leaking
    because the picture prints "-10". A one- or two-character answer is not
    checked at all — "A" appears in half the labels on any diagram and flagging
    that would train a reviewer to ignore this.
    """
    wanted = _norm(answer)
    if len(wanted) < 3:
        return ""
    for line in shown:
        if wanted and wanted in _norm(line).split() or wanted == _norm(line):
            return line
        # A multi-word answer printed as a phrase.
        if " " in wanted and wanted in _norm(line):
            return line
    return ""


def review(diagram: dict[str, Any], binding: dict[str, Any] | None,
           answer: str = "") -> Verdict:
    """Manipulate the diagram as the question does, then inspect the result."""
    from . import diagram_scene

    verdict = Verdict()

    svg = str(diagram.get("svg_markup") or diagram.get("diagram_svg") or "")
    if not svg.strip():
        verdict.findings.append(Finding(
            NO_DIAGRAM, "There is no drawing to ask about.",
            "The plan was written but nothing was drawn from it, so this "
            "question points at a blank space."))
        return verdict

    try:
        verdict.learner_view = diagram_scene.render_for_question(
            diagram, binding, with_answers=False)
        verdict.marking_view = diagram_scene.render_for_question(
            diagram, binding, with_answers=True)
    except Exception as exc:  # noqa: BLE001
        # A manipulation that throws is a finding, not a crash: the paper would
        # have thrown too.
        logger.warning("Could not manipulate the diagram: %s", exc)
        verdict.findings.append(Finding(
            NO_DIAGRAM, "The diagram could not be manipulated.", str(exc)[:160]))
        return verdict

    verdict.checked = True

    scene = diagram.get("scene_document") or {}
    parts = [p for p in (scene.get("parts") or []) if isinstance(p, dict)]
    by_id = {str(p.get("id") or p.get("part_id") or ""): p for p in parts}

    hidden_ids = list((binding or {}).get("hide_part_ids") or [])
    verdict.hidden_labels = [
        str(by_id.get(pid, {}).get("label") or pid) for pid in hidden_ids
    ]

    before = visible_text(verdict.marking_view)
    after = visible_text(verdict.learner_view)

    # 1. Was anything actually taken away?
    if hidden_ids and len(after) >= len(before):
        verdict.findings.append(Finding(
            NOT_HIDDEN,
            "Nothing was removed from the learner's copy.",
            f"The question hides {', '.join(verdict.hidden_labels)}, but the "
            f"learner's diagram prints as much text as the marking copy. The "
            f"answer is on the paper."))

    # 2. Is the answer still readable on the learner's copy?
    leaked = _leaks(answer, after)
    if leaked:
        verdict.findings.append(Finding(
            LEAK,
            "The answer is printed on the learner's own diagram.",
            f'"{leaked}" is still shown, so this question awards its marks for '
            f"reading the picture rather than knowing it."))

    # 3. One question, one answer.
    if len(hidden_ids) > 1:
        verdict.findings.append(Finding(
            AMBIGUOUS,
            f"{len(hidden_ids)} parts are hidden at once.",
            f"Hidden: {', '.join(verdict.hidden_labels)}. A question asking "
            f"for 'the labelled part' has more than one right answer."))

    # 4. Is the region it points at actually on the picture?
    region_id = str((binding or {}).get("region_id") or "")
    if region_id:
        regions = {str(r.get("id") or ""): r
                   for r in (scene.get("regions") or []) if isinstance(r, dict)}
        if region_id not in regions and region_id not in by_id:
            verdict.findings.append(Finding(
                OFF_CANVAS,
                "The question points at a region the diagram does not have.",
                f"'{region_id}' is not a part or region of this scene."))

    return verdict


def gate_of(verdicts: list[Verdict]) -> dict[str, Any]:
    """The diagram-question check, in the shape every station reports."""
    checked = [v for v in verdicts if v.checked]
    unsound = [v for v in checked if v.findings]
    total = len(verdicts) or 1
    score = round(len(checked and [v for v in checked if v.sound]) / total * 100, 1)

    counts: dict[str, int] = {}
    for verdict in verdicts:
        for finding in verdict.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1

    actions: list[str] = []
    if counts.get(LEAK):
        actions.append(
            f"{counts[LEAK]} question(s) print their own answer on the learner's "
            f"diagram. Hide the labelled part, or ask about something the "
            f"picture does not already say.")
    if counts.get(NOT_HIDDEN):
        actions.append(
            f"{counts[NOT_HIDDEN]} question(s) hide nothing — the learner sees "
            f"the marking copy. Check the part id in the binding matches a part "
            f"in the scene.")
    if counts.get(AMBIGUOUS):
        actions.append(
            f"{counts[AMBIGUOUS]} question(s) hide more than one part, so 'the "
            f"labelled part' has several right answers. Hide one.")
    if counts.get(NO_DIAGRAM):
        actions.append(
            f"{counts[NO_DIAGRAM]} question(s) point at a diagram that was "
            f"planned but never drawn. Draw it from the diagram station first.")

    return {
        "passed": not unsound and bool(checked),
        "overall_score": int(round(score)),
        "layer_name": "diagram_questions",
        "summary_message": (
            f"{len(checked) - len(unsound)} of {len(verdicts)} diagram "
            f"question(s) survive the manipulation they describe."),
        "reviewer": {
            "score": int(round(score)),
            "passed": not unsound and bool(checked),
            "status": "approved" if not unsound and checked else "revise",
            "feedback": [
                {"aspect": "answer_hidden", "method": "text_diff_after_occlusion",
                 "status": "fail" if counts.get(LEAK) or counts.get(NOT_HIDDEN) else "pass",
                 "score": round(1 - (counts.get(LEAK, 0) + counts.get(NOT_HIDDEN, 0)) / total, 4),
                 "comment": f"{counts.get(LEAK, 0)} print the answer, "
                            f"{counts.get(NOT_HIDDEN, 0)} hide nothing"},
                {"aspect": "single_answer", "method": "hidden_part_count",
                 "status": "fail" if counts.get(AMBIGUOUS) else "pass",
                 "score": round(1 - counts.get(AMBIGUOUS, 0) / total, 4),
                 "comment": f"{counts.get(AMBIGUOUS, 0)} hide more than one part"},
                {"aspect": "diagram_exists", "method": "svg_present",
                 "status": "fail" if counts.get(NO_DIAGRAM) else "pass",
                 "score": round(1 - counts.get(NO_DIAGRAM, 0) / total, 4),
                 "comment": f"{counts.get(NO_DIAGRAM, 0)} point at nothing drawn"},
            ],
        },
        "next_actions": actions,
    }

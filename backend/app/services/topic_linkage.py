"""A diagram may only depict what the lesson actually teaches.

An asset planner is given the sub-strand's title and outcomes and asked for
visuals. It obliges: a soil-profile schematic, an erosion diagram, a titration
apparatus — all plausible for the subject, none of them things the lesson plan
mentions. The diagram is then drawn, reviewed on its own terms, approved, and
printed beside a lesson it illustrates nothing in.

Nothing catches it, because every check downstream asks whether the DIAGRAM is
good. None asks whether the lesson contains it.

So the plan's own topics become the vocabulary an asset is allowed to draw
from, and anything outside it is reported by name. Not to forbid a visual
metaphor — a picture of a mother giving food is the right illustration for "God
provides" and appears nowhere in the plan's words — but to separate the two
cases, which read identically in the artifact and are not the same thing at
all: a picture of something taught elsewhere, and a picture of something not
taught at all.
"""
from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-topic-linkage")

# How close an asset's subject has to be to something the plan says before it
# counts as illustrating it.
MATCH = 0.55

# Words that carry no subject. Matching on these makes every asset look linked.
_GENERIC = {
    "the", "and", "for", "with", "from", "that", "this", "into", "about",
    "lesson", "hour", "part", "topic", "learners", "learner", "children",
    "child", "teacher", "class", "activity", "diagram", "picture", "image",
    "photo", "video", "chart", "illustration", "showing", "shows", "show",
    "simple", "drawn", "drawing",
}


@dataclass(slots=True)
class Linkage:
    checked: bool = False
    topics: list[str] = field(default_factory=list)
    linked: list[dict[str, Any]] = field(default_factory=list)
    unlinked: list[dict[str, Any]] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.linked) + len(self.unlinked)

    @property
    def score(self) -> float:
        if not self.total:
            return 100.0
        return round(len(self.linked) / self.total * 100, 1)

    @property
    def clean(self) -> bool:
        return self.checked and not self.unlinked

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked, "clean": self.clean, "score": self.score,
            "topics": self.topics, "total": self.total,
            "linked": self.linked, "unlinked": self.unlinked,
            "uncovered": self.uncovered,
        }


def _words(text: Any) -> set[str]:
    return {
        w for w in re.sub(r"[^a-z0-9 ]+", " ", str(text).lower()).split()
        if len(w) > 3 and w not in _GENERIC
    }


def _modules(plan: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "lessons"):
        found = plan.get(key)
        if isinstance(found, list) and found:
            return [m for m in found if isinstance(m, dict)]
    return []


def topics_of(plan: dict[str, Any]) -> list[str]:
    """Everything the plan says is taught, as a flat list a diagram can match.

    Titles and segment topics, not the whole prose: an asset that shares three
    words with a paragraph is not thereby illustrating it, and matching against
    the whole plan makes everything look linked.
    """
    if not isinstance(plan, dict):
        return []
    out: list[str] = []
    for module in _modules(plan):
        for value in (module.get("title"), module.get("learning_intent")):
            if str(value or "").strip():
                out.append(str(value).strip())
        for segment in (module.get("exposition_segments") or []):
            if isinstance(segment, dict) and str(segment.get("topic") or "").strip():
                out.append(str(segment["topic"]).strip())
        for slo in (module.get("slos_covered") or []):
            if str(slo or "").strip():
                out.append(str(slo).strip())
    seen, unique = set(), []
    for topic in out:
        key = topic.lower()
        if key not in seen:
            seen.add(key)
            unique.append(topic)
    return unique


def _assets(content: Any) -> list[dict[str, Any]]:
    """Every planned asset, whatever the station called its list."""
    if isinstance(content, list):
        return [a for a in content if isinstance(a, dict)]
    if not isinstance(content, dict):
        return []
    for key in ("visuals", "assets", "diagrams", "media", "prompts",
                "simulations", "activities", "items"):
        found = content.get(key)
        if isinstance(found, list) and found:
            return [a for a in found if isinstance(a, dict)]
    return []


def _subject_of(asset: dict[str, Any]) -> str:
    parts = [asset.get(k) for k in
             ("title", "micro_concept", "concept", "subject", "description",
              "what_it_shows", "caption", "hour_title")]
    return " ".join(str(p) for p in parts if p)


def _best(subject: str, topics: list[str]) -> tuple[str, float]:
    words = _words(subject)
    best, score = "", 0.0
    for topic in topics:
        topic_words = _words(topic)
        if not topic_words or not words:
            continue
        # Shared vocabulary first — an asset called "Saying the Name of God"
        # and a topic of the same name share every content word — then a
        # sequence ratio, which catches rewordings the word sets miss.
        overlap = len(words & topic_words) / min(len(words), len(topic_words))
        ratio = difflib.SequenceMatcher(
            None, " ".join(sorted(words)), " ".join(sorted(topic_words))).ratio()
        value = max(overlap, ratio)
        if value > score:
            best, score = topic, value
    return best, round(score, 2)


def check(assets: Any, plan: dict[str, Any]) -> Linkage:
    """Which planned assets illustrate something the plan teaches, and which do not."""
    report = Linkage()
    topics = topics_of(plan)
    if not topics:
        return report

    report.checked = True
    report.topics = topics
    hit: set[str] = set()

    for asset in _assets(assets):
        subject = _subject_of(asset).strip()
        if not subject:
            continue
        topic, score = _best(subject, topics)
        row = {
            "asset": str(asset.get("asset_id") or asset.get("title") or subject)[:120],
            "subject": subject[:160],
            "closest_topic": topic,
            "match": score,
        }
        if score >= MATCH:
            report.linked.append(row)
            hit.add(topic)
        else:
            report.unlinked.append(row)

    report.uncovered = [t for t in topics if t not in hit]
    return report


def render(report: Linkage) -> str:
    """The block a reviewer reads instead of judging a picture on its own terms."""
    if not report.checked or report.clean:
        return ""

    lines = [
        "=== WHAT THE LESSON PLAN ACTUALLY TEACHES ===",
        "Every planned asset was matched against the plan's own topics before "
        "you saw it. An asset illustrates the lesson or it illustrates "
        "something else, and the two read identically in the artifact.",
        "",
        f"The plan teaches: {'; '.join(report.topics[:20])}",
        "",
    ]
    for row in report.unlinked:
        lines.append(
            f"  NOT IN THE PLAN: \"{row['asset']}\" — {row['subject']}"
        )
        if row["closest_topic"]:
            lines.append(
                f"      closest the plan comes: \"{row['closest_topic']}\" "
                f"({int(row['match'] * 100)}% alike)"
            )
        lines.append("")

    lines += [
        "Judge each of these. A visual METAPHOR for something the plan teaches "
        "is right and will not match — a picture of a mother giving food "
        "illustrates \"God provides\" and shares no words with it. Say so and "
        "move on.",
        "What is wrong is an asset about something the lesson does not teach: "
        "it will be drawn, reviewed on its own terms, approved, and printed "
        "beside a lesson it illustrates nothing in. Raise it under "
        "curriculum_alignment, naming the asset.",
    ]
    if report.uncovered:
        lines += [
            "",
            "Taught and illustrated by nothing: "
            + "; ".join(report.uncovered[:10])
            + ". Not a defect on its own — not everything needs a picture.",
        ]
    return "\n".join(lines)

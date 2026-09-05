"""What the lesson plan says it needs a picture, a recording or a video OF.

The plan already names its assets. Lesson 1 asks for "an audio clip of a song
about God" and "visual aids for gestures"; a segment says "observe pictures of
Adam and Eve" because the design said so. Those are requirements, written down,
in the plan's own words.

The asset stations were not reading them. Each was given the sub-strand's title
and outcomes and asked to plan visuals from scratch — which is why they came
back with a soil-profile schematic for a lesson about God, and why nothing the
plan actually asked for was guaranteed to exist. The plan said "visual aids for
gestures" and no brief for one was ever written.

So the requirements are read off the plan first, and the stations are told what
to produce rather than asked what they would like to. A picture the lesson asks
for and never gets is the failure this exists to catch; a picture nothing asked
for is the other one, and `topic_linkage` catches that.

Not everything named is an asset. "Space for group singing" is a room, and a
station that produced a brief for a room would be producing nothing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-asset-requirements")

# What a requirement is FOR, which decides which station owes it.
KINDS = ("diagram", "image", "video", "audio", "simulation", "object")

# Which station produces each kind. `object` has none: a drum, a Bible and a
# cleared floor are brought, not generated.
STATION: dict[str, str] = {
    "diagram": "diagram",
    "image": "media",
    "video": "media",
    "audio": "media",
    "simulation": "simulation",
    "object": "",
}

# Read in order; the first match wins, so the more specific patterns come
# first. Written against how KICD designs and these plans actually phrase it
# rather than against a taxonomy.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("video", re.compile(
        r"\b(videos?|films?|clip of .{0,30}(showing|demonstrat)|watch a|screening)\b", re.I)),
    ("audio", re.compile(
        r"\b(audio|recorded|recording|listen to|song|sung|chant|rhyme|played aloud)\b", re.I)),
    ("simulation", re.compile(
        r"\b(simulation|interactive|animation|model of the|virtual)\b", re.I)),
    ("diagram", re.compile(
        # A WALL chart of children in church is a picture; a chart of the
        # water cycle is a diagram. The lookbehind is the whole difference.
        r"\b(diagrams?|flowcharts?|labelled|labeled|schematics?|maps?|graphs?|"
        r"(?<!wall )charts?|table of)\b", re.I)),
    # Plurals matter more than they look: "visual aid" with a trailing word
    # boundary does not match "visual aids", which is how every plan writes it,
    # and the requirement was then filed as an object to bring.
    ("image", re.compile(
        r"\b(pictures?|photos?|photographs?|images?|illustrations?|drawn|drawing|"
        r"flash ?cards?|posters?|wall ?charts?|visual aids?|cut-?outs?)\b", re.I)),
)

# Named in a plan and produced by nobody: brought to the room, not generated.
_OBJECT = re.compile(
    r"\b(space|room|floor|area|clay|dough|crayon|pencil|paper|scissors|glue|"
    r"chalk|board|instrument|drum|shaker|bible|book|cup|plate|water|seed|"
    r"costume|prop|material for|materials)\b", re.I)


@dataclass(slots=True)
class Requirement:
    kind: str
    what: str
    module_number: int
    module_title: str
    topic: str = ""
    # Where in the plan it was named — a reader who disagrees should be able to
    # go and look.
    source: str = "resources_needed"

    @property
    def station(self) -> str:
        return STATION.get(self.kind, "")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "what": self.what,
                "module_number": self.module_number,
                "module_title": self.module_title, "topic": self.topic,
                "source": self.source, "station": self.station}


@dataclass(slots=True)
class Requirements:
    items: list[Requirement] = field(default_factory=list)

    def for_station(self, station: str) -> list[Requirement]:
        return [r for r in self.items if r.station == station]

    @property
    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items:
            out[item.kind] = out.get(item.kind, 0) + 1
        return out

    @property
    def generated(self) -> list[Requirement]:
        """The ones a station owes a brief for."""
        return [r for r in self.items if r.station]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": len(self.items),
            "to_generate": len(self.generated),
            "by_kind": self.by_kind,
            "by_station": {
                station: len(self.for_station(station))
                for station in sorted({r.station for r in self.items if r.station})
            },
            "items": [r.to_dict() for r in self.items],
        }


# A resources line is often a LIST — "number cards, charts, worksheets" — and
# a list is a shopping list, not one figure. It reserved a plate on the page
# captioned "number cards, charts, worksheets" and offered a prompt to draw it.
_LIST = re.compile(r",|\band\b", re.I)

# Things a teacher carries into the room. A "chart" among them is a piece of
# card, not a diagram anybody generates.
_CLASSROOM = re.compile(
    r"\b(cards?|worksheets?|counters?|dice|beads?|sticks?|bottle tops?|"
    r"stones?|straws?|rulers?|tape measures?|thermometers?|calculators?|"
    r"charts?|manila|markers?|string)\b", re.I)


def _is_a_shopping_list(text: str) -> bool:
    """Two or more classroom objects named together: bring these, draw none."""
    if not _LIST.search(text):
        return False
    named = len(_CLASSROOM.findall(text))
    return named >= 2 or (named >= 1 and len(_LIST.findall(text)) >= 2)


def _classify(text: str) -> str:
    """What kind of thing this is, or "object" if nobody generates it."""
    if _is_a_shopping_list(text):
        return "object"
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            # A song is audio; a song sheet is not. Where an object word is the
            # HEAD of the phrase, it is a thing to bring.
            if kind == "image" and _OBJECT.search(text) and not re.search(
                    r"\b(picture|photo|image|illustration|drawn|flashcard|poster)\b",
                    text, re.I):
                return "object"
            return kind
    if _OBJECT.search(text):
        return "object"
    return "object"


def _modules(plan: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "lessons"):
        found = plan.get(key)
        if isinstance(found, list) and found:
            return [m for m in found if isinstance(m, dict)]
    return []


# Phrases in a segment's own words that ask for something to be shown or heard.
_ASKS = re.compile(
    r"((?:observe|show|hold up|display|play|watch|listen to|point at|look at)\b[^.!?]{6,120})",
    re.I)


def read(plan: dict[str, Any]) -> Requirements:
    """Every asset the plan asks for, per lesson, in the plan's own words."""
    out = Requirements()
    if not isinstance(plan, dict):
        return out

    seen: set[tuple[int, str]] = set()

    for i, module in enumerate(_modules(plan), start=1):
        try:
            number = int(module.get("module_number") or i)
        except (TypeError, ValueError):
            number = i
        title = str(module.get("title") or f"Lesson {number}")

        def add(text: str, topic: str, source: str) -> None:
            what = " ".join(str(text).split()).strip(" .,;")
            if len(what) < 4:
                return
            key = (number, what.lower())
            if key in seen:
                return
            seen.add(key)
            out.items.append(Requirement(
                kind=_classify(what), what=what, module_number=number,
                module_title=title, topic=topic, source=source))

        # What the plan says the teacher must have ready. The plainest
        # statement of a requirement there is.
        for entry in (module.get("resources_needed") or []):
            add(str(entry), "", "resources_needed")

        # And what the teaching itself asks to be shown or heard, which the
        # resources list often misses — a segment saying "observe pictures of
        # Adam and Eve" is asking for a picture whether or not anyone wrote it
        # under resources.
        for segment in (module.get("exposition_segments") or []):
            if not isinstance(segment, dict):
                continue
            topic = str(segment.get("topic") or "")
            for match in _ASKS.finditer(str(segment.get("body") or "")):
                add(match.group(1), topic, "exposition")

    return out


def render(requirements: Requirements, station: str = "") -> str:
    """What to produce, for the station that owes it.

    Given to the asset stations instead of the sub-strand's title and outcomes,
    which is what they were planning from — and why they returned assets for a
    lesson that never mentioned them.
    """
    wanted = requirements.for_station(station) if station else requirements.generated
    if not wanted:
        return ""

    lines = [
        "=== WHAT THE LESSON PLAN ASKS FOR ===",
        "Read off the plan itself, lesson by lesson. These are not "
        "suggestions to improve on: the plan is what the teacher will teach "
        "from, and an asset it asks for and never gets is a lesson with a hole "
        "in it.",
        "",
    ]
    by_module: dict[int, list[Requirement]] = {}
    for item in wanted:
        by_module.setdefault(item.module_number, []).append(item)

    for number in sorted(by_module):
        items = by_module[number]
        lines.append(f"  {items[0].module_title}")
        for item in items:
            where = f" (in \"{item.topic}\")" if item.topic else ""
            lines.append(f"      [{item.kind}] {item.what}{where}")
        lines.append("")

    lines += [
        "Produce one for each. Where the plan asks for something you cannot "
        "brief — it names an object to bring rather than an asset to make — "
        "say so rather than inventing a picture of it.",
        "Do NOT add assets the plan does not ask for. Something the lesson "
        "never mentions will be drawn, reviewed on its own terms, approved, "
        "and printed beside a lesson it illustrates nothing in.",
    ]
    return "\n".join(lines)

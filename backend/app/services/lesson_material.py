"""The words themselves, not the instruction to find them.

Everything this pipeline has produced so far is a DIRECTION. "Choose a simple
song about God." "Tell a simple story that illustrates God's love." "Play a
recorded clip of a short prayer." A teacher reading that still has to find the
song, write the story and record the prayer — which is the whole of the work,
and none of it is here. The same is true one station over: a diagram artifact
is a brief for a diagram, a photo prompt is a brief for a photograph. Briefs
are the right output for those, because something else draws the picture.

Nobody was writing the words.

So this is the layer under the plan. Each segment of the plan carries a
DIRECTIVE — the teacher move, in the imperative — and this fulfils it with the
thing itself: the song's actual verse, the story as it is told, the prayer as
it is said, the explanation in the words the teacher speaks aloud. A guide
without it is a shopping list; with it, a teacher can open the page and teach.

It is a separate artifact on purpose. The plan is checked against the design —
does it teach what KICD funded? The material is checked against the plan and
against the child — are these words true, and can a four-year-old hear them?
Those are different questions, and one review that tries to ask both asks
neither well.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-lesson-material")

# What a segment's material can be. Named so the generator commits to a form
# rather than returning prose that might be a song or might be a paraphrase.
FORMS = ("explanation", "story", "song", "prayer", "rhyme", "dialogue",
         "worked_example", "demonstration", "question_set")

# A directive that produces less than this is a heading, not material.
MIN_MATERIAL_CHARS = 120

# Material this close to the length of its own instruction is a restatement of
# it. Real material for a ten-minute segment runs several times the length of
# the sentence that asked for it.
ECHO_LENGTH_RATIO = 1.6
ECHO_OVERLAP = 0.7

# Verbs that mark a segment as asking for something the teacher must supply.
# These are exactly the places a guide leaves the work undone.
_UNFULFILLED = re.compile(
    r"\b(choose|select|find|pick|play a recording|use a song|tell a( simple)? story"
    r"|sing a song|teach (them|the children) (a|the) song|read (the|a) story"
    r"|introduce the phrase|share an example|give an example)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Directive:
    """One instruction from the plan, and where it came from."""

    module_number: int
    module_title: str
    index: int
    topic: str
    minutes: int
    instruction: str
    unfulfilled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_number": self.module_number,
            "module_title": self.module_title,
            "index": self.index, "topic": self.topic,
            "minutes": self.minutes, "instruction": self.instruction,
            "unfulfilled": self.unfulfilled,
        }


@dataclass(slots=True)
class Plan:
    directives: list[Directive] = field(default_factory=list)
    modules: int = 0

    @property
    def unfulfilled(self) -> list[Directive]:
        return [d for d in self.directives if d.unfulfilled]

    def to_dict(self) -> dict[str, Any]:
        return {"modules": self.modules,
                "directives": len(self.directives),
                "unfulfilled": len(self.unfulfilled)}


def _modules(plan: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "lessons"):
        found = plan.get(key)
        if isinstance(found, list) and found:
            return [m for m in found if isinstance(m, dict)]
    return []


def directives_of(plan: dict[str, Any]) -> Plan:
    """Every instruction the plan gives, in the order a lesson runs.

    Flattened deliberately: the material generator is asked to fulfil ONE
    directive at a time, and a segment that arrives inside a whole guide gets
    the attention a paragraph gets rather than the attention it needs.
    """
    out = Plan()
    if not isinstance(plan, dict):
        return out

    modules = _modules(plan)
    out.modules = len(modules)
    for i, module in enumerate(modules, start=1):
        try:
            number = int(module.get("module_number") or i)
        except (TypeError, ValueError):
            number = i
        title = str(module.get("title") or f"Lesson {number}")

        segments = [s for s in (module.get("exposition_segments") or [])
                    if isinstance(s, dict)]
        if not segments and module.get("teacher_exposition"):
            segments = [{"topic": title, "body": module["teacher_exposition"],
                         "minutes": module.get("duration_minutes")}]

        for j, segment in enumerate(segments, start=1):
            body = str(segment.get("body") or "").strip()
            if not body:
                continue
            try:
                minutes = int(segment.get("minutes") or 0)
            except (TypeError, ValueError):
                minutes = 0
            out.directives.append(Directive(
                module_number=number, module_title=title, index=j,
                topic=str(segment.get("topic") or f"Part {j}"),
                minutes=minutes, instruction=body,
                unfulfilled=bool(_UNFULFILLED.search(body)),
            ))
    return out


def prompt_for(directive: Directive, *, register: str, faith: str,
               sub_strand: str, slos: list[str], language: str = "") -> str:
    """What to ask for, for ONE directive.

    One directive per call rather than a whole guide per call, because the
    failure this layer exists to prevent is exactly the failure a long prompt
    produces: something general where something specific was needed. A song is
    either written out or it is not, and that is easier to get right — and
    easier to check — one song at a time.
    """
    return "\n".join([
        "You are writing the MATERIAL for one part of one lesson.",
        "",
        f"Sub-strand: {sub_strand}",
        f"Lesson {directive.module_number}: {directive.module_title}",
        f"This part: {directive.topic}"
        + (f" ({directive.minutes} minutes)" if directive.minutes else ""),
        "",
        "=== THE INSTRUCTION YOU ARE FULFILLING ===",
        directive.instruction,
        "",
        "=== WHAT TO RETURN ===",
        "That instruction tells a teacher WHAT TO DO. It does not give them "
        "the words. Your job is the words.",
        "",
        "Where it says to choose a song, WRITE THE VERSE OUT, line by line, "
        "with the actions beside it. Where it says to tell a story, TELL THE "
        "STORY, in the sentences the teacher says aloud. Where it says to "
        "explain something, WRITE THE EXPLANATION as it is spoken — not a "
        "summary of it, not a description of what would be said. Where it says "
        "to play a recording, write what the recording says so a teacher "
        "without one can read it aloud.",
        "",
        "Do not repeat the instruction back. Do not describe the material. "
        "Produce it.",
        "",
        *( ["=== WHO IS LISTENING ===", register, ""] if register else []),
        # The register above governs what the learner may be ASKED to do. This
        # governs the sentences they hear while being asked, and it is the half
        # that goes wrong quietly: a guide can ask a four-year-old to do exactly
        # the right thing in words they cannot follow.
        *( [language, ""] if language else []),
        *( [faith, ""] if faith else []),
        "=== WHAT THIS PART SERVES ===",
        *( [f"- {s}" for s in slos] if slos else ["- (no outcome recorded)"]),
        "",
        "Every word must be true and must be sayable to this learner. Invent "
        "no scripture reference, no statistic and no source. Where a song or a "
        "story is widely known, write the words as they are commonly sung or "
        "told; where you would have to invent one, write an original and say "
        "so in `attribution`.",
        "",
        "Return ONLY valid JSON:",
        "{",
        f'  "form": "one of: {", ".join(FORMS)}",',
        '  "title": "what this piece of material is called, if it has a name",',
        '  "say": "the words the teacher speaks, verbatim, in the order they '
        'are spoken. This is the substance — it must be long enough to fill '
        'the time above.",',
        '  "learner_does": "what the children do while this happens",',
        '  "attribution": "where these words come from: traditional, widely '
        'known, or written here for this lesson. Say which — a teacher '
        'introducing a song to a class should know whether it is one the '
        'children may already know.",',
        '  "notes_for_the_teacher": "anything about delivering these exact '
        'words: where to pause, what to hold up, what a child will say back."',
        "}",
    ])


@dataclass(slots=True)
class MaterialReport:
    total: int = 0
    written: int = 0
    thin: list[dict[str, Any]] = field(default_factory=list)
    echoed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.thin and not self.echoed and self.written == self.total

    @property
    def score(self) -> float:
        if not self.total:
            return 100.0
        good = self.total - len(self.thin) - len(self.echoed)
        return round(max(0.0, good) / self.total * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "written": self.written,
                "thin": self.thin, "echoed": self.echoed,
                "clean": self.clean, "score": self.score}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", str(text)).lower()).strip()


def check(material: dict[str, Any], plan: Plan) -> MaterialReport:
    """Did each directive get material, or did it get its own words back?

    The failure mode here is not fabrication, it is ECHO: asked to write the
    song, a model returns "a simple song about God's love, sung with actions" —
    which is the instruction again, one adjective longer, and leaves the
    teacher exactly where they started.
    """
    report = MaterialReport(total=len(plan.directives))
    pieces = material.get("material") if isinstance(material, dict) else None
    if not isinstance(pieces, list):
        return report

    by_key = {}
    for piece in pieces:
        if isinstance(piece, dict):
            by_key[(piece.get("module_number"), piece.get("index"))] = piece

    for directive in plan.directives:
        piece = by_key.get((directive.module_number, directive.index))
        if not piece:
            continue
        said = str(piece.get("say") or "").strip()
        if not said:
            continue
        report.written += 1

        where = {"lesson": directive.module_number, "topic": directive.topic}
        if len(said) < MIN_MATERIAL_CHARS:
            report.thin.append({**where, "chars": len(said), "say": said[:120]})
            continue

        # Echo: what came back is the instruction in other words.
        #
        # Narrow on purpose. The rule is "no longer than its instruction, and
        # sharing its vocabulary", which has almost no false positives. A
        # restatement padded with connectives until it is twice the length
        # escapes it, and is left to the reviewer — a judgement dressed up as a
        # measurement is how this pipeline came to trust numbers it should not
        # have.
        #
        # Vocabulary overlap alone is not enough to say so. An instruction that
        # NAMES the song — "such as 'He's Got the Whole World in His Hands'" —
        # shares almost every word with the song's actual verse, and flagging
        # that would report correct material as an echo. What a restatement
        # cannot do is be much longer than the thing it restates.
        instruction = _norm(directive.instruction)
        words = {w for w in _norm(said).split() if len(w) > 3}
        if words and len(said) < len(directive.instruction) * ECHO_LENGTH_RATIO:
            shared = sum(1 for w in words if w in instruction) / len(words)
            if shared > ECHO_OVERLAP:
                report.echoed.append({**where, "overlap": round(shared * 100),
                                      "say": said[:120]})
    return report

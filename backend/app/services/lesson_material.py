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

from . import material_form

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


AGENT = "material-generator"


def prompt_for(directive: Directive, *, register: str, faith: str,
               sub_strand: str, slos: list[str], language: str = "",
               notation: str = "", target_language: str = "",
               grade: str = "") -> str:
    """What to ask for, for ONE directive.

    One directive per call rather than a whole guide per call, because the
    failure this layer exists to prevent is exactly the failure a long prompt
    produces: something general where something specific was needed. A song is
    either written out or it is not, and that is easier to get right — and
    easier to check — one song at a time.

    The TEXT lives in Langfuse under `generate/lesson-material`. It was built
    here in Python, which made it the one prompt in the system that could not
    be read or improved without a deploy — and it is the station whose output a
    child hears verbatim. The assembly stays here because it is per directive;
    only the words are editable.
    """
    from . import material_form
    from .langfuse_context import langfuse_context_service

    template = langfuse_context_service.get_agent_prompt(AGENT)
    minutes = f" ({directive.minutes} minutes)" if directive.minutes else ""
    outcomes = "\n".join(f"- {s}" for s in slos) if slos else "- (no outcome recorded)"

    for slot, value in (
        ("sub_strand", sub_strand),
        ("module_number", str(directive.module_number)),
        ("module_title", directive.module_title),
        ("topic", directive.topic),
        ("minutes", minutes),
        ("instruction", directive.instruction),
        ("level_register", register),
        # What SHAPE the page takes, which the register alone never said. A
        # Grade 9 learner reads a textbook page; a PP1 child is read to.
        ("material_form", material_form.block_for(grade)),
        ("notation", notation),
        ("target_language", target_language),
        ("language_block", language),
        ("faith_scope", faith),
        ("slos", outcomes),
        ("forms", ", ".join(FORMS)),
    ):
        template = template.replace("{{ " + slot + " }}", value or "")
    return template


@dataclass(slots=True)
class MaterialReport:
    total: int = 0
    written: int = 0
    thin: list[dict[str, Any]] = field(default_factory=list)
    echoed: list[dict[str, Any]] = field(default_factory=list)
    # Written to an older learner as if to an infant.
    infantilised: list[dict[str, Any]] = field(default_factory=list)
    # A language lesson scripted in English.
    unscripted: list[dict[str, Any]] = field(default_factory=list)
    # A page for a reader that opens by announcing the lesson — "Today, we are
    # going to explore..." — in every section.
    announced: list[dict[str, Any]] = field(default_factory=list)
    # A page that scripts a class discussion, inventing the learners' replies.
    staged: list[dict[str, Any]] = field(default_factory=list)
    # A lesson that gives the learner nothing to work. Counted per LESSON, so
    # it is reported separately from the per-piece findings above.
    unexercised: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (not self.thin and not self.echoed and not self.infantilised
                and not self.unscripted and not self.announced
                and not self.staged and not self.unexercised
                and self.written == self.total)

    @property
    def score(self) -> float:
        if not self.total:
            return 100.0
        # `unexercised` is per lesson, not per piece, so it is not subtracted
        # from a piece count. It is a gate condition instead — see gate_of.
        good = (self.total - len(self.thin) - len(self.echoed)
                - len(self.infantilised) - len(self.unscripted)
                - len(self.announced) - len(self.staged))
        return round(max(0.0, good) / self.total * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "written": self.written,
                "thin": self.thin, "echoed": self.echoed,
                "infantilised": self.infantilised,
                "unscripted": self.unscripted,
                "announced": self.announced,
                "staged": self.staged,
                "unexercised": self.unexercised,
                "clean": self.clean, "score": self.score}


# What this station has to reach before its output moves on. Lower than the
# plan's gate on purpose: the plan is judged on whether a teacher could teach
# from it, and the material on whether each instruction actually got words.
PASS_SCORE = 90.0


def gate_of(report: "MaterialReport") -> dict[str, Any]:
    """The material check, in the shape every other station reports.

    This station returned its findings under `coverage` and no `quality_gate`
    at all — so the review loop, which reads `quality_gate`, saw no score, no
    pass and nothing to act on. It filed a run that had fulfilled 21 of 21
    instructions at 95.2/100 as **0/100, not passed, "the gate failed but named
    nothing to fix"**, and stopped. The number the operator saw had no relation
    to the work.

    `next_actions` is the part that matters beyond the score: without it the
    loop has a failure it cannot regenerate against, which is the same call
    again at the same price.
    """
    # `unexercised` is a gate condition rather than a score penalty: it is
    # counted per lesson, and a Grade 9 page with no practice on it fails
    # whatever the per-piece score says.
    passed = (report.score >= PASS_SCORE and report.written == report.total
              and not report.unexercised)

    feedback = [
        {"aspect": "instructions_fulfilled", "method": "written_vs_asked",
         "status": "pass" if report.written == report.total else "fail",
         "score": round(report.written / report.total, 4) if report.total else 1.0,
         "comment": f"{report.written} of {report.total} instruction(s) got material"},
        {"aspect": "substance", "method": "length_vs_floor",
         "status": "fail" if report.thin else "pass",
         "score": round(1 - len(report.thin) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.thin)} too short to use"
                    if report.thin else "every piece has substance"},
        {"aspect": "register", "method": "nursery_phrases_above_lower_primary",
         "status": "fail" if report.infantilised else "pass",
         "score": round(1 - len(report.infantilised) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.infantilised)} written to this learner as an infant"
                    if report.infantilised else "written at the right age"},
        {"aspect": "target_language", "method": "script_present_per_piece",
         "status": "fail" if report.unscripted else "pass",
         "score": round(1 - len(report.unscripted) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.unscripted)} scripted in English only"
                    if report.unscripted else "the language is in the script"},
        {"aspect": "form", "method": "opening_announces_the_lesson",
         "status": "fail" if report.announced else "pass",
         "score": round(1 - len(report.announced) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.announced)} of {report.total} open by announcing the lesson"
                    if report.announced else "no section announces itself"},
        {"aspect": "page_not_transcript", "method": "invented_learner_replies",
         "status": "fail" if report.staged else "pass",
         "score": round(1 - len(report.staged) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.staged)} script a class discussion onto the page"
                    if report.staged else "written as a page, not a transcript"},
        {"aspect": "practice", "method": "numbered_questions_per_lesson",
         "status": "fail" if report.unexercised else "pass",
         "score": 0.0 if report.unexercised else 1.0,
         "comment": f"{len(report.unexercised)} lesson(s) give the learner nothing to work"
                    if report.unexercised else "every lesson has practice"},
        {"aspect": "not_an_echo", "method": "overlap_with_the_instruction",
         "status": "fail" if report.echoed else "pass",
         "score": round(1 - len(report.echoed) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.echoed)} handed the instruction back"
                    if report.echoed else "nothing echoed the instruction"},
    ]

    # Named per piece, so a regeneration knows WHICH song to write rather than
    # being told the average was low.
    actions = []
    for item in report.echoed[:4]:
        actions.append(
            f"\"{item.get('title') or item.get('directive') or 'One piece'}\" gave the "
            f"instruction back instead of the words. Write the thing itself — "
            f"the actual verse, the actual sentences the teacher says aloud."
        )
    for item in report.unscripted[:4]:
        actions.append(
            f"\"{item.get('title') or 'One piece'}\" asks the learners to speak "
            f"and gives them English. Write every phrase they say in "
            f"{item.get('language')}, with a transliteration and its meaning — "
            f"a learner repeating \"My name is\" in English is learning nothing."
        )
    for item in report.infantilised[:4]:
        actions.append(
            f"\"{item.get('title') or 'One piece'}\" is written to an infant: "
            f"{', '.join(item.get('phrases') or [])}. This learner is not four. "
            f"Address them as the register says — 'learners', not 'children' — "
            f"and drop the praise after every turn."
        )
    for item in report.announced[:3]:
        actions.append(
            f"\"{item.get('topic') or 'One section'}\" opens by announcing the "
            f"lesson: \"{(item.get('opening') or '')[:60]}…\". A textbook page "
            f"states the thing; it does not say it is about to. Begin with the "
            f"heading and the definition."
        )
    for item in report.staged[:3]:
        actions.append(
            f"\"{item.get('topic') or 'One section'}\" scripts a class "
            f"discussion and invents the learners' answers. This is a page they "
            f"read on their own — cut the questions to the room and the replies "
            f"nobody gave."
        )
    for item in report.unexercised[:3]:
        actions.append(
            f"Lesson {item.get('lesson')} gives the learner nothing to work: "
            f"{item.get('numbered_questions', 0)} numbered questions. Add an "
            f"exercise set of at least five, the later ones harder than the first."
        )
    for item in report.thin[:4]:
        actions.append(
            f"\"{item.get('title') or item.get('directive') or 'One piece'}\" is "
            f"{item.get('chars', 'too few')} characters — too short to use as it "
            f"stands. Write it in full."
        )
    if report.written < report.total:
        actions.append(
            f"{report.total - report.written} instruction(s) got no material at all. "
            f"Every directive the plan gives needs its own piece."
        )

    return {
        "passed": passed,
        "overall_score": int(round(report.score)),
        "layer_name": "material",
        "summary_message": (
            f"Material gate {'passed' if passed else 'not passed'} at "
            f"{report.score}/100. {report.written} of {report.total} instruction(s) "
            f"fulfilled"
            + (f", {len(report.thin)} thin" if report.thin else "")
            + (f", {len(report.echoed)} echoed" if report.echoed else "")
            + (f", {len(report.infantilised)} at the wrong register"
               if report.infantilised else "")
            + (f", {len(report.unscripted)} in English only"
               if report.unscripted else "")
            + "."
        ),
        "reviewer": {"score": int(round(report.score)), "passed": passed,
                     "status": "approved" if passed else "revise",
                     "feedback": feedback, "risk_flags": []},
        "next_actions": actions,
    }


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"\s+", " ", str(text)).lower()).strip()


# Nursery register, and the grades it is wrong for. Not a style preference:
# a Grade 6 Arabic lesson came back saying "Wonderful! Fantastic! Great job,
# everyone!" after every turn, and telling the teacher what "the children" do.
# An eleven-year-old reads that as being talked down to, and the teacher
# reading it aloud has to rewrite it in front of the class.
_NURSERY = (
    "boys and girls", "the children", "children,", "little ones", "kiddies",
    "wonderful!", "fantastic!", "excellent!", "well done, everyone",
    "great job, everyone", "good job, everyone", "let's all say",
    "clap your hands", "everybody clap",
)

# Below this, that register is right rather than wrong.
_YOUNG = ("grade-pp1", "grade-pp2", "grade-1", "grade-2", "grade-3")


def nursery_register(material: dict[str, Any], grade: str) -> list[dict[str, Any]]:
    """Where an older learner is written to as an infant.

    Checked mechanically because the prompt alone does not hold it: the model
    has one warm classroom voice and reaches for it whenever the subject is a
    language or a song, whatever the grade says.
    """
    from .grade_order import normalize_grade

    if normalize_grade(grade) in _YOUNG:
        return []

    found: list[dict[str, Any]] = []
    for piece in (material.get("material") or []):
        if not isinstance(piece, dict):
            continue
        spoken = f"{piece.get('say') or ''} {piece.get('learner_does') or ''}".lower()
        hits = sorted({phrase for phrase in _NURSERY if phrase in spoken})
        if hits:
            found.append({
                "title": str(piece.get("title") or piece.get("topic") or "One piece"),
                "module_number": piece.get("module_number"),
                "phrases": hits[:5],
            })
    return found


def unscripted_language(material: dict[str, Any], subject: str) -> list[dict[str, Any]]:
    """Pieces of a language lesson that carry none of the language.

    Per piece, not per document: one lesson came back with 'أ' (alif) in its
    first part and, three parts later, "The first phrase is 'My name is...'.
    Now, say it with me: 'My name is...'" — the learners repeat English. A
    document-level check passes that, because the script IS there somewhere.

    Only where the script is not Latin. A French lesson written entirely in
    English looks, to a pattern, exactly like a French lesson — that one the
    prompt has to carry, and it is reported as unmeasured rather than passed.
    """
    from .target_language import for_subject, scripted

    language = for_subject(subject)
    if language is None or not language.pattern:
        return []

    out: list[dict[str, Any]] = []
    for piece in (material.get("material") or []):
        if not isinstance(piece, dict):
            continue
        said = str(piece.get("say") or "")
        if said.strip() and not scripted(said, subject):
            out.append({
                "title": str(piece.get("title") or piece.get("topic") or "One piece"),
                "module_number": piece.get("module_number"),
                "language": language.name,
            })
    return out


def check(material: dict[str, Any], plan: Plan, grade: str = "",
          subject: str = "") -> MaterialReport:
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
    # Checked over the whole set, not per directive: the voice is a
    # property of the writing, and one piece in the right register
    # beside three in the wrong one is still a lesson that lurches.
    report.infantilised = nursery_register(material, grade)
    report.unscripted = unscripted_language(material, subject)
    # The FORM the band calls for, which is not the same question as the
    # reading level. A Grade 9 page that announces itself in every section and
    # never asks the learner to work anything is pitched correctly and shaped
    # wrongly, and only these three notice that.
    report.announced = material_form.announced(material, grade)
    report.staged = material_form.staged(material, grade)
    report.unexercised = material_form.unexercised(material, grade)
    return report

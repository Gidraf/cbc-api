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
from .level_register import teacher_block

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
               domain: str = "", demand: str = "", elements: str = "",
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
        # Who READS this page. Everything above says who the learner is,
        # and a guide is written for a teacher — so a Grade 9 lesson
        # explained which key on a calculator is the minus sign.
        ("teacher_band", teacher_block(grade)),
        # What SHAPE the page takes, which the register alone never said. A
        # Grade 9 learner reads a textbook page; a PP1 child is read to.
        ("material_form", material_form.block_for(grade)),
        ("notation", notation),
        # What THIS subject needs that no other does — including how demanding
        # a maths item has to be at this grade. The station that writes the
        # worked examples was the one station receiving no domain block at all,
        # so the rule about difficulty reached every generator except the one
        # that produces the thing being judged.
        ("domain_directives", domain),
        # How demanding a worked example on this sub-strand has to be. This is
        # the station whose examples a reviewer opens first.
        ("demand_profile", demand),
        # Every element this sub-strand's design asks for, numbered, so the
        # piece can name which one it realises. Without it a guide can only
        # say "written here for this lesson", which is not provenance — it is
        # an admission that there is none.
        ("design_elements", elements),
        ("target_language", target_language),
        ("language_register", language),
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
    # Pieces that name nothing in the design they realise.
    unsourced: list[dict[str, Any]] = field(default_factory=list)
    # The same teaching, or the same task, delivered twice as though it were new.
    repeated: list[dict[str, Any]] = field(default_factory=list)
    # Questions the piece sets and never answers.
    unanswered: list[dict[str, Any]] = field(default_factory=list)
    # An answer the maths engine disagrees with.
    wrong_answers: list[dict[str, Any]] = field(default_factory=list)
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
    # Worked examples whose arithmetic is right and whose MODELLING is not: a
    # temperature falling from 5°C to -3°C written as 5 + (-3) = 2, a hiker
    # "climbing" from 200 m to 50 m, a rule stated for every case that fails on
    # the second case. The maths engine verified all three sums; the sentence
    # around each one was the fault, and nothing looked at it.
    miscast: list[dict[str, Any]] = field(default_factory=list)
    # Fields that came back holding the schema's own description of them —
    # a `form` reading "one of: explanation, story, ..." or a citation quoting
    # the prompt at a page number the prompt invented.
    echoed_schema: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (not self.thin and not self.echoed and not self.infantilised
                and not self.unscripted and not self.announced
                and not self.staged and not self.unexercised
                and not self.echoed_schema
                and self.written == self.total)

    @property
    def score(self) -> float:
        if not self.total:
            return 100.0
        # `unexercised` is per lesson, not per piece, so it is not subtracted
        # from a piece count. It is a gate condition instead — see gate_of.
        good = (self.total - len(self.thin) - len(self.echoed)
                - len(self.infantilised) - len(self.unscripted)
                - len(self.announced) - len(self.staged)
                - len(self.echoed_schema))
        return round(max(0.0, good) / self.total * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "written": self.written,
                "thin": self.thin, "echoed": self.echoed,
                "infantilised": self.infantilised,
                "unscripted": self.unscripted,
                "announced": self.announced,
                "staged": self.staged,
                "unexercised": self.unexercised,
                "echoed_schema": self.echoed_schema,
                "clean": self.clean, "score": self.score}


# What this station has to reach before its output moves on. Lower than the
# plan's gate on purpose: the plan is judged on whether a teacher could teach
# from it, and the material on whether each instruction actually got words.
PASS_SCORE = 90.0


def _check_exercises(piece: dict[str, Any], report: "MaterialReport") -> None:
    """Every question this piece sets, against the answer it gives for it."""
    from .notes_renderer import _numbered_items

    said = str(piece.get("say") or "")
    asked = _numbered_items(said)
    if not asked:
        for line in said.splitlines():
            asked += _numbered_items(line)

    exercises = [e for e in (piece.get("exercises") or []) if isinstance(e, dict)]
    answered = [e for e in exercises if str(e.get("answer") or "").strip()]
    where = {"lesson": piece.get("module_number"),
             "topic": piece.get("title") or piece.get("topic") or ""}

    if asked and len(answered) < len(asked):
        report.unanswered.append({
            **where, "asked": len(asked), "answered": len(answered),
            "first_unanswered": asked[len(answered)][:160] if
            len(answered) < len(asked) else "",
        })

    # And the ones that ARE answered, against the engine. A marking key nobody
    # checked is a marking key that teaches the mistake to every learner who
    # marks their own work against it.
    from . import worked_solutions

    for index, exercise in enumerate(answered[:40], start=1):
        question = str(exercise.get("question") or "")
        answer = str(exercise.get("answer") or "")
        verdict = worked_solutions.check(question, answer)
        if verdict["checked"] and verdict["agrees"] is False:
            report.wrong_answers.append({
                **where, "number": index, "question": question[:160],
                "given": answer[:60], "engine": verdict["engine_answer"][:60],
            })


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
              and not report.unexercised and not report.miscast
              and not report.unanswered and not report.wrong_answers
              and not report.repeated and not report.unsourced)

    feedback = [
        # The arithmetic being right is not the same as it answering the
        # question the words ask. A guide printed "the temperature drops from
        # 5°C to -3°C, so 5 + (-3) = 2" — a correct sum, and a fall of 8.
        {"aspect": "examples_model_what_they_describe",
         "method": "expression_against_its_own_wording",
         "status": "fail" if report.miscast else "pass",
         "score": 0.0 if report.miscast else 1.0,
         "comment": (f"{len(report.miscast)} worked example(s) do not compute "
                     f"what their words ask for"
                     if report.miscast else
                     "every worked example matches its own description")},
        # A quiz with no key. These notes are read by machine to build
        # question papers, so an unanswered question becomes an unanswerable
        # item on a paper somebody sits.
        # The second copy teaches nothing and takes the place of the lesson
        # that was funded.
        # These notes are not written from open ground. A piece that names
        # nothing in the design is a piece nobody can look up, defend or find
        # again — and it is the difference between a curriculum guide and an
        # essay about the subject.
        {"aspect": "every_piece_names_what_it_serves",
         "method": "serves_refs_against_the_design_s_own_elements",
         "status": "fail" if report.unsourced else "pass",
         "score": 0.0 if report.unsourced else 1.0,
         "comment": (f"{len(report.unsourced)} piece(s) name nothing in the "
                     f"design that they realise"
                     if report.unsourced else
                     "every piece names the design element it serves")},
        {"aspect": "nothing_is_taught_twice",
         "method": "every_lesson_and_every_task_against_every_other",
         "status": "fail" if report.repeated else "pass",
         "score": 0.0 if report.repeated else 1.0,
         "comment": (f"{len(report.repeated)} piece(s) of teaching or task(s) "
                     f"appear more than once"
                     if report.repeated else "nothing is taught twice")},
        {"aspect": "every_question_set_is_answered",
         "method": "questions_in_the_text_vs_answers_given",
         "status": "fail" if report.unanswered else "pass",
         "score": 0.0 if report.unanswered else 1.0,
         "comment": (
             f"{sum(u['asked'] - u['answered'] for u in report.unanswered)} "
             f"question(s) are set with no answer given"
             if report.unanswered else
             "every question this material sets has an answer")},
        # And a key nobody checked teaches its mistake to every learner who
        # marks their own work against it.
        {"aspect": "the_answers_given_are_right",
         "method": "answer_against_the_maths_engine",
         "status": "fail" if report.wrong_answers else "pass",
         "score": 0.0 if report.wrong_answers else 1.0,
         "comment": (f"{len(report.wrong_answers)} answer(s) the maths engine "
                     f"disagrees with"
                     if report.wrong_answers else
                     "every checkable answer agrees with the maths engine")},
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
        {"aspect": "own_words", "method": "schema_description_returned_as_value",
         "status": "fail" if report.echoed_schema else "pass",
         "score": round(1 - len(report.echoed_schema) / report.total, 4) if report.total else 1.0,
         "comment": f"{len(report.echoed_schema)} handed the schema's own wording back"
                    if report.echoed_schema else "no field echoed its own description"},
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
    # First, because it is the one a buyer notices and cannot forgive: a sum
    # that is arithmetically correct and answers a different question.
    for item in report.miscast[:5]:
        actions.append(f"{item.get('says')} {item.get('fix') or ''}".strip())
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
    for item in report.echoed_schema[:3]:
        actions.append(
            f"\"{item.get('topic') or 'One piece'}\" returned the schema's own "
            f"description instead of a value in: {', '.join(item.get('fields') or [])}. "
            f"`form` is one word. `citation.ref` is the page and line this content "
            f"actually came from, and `citation.quote` the design's words there — "
            f"leave both empty rather than copying the example."
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
    # Named before anything about length or register: a wrong marking key is
    # taught to every learner who marks their own work against it, and an
    # unanswered question becomes an unanswerable item on a paper.
    for item in report.unsourced[:4]:
        actions.append(
            f"Lesson {item.get('lesson')} \"{item.get('topic', '')}\" names no "
            f"design element. Put the ref(s) it realises in `serves` — "
            + (f"the design offers {item['available']}."
               if item.get("available") else
               "or say plainly that the design funds nothing here."))
    for item in report.repeated[:4]:
        if item.get("kind") == "lesson":
            actions.append(
                "Two lessons are substantially the same teaching. Write the "
                "second one, or merge them and give the freed time back.")
        else:
            actions.append(
                f"The {item['kind']} \"{item.get('task', '')}\" is set in "
                f"{item.get('where')} and was already set in "
                f"{item.get('first_seen')}. Replace it — a learner meeting it "
                f"twice is taught nothing the second time.")
    for item in report.wrong_answers[:4]:
        actions.append(
            f"Lesson {item.get('lesson')}: the answer given for \""
            f"{item.get('question', '')}\" is {item.get('given')}, and the "
            f"maths engine makes it {item.get('engine')}. Work it again."
        )
    for item in report.unanswered[:4]:
        actions.append(
            f"Lesson {item.get('lesson')} sets {item.get('asked')} question(s) "
            f"and answers {item.get('answered')} of them. Put every question in "
            f"`exercises` with its answer — starting with \""
            f"{item.get('first_unanswered', '')}\"."
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
          subject: str = "", strand: str = "", sub_strand: str = "") -> MaterialReport:
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

    # The worked examples, against the words around their arithmetic.
    try:
        from . import example_check

        for finding in example_check.check_material(
                material, grade=grade, subject=subject, strand=strand,
                sub_strand=sub_strand).findings:
            report.miscast.append(finding.to_dict())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not check the worked examples: %s", exc)

    # Anything the material SETS, it must answer — and the answers it gives
    # are checked. These notes are read by machine to build question papers, so
    # an unanswered question becomes an unanswerable item on a paper somebody
    # sits, and a wrong answer becomes a wrong marking key.
    for piece in pieces:
        if isinstance(piece, dict):
            _check_exercises(piece, report)
    report.repeated = check_repetition(material)
    report.unsourced = check_provenance(material, grade, subject, sub_strand,
                                        strand)

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
    from . import placeholder_echo

    report.echoed_schema = placeholder_echo.scan(material)
    report.announced = material_form.announced(material, grade)
    report.staged = material_form.staged(material, grade)
    report.unexercised = material_form.unexercised(material, grade)
    return report


def repair_examples(material: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace every wrong worked example's arithmetic with the engine's.

    Done BEFORE the material is filed, not at render time, because these notes
    are read by machine to build question papers — a wrong example corrected
    only on the page is still wrong in the data every downstream station reads.
    """
    from . import worked_solutions

    repaired: list[dict[str, Any]] = []
    for piece in (material.get("material") or []):
        if not isinstance(piece, dict):
            continue
        examples = piece.get("worked_examples")
        if not isinstance(examples, list):
            continue
        out = []
        for index, example in enumerate(examples, start=1):
            if not isinstance(example, dict):
                out.append(example)
                continue
            fixed, why = worked_solutions.rebuild(example)
            out.append(fixed)
            if why:
                repaired.append({"lesson": piece.get("module_number"),
                                 "topic": piece.get("title") or "",
                                 "example": index, "why": why})
        piece["worked_examples"] = out
    return repaired


_OPERATOR = re.compile(r"[+×÷*/]|(?<=\d)\s*-\s*(?=\d|\()")


def _norm_task(text: str) -> str:
    """A task reduced to what makes it that task.

    Where there is arithmetic, the ARITHMETIC is the task: "Evaluate 5 + 3 × 2
    - 4" and "Work out: 5+3*2-4." are the same question with different words in
    front, and a guide that varies its wording every lesson while setting the
    identical sums has still set the identical sums.

    Where there is none — a word problem, a discussion prompt — the words are
    all there is, so they are compared instead. Stripping them too would make
    "a hiker descends 300 m then ascends 150 m" and "a trader buys 300 at 150"
    the same task, which they are not.
    """
    raw = str(text or "").lower().replace("×", "*").replace("÷", "/")
    if _OPERATOR.search(raw):
        return re.sub(r"[^0-9+\-*/()=.]", "", raw).strip(".")
    return re.sub(r"[^a-z0-9]", "", raw)


def check_repetition(material: dict[str, Any]) -> list[dict[str, Any]]:
    """The same teaching, or the same task, delivered twice as new.

    Two passes, because they catch different things. `redundancy_check`
    compares whole pieces as prose and finds a lesson padded out of another
    one; this also compares the individual TASKS, because a guide can vary its
    wording in every lesson and still set the identical three exercises in all
    six — which is what one Grade 9 guide did, alongside working one expression
    sixteen times.

    A reader meets all of it. The second copy teaches nothing and takes the
    place of the lesson that was funded.
    """
    from . import redundancy_check

    found: list[dict[str, Any]] = []
    try:
        report = redundancy_check.inspect(material)
        for group in (report.get("near_duplicates") or []):
            found.append({"kind": "lesson", "detail": group})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not measure repetition: %s", exc)

    # Every task in the guide, wherever it is set, against every other.
    seen: dict[str, str] = {}
    for piece in (material.get("material") or []):
        if not isinstance(piece, dict):
            continue
        where = f"lesson {piece.get('module_number')}"
        tasks: list[tuple[str, str]] = []
        for exercise in (piece.get("exercises") or []):
            if isinstance(exercise, dict):
                tasks.append(("exercise", str(exercise.get("question") or "")))
        for example in (piece.get("worked_examples") or []):
            if isinstance(example, dict):
                tasks.append(("worked example", str(example.get("statement") or "")))
        for kind, text in tasks:
            key = _norm_task(text)
            if len(key) < 6:
                continue
            if key in seen and seen[key] != where:
                found.append({"kind": kind, "where": where,
                              "first_seen": seen[key], "task": text[:120]})
            else:
                seen.setdefault(key, where)
    return found


def check_provenance(material: dict[str, Any], grade: str, subject: str,
                     sub_strand: str, strand: str = "") -> list[dict[str, Any]]:
    """Every piece, against the design elements it claims to realise.

    A guide that says "Not quoted from the design — written here for this
    lesson" under every piece has told the reader there is no provenance. That
    is not what a curriculum guide is: the notes exist because the design asks
    for something, and naming which thing is what makes a page findable in the
    Grade design and in the BECF a term later.

    An invented ref is worse than none and is discarded rather than reported as
    provenance, for the same reason it is discarded on a question.
    """
    from . import design_elements

    row = _design_row(grade, subject, sub_strand, strand)
    if not row:
        # Nothing to check against. Silence rather than failing every piece for
        # a design this system has not read.
        return []
    available = design_elements.refs(row)
    if not available:
        return []

    out: list[dict[str, Any]] = []
    for piece in (material.get("material") or []):
        if not isinstance(piece, dict):
            continue
        kept, invented = design_elements.valid_serves(piece.get("serves"), row)
        if kept:
            continue
        out.append({
            "lesson": piece.get("module_number"),
            "topic": piece.get("title") or piece.get("topic") or "",
            "invented": invented,
            "available": ", ".join(sorted(available)[:6]),
        })
    return out


def _design_row(grade: str, subject: str, sub_strand: str,
                strand: str = "") -> dict[str, Any]:
    from ..infra.db import fetch_one

    from .grade_sql import clause

    try:
        return fetch_one(
            f"""
            SELECT slos, key_inquiry_questions, learning_experiences,
                   core_competencies, values, required_diagrams, experiments
            FROM curriculum_substrands
            WHERE {clause('grade')}
              AND LOWER(subject) = LOWER(:subject)
              AND LOWER(sub_strand_name) = LOWER(:sub_strand)
            LIMIT 1
            """,
            {"grade": grade, "subject": subject, "sub_strand": sub_strand},
        ) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("No design row for %s (%s)", sub_strand, exc)
        return {}

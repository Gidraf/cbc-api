"""How demanding THIS sub-strand's tasks must be, read out of its own design.

The floors in `task_demand` and `command_words` are bands: three numeric floors
across Grades 4-12, four command-word floors across the whole of basic
education. They are honest as far as they go, and they do not go far. Grade 7
and Grade 9 share one floor because inventing a difference between them would
have been inventing a syllabus, and a fabricated rule reads exactly like a real
one.

The design documents already contain the difference. A sub-strand's own
outcomes are written in command words, its assessment rubric separates
performance levels in those same words, and its allocated hours say how much
work is expected of it. So the profile is EXTRACTED rather than authored: an
agent reads the sub-strand's outcomes, rubric and hours and states what a task
at that level has to be.

WHAT KEEPS IT HONEST. A generated profile is not trusted because a model
produced it. It is validated:

  * every rung it names must exist on the ladder — a model that invents a
    seventh level of Bloom is refused rather than stored;
  * it must cite the design text it came from, so a profile that is a
    recollection of the subject rather than a reading of the design is visible;
  * its own worked exemplar must CLEAR the floor the profile itself states.
    A profile demanding an evaluation and illustrating it with a list has
    described one thing and shown another, and the exemplar is what a
    generator will actually imitate.

WHERE THERE IS NO PROFILE the band floors apply unchanged. A sub-strand nobody
has extracted yet is measured less precisely, never waved through.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from . import command_words, task_demand

logger = logging.getLogger("cbc-demand-profile")

AGENT = "demand-profile"

# The most a share can be off by and still be called a distribution. Models
# round; 0.34 + 0.33 + 0.33 is a correct answer written by a careful one.
_SHARE_TOLERANCE = 0.06


@dataclass
class Rungshare:
    rank: int
    share: float

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "share": round(self.share, 3),
                "name": _rung_name(self.rank)}


def _rung_name(rank: int) -> str:
    for rung in command_words.LADDER:
        if rung.rank == rank:
            return rung.name
    return str(rank)


@dataclass
class Profile:
    """What a task on this sub-strand has to be."""

    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    lesson_hours: str = ""
    # The command-word floor, and how the set should spread across the ladder.
    top: int = 0
    distinct: int = 1
    mix: list[Rungshare] = field(default_factory=list)
    # The arithmetic floor, for a subject that has one.
    operations: int = 0
    kinds: int = 0
    depth: int = 0
    # One item at the top of the range, and its answer.
    exemplar_question: str = ""
    exemplar_answer: str = ""
    marks: str = ""
    # What in the design this was read out of. A profile with none of this is a
    # recollection of the subject rather than a reading of the design.
    because: str = ""
    design_quote: str = ""

    @property
    def numeric(self) -> bool:
        return bool(self.operations)

    def required(self) -> dict[str, Any]:
        """The shape `command_words.check_set` takes as an override."""
        return {"top": self.top, "distinct": self.distinct,
                "because": self.because, "level": ""}

    def floor(self) -> task_demand.Floor | None:
        """The shape `task_demand.shortfall` takes, where this subject has one."""
        if not self.numeric:
            return None
        return task_demand.Floor(
            level=f"{self.sub_strand or self.subject}",
            operations=self.operations, kinds=self.kinds, depth=self.depth,
            order_matters=self.kinds >= 2,
            exemplar=self.exemplar_question,
            because=self.because or "this sub-strand's own design",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade, "subject": self.subject, "strand": self.strand,
            "sub_strand": self.sub_strand, "lesson_hours": self.lesson_hours,
            "top": self.top, "top_name": _rung_name(self.top),
            "distinct": self.distinct, "mix": [m.to_dict() for m in self.mix],
            "operations": self.operations, "kinds": self.kinds, "depth": self.depth,
            "numeric": self.numeric,
            "exemplar_question": self.exemplar_question,
            "exemplar_answer": self.exemplar_answer,
            "marks": self.marks, "because": self.because,
            "design_quote": self.design_quote,
        }


# ── validation ───────────────────────────────────────────────────────────────


_RANKS = {rung.rank for rung in command_words.LADDER}


def validate(raw: Any, *, grade: str = "", subject: str = "",
             strand: str = "", sub_strand: str = "",
             lesson_hours: str = "") -> tuple[Profile | None, list[str]]:
    """A generated profile, or the reasons it was refused.

    Refusing is the point. A profile is consulted by every station afterwards,
    so a wrong one is wrong everywhere and quietly — which is worse than having
    none, because the band floor that would have caught the problem has been
    replaced by a fabricated one that does not.
    """
    problems: list[str] = []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None, ["the profile did not come back as JSON"]
    if not isinstance(raw, dict):
        return None, ["the profile did not come back as an object"]

    top = raw.get("top") or raw.get("top_rank")
    try:
        top = int(top)
    except (TypeError, ValueError):
        return None, ["no `top` rung was given, so there is no floor to apply"]
    if top not in _RANKS:
        return None, [f"rung {top} is not on the ladder — it has "
                      f"{min(_RANKS)} to {max(_RANKS)}"]

    mix: list[Rungshare] = []
    for entry in (raw.get("mix") or []):
        if not isinstance(entry, dict):
            continue
        try:
            rank, share = int(entry.get("rank")), float(entry.get("share"))
        except (TypeError, ValueError):
            problems.append("a mix entry had no rank or no share")
            continue
        if rank not in _RANKS:
            problems.append(f"the mix names rung {rank}, which is not on the ladder")
            continue
        mix.append(Rungshare(rank=rank, share=share))

    if mix:
        total = sum(m.share for m in mix)
        if abs(total - 1.0) > _SHARE_TOLERANCE:
            problems.append(f"the mix shares add up to {total:.2f}, not 1.0")
        if max(m.rank for m in mix) < top:
            problems.append(
                f"the mix never reaches rung {top}, which the profile itself "
                f"says is the floor")

    because = str(raw.get("because") or "").strip()
    quote = str(raw.get("design_quote") or raw.get("quote") or "").strip()
    if not quote:
        problems.append(
            "no design text was quoted, so this is a recollection of the "
            "subject rather than a reading of the design")

    profile = Profile(
        grade=grade or str(raw.get("grade") or ""),
        subject=subject or str(raw.get("subject") or ""),
        strand=strand or str(raw.get("strand") or ""),
        sub_strand=sub_strand or str(raw.get("sub_strand") or ""),
        lesson_hours=lesson_hours or str(raw.get("lesson_hours") or ""),
        top=top,
        distinct=max(1, int(raw.get("distinct") or 1)),
        mix=mix,
        operations=max(0, int(raw.get("operations") or 0)),
        kinds=max(0, int(raw.get("kinds") or 0)),
        depth=max(0, int(raw.get("depth") or 0)),
        exemplar_question=str(raw.get("exemplar_question") or "").strip(),
        exemplar_answer=str(raw.get("exemplar_answer") or "").strip(),
        marks=str(raw.get("marks") or "").strip(),
        because=because, design_quote=quote,
    )

    problems += _exemplar_problems(profile)
    return (None, problems) if problems else (profile, [])


def _exemplar_problems(profile: Profile) -> list[str]:
    """Whether the profile's own worked example clears the floor it states.

    This is the check that matters. A generator imitates the exemplar, not the
    numbers beside it, so a profile demanding an evaluation and illustrating it
    with a list has told every station downstream to write lists.
    """
    problems: list[str] = []
    if not profile.exemplar_question:
        return ["no exemplar question was given, and the exemplar is what a "
                "generator actually imitates"]
    if not profile.exemplar_answer:
        problems.append("the exemplar has no answer, so nobody can see whether "
                        "it is answerable at this level")

    rung = command_words.rung_of(profile.exemplar_question)
    if rung is None:
        problems.append("the exemplar question has no command word in it")
    elif rung.rank < profile.top:
        problems.append(
            f"the exemplar asks only for \"{rung.name}\" while the profile "
            f"sets the floor at \"{_rung_name(profile.top)}\"")

    if profile.numeric:
        item = {"statement": profile.exemplar_question,
                "steps": [{"working": profile.exemplar_answer}]}
        short = task_demand.shortfall(task_demand.measure_item(item),
                                      profile.floor())
        if short.below:
            problems.append("the exemplar does not meet the arithmetic floor "
                            "the profile states: " + "; ".join(short.misses))
    return problems


# ── the prompt block ─────────────────────────────────────────────────────────


def block_for(grade: str | None, subject: str = "",
              profile: Profile | None = None) -> str:
    """What every authoring station is told about how demanding to be.

    One block, so there is one place to change it, and it is RENDERED from the
    same tables the gates measure against. A generator told one thing and
    judged by another is held for doing as it was told.
    """
    parts = [command_words.block_for(grade)]

    floor = task_demand.floor_for(grade, subject or None)
    if floor:
        from .prompt_store import render

        shapes = "\n".join(f"  {e}" for e in (floor.exemplar, *floor.also))
        parts.append(render(
            "arithmetic-floor", _ARITHMETIC_BLOCK,
            operations=floor.operations, kinds=floor.kinds,
            because=f"{floor.because[0].upper()}{floor.because[1:]}",
            shapes=shapes))

    if profile:
        parts.append(_profile_block(profile))
    return "\n\n".join(p for p in parts if p and p.strip())


_ARITHMETIC_BLOCK = """=== HOW HARD THE ARITHMETIC HAS TO BE ===
At least {{ operations }} operations of at least {{ kinds }} different kinds, with brackets or a fraction bar deciding the order. {{ because }}.

These are all AT that level. They share a difficulty and share no numbers:
{{ shapes }}

DO NOT USE ANY OF THEM. They are here to show you the LEVEL, not the question. A guide that copied the first one worked it in sixteen examples across six lessons, which is one example and five wasted lessons. Write your own, at that difficulty, different in every lesson.

An easy opener is fine. A set whose HARDEST item is one operation has not reached the grade anywhere."""

_PROFILE_BLOCK = """=== THIS SUB-STRAND'S OWN DEMAND, FROM ITS DESIGN ===
Sub-strand: {{ sub_strand }}{{ hours }}
Highest command word required: {{ top_name }}.
Spread the set across at least {{ distinct }} rungs: {{ mix }}.
{{ extras }}
ONE TASK AT THE TOP OF THE RANGE, AND ITS ANSWER — write to this standard, do not copy it:
  Q: {{ exemplar_question }}
  A: {{ exemplar_answer }}"""


def seed_prompts() -> dict[str, str]:
    return {"arithmetic-floor": _ARITHMETIC_BLOCK,
            "profile-demand": _PROFILE_BLOCK,
            "batch-plan": _BATCH_BLOCK}


def _profile_block(profile: Profile) -> str:
    from .prompt_store import render

    mix = ", ".join(f"{_rung_name(m.rank)} {round(m.share * 100)}%"
                    for m in profile.mix) or "not stated"
    extras: list[str] = []
    if profile.numeric:
        extras.append(f"Arithmetic: at least {profile.operations} operations of "
                      f"{profile.kinds} kinds, bracket depth {profile.depth}.")
    if profile.marks:
        extras.append(f"Marks a task at the top of this range carries: "
                      f"{profile.marks}.")
    if profile.because:
        extras.append(f"Why: {profile.because}")
    if profile.design_quote:
        extras.append(f"The design's own words: \"{profile.design_quote}\"")
    return render(
        "profile-demand", _PROFILE_BLOCK,
        sub_strand=profile.sub_strand or "(unnamed)",
        hours=f"  ({profile.lesson_hours})" if profile.lesson_hours else "",
        top_name=_rung_name(profile.top), distinct=profile.distinct, mix=mix,
        extras="\n".join(extras) + ("\n" if extras else ""),
        exemplar_question=profile.exemplar_question,
        exemplar_answer=profile.exemplar_answer)


# ── storage ──────────────────────────────────────────────────────────────────


def _profile_id(grade: str, subject: str, strand: str, sub_strand: str) -> str:
    import hashlib

    from .grade_order import normalize_grade

    key = "|".join((normalize_grade(grade), (subject or "").strip().lower(),
                    (strand or "").strip().lower(),
                    (sub_strand or "").strip().lower()))
    return "dp_" + hashlib.sha256(key.encode()).hexdigest()[:16]


def save(profile: Profile, *, model: str = "") -> str:
    """One profile per sub-strand, replaced on regeneration.

    Replaced rather than versioned: a second profile for the same sub-strand is
    not a second opinion, it is the same question answered again, and two of
    them means every station has to decide which one it believes.
    """
    from ..infra.db import execute

    profile_id = _profile_id(profile.grade, profile.subject, profile.strand,
                             profile.sub_strand)
    execute(
        """
        INSERT INTO demand_profiles (
            profile_id, grade, subject, strand, sub_strand, lesson_hours,
            top, distinct_rungs, mix, operations, kinds, depth,
            exemplar_question, exemplar_answer, marks, because, design_quote,
            model)
        VALUES (
            :profile_id, :grade, :subject, :strand, :sub_strand, :lesson_hours,
            :top, :distinct_rungs, CAST(:mix AS JSONB), :operations, :kinds,
            :depth, :exemplar_question, :exemplar_answer, :marks, :because,
            :design_quote, :model)
        ON CONFLICT (grade, subject, strand, sub_strand) DO UPDATE SET
            lesson_hours = EXCLUDED.lesson_hours,
            top = EXCLUDED.top,
            distinct_rungs = EXCLUDED.distinct_rungs,
            mix = EXCLUDED.mix,
            operations = EXCLUDED.operations,
            kinds = EXCLUDED.kinds,
            depth = EXCLUDED.depth,
            exemplar_question = EXCLUDED.exemplar_question,
            exemplar_answer = EXCLUDED.exemplar_answer,
            marks = EXCLUDED.marks,
            because = EXCLUDED.because,
            design_quote = EXCLUDED.design_quote,
            model = EXCLUDED.model,
            updated_at = NOW()
        """,
        {"profile_id": profile_id, "grade": profile.grade,
         "subject": profile.subject, "strand": profile.strand,
         "sub_strand": profile.sub_strand, "lesson_hours": profile.lesson_hours,
         "top": profile.top, "distinct_rungs": profile.distinct,
         "mix": json.dumps([m.to_dict() for m in profile.mix]),
         "operations": profile.operations, "kinds": profile.kinds,
         "depth": profile.depth,
         "exemplar_question": profile.exemplar_question,
         "exemplar_answer": profile.exemplar_answer, "marks": profile.marks,
         "because": profile.because, "design_quote": profile.design_quote,
         "model": model},
    )
    return profile_id


def _from_row(row: dict[str, Any]) -> Profile:
    mix_raw = row.get("mix")
    if isinstance(mix_raw, str):
        try:
            mix_raw = json.loads(mix_raw)
        except ValueError:
            mix_raw = []
    return Profile(
        grade=row.get("grade") or "", subject=row.get("subject") or "",
        strand=row.get("strand") or "", sub_strand=row.get("sub_strand") or "",
        lesson_hours=row.get("lesson_hours") or "",
        top=int(row.get("top") or 0),
        distinct=int(row.get("distinct_rungs") or 1),
        mix=[Rungshare(rank=int(m.get("rank")), share=float(m.get("share")))
             for m in (mix_raw or []) if isinstance(m, dict)
             and m.get("rank") is not None and m.get("share") is not None],
        operations=int(row.get("operations") or 0),
        kinds=int(row.get("kinds") or 0), depth=int(row.get("depth") or 0),
        exemplar_question=row.get("exemplar_question") or "",
        exemplar_answer=row.get("exemplar_answer") or "",
        marks=row.get("marks") or "", because=row.get("because") or "",
        design_quote=row.get("design_quote") or "",
    )


def load(grade: str, subject: str, strand: str = "",
         sub_strand: str = "") -> Profile | None:
    """The stored profile for this scope, or None.

    None is not a failure. A sub-strand nobody has extracted yet falls back to
    the band floor, which is less precise and still a floor.
    """
    from ..infra.db import fetch_one

    from .grade_sql import clause

    try:
        row = fetch_one(
            f"""
            SELECT * FROM demand_profiles
            WHERE {clause('grade')}
              AND LOWER(subject) = LOWER(:subject)
              AND LOWER(sub_strand) = LOWER(:sub_strand)
              AND (:strand = '' OR LOWER(strand) = LOWER(:strand))
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"grade": grade, "subject": subject, "strand": strand or "",
             "sub_strand": sub_strand or ""},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the demand profile for %s/%s: %s",
                       subject, sub_strand, exc)
        return None
    return _from_row(row) if row else None


def listing(grade: str = "", subject: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """Every profile in a scope, for a console that shows what has been read."""
    from ..infra.db import fetch_all

    from .grade_sql import clause

    where, params = ["1=1"], {"limit": limit}
    if grade:
        where.append(clause("grade"))
        params["grade"] = grade
    if subject:
        where.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject
    try:
        rows = fetch_all(
            f"SELECT * FROM demand_profiles WHERE {' AND '.join(where)} "
            f"ORDER BY subject, strand, sub_strand LIMIT :limit", params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list demand profiles: %s", exc)
        return []
    return [_from_row(row).to_dict() for row in rows]


def plan_for(count: int, grade: str, profile: Profile | None) -> list[tuple[int, int]]:
    """How many of a batch of `count` sit on each rung.

    A number the generator can be held to. "Spread across the ladder" is
    advice; "four at understand, three at apply, three at analyse" is an
    instruction, and it is the instruction the gate then measures.

    From the sub-strand's own mix where there is one. Where there is not, the
    band floor is spread evenly from the floor's own top rung downwards — never
    below rung 1 and never above the ladder.
    """
    if count <= 0:
        return []
    if profile and profile.mix:
        shares = [(m.rank, m.share) for m in profile.mix]
    else:
        floor = command_words.floor_for(grade)
        if floor is None:
            return []
        ranks = list(range(max(1, floor.top - floor.distinct + 1), floor.top + 1))
        shares = [(r, 1 / len(ranks)) for r in ranks]

    # Largest remainder, so the parts add up to the whole. Rounding each share
    # on its own gives 9 or 11 questions for a batch of 10, and the batch count
    # is the one number the operator actually set.
    raw = [(rank, share * count) for rank, share in shares]
    out = [(rank, int(value)) for rank, value in raw]
    short = count - sum(n for _r, n in out)
    order = sorted(range(len(raw)), key=lambda i: -(raw[i][1] - int(raw[i][1])))
    for i in order[:short]:
        out[i] = (out[i][0], out[i][1] + 1)
    return [(rank, n) for rank, n in out if n]


def for_prompt(grade: str, subject: str, strand: str = "",
               sub_strand: str = "", count: int = 0,
               lesson_hours: str = "") -> str:
    """The block every authoring station is given. Never raises, never blank
    where a band floor exists — a station that cannot reach the database is
    told the band rule rather than nothing at all."""
    profile = None
    if sub_strand:
        try:
            profile = load(grade, subject, strand, sub_strand)
        except Exception as exc:  # noqa: BLE001
            logger.debug("No stored profile for %s/%s (%s)", subject, sub_strand, exc)

    block = block_for(grade, subject, profile)
    plan = plan_for(count, grade, profile)
    if plan:
        from .prompt_store import render

        rows = "\n".join(
            f"  - {n} at rung {rank} ({_rung_name(rank)}): "
            f"{', '.join(_verbs_for(rank))}" for rank, n in plan)
        hours = lesson_hours or (profile.lesson_hours if profile else "")
        block += "\n\n" + render(
            "batch-plan", _BATCH_BLOCK, count=count, rows=rows,
            hours=(f"The design funds {hours} for this sub-strand; the marks "
                   f"and the length of these items should fit that."
                   if hours else ""))
    return block


def _verbs_for(rank: int) -> list[str]:
    """House spellings only — the ladder recognises "analyze", it never
    suggests it."""
    for rung in command_words.LADDER:
        if rung.rank == rank:
            return command_words._suggestable(rung)
    return []


_BATCH_BLOCK = """=== WHAT THIS BATCH OF {{ count }} MUST CONTAIN ===
Not "a range of difficulty" — these counts:
{{ rows }}

Write the command word into the stem. A question that asks for an analysis without using an analysis verb is marked as though it asked for a description, because that is what the marker reads.
{{ hours }}"""


# ── generation ───────────────────────────────────────────────────────────────


def generate(*, grade: str, subject: str, strand: str = "", sub_strand: str,
             lesson_hours: str = "", design_extract: str = "",
             slos: list[Any] | None = None, rubrics: list[Any] | None = None,
             resolved: Any = None, store: bool = True
             ) -> tuple[Profile | None, list[str]]:
    """Read this sub-strand's design and state how demanding its tasks are.

    Returns the profile, or the reasons it was refused. A refusal is not an
    error to swallow: the sub-strand keeps the band floor, which is coarser and
    correct, and the reasons say what the next attempt has to fix.
    """
    from . import prompt_fragments
    from .langfuse_context import langfuse_context_service
    from .faith_scope import prompt_block as faith_block
    from .level_register import register_block, teacher_block
    from .notation import block_for as notation_block
    from .llm_client import llm_client

    if resolved is None:
        from .pipeline import pipeline_orchestrator

        resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")

    variables = {
        "grade": grade, "subject": subject, "strand": strand,
        "sub_strand": sub_strand,
        "lesson_hours": lesson_hours or "not stated in the design",
        "design_extract": (design_extract or "")[:20_000],
        "slos": json.dumps(slos or [], ensure_ascii=False, default=str),
        "rubrics": json.dumps(rubrics or [], ensure_ascii=False, default=str),
        "level_register": register_block(grade),
        "teacher_band": teacher_block(grade),
        "notation": notation_block(subject, grade=grade),
        "faith_scope": faith_block(subject),
        "domain_directives": prompt_fragments.compose(subject, "questions", grade),
        # The same ladder the gate measures against, rendered from the same
        # table. Two lists that mean to agree and are maintained apart do not.
        "command_ladder": command_words.block_for(grade),
    }
    template = langfuse_context_service.get_agent_prompt(AGENT)
    prompt = langfuse_context_service._render_template(template, variables)

    try:
        response = llm_client.generate(
            resolved, [{"role": "user", "content": prompt}], temperature=0.1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Demand profile for %s/%s failed: %s", subject, sub_strand, exc)
        return None, [f"the model call failed: {exc}"]

    profile, problems = validate(
        response.content, grade=grade, subject=subject, strand=strand,
        sub_strand=sub_strand, lesson_hours=lesson_hours)
    if profile is None:
        logger.info("Demand profile for %s/%s refused: %s",
                    subject, sub_strand, "; ".join(problems))
        return None, problems

    if store:
        try:
            save(profile, model=getattr(resolved, "model", ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store the demand profile for %s/%s: %s",
                           subject, sub_strand, exc)
            problems.append(f"generated but not stored: {exc}")
    return profile, problems


# ── the one judgement every station's gate asks for ──────────────────────────


@dataclass
class Judgement:
    """Whether a set of tasks is as demanding as its sub-strand requires.

    Two measures, because two things can be wrong independently: a set can be
    arithmetically demanding and ask only for recall (evaluate this expression,
    forty times), or ask for an evaluation of nothing harder than 7 - 4.
    """

    numeric: task_demand.SetReport = field(
        default_factory=task_demand.SetReport)
    command: command_words.Report = field(default_factory=command_words.Report)
    profile: Profile | None = None

    @property
    def below(self) -> bool:
        return self.numeric.below or self.command.below

    def says(self) -> str:
        return " ".join(s for s in (self.numeric.says(), self.command.says()) if s)

    def fix(self) -> str:
        return " ".join(s for s in (self.numeric.fix(), self.command.fix()) if s)

    def to_dict(self) -> dict[str, Any]:
        return {"below": self.below, "says": self.says(), "fix": self.fix(),
                "numeric": self.numeric.to_dict(),
                "command": self.command.to_dict(),
                "from_profile": self.profile is not None,
                "profile": self.profile.to_dict() if self.profile else None}


def judge(items: list[Any], *, grade: str, subject: str = "", strand: str = "",
          sub_strand: str = "") -> Judgement:
    """Every gate's question, answered in one place.

    The sub-strand's own profile is preferred where one has been extracted and
    the band floor applies where none has. Both are floors — the difference is
    how precisely the floor is known, never whether there is one.
    """
    profile = None
    if sub_strand:
        try:
            profile = load(grade, subject, strand, sub_strand)
        except Exception as exc:  # noqa: BLE001
            logger.debug("No stored profile for %s/%s (%s)", subject, sub_strand, exc)

    numeric = task_demand.check_set(items, grade, subject or None)
    if profile is not None and profile.numeric:
        floor = profile.floor()
        report = task_demand.SetReport(level=floor.level, floor=floor)
        hardest_short = None
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            demand = task_demand.measure_item(item)
            if not demand.measurable:
                continue
            report.measured += 1
            short = task_demand.shortfall(demand, floor)
            if not short.below:
                report.at_grade += 1
            if (demand.operations, demand.depth, len(demand.kinds)) > \
                    (report.hardest.operations, report.hardest.depth,
                     len(report.hardest.kinds)):
                report.hardest, hardest_short = demand, short
        report.shortfall = hardest_short
        numeric = report

    command = command_words.check_set(
        items, grade, required=profile.required() if profile else None)
    return Judgement(numeric=numeric, command=command, profile=profile)

"""What a learner at a given grade can actually do, stated for the generators.

Every authoring prompt in this system was written with one reader in mind: a
secondary-school agriculture student. The worked examples said "Kenyan
agriculture/industry", "farm plots", "local apparatus", "Flowchart of
Agricultural Economic Sectors in Kenya". Few-shot examples set the register, so
a pre-primary sub-strand on greetings came back demanding a flowchart for a
four-year-old who cannot read, and a mandatory audit of toxic-chemical handling
for a lesson about saying "good morning".

The register is not a style preference. It is a correctness constraint: content
pitched above the learner is content the learner cannot use, and a paper nobody
can sit is worth nothing. So it is derived from the grade rather than baked into
each prompt, and every generator is given the same block.

Sources are the KICD designs themselves: the Pre-Primary design states 30-minute
lessons (PP1 p.9) and organises Language Activities through themes (p.14-16);
DTE is a diploma for adult trainee teachers, not a school grade.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .grade_order import GRADE_SEQUENCE, grade_label, grade_level, normalize_grade


@dataclass(slots=True)
class LevelRegister:
    """The authoring constraints that follow from who the learner is."""

    level: str
    grade_label: str
    audience: str
    typical_ages: str
    literacy: str
    can: list[str] = field(default_factory=list)
    cannot: list[str] = field(default_factory=list)
    time_unit: str = "lessons"
    lesson_minutes: int = 0
    # KICD calls these "Activity Areas" / "learning areas" at pre-primary and
    # lower primary, and "subjects" from upper primary on. Using "subject" for
    # a four-year-old's Language Activities is not how the design speaks.
    area_noun: str = "subject"
    practicals: str = ""
    uses_themes: bool = False
    scenario_world: str = ""
    # A band is not a grade. Grade 1 and Grade 3 are both "Lower Primary", but
    # content pitched identically at both is wrong for one of them.
    year_in_level: str = ""
    builds_on: str = ""
    prepares_for: str = ""
    grade_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "grade": self.grade_label,
            "audience": self.audience,
            "typical_ages": self.typical_ages,
            "literacy": self.literacy,
            "can": list(self.can),
            "cannot": list(self.cannot),
            "time_unit": self.time_unit,
            "lesson_minutes": self.lesson_minutes,
            "area_noun": self.area_noun,
            "practicals": self.practicals,
            "uses_themes": self.uses_themes,
            "scenario_world": self.scenario_world,
            "year_in_level": self.year_in_level,
            "builds_on": self.builds_on,
            "prepares_for": self.prepares_for,
            "grade_notes": list(self.grade_notes),
        }

    def format_for_prompt(self) -> str:
        """The block injected into every authoring prompt."""
        lines = [
            f"AUDIENCE: {self.audience} — {self.grade_label} ({self.level}), typically {self.typical_ages}.",
            f"LITERACY: {self.literacy}",
            f"TERMINOLOGY: at this level KICD calls these {self.area_noun}s, not "
            f"{'subjects' if self.area_noun != 'subject' else 'learning areas'}. Use that word.",
        ]
        if self.can:
            lines.append("At this level learners CAN:")
            lines.extend(f"  - {c}" for c in self.can)
        if self.cannot:
            lines.append("At this level learners CANNOT — never require any of these:")
            lines.extend(f"  - {c}" for c in self.cannot)
        if self.lesson_minutes:
            lines.append(
                f"TIME: the design states {self.time_unit}, not hours. "
                f"One lesson is {self.lesson_minutes} minutes. Copy the design's own figure verbatim "
                f"and never convert it."
            )
        else:
            lines.append(
                f"TIME: the design states {self.time_unit}. Copy its own figure verbatim and never convert it."
            )
        if self.practicals:
            lines.append(f"PRACTICAL WORK: {self.practicals}")
        if self.scenario_world:
            lines.append(f"CONTEXT FOR EXAMPLES: {self.scenario_world}")
        if self.year_in_level:
            lines.append(f"POSITION: {self.grade_label} is the {self.year_in_level}.")
        if self.builds_on or self.prepares_for:
            progression = []
            if self.builds_on:
                progression.append(
                    f"Learners arrive having completed {self.builds_on}; do not re-teach it."
                )
            if self.prepares_for:
                progression.append(
                    f"They go on to {self.prepares_for}; do not pre-empt its content."
                )
            lines.append("PROGRESSION: " + " ".join(progression))
        if self.grade_notes:
            lines.append(f"WHAT {self.grade_label.upper()} ACTUALLY COVERS, from its own design:")
            lines.extend(f"  - {n}" for n in self.grade_notes)
        if self.uses_themes:
            lines.append(
                "STRUCTURE: subject -> STRAND -> SUB-STRAND is the spine. SOME learning areas "
                "at this level add a THEME axis on top of it (PP1 Language Activities runs six "
                "themes across three strands: Listening and Speaking, Reading, Writing). Others "
                "use their themes AS the strands (Creative and Environmental Activities), and "
                "the religious education areas have no themes at all. Read what THIS learning "
                "area does. Where a theme axis exists, record the theme; never report a theme as "
                "if it were a strand or a sub-strand."
            )
        return "\n".join(lines)


# How the words themselves have to sound, by age band. The rest of this module
# governs what a learner may be ASKED to do; this governs the sentences they
# hear while being asked.
#
# The sentence-length figure is not invented here. It is read from
# `dna_scoring`, which is what MEASURES the finished material — a prompt asking
# for one register while the check grades against another is how content comes
# back "correct" and unusable, and neither number is wrong on its own.
_LANGUAGE: dict[str, dict[str, str]] = {
    "Pre-Primary": {
        "vocabulary":
            "Words a four-year-old already uses at home. No word needs "
            "explaining unless explaining it IS the lesson. Concrete nouns "
            "they can point at: mother, food, water, hand, song. Nothing "
            "abstract standing alone — 'God provides' means nothing; 'God "
            "gives us food, the way your mother gives you food' does.",
        "sentences":
            "Short and complete. One idea each. No clauses joined by 'which', "
            "'although' or 'however'. A sentence a child cannot hold to its "
            "end has not been said.",
        "person":
            "Speak TO the child, not about them: 'Look at your hands' rather "
            "than 'learners observe their hands'. Repeat the key phrase — "
            "repetition is how this age learns, not padding.",
    },
    "Lower Primary": {
        "vocabulary":
            "Everyday words, with new terms introduced one at a time and used "
            "again immediately. A new word met once is a word not learned.",
        "sentences":
            "Two clauses at most. Read aloud, each should be sayable in one "
            "breath.",
        "person":
            "Speak to the child directly. Questions rather than statements "
            "wherever the answer is something they already know.",
    },
    "Upper Primary": {
        "vocabulary":
            "Subject terms are introduced deliberately and defined in the "
            "sentence that first uses them. Everyday words elsewhere.",
        "sentences":
            "Full sentences with connectives — because, so that, if. This is "
            "where reasoning is carried by the grammar and should be.",
        "person":
            "Address the learner, but expect them to follow an argument of two "
            "or three steps.",
    },
    "Junior School": {
        "vocabulary":
            "Subject vocabulary used precisely and consistently. Do not "
            "simplify a technical term into a vaguer one — name it and define "
            "it.",
        "sentences":
            "Complex sentences are fine where the idea is complex. Keep them "
            "short where it is not.",
        "person":
            "Explain rather than instruct. A learner at this age can be told "
            "why, and should be.",
    },
    "Senior School": {
        "vocabulary":
            "Full subject register, at the level an examiner would expect in "
            "an answer.",
        "sentences":
            "Whatever the reasoning requires. Precision over brevity.",
        "person":
            "Address a young adult preparing for an examination.",
    },
}


_PRE_PRIMARY = LevelRegister(
    level="Pre-Primary",
    grade_label="PP1/PP2",
    audience="Pre-primary children",
    typical_ages="4-5 years old",
    literacy="Pre-literate. They are learning letter sounds and how to hold a pencil. They cannot read a sentence and cannot write one.",
    can=[
        "listen, speak, sing, chant rhymes, recite short poems",
        "role-play, play games, take a nature walk",
        "look at and talk about pictures",
        "scribble, colour within a border, join dots, trace, model with clay or dough",
        "sort, match and group physical objects",
    ],
    cannot=[
        "read any written question, instruction or label",
        "write words or sentences",
        "read a flowchart, a table, a graph or a labelled diagram",
        "handle chemicals, heat, flames or sharp tools",
        "carry out a laboratory procedure or record measurements",
    ],
    time_unit="lessons",
    lesson_minutes=30,
    practicals="Play-based and sensory only: singing games, role-play, modelling, nature walks, water play. There are no experiments at this level.",
    uses_themes=True,
    scenario_world="The child's own world: self, family, home, neighbourhood, school. Not farms, industry, counties or national development.",
    area_noun="learning area",
)

_LOWER_PRIMARY = LevelRegister(
    level="Lower Primary",
    grade_label="Grades 1-3",
    audience="Lower-primary children",
    typical_ages="6-8 years old",
    literacy="Emerging readers and writers. Short simple sentences only.",
    can=[
        "read and write simple words and short sentences",
        "follow a short spoken instruction",
        "sing, recite, role-play, play structured games",
        "draw, colour, cut, paste and model",
        "observe, sort, count and compare concrete objects",
    ],
    cannot=[
        "read a long passage or a dense table",
        "handle chemicals, heat, flames or sharp tools unsupervised",
        "write an extended structured answer",
    ],
    time_unit="lessons",
    lesson_minutes=30,
    practicals="Simple guided observation and hands-on making with safe everyday materials.",
    uses_themes=True,
    scenario_world="Home, school and the immediate neighbourhood.",
    area_noun="learning area",
)

_UPPER_PRIMARY = LevelRegister(
    level="Upper Primary",
    grade_label="Grades 4-6",
    audience="Upper-primary learners",
    typical_ages="9-11 years old",
    literacy="Reading fluently. Can write a short structured answer.",
    can=[
        "read a passage and answer written questions",
        "read a simple labelled diagram, table or chart",
        "carry out a guided practical with everyday materials",
        "work in groups and present findings",
    ],
    cannot=[
        "handle hazardous chemicals or open flames without direct supervision",
        "sustain a long formal essay",
    ],
    time_unit="lessons",
    lesson_minutes=35,
    practicals="Guided practical investigation with everyday and improvised materials; adult supervision for anything sharp or hot.",
    scenario_world="Home, school, the local community and the county.",
)

_JUNIOR = LevelRegister(
    level="Junior School",
    grade_label="Grades 7-9",
    audience="Junior-school learners",
    typical_ages="12-14 years old",
    literacy="Competent readers and writers of structured prose.",
    can=[
        "read and interpret diagrams, tables, graphs and data",
        "carry out laboratory and workshop procedures under supervision",
        "write structured and extended responses",
        "plan and report an investigation",
    ],
    cannot=["work unsupervised with hazardous reagents or power tools"],
    time_unit="lessons",
    practicals="Laboratory and workshop work under supervision, with explicit safety protocols where reagents, heat or tools are involved.",
    scenario_world="School, community, county and national contexts.",
)

_SENIOR = LevelRegister(
    level="Senior School",
    grade_label="Grades 10-12",
    audience="Senior-school learners on a chosen pathway",
    typical_ages="15-17 years old",
    literacy="Fluent; capable of extended analytical writing.",
    can=[
        "analyse, evaluate and argue from evidence",
        "carry out full practical and field procedures",
        "handle specialist apparatus appropriate to the pathway",
    ],
    cannot=[],
    time_unit="lessons",
    practicals="Full practical, field and project work with formal safety protocols.",
    scenario_world="Community, county, national and international contexts appropriate to the pathway.",
)

_TERTIARY = LevelRegister(
    level="Tertiary",
    grade_label="Diploma in Teacher Education",
    audience="ADULT trainee teachers, not children",
    typical_ages="adults in professional training",
    literacy="Adult academic literacy.",
    can=[
        "read and critique professional and academic literature",
        "plan, teach and evaluate lessons",
        "conduct and write up practitioner research",
    ],
    cannot=[],
    time_unit="hours",
    practicals="Microteaching, teaching practice, and subject-method workshops.",
    scenario_world="Kenyan classrooms, schools and the teaching profession. The learner here is the trainee teacher; the children are whom they will teach.",
)

_BY_LEVEL: dict[str, LevelRegister] = {
    "Pre-Primary": _PRE_PRIMARY,
    "Lower Primary": _LOWER_PRIMARY,
    "Upper Primary": _UPPER_PRIMARY,
    "Junior School": _JUNIOR,
    "Senior School": _SENIOR,
    "Tertiary": _TERTIARY,
}

# When the grade is unknown we must not silently fall back to the most demanding
# register — that is how a four-year-old ends up with a titration. Say so.
_UNKNOWN = LevelRegister(
    level="Unknown",
    grade_label="unknown grade",
    audience="learners of an unstated level",
    typical_ages="unknown",
    literacy="Unknown. Do not assume fluent literacy.",
    can=[],
    cannot=[
        "be assumed to read, write or handle apparatus at any particular level",
    ],
    time_unit="the unit the design itself states",
    practicals="Only what the design itself describes. Do not invent practical work.",
    scenario_world="Only the contexts the design itself uses.",
)



# Age is a per-grade fact, not a band one. PP2 inheriting "4-5 years old" from
# the Pre-Primary band is the same error as Grade 1 and Grade 3 sharing a
# reader: it makes the register look specific while being wrong.
_GRADE_AGES: dict[str, str] = {
    "grade-pp1": "4-5 years old", "grade-pp2": "5-6 years old",
    "grade-1": "6-7 years old", "grade-2": "7-8 years old", "grade-3": "8-9 years old",
    "grade-4": "9-10 years old", "grade-5": "10-11 years old", "grade-6": "11-12 years old",
    "grade-7": "12-13 years old", "grade-8": "13-14 years old", "grade-9": "14-15 years old",
    "grade-10": "15-16 years old", "grade-11": "16-17 years old", "grade-12": "17-18 years old",
}


# ── Per-grade specifics ──────────────────────────────────────────────────────
# Only what the grade's own published design actually says. Where a design has
# not been read, the entry is absent and the register falls back to progression
# facts alone — which are derivable — rather than inventing a syllabus. An
# invented "Grade 5 covers fractions to 1/8" reads exactly like a real one.
_GRADE_NOTES: dict[str, list[str]] = {
    "grade-pp2": [
        "The second and final pre-primary year, and the one that completes the "
        "Pre-Primary level outcomes.",
        "PP1 covers letter SOUNDS only. The PP1 design's Subject General Learning "
        "Outcomes state that by the END of Pre-Primary Education the learner "
        "articulates letter sounds AND syllables, forming three-letter words — so "
        "syllables and three-letter words belong to PP2, not PP1.",
        "PP1 stops at 10 in Mathematical Activities (rote count 1-10, symbols 1-9). "
        "PP2 extends beyond that; read the PP2 design for its actual range rather "
        "than assuming one.",
        "Everything else specific to PP2 must be read from the PP2 design document.",
    ],
    "grade-pp1": [
        "25 lessons a week across all learning areas, 30 minutes each.",
        "Language Activities (150 lessons): letter SOUNDS only, introduced in "
        "blocks a-e, f-j, k-r, s-z, plus the vowels a/e/i/o/u, letter names and "
        "upper/lower case recognition. Learners do not read or write words.",
        "Mathematical Activities (150 lessons): rote counting 1-10; recognising, "
        "sequencing and writing number symbols 1-9; counting concrete objects "
        "1-9. Nothing beyond 10.",
        "Creative Activities (180 lessons): scribbling, printing, colouring, "
        "joining dots, modelling, musical sounds, crawling and bending, singing "
        "games, water play.",
        "Environmental Activities (154 lessons): self-awareness, external body "
        "parts, handwashing, brushing teeth, family, feeding, utensils, "
        "furniture, classmates, friends, parts of a plant, care of the class, "
        "cleanliness and toileting.",
        "Religious Education (90 lessons): CRE, HRE or IRE, one per learner.",
    ],
}

# Grades whose design this system has not read. Saying so in the prompt is the
# difference between "I do not know" and a confident fabrication.
_UNREAD_DESIGN_NOTE = (
    "The specific content for this grade must be read from its own KICD design "
    "document. Do not carry over another grade's scope."
)


def _progression(slug: str) -> tuple[str, str, str]:
    """Where a grade sits: year within its level, what precedes it, what follows."""
    slugs = [s for s, _l, _lv in GRADE_SEQUENCE]
    if slug not in slugs:
        return "", "", ""
    index = slugs.index(slug)

    level = GRADE_SEQUENCE[index][2]
    peers = [i for i, (_s, _l, lv) in enumerate(GRADE_SEQUENCE) if lv == level]
    position = peers.index(index) + 1
    ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth"}
    if len(peers) == 1:
        year_in_level = f"the whole of {level}"
    else:
        year_in_level = (
            f"{ordinals.get(position, str(position))} of {len(peers)} years of {level}"
        )

    # DTE trainees are adults entering a diploma, not children promoted from
    # Grade 12, so "do not re-teach Grade 12" would be the wrong instruction.
    builds_on = "" if slug == "grade-dte" else (GRADE_SEQUENCE[index - 1][1] if index > 0 else "")
    # DTE follows senior school in the listing but is not the next school year.
    nxt = GRADE_SEQUENCE[index + 1] if index + 1 < len(GRADE_SEQUENCE) else None
    prepares_for = ""
    if nxt and not (nxt[0] == "grade-dte" and slug != "grade-12"):
        prepares_for = nxt[1] if nxt[0] != "grade-dte" else ""
    return year_in_level, builds_on, prepares_for


def register_for_grade(grade: str | None, notes: list[str] | None = None) -> LevelRegister:
    """The authoring register implied by a grade slug.

    ``notes`` are the grade's own scope, derived from its design and stored by
    grade_scope. When supplied they replace the hand-written or "unread design"
    default, so a grade becomes as sharp as PP1 the moment its design is read.
    """
    slug = normalize_grade(grade)
    if not slug:
        return _UNKNOWN
    level = grade_level(slug)
    register = _BY_LEVEL.get(level)
    if register is None:
        return _UNKNOWN
    # Report the specific grade rather than the band it belongs to: Grade 1 and
    # Grade 3 share a band but not a reader.
    year_in_level, builds_on, prepares_for = _progression(slug)
    derived = [n for n in (notes or []) if str(n).strip()]
    resolved_notes = derived or list(_GRADE_NOTES.get(slug, [])) or [_UNREAD_DESIGN_NOTE]
    return replace(
        register,
        grade_label=grade_label(slug) or register.grade_label,
        typical_ages=_GRADE_AGES.get(slug, register.typical_ages),
        year_in_level=year_in_level,
        builds_on=builds_on,
        prepares_for=prepares_for,
        grade_notes=resolved_notes,
    )


def register_block(grade: str | None, notes: list[str] | None = None) -> str:
    """The prompt-ready register block for a grade."""
    return register_for_grade(grade, notes=notes).format_for_prompt()


def language_block(grade: str) -> str:
    """How the words must SOUND for this grade, with the age they are for.

    Kept beside the rest of the register because it answers the same question —
    who is this for — and separate from it in the prompt because it governs the
    prose rather than the task. A guide can ask a four-year-old to do exactly
    the right thing in sentences they cannot follow.
    """
    register = register_for_grade(grade)
    band = _LANGUAGE.get(register.level)
    if not band:
        return ""

    try:
        from .dna_scoring import _reading_target
        from .grade_order import grade_ordinal

        target = _reading_target(grade_ordinal(grade))
    except Exception:  # noqa: BLE001
        target = 0.0

    lines = [
        "=== HOW THE WORDS MUST SOUND ===",
        f"These words are heard by {register.audience.lower()}, "
        f"typically {register.typical_ages}. {register.literacy}",
        "",
        f"VOCABULARY: {band['vocabulary']}",
        f"SENTENCES: {band['sentences']}",
        f"HOW TO ADDRESS THEM: {band['person']}",
    ]
    if target:
        lines.append(
            f"LENGTH: aim near {target:.0f} words a sentence on average. This "
            f"is the figure the finished material is measured against, so it "
            f"is a target rather than a suggestion — but it is a MEAN. A short "
            f"question and a longer explanation either side of it is right; "
            f"every sentence the same length is not."
        )
    lines.append(
        "A sentence this learner cannot follow has not taught them anything, "
        "however true it is."
    )
    return "\n".join(lines)

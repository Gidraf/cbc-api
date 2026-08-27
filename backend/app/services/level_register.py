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

from .grade_order import grade_label, grade_level, normalize_grade


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
    practicals: str = ""
    uses_themes: bool = False
    scenario_world: str = ""

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
            "practicals": self.practicals,
            "uses_themes": self.uses_themes,
            "scenario_world": self.scenario_world,
        }

    def format_for_prompt(self) -> str:
        """The block injected into every authoring prompt."""
        lines = [
            f"AUDIENCE: {self.audience} — {self.grade_label} ({self.level}), typically {self.typical_ages}.",
            f"LITERACY: {self.literacy}",
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
        if self.uses_themes:
            lines.append(
                "STRUCTURE: this level organises the syllabus as THEME x STRAND -> SUB-STRAND. "
                "Record the theme; do not report a theme as if it were a strand or a sub-strand."
            )
        return "\n".join(lines)


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


def register_for_grade(grade: str | None) -> LevelRegister:
    """The authoring register implied by a grade slug."""
    slug = normalize_grade(grade)
    if not slug:
        return _UNKNOWN
    level = grade_level(slug)
    register = _BY_LEVEL.get(level)
    if register is None:
        return _UNKNOWN
    # Report the specific grade rather than the band it belongs to.
    return replace(register, grade_label=grade_label(slug) or register.grade_label)


def register_block(grade: str | None) -> str:
    """The prompt-ready register block for a grade."""
    return register_for_grade(grade).format_for_prompt()

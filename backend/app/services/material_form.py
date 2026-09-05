"""What SHAPE the material takes, which is not the same as its reading level.

`level_register` already tells a generator who the learner is — their age, what
they can read, how long a lesson runs. Every band got that, and every band
still got the same ARTIFACT: a spoken teacher script.

    "Today, we are going to explore integers. Integers are whole numbers that
     can be positive, negative, or zero..."

For a five-year-old that is exactly right — the child cannot read, so the
material IS what the teacher says aloud. For a Grade 9 learner it is wrong
twice over. It is pitched at a child who has never met a negative number, when
Grade 9 met integers in Grade 7 and is here for operations and order. And it is
the wrong OBJECT: a Grade 9 learner reads, so the material they need is the
page they read, not a transcript of the teacher talking at them.

What a Grade 9 mathematics page actually looks like:

    What is an integer?
    An integer is a positive whole number, a negative whole number, or zero.
    Examples: 2, -3, 5, 0, 7.

    The number line
    Any integer is less than every integer to the right of it.
    Thus -2 < -1 and -2 > -3.

    Exercise
    Use < or > to compare:
    1. -5 and +1     2. -3 and +4     3. -10 and +1

Definitions, notation stated explicitly, worked comparisons, then exercises the
learner does. No "today we are going to", no "can anyone tell me", no
narration of what the class is about to feel.

So the band chooses the FORM, and the form is stated to the generator as
plainly as the register is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .grade_order import grade_label, grade_level, normalize_grade


@dataclass(slots=True)
class MaterialForm:
    """The shape of the page, for one band."""

    key: str
    band: str
    # What the artifact IS, in one line.
    artifact: str
    # Who the words address.
    addressed_to: str
    voice: str
    structure: list[str] = field(default_factory=list)
    # Exercises the learner works, rather than questions the teacher asks aloud.
    wants_exercises: bool = False
    forbidden: list[str] = field(default_factory=list)
    example: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "band": self.band, "artifact": self.artifact,
                "addressed_to": self.addressed_to, "voice": self.voice,
                "structure": self.structure,
                "wants_exercises": self.wants_exercises,
                "forbidden": self.forbidden}


SPOKEN = MaterialForm(
    key="spoken",
    band="Pre-Primary and Lower Primary",
    artifact="the words the teacher says aloud, verbatim",
    addressed_to="the teacher, who reads it to children who cannot yet read it themselves",
    voice="Warm and spoken. Short sentences. The teacher's own voice.",
    structure=[
        "The words themselves — the whole song, the whole story, the whole "
        "explanation, written out so a teacher can open the page and say it.",
        "Where the directive calls for a song, rhyme or story, write ALL of it. "
        "A title and a description is the instruction again, not the material.",
        "Actions and gestures in brackets where the words alone are not enough.",
    ],
    wants_exercises=False,
    forbidden=[
        "Written exercises. These children cannot read a question paper.",
        "Abstract notation. A symbol is a mark on a page until it has been "
        "handled as objects first.",
    ],
    example=(
        "Hands up high, hands down low,\\n"
        "That is how the tall trees grow. (raise arms, then crouch)"
    ),
)

GUIDED = MaterialForm(
    key="guided",
    band="Upper Primary",
    artifact="a short page the learner reads, with practice underneath it",
    addressed_to="the learner, who reads independently but is still learning how a textbook works",
    voice=("Plain and direct. Explain, then show, then let them try. Short "
           "paragraphs — four or five sentences at most before an example."),
    structure=[
        "A heading that names the idea.",
        "The idea in plain sentences, with a worked example straight after it.",
        "A short practice set the learner works themselves.",
    ],
    wants_exercises=True,
    forbidden=[
        "Long unbroken prose. A page of paragraphs is a page they will not read.",
    ],
    example=(
        "**Equivalent fractions**\\n"
        "Two fractions are equivalent when they name the same amount.\\n"
        "1/2 and 2/4 are equivalent: both are half of the whole.\\n\\n"
        "**Practice**\\n"
        "Write an equivalent fraction for each:\\n"
        "1. 1/3    2. 3/4    3. 2/5"
    ),
)

EXPOSITION = MaterialForm(
    key="exposition",
    band="Junior School, Senior School and Diploma",
    artifact="the textbook page itself — what a learner reads, studies from, and revises",
    addressed_to="the learner, reading on their own, possibly the night before an exam",
    voice=(
        "The voice of a textbook, not a teacher talking. Declarative and "
        "economical. State the thing; do not announce that you are about to "
        "state it. Definitions are definitions, not conversation."
    ),
    structure=[
        "A sub-heading naming the concept — often as the question it answers "
        "(\"What is an integer?\").",
        "The definition, stated once and precisely.",
        "Examples immediately after the definition. Concrete, several, terse.",
        "The notation and symbols stated explicitly, with what each one means.",
        "Worked cases showing the rule applied, with the reasoning visible.",
        "An EXERCISE SET the learner works: numbered questions, increasing in "
        "difficulty, enough of them to practise on (at least five).",
    ],
    wants_exercises=True,
    forbidden=[
        "Announcing the lesson. \"Today, we are going to explore...\" is not how "
        "a textbook page begins, and it is not how any of them begin.",
        "Narrating the classroom. \"Can anyone tell me...\", \"Yes, that's right!\", "
        "\"Let's begin!\" — a page cannot hear an answer, and inventing the "
        "learner's reply teaches nothing.",
        "Re-teaching what earlier grades already covered, unless the design "
        "says to revise it. State it once as assumed knowledge and move on.",
        "Padding a definition into a paragraph. Precision is shorter.",
    ],
    example=(
        "**What is an integer?**\\n"
        "An integer is a positive whole number, a negative whole number, or zero.\\n"
        "Examples: 2, -3, 5, 0, 7.\\n\\n"
        "**Order on the number line**\\n"
        "Any integer is less than every integer to the right of it.\\n"
        "The symbols < and > denote 'less than' and 'greater than'.\\n"
        "Thus -2 < -1, and -2 > -3.\\n\\n"
        "**Exercise**\\n"
        "Use < or > to compare each pair:\\n"
        "1. -5 and +1     2. -3 and +4     3. -7 and -9     4. -20 and -36"
    ),
)

# One form per BECF level band. `grade_level` already returns these names.
_BY_LEVEL: dict[str, MaterialForm] = {
    "Pre-Primary": SPOKEN,
    "Lower Primary": SPOKEN,
    "Upper Primary": GUIDED,
    "Junior School": EXPOSITION,
    "Senior School": EXPOSITION,
    "Tertiary": EXPOSITION,
}


def form_for(grade: str | None) -> MaterialForm:
    """The shape of the page for this grade. Unknown grades read as a textbook.

    Defaulting to EXPOSITION rather than SPOKEN on purpose: a spoken script
    given to a reader is patronising, and a page given to a class that cannot
    read it yet is at least read aloud by the teacher.
    """
    return _BY_LEVEL.get(grade_level(grade), EXPOSITION)


def band_known(grade: str | None) -> bool:
    """Whether we actually know which band this is.

    `form_for` defaults to EXPOSITION so that a prompt still says something
    useful when the grade is missing. A FINDING is different: reporting "this
    lesson has no exercises" because we guessed the band is how a checker
    loses the operator's trust. So every check below is silent here.
    """
    return grade_level(grade) in _BY_LEVEL


def block_for(grade: str | None) -> str:
    """The form, as a prompt block."""
    form = form_for(grade)
    label = grade_label(grade)

    lines = [
        "=== WHAT YOU ARE WRITING ===",
        f"{label} sits in {form.band}.",
        "",
        f"This material is {form.artifact}.",
        f"It is addressed to {form.addressed_to}.",
        "",
        f"VOICE: {form.voice}",
        "",
        "SHAPE — every piece follows this:",
    ]
    lines += [f"  {n}. {item}" for n, item in enumerate(form.structure, 1)]
    lines += ["", "NEVER:"]
    lines += [f"  - {item}" for item in form.forbidden]

    if form.wants_exercises:
        lines += [
            "",
            "EXERCISES ARE PART OF THE MATERIAL, not an optional extra. A page "
            "a learner cannot practise on is a page they read once and forget. "
            "Number them, and make the last ones harder than the first.",
        ]

    lines += [
        "",
        "This is the shape — not the content, which comes from the design:",
        form.example,
        "",
        "=== DO NOT WRITE EVERY PIECE THE SAME WAY ===",
        "A lesson whose every section opens with the same sentence reads as a "
        "form letter, and a learner stops seeing the words. Vary how each piece "
        "begins. If two pieces in this lesson would start alike, rewrite one.",
    ]
    return "\n".join(lines)


# ── checking what came back ─────────────────────────────────────────────────

# The openings that made every section of a Grade 9 lesson sound identical.
_ANNOUNCEMENT = re.compile(
    r"^\s*(?:so\s+)?(?:today|now|in this (?:lesson|section|topic))\b"
    r"|^\s*let(?:'|’)?s\s+(?:begin|start|explore|look|discuss|talk|dive)\b"
    r"|^\s*we\s+(?:are|will)\s+(?:going\s+to\s+)?(?:explore|discuss|look|learn|talk|begin|start)\b",
    re.IGNORECASE,
)

# A page cannot hear an answer. These invent the learner's side of a
# conversation that is not happening.
_IMAGINED_REPLY = re.compile(
    r"\b(?:yes,?\s+that(?:'|’)?s\s+right|correct!|exactly!|great!|"
    r"can anyone (?:tell|think|share)|who would like to (?:share|start)|"
    r"raise your hand)\b",
    re.IGNORECASE,
)

_NUMBERED = re.compile(r"(?:^|\n)\s*(?:\d+[\.\)]|\(\d+\))\s+\S")


def _pieces(material: dict[str, Any]) -> list[dict[str, Any]]:
    found = material.get("material") if isinstance(material, dict) else None
    return [p for p in found if isinstance(p, dict)] if isinstance(found, list) else []


def announced(material: dict[str, Any], grade: str) -> list[dict[str, Any]]:
    """Pieces that open by announcing the lesson, where the form forbids it.

    The complaint this exists for: fourteen of eighteen sections of one Grade 9
    lesson began "Today, we are going to...".
    """
    if not band_known(grade):
        return []
    if not band_known(grade):
        return []
    form = form_for(grade)
    if form.key == "spoken":
        return []  # a teacher greeting a class is not a defect

    flagged: list[dict[str, Any]] = []
    for piece in _pieces(material):
        said = str(piece.get("say") or "").strip()
        if not said:
            continue
        opening = said.split("\n", 1)[0][:160]
        if _ANNOUNCEMENT.search(opening):
            flagged.append({
                "lesson": piece.get("module_number"),
                "topic": piece.get("topic") or piece.get("title"),
                "opening": opening[:100],
            })
    return flagged


def staged(material: dict[str, Any], grade: str) -> list[dict[str, Any]]:
    """Pieces that script a class discussion onto a page meant to be read."""
    form = form_for(grade)
    if form.key == "spoken":
        return []

    flagged: list[dict[str, Any]] = []
    for piece in _pieces(material):
        said = str(piece.get("say") or "")
        hits = _IMAGINED_REPLY.findall(said)
        if len(hits) >= 2:
            flagged.append({
                "lesson": piece.get("module_number"),
                "topic": piece.get("topic") or piece.get("title"),
                "count": len(hits),
            })
    return flagged


def unexercised(material: dict[str, Any], grade: str) -> list[dict[str, Any]]:
    """Lessons that never give the learner anything to work.

    Checked per LESSON rather than per piece: an exposition lesson needs
    practice somewhere in it, not in every paragraph.
    """
    if not band_known(grade):
        return []
    form = form_for(grade)
    if not form.wants_exercises:
        return []

    by_lesson: dict[Any, list[str]] = {}
    for piece in _pieces(material):
        by_lesson.setdefault(piece.get("module_number"), []).append(
            str(piece.get("say") or "")
        )

    flagged: list[dict[str, Any]] = []
    for lesson, texts in sorted(by_lesson.items(), key=lambda kv: str(kv[0])):
        joined = "\n".join(texts)
        questions = len(_NUMBERED.findall(joined))
        if questions < 3:
            flagged.append({"lesson": lesson, "numbered_questions": questions})
    return flagged

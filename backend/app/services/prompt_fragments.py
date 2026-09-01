"""Small pieces of prompt, chosen by context, instead of one large one.

Education is wide. Geography needs maps and the solar system; Chemistry needs
equations that balance; Music needs staves and time signatures; Home Science
needs quantities, timings and a hygiene rule; Carpentry needs orthographic
projection and a cutting list. None of that belongs in a Christian Religious
Education prompt, and all of it belongs somewhere.

Putting it all in one prompt per station does not work, and not only because of
length. A prompt that must serve every subject is a prompt nobody can improve:
change the paragraph about balancing equations and you have edited the prompt
that writes a PP1 singing lesson. So the person who knows chemistry will not
touch it, and it stays wrong.

So the pieces are separate, each with its own name, its own text and its own
rule for when it applies:

    domain/chemistry-equations   Chemistry, Integrated Science
    domain/geography-maps        Geography, Social Studies
    domain/music-notation        Music
    craft/technical-drawing      Carpentry, Technical Drawing, Design

`compose()` picks the ones that apply and returns them in a fixed order. Each
is also a Langfuse prompt under its own name, so somebody who knows chemistry
can improve the chemistry fragment without reading a word of the rest.

WHAT IS NOT HERE. Who the learner is (`level_register`), how the words must
sound (`language_block`), what faith is in scope (`faith_scope`) and what the
notation is (`notation`) are already their own modules and already composed
this way. This is for the DOMAIN — the things a subject needs that no other
subject does.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-prompt-fragments")

# Where a fragment goes. A station not named here never receives it, which is
# how a cutting list stays out of a question paper.
STATIONS = ("notes", "material", "diagram", "media", "simulation", "activity",
            "questions")


@dataclass(slots=True)
class Fragment:
    """One piece of domain knowledge, and when it applies."""

    name: str
    title: str
    body: str
    # Matched against the subject name, case-insensitively, as a stem.
    subjects: tuple[str, ...] = ()
    # Which stations get it. Empty means every station.
    stations: tuple[str, ...] = ()
    # Grades it applies to, BY SLUG. Ordinals are 1-based over the whole
    # sequence — grade-pp1 is 1, so Grade 4 is 6 — and writing `from_ordinal=4`
    # meaning Grade 4 silently gave every map fragment to Grade 2. Naming the
    # grade removes the arithmetic and the mistake with it.
    from_grade: str = ""
    to_grade: str = ""
    # Why this exists, for whoever edits it next.
    why: str = ""
    # What in the KICD design this serves. A fragment is domain knowledge, and
    # domain knowledge is exactly where a prompt drifts away from the
    # curriculum and towards what the author happens to know about the subject.
    # Naming the design's own hook is what keeps a chemistry fragment about
    # KICD chemistry rather than about chemistry.
    kicd: str = ""

    @property
    def langfuse_name(self) -> str:
        return f"fragment/{self.name}"

    @property
    def from_ordinal(self) -> int:
        from .grade_order import grade_ordinal

        return grade_ordinal(self.from_grade) if self.from_grade else 0

    @property
    def to_ordinal(self) -> int:
        from .grade_order import grade_ordinal

        return grade_ordinal(self.to_grade) if self.to_grade else 99

    def applies(self, subject: str, station: str, ordinal: int) -> bool:
        if self.stations and station and station not in self.stations:
            return False
        if not (self.from_ordinal <= ordinal <= self.to_ordinal):
            return False
        if not self.subjects:
            return True
        return any(re.search(rf"\b{s}", subject or "", re.I) for s in self.subjects)

    def to_dict(self) -> dict[str, Any]:
        from .grade_order import GRADE_SEQUENCE

        # `grade_ordinal` is 1-based and the sequence is 0-based, so an
        # off-by-one here showed "maps from Grade 2" for a fragment that starts
        # at Grade 4 — and the console is where somebody checks that.
        grades = [
            slug for i, (slug, _, _) in enumerate(GRADE_SEQUENCE, start=1)
            if self.from_ordinal <= i <= self.to_ordinal
        ]
        return {"name": self.name, "langfuse_name": self.langfuse_name,
                "title": self.title, "subjects": list(self.subjects),
                "stations": list(self.stations) or list(STATIONS),
                "from_ordinal": self.from_ordinal, "to_ordinal": self.to_ordinal,
                "grades": grades,
                "why": self.why, "kicd": self.kicd,
                "chars": len(self.body), "body": self.body}


FRAGMENTS: tuple[Fragment, ...] = (
    Fragment(
        name="geography-maps",
        kicd=(
            "The designs ask learners to 'draw a sketch map of the school compound' and 'locate physical features on a map of Kenya', and the assessment rubrics mark on scale, key and direction. Those three are the rubric, so they are what the fragment insists on."
        ),
        title="Maps",
        subjects=("geograph", "social studies", "environmental"),
        # Scale, grid references and a key are Upper Primary onward. An
        # Environmental Activities lesson at PP1 is about parts of a plant.
        from_grade="grade-4",
        why="A map drawn without a scale, a north arrow or a key is a picture "
            "of a shape. A learner cannot measure a distance on it, cannot say "
            "which way a river runs, and cannot be asked anything that has a "
            "markable answer.",
        body="""=== HOW TO SPECIFY A MAP ===
Every map carries four things, and a map missing any of them cannot be asked a
question about:
  - a SCALE, stated as a ratio and as a bar (1:50 000, and a bar in km),
  - a NORTH arrow,
  - a KEY naming every symbol used, and no symbol that is not in the key,
  - a TITLE saying what area and what theme.

Give the map as data, not as a description:
  "map": {
    "extent": "Nyeri County" | "Kenya" | "East Africa" | "the school compound",
    "projection_note": "sketch map, not to projection" | "topographic",
    "scale": {"ratio": "1:50 000", "bar_km": 5},
    "features": [
      {"kind": "river|road|railway|settlement|contour|boundary|relief|vegetation",
       "name": "Chania River", "note": "flows south-east"}
    ],
    "key": [{"symbol": "blue line", "means": "river"}],
    "grid": {"kind": "eastings_northings" | "lat_long" | "none"}
  }

WHAT THE LEARNER DOES ON IT is what decides what the map must show. If the
question asks for a distance, the scale must allow it to be measured. If it
asks for direction, the north arrow must be there. Do not draw a feature the
lesson never mentions: a map with six rivers on it when the lesson names one is
six things to be asked about and one that was taught.""",
    ),
    Fragment(
        name="astronomy-solar-system",
        kicd=(
            "Where a design names the solar system it names ORDER and RELATIVE SIZE, and its rubrics ask learners to 'arrange the planets in order from the sun'. A figure that is neither to scale nor labelled as schematic cannot be marked against that."
        ),
        title="The solar system and the sky",
        # "science" as a bare stem swept up Home Science, which is cookery.
        subjects=("geograph", "integrated science", "astronom", "physic"),
        from_grade="grade-4",
        why="Scale is the whole lesson and the whole difficulty. A diagram of "
            "the solar system drawn to scale is mostly empty paper; one drawn "
            "to fit the page teaches that Neptune is close.",
        body="""=== DIAGRAMS OF THE SKY ===
Say which of the two kinds of drawing this is, because they cannot be the same
drawing:
  - TO SCALE — distances or sizes in proportion, and therefore mostly empty
    paper. Use it when the lesson is ABOUT the scale.
  - SCHEMATIC — order and relationship only, sizes not in proportion. Use it
    for everything else, and LABEL IT "not to scale" on the figure itself.

A figure that is neither, drawn to fill the page and unlabelled, teaches that
Neptune is a short way past Saturn.

Give the order outward from the Sun, name what is being shown (orbit, phase,
eclipse, rotation, season), and where a phenomenon depends on a viewing
position — phases, eclipses, seasons — put the observer in the figure. A phase
diagram without an observer shows a lit hemisphere and explains nothing.""",
    ),
    Fragment(
        name="chemistry-equations",
        kicd=(
            "The designs' outcomes say 'write and balance chemical equations', and the rubric levels separate 'balances the equation' from 'writes the equation'. Splitting the skeleton, the balanced form and the atom count is what makes those two markable apart."
        ),
        title="Chemical equations",
        subjects=("chemist", "integrated science", "physical science"),
        stations=("notes", "material", "questions", "diagram", "simulation"),
        from_grade="grade-8",
        why="An unbalanced equation printed in a guide is taught as correct, "
            "and a learner marking their own work against it learns that "
            "chemistry does not have to balance.",
        body="""=== EQUATIONS MUST BALANCE, AND YOU MUST CHECK ===
Before you write any equation, count the atoms of each element on both sides
and the charge on both sides. Write it only when they match.

  $$2H_2(g) + O_2(g) \\rightarrow 2H_2O(l)$$

State phases after every species — $(s)$, $(l)$, $(g)$, $(aq)$ — and put
conditions above the arrow where they matter (heat, catalyst, reversible).

FOR A BALANCING EXERCISE, give the unbalanced skeleton, the balanced answer and
the coefficients separately, so the item can be marked without a person reading
the whole equation:
  "balancing": {
    "skeleton": "H_2 + O_2 \\rightarrow H_2O",
    "balanced": "2H_2 + O_2 \\rightarrow 2H_2O",
    "coefficients": {"H_2": 2, "O_2": 1, "H_2O": 2},
    "atom_count": {"H": {"left": 4, "right": 4}, "O": {"left": 2, "right": 2}}
  }
The atom count is the working. A learner who gets it wrong is wrong at a
specific element, and a scheme that shows the count can say which.""",
    ),
    Fragment(
        name="music-notation",
        kicd=(
            "Creative Arts and Music designs ask learners to 'sing songs in sol-fa' and 'clap the rhythm', and name sol-fa rather than staff notation throughout. The fragment follows the design's own notation, not the one a conservatoire would use."
        ),
        title="Music",
        subjects=("music", "creative"),
        why="A song named and not written down is a song the teacher must "
            "already know. Most cannot read staff notation; almost all can "
            "read sol-fa, which is what Kenyan classrooms actually use.",
        body="""=== HOW TO WRITE MUSIC DOWN ===
Name the song, then WRITE IT. A song named and not written is a song the
teacher must already know.

Give it in SOL-FA first, because that is what a Kenyan classroom reads:
  "music": {
    "title": "...",
    "key": "C",
    "time_signature": "4/4",
    "tempo": "moderate, about 100 beats a minute",
    "solfa": "d : d : r : m | m : r : d : -",
    "lyrics": ["line one, as it is sung", "line two"],
    "actions": ["what the children do on each line"],
    "origin": "traditional | widely known in Kenyan schools | written for this lesson"
  }

Bar lines as `|`, beats separated by `:`, a held note as `-`. Staff notation may
be added, never substituted: most primary teachers do not read it.

Where a lesson asks for rhythm rather than melody, give the pattern in claps or
syllables (ta, ti-ti) and say how many beats a bar. Where it asks for an
instrument, name one a Kenyan school has: a drum, shakers, a whistle, clapping,
desks.""",
    ),
    Fragment(
        name="home-science-practical",
        kicd=(
            "Home Science designs fund practicals by lesson and their rubrics mark on 'observes hygiene' and 'follows the procedure'. A procedure without quantities and a 'how you know it is done' cannot be followed, and hygiene is a rubric row rather than a footnote."
        ),
        title="Cooking and household practicals",
        subjects=("home science", "nutrition", "food"),
        stations=("notes", "material", "activity", "diagram"),
        why="A recipe without quantities, timings and a temperature is not a "
            "recipe. And this is the one subject where a mistake burns a "
            "child, so hygiene and heat are not optional paragraphs.",
        body="""=== A PRACTICAL THAT CAN ACTUALLY BE DONE ===
Give quantities, timings and temperatures, in the units a Kenyan kitchen uses:
grams, millilitres, cups, minutes, °C. "Some flour" and "cook until ready" are
not instructions.

  "practical": {
    "yield": "serves 4",
    "ingredients": [{"item": "maize flour", "quantity": "500 g",
                     "substitute": "sorghum flour"}],
    "equipment": ["sufuria", "wooden spoon", "jiko or gas ring"],
    "steps": [{"step": 1, "do": "...", "minutes": 5, "temperature": "medium heat",
               "how_you_know": "the mixture pulls away from the sides"}],
    "hygiene": ["wash hands before and after", "tie hair back"],
    "hazards": [{"hazard": "hot sufuria", "control": "use a cloth; only the "
                 "teacher lifts it"}]
  }

EVERY STEP SAYS HOW YOU KNOW IT IS DONE. "Cook for five minutes" and "cook
until it pulls away from the sides" are different instructions, and only the
second one works on a jiko whose heat nobody measured.

HEAT AND BLADES ARE THE TEACHER'S. Say so explicitly at every step where they
appear, and say what the children do instead while it happens.

Name ingredients a Kenyan household has, and give a substitute for anything
seasonal or costly. A practical nobody can afford is a practical nobody does.""",
    ),
    Fragment(
        name="technical-drawing",
        kicd=(
            "Pre-Technical and Technical designs ask for orthographic projection by name, and their rubrics mark on dimensioning. A drawing without dimensions scores nothing on the design's own rubric however well it is drawn."
        ),
        title="Technical drawing and construction",
        subjects=("carpentr", "technical", "design", "pre-technical",
                  "woodwork", "metalwork", "building"),
        from_grade="grade-7",
        why="A workshop drawing that cannot be built from is decoration. "
            "Dimensions, materials and a cutting list are the drawing.",
        body="""=== A DRAWING SOMETHING CAN BE BUILT FROM ===
Give orthographic views — front, top, side — and say which is which. Add an
isometric only as an extra; it is for understanding, not for building.

  "drawing": {
    "views": ["front", "top", "side"],
    "units": "mm",
    "dimensions": [{"between": ["A", "B"], "value": 450, "tolerance": "±2"}],
    "scale": "1:5",
    "material": "cypress, planed both sides",
    "cutting_list": [{"part": "leg", "quantity": 4, "length": 450,
                      "width": 45, "thickness": 45}],
    "joints": [{"kind": "mortise and tenon", "where": "leg to rail"}],
    "finish": "sanded to 180 grit, one coat of varnish"
  }

DIMENSION EVERY PART ONCE. A measurement given on two views is two places to be
wrong, and the workshop will find the second one.

Use millimetres throughout — mixing mm and cm on one drawing is how a part is
cut ten times too short. Name a material a Kenyan workshop stocks, and a joint
the tools in a school workshop can actually cut.""",
    ),
    Fragment(
        name="agriculture-field",
        kicd=(
            "Agriculture designs specify spacing and season in the learning experiences themselves — 'plant at the correct spacing', 'observe germination'. The numbers are the outcome, not the detail."
        ),
        title="Field and farm practicals",
        subjects=("agricultur", "environmental"),
        stations=("notes", "material", "activity", "diagram"),
        from_grade="grade-4",
        why="Spacing, depth and season are the content. A planting activity "
            "without them is gardening.",
        body="""=== A FIELD PRACTICAL WITH THE NUMBERS IN IT ===
Spacing, depth, season and quantity are the content, not the detail. Give them:
  "field": {
    "crop_or_animal": "kale (sukuma wiki)",
    "spacing": "60 cm between rows, 45 cm within the row",
    "depth": "1 cm",
    "season": "long rains, March to May",
    "inputs": [{"input": "well-rotted manure", "rate": "2 handfuls per hole"}],
    "plot_size": "2 m x 3 m demonstration bed",
    "observations": [{"after_days": 7, "look_for": "first true leaves"}]
  }

Say what is observed and when. A practical with no observation schedule is a
practical whose result nobody records, and the lesson after it has nothing to
work from.

Use local names beside the standard ones — sukuma wiki, njahi, matoke — and
name the season the way a Kenyan farmer does, by the rains rather than by the
month alone.""",
    ),
    Fragment(
        name="language-text",
        kicd=(
            "Language designs fund comprehension and set texts by lesson, and their rubrics mark on answering FROM the passage. There is nothing to answer from if the passage was named and not written."
        ),
        title="Passages, poems and set texts",
        subjects=("english", "kiswahili", "literature", "language", "fasihi",
                  "lugha"),
        why="A comprehension question about a passage nobody printed cannot be "
            "answered. The passage IS the resource.",
        body="""=== THE PASSAGE IS THE RESOURCE ===
Where a lesson works from a passage, a poem or a dialogue, WRITE IT OUT in
full. A comprehension question about a text nobody printed cannot be answered,
and "a suitable passage about farming" is not a passage.

  "text": {
    "kind": "passage | poem | dialogue | song | letter",
    "title": "...",
    "body": "The full text, exactly as the learner reads it.",
    "word_count": 180,
    "origin": "written for this lesson | traditional | from the design",
    "glossary": [{"word": "...", "means": "...", "in_line": 4}]
  }

LENGTH FOLLOWS THE READER. The register above says what this learner can hold:
a Grade 3 comprehension passage is not a Grade 9 one at a smaller font. Count
the words and say the count.

Gloss any word the learner has not met, once, with the line it appears on —
and if a passage needs more than four or five glosses it is the wrong passage
for this grade.""",
    ),
    Fragment(
        name="physical-education",
        kicd=(
            "PE designs ask for participation by every learner — the rubrics mark on 'takes part' — which is why a rotation that gives everybody a turn is part of the specification and not a nicety."
        ),
        title="Movement and games",
        subjects=("physical", "sport", "games", "health"),
        stations=("notes", "material", "activity"),
        why="Space, numbers and a safety rule are what make a game playable in "
            "a Kenyan school field with forty children and one ball.",
        body="""=== A GAME FORTY CHILDREN CAN ACTUALLY PLAY ===
Say the space, the numbers and the equipment, for a class of forty and one set
of equipment:
  "activity": {
    "space": "a 20 m x 10 m area of level ground",
    "group_size": "pairs" | "groups of 5" | "whole class",
    "equipment": ["one ball", "four markers — stones will do"],
    "rotation": "how everyone gets a turn, not only the quick ones",
    "progression": "how to make it harder for those who find it easy",
    "regression": "how to make it possible for those who do not",
    "safety": ["clear the ground of stones first", "no tackling"]
  }

EQUIPMENT A SCHOOL HAS. Stones for markers, a made ball, hands for a net. An
activity that needs a set of bibs is an activity most classes will skip.

SAY HOW EVERYONE GETS A TURN. A game where the fastest child holds the ball for
ten minutes has taught thirty-nine children to wait.""",
    ),
)

_BY_NAME = {f.name: f for f in FRAGMENTS}


def for_context(subject: str, station: str = "", grade: str = "") -> list[Fragment]:
    """Every fragment that applies here, in declaration order."""
    from .grade_order import grade_ordinal

    ordinal = grade_ordinal(grade) if grade else 50
    return [f for f in FRAGMENTS if f.applies(subject, station, ordinal)]


def compose(subject: str, station: str = "", grade: str = "") -> str:
    """The domain blocks for this subject and station, as one piece of prompt.

    Nothing for most combinations, which is the point: a CRE lesson plan
    receives no paragraph about cutting lists, and the instructions it does
    receive are easier to find for it.
    """
    # A station outside the list gets nothing at all. Reading a strand list out
    # of a table needs no paragraph about maps, and a fragment with no explicit
    # station list would otherwise reach every caller including that one.
    if station and station not in STATIONS:
        return ""
    chosen = for_context(subject, station, grade)
    if not chosen:
        return ""
    return "\n\n".join(_body(f) for f in chosen)


def _body(fragment: Fragment) -> str:
    """The fragment's text, preferring whatever has been edited in Langfuse.

    The code holds the default so a fresh deployment works with no prompt store
    at all; Langfuse holds the improvements, under the fragment's own name, so
    somebody who knows chemistry can change the chemistry without reading a
    word of the rest.
    """
    try:
        from .langfuse_context import langfuse_context_service

        found = langfuse_context_service.get_prompt(fragment.langfuse_name)
        text = getattr(found, "prompt", "")
        if text and text.strip():
            return text
    except Exception as exc:  # noqa: BLE001
        logger.debug("No stored fragment %s (%s); using the built-in.",
                     fragment.langfuse_name, exc)
    return fragment.body


def catalogue() -> list[dict[str, Any]]:
    """Every fragment, for a console that lists what can be edited."""
    return [f.to_dict() for f in FRAGMENTS]


def seed_prompts() -> dict[str, str]:
    """Each fragment as its own Langfuse prompt, under `fragment/<name>`."""
    return {f.langfuse_name: f.body for f in FRAGMENTS}

"""Which model runs which stage, and what happens when one is unbound.

Six stages existed and four of them did the work of fourteen. `notes_generation`
resolved the notes AND the strand generator, the sub-strand generator, the
learning-area ingest, the grade-scope derivation and the content-type profile
writer — so moving the notes to a stronger model moved six other things with
them, including two that read a 296-page document and are billed by the page.

Each station now names its own stage. That is the whole point: the notes are
worth a strong model, extracting a strand list from a table is not, and nobody
should have to buy both to get one.

FALLBACKS matter as much as the split. Adding a stage to a system where
`notes_generation` was already bound to a good model would otherwise drop every
new stage to the hardcoded default — a silent downgrade, on the run after a
deploy, with nothing in the output saying why the quality fell. So an unbound
stage inherits from the nearest bound relative before anything defaults.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Stage:
    name: str
    label: str
    # What actually calls it, so an operator setting a price knows what they buy.
    drives: str
    # Where to inherit from while this stage is unbound.
    falls_back_to: str = ""
    # A hint about what the work needs, not a recommendation of any one model.
    guidance: str = ""


STAGES: tuple[Stage, ...] = (
    Stage(
        "notes_generation", "Lesson notes",
        "The teacher's guide for a sub-strand: one module per funded lesson, "
        "each with the teacher's own words, misconceptions and formative checks.",
        guidance="The longest and most judgement-heavy writing in the pipeline, "
                 "and the one where a weak model shows first — modules come back "
                 "at a third of the required depth however the prompt is worded.",
    ),
    Stage(
        "material_generation", "Lesson material",
        "The words themselves, written from the plan: the song's verse, the "
        "story as it is told, the prayer as it is said, the explanation in the "
        "sentences the teacher speaks aloud. One call per instruction.",
        falls_back_to="notes_generation",
        guidance="Short outputs, many of them, and the only stage whose product "
                 "a child hears verbatim. A weak model here does not come back "
                 "shallow — it comes back with the instruction reworded, which "
                 "reads as material and is not. Worth more than the plan above "
                 "it: the plan can be corrected by a teacher who knows the "
                 "subject; these words are what the teacher would otherwise "
                 "have had to write.",
    ),
    Stage(
        "structure_generation", "Strands & sub-strands",
        "Reading the strand list and each strand's sub-strands out of the "
        "design's own tables.",
        falls_back_to="notes_generation",
        guidance="Extraction from a table that is already correct. Accuracy "
                 "matters; invention is the risk, not fluency.",
    ),
    Stage(
        "ingest_extraction", "Reading the design",
        "Ingesting a learning area from the published PDF, and deriving the "
        "grade scope. Chunked page by page, so this is billed by the page.",
        falls_back_to="structure_generation",
        guidance="The highest token volume in the pipeline by a wide margin — a "
                 "296-page design, one call per chunk. A costly model here is "
                 "felt immediately.",
    ),
    Stage(
        "diagram_generation", "Diagrams",
        "Vector diagrams with addressable parts, so a question can test one region.",
        guidance="Generates SVG. Benefits from a model that writes code well.",
    ),
    Stage(
        "media_generation", "Photo & video briefs",
        "Prompts, shot lists and alt text for photographs and video.",
        falls_back_to="diagram_generation",
        guidance="Descriptive writing, not code. The brief is the deliverable; "
                 "the asset is produced elsewhere.",
    ),
    Stage(
        "simulation_generation", "Interactive simulations",
        "Build briefs for simulations a learner manipulates.",
        falls_back_to="diagram_generation",
        guidance="Specifies behaviour, controls and acceptance criteria. A "
                 "code-capable model reads this work best.",
    ),
    Stage(
        "activity_generation", "Activities & experiments",
        "Hands-on tasks with whatever safety guidance their materials require.",
        guidance="Practical sequencing and real materials.",
    ),
    Stage(
        "question_generation", "Questions",
        "Assessment items grounded in the notes, diagrams and practicals.",
        guidance="Must respect the level register and the diagram part ids it "
                 "is given.",
    ),
    Stage(
        "profile_generation", "Teaching profiles",
        "The per-subject teaching profile every other station is steered by.",
        falls_back_to="notes_generation",
        guidance="Runs rarely and steers everything. Cheap to get right once.",
    ),
    Stage(
        "reviewer_panel", "Review layers",
        "The independent review of a filed version.",
        guidance="Layer 2 must come from a different vendor than the generator, "
                 "or it is one opinion asked twice.",
    ),
    Stage(
        "regeneration", "Regeneration",
        "Rewriting a version from its reviewers' findings.",
        falls_back_to="notes_generation",
    ),
)

BY_NAME: dict[str, Stage] = {s.name: s for s in STAGES}
NAMES: frozenset[str] = frozenset(BY_NAME)


# Which stations are worth running on your own machine, and which are not.
#
# Not a preference — a consequence of what each station does. `material` is
# many short calls against an explicit instruction ("the plan says choose a
# simple song; write the song"), which is exactly the work a 14B model does
# competently and exactly the work that costs the most tokens. `notes` is the
# opposite: one long call, the most judgement in the pipeline, and everything
# downstream is grounded in it — the stage's own guidance says a weak model
# shows here first.
#
# And a REVIEWER weaker than the generator is not a reviewer. It agrees.
LOCAL_FRIENDLY: tuple[str, ...] = (
    "material_generation",
    "media_generation",
    "activity_generation",
    "profile_generation",
)

# Never local, whatever the preset. Layer 2 exists to be a second opinion, and
# a second opinion that cannot see what the first one missed is one opinion
# asked twice.
HOSTED_ONLY: tuple[str, ...] = (
    "reviewer_panel",
    "notes_generation",
    "ingest_extraction",
)


def split_by_role(preset: str) -> dict[str, str]:
    """Which stations go local, for a given appetite. The rest stay hosted.

    `careful`  — only the stations whose work is short, high-volume and driven
                 by an instruction the plan already wrote.
    `most`     — everything except the reading, the plan and the review. Saves
                 the most and is where quality starts to show.
    """
    if preset == "most":
        local = [s.name for s in STAGES if s.name not in HOSTED_ONLY]
    elif preset == "careful":
        local = list(LOCAL_FRIENDLY)
    else:
        local = []
    return {s.name: ("local" if s.name in local else "hosted") for s in STAGES}


def chain(stage: str) -> list[str]:
    """The stage, then whatever it inherits from, in order.

    Cycle-safe: a mis-edited fallback that pointed at itself would otherwise
    hang the first request that touched it.
    """
    seen: list[str] = []
    current = stage
    while current and current not in seen:
        seen.append(current)
        current = BY_NAME[current].falls_back_to if current in BY_NAME else ""
    return seen


def describe(stage: str) -> dict[str, str]:
    found = BY_NAME.get(stage)
    if not found:
        return {"name": stage, "label": stage, "drives": "", "guidance": ""}
    return {"name": found.name, "label": found.label, "drives": found.drives,
            "falls_back_to": found.falls_back_to, "guidance": found.guidance}

"""The single question contract.

Both generation paths (``pipeline.run_full_pipeline`` and the Questions Factory)
emit this model, the quality gate validates it, and the public exam-builder API
serves it. Previously each path had its own shape and only one was validated.

Invariants that used to be assumed are enforced here, most importantly that an
answer key is never inferred: a multiple-choice item without exactly one correct
option is rejected rather than silently defaulting to the first option.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# ─────────────────────────────────────────────────────────────────────────────
# Typology families
#
# The mix policy is expressed against families rather than a hardcoded name list,
# so adding a typology does not silently break the policy check.
# ─────────────────────────────────────────────────────────────────────────────

SELECTED_RESPONSE: frozenset[str] = frozenset({
    "multiple_choice",
    "assertion_reason",
    "matching",
    "true_false",
})

CONSTRUCTED_RESPONSE: frozenset[str] = frozenset({
    "short_answer",
    "structured_inquiry",
    "structured_scenario",
    "diagram_based",
    "experiment_based",
    "quantitative_calculation",
    "extended_essay",
    "practical_performance_task",
    "cloze",
})

ALL_QUESTION_TYPES: frozenset[str] = SELECTED_RESPONSE | CONSTRUCTED_RESPONSE

BLOOM_LEVELS: tuple[str, ...] = (
    "Recall",
    "Understanding",
    "Application",
    "Analysis",
    "Evaluation",
    "Creation",
)


def family_of(question_type: str) -> str:
    if question_type in SELECTED_RESPONSE:
        return "selected_response"
    if question_type in CONSTRUCTED_RESPONSE:
        return "constructed_response"
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Components
# ─────────────────────────────────────────────────────────────────────────────


class AnswerOption(BaseModel):
    id: str
    text: str
    is_correct: bool = False
    distractor_rationale: str = ""


class StructuredPart(BaseModel):
    part_id: str
    sub_question: str
    marks: int = Field(default=1, ge=0)
    model_answer: str = ""


class KicdRubric(BaseModel):
    """The four criterion-referenced performance levels.

    Criterion-referenced by design: levels describe the learner against the
    standard, never against other learners.
    """

    exceeding: str = ""
    meeting: str = ""
    approaching: str = ""
    below: str = ""

    def is_complete(self) -> bool:
        return all([self.exceeding, self.meeting, self.approaching, self.below])


class DiagramBinding(BaseModel):
    """How a question points at a visual.

    ``part_ids`` and ``region_id`` address *inside* a diagram, which is what makes
    "ask about part of the diagram" expressible. ``hide_layers`` is what lets the
    learner's paper and the marking scheme render from one source: strip the
    label layer for the question, keep it for the answer.
    """

    diagram_id: str
    diagram_title: str = ""
    region_id: str | None = None
    part_ids: list[str] = Field(default_factory=list)
    hide_layers: list[str] = Field(default_factory=list)
    storage_url: str = ""
    # "only-one": the sub-strand had exactly one diagram, so there was nothing
    # to choose between and the wording similarity did not matter. Recorded as
    # its own method rather than dressed up as a semantic match, because a
    # reviewer should be able to tell the two apart.
    binding_method: Literal["explicit", "semantic", "anchored", "authored",
                            "only-one", "unbound"] = "unbound"
    binding_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Occlusion. ``hide_part_ids`` blanks named parts rather than a whole layer,
    # and ``slots`` names the marker printed in each gap. Both are carried on the
    # binding so the learner's paper, the marking scheme and the question text
    # are rendered from one description instead of three.
    variant_mode: Literal["label_blanks", "hide_parts", "crop_region", "missing_parameters", "full"] = "full"
    hide_part_ids: list[str] = Field(default_factory=list)
    slots: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_slots_cover_hidden_parts(self) -> "DiagramBinding":
        """Every blanked part must have a marker.

        A part removed without a marker leaves a silent hole: the learner sees
        nothing to answer, and the marking scheme still expects a response.
        """
        missing = [pid for pid in self.hide_part_ids if pid not in self.slots]
        if missing:
            raise ValueError(
                f"diagram binding '{self.diagram_id}' hides {missing} without a blank marker; "
                f"the learner would not know which part to name."
            )
        return self


class QuestionCurriculum(BaseModel):
    level: str = ""
    grade: str
    grade_ordinal: int = 999
    subject: str
    subject_code: str = ""
    strand: str = ""
    sub_strand: str = ""
    slo_id: str = ""
    slo_text: str = ""


class QuestionPedagogy(BaseModel):
    bloom_level: str = "Application"
    difficulty_index: float = Field(default=0.5, ge=0.0, le=1.0)
    max_marks: int = Field(default=1, ge=0)
    estimated_time_mins: int = Field(default=2, ge=0)
    micro_concept: str = ""
    core_competency: str = ""
    constitutional_value: str = ""
    pertinent_issue: str = ""
    source_hour: int | None = None
    source_hour_title: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# The item
# ─────────────────────────────────────────────────────────────────────────────


class QuestionItem(BaseModel):
    question_id: str
    universal_id: str
    display_label: str = ""
    version: int = 1

    question_type: str
    curriculum: QuestionCurriculum
    pedagogy: QuestionPedagogy

    stimulus_context: str = ""
    question_text: str

    options: list[AnswerOption] = Field(default_factory=list)
    correct_answer: str | None = None
    structured_parts: list[StructuredPart] = Field(default_factory=list)

    model_answer: str = ""
    marking_scheme: str = ""
    rubric: KicdRubric = Field(default_factory=KicdRubric)

    diagram: DiagramBinding | None = None
    activity_ref: str = ""
    provenance_citation: str = ""

    dna_id: str = ""
    status: str = "draft"

    @property
    def family(self) -> str:
        return family_of(self.question_type)

    @model_validator(mode="after")
    def _check_type(self) -> "QuestionItem":
        if self.question_type not in ALL_QUESTION_TYPES:
            raise ValueError(
                f"Unknown question_type '{self.question_type}'. "
                f"Expected one of: {', '.join(sorted(ALL_QUESTION_TYPES))}"
            )
        return self

    @model_validator(mode="after")
    def _check_answer_key(self) -> "QuestionItem":
        """A selected-response item must carry an unambiguous key.

        This is the guard for the defect where a missing ``correct_answer`` fell
        back to the first option, shipping a wrong key into printed papers.
        """
        if self.question_type not in SELECTED_RESPONSE:
            return self

        if len(self.options) < 2:
            raise ValueError(
                f"{self.question_type} item '{self.question_id}' has "
                f"{len(self.options)} option(s); at least 2 are required"
            )

        flagged = [o.id for o in self.options if o.is_correct]

        if self.correct_answer:
            stated = {c.strip().upper() for c in self.correct_answer.split(",") if c.strip()}
            known = {o.id.strip().upper() for o in self.options}
            unknown = stated - known
            if unknown:
                raise ValueError(
                    f"Item '{self.question_id}' names correct answer(s) "
                    f"{sorted(unknown)} that are not among its options {sorted(known)}"
                )
            # Reconcile the flags to the stated key rather than trusting both.
            for opt in self.options:
                opt.is_correct = opt.id.strip().upper() in stated
            flagged = [o.id for o in self.options if o.is_correct]

        if len(flagged) != 1:
            raise ValueError(
                f"Item '{self.question_id}' must have exactly one correct option, "
                f"found {len(flagged)}. An answer key is never inferred."
            )

        self.correct_answer = flagged[0]
        return self

    @model_validator(mode="after")
    def _check_constructed_response(self) -> "QuestionItem":
        if self.question_type not in CONSTRUCTED_RESPONSE:
            return self

        if not self.model_answer.strip():
            raise ValueError(
                f"{self.question_type} item '{self.question_id}' is missing a model_answer"
            )
        if not self.marking_scheme.strip() and not self.rubric.is_complete():
            raise ValueError(
                f"{self.question_type} item '{self.question_id}' needs either a "
                f"marking_scheme or a complete four-level rubric"
            )
        return self

    @model_validator(mode="after")
    def _check_marks(self) -> "QuestionItem":
        """Part marks must sum to the item's total, or the paper won't add up."""
        if not self.structured_parts:
            return self
        part_total = sum(p.marks for p in self.structured_parts)
        if part_total and self.pedagogy.max_marks and part_total != self.pedagogy.max_marks:
            # Trust the parts — they are what gets printed next to each sub-question.
            self.pedagogy.max_marks = part_total
        elif part_total and not self.pedagogy.max_marks:
            self.pedagogy.max_marks = part_total
        return self

    @model_validator(mode="after")
    def _check_diagram_question(self) -> "QuestionItem":
        if self.question_type == "diagram_based" and self.diagram is None:
            raise ValueError(
                f"diagram_based item '{self.question_id}' has no diagram binding. "
                f"A diagram question with no diagram cannot be printed."
            )
        return self

    # ── Serialisation for the public API ────────────────────────────────────

    def to_public_dict(self, include_answers: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "question_id": self.question_id,
            "universal_id": self.universal_id,
            "display_label": self.display_label,
            "version": self.version,
            "question_type": self.question_type,
            "family": self.family,
            "curriculum": self.curriculum.model_dump(),
            "pedagogy": self.pedagogy.model_dump(),
            "stimulus_context": self.stimulus_context,
            "question_text": self.question_text,
            "structured_parts": [
                {"part_id": p.part_id, "sub_question": p.sub_question, "marks": p.marks}
                for p in self.structured_parts
            ],
            "diagram": self.diagram.model_dump() if self.diagram else None,
            "provenance_citation": self.provenance_citation,
            "dna_id": self.dna_id,
            "status": self.status,
        }

        data["options"] = [
            {"id": o.id, "text": o.text} if not include_answers else o.model_dump()
            for o in self.options
        ]

        if include_answers:
            data["correct_answer"] = self.correct_answer
            data["model_answer"] = self.model_answer
            data["marking_scheme"] = self.marking_scheme
            data["rubric"] = self.rubric.model_dump()
            for src, dst in zip(self.structured_parts, data["structured_parts"]):
                dst["model_answer"] = src.model_answer

        return data


class QuestionBatch(BaseModel):
    sub_strand: str
    items: list[QuestionItem] = Field(default_factory=list)
    rejected: list[dict[str, Any]] = Field(default_factory=list)

    def mix(self) -> dict[str, float]:
        total = len(self.items)
        if not total:
            return {"selected_response": 0.0, "constructed_response": 0.0}
        selected = sum(1 for i in self.items if i.family == "selected_response")
        return {
            "selected_response": round(selected / total, 4),
            "constructed_response": round((total - selected) / total, 4),
        }

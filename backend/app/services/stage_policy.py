"""What each stage must pass before its output may move on.

The gate was one rule for the whole pipeline: two review layers, two vendors, a
person signs. That is right for a lesson plan and absurd for reading a strand
list out of a table that is already correct — so an operator either ran a full
review chain on an extraction, or turned the gate off and lost it for the
lesson plan too.

A stage is a build step. This is its quality gate, configured per step the way
a build configures its own tests: some steps run a linter, some run the full
suite, and one of them will not deploy without a person's name on it.

The defaults below are opinions, not laws. They are set from what each stage
actually risks: an extraction can be wrong but rarely dangerous; a lesson plan
reaches a classroom; the material is the only thing a child hears verbatim.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-stage-policy")


@dataclass(slots=True)
class Policy:
    stage: str
    required_layers: list[int] = field(default_factory=list)
    min_vendors: int = 1
    overall_target: int = 90
    dimension_target: int = 85
    requires_human: bool = True
    blocks_downstream: bool = True
    max_refine_cycles: int = 3
    updated_by: str = ""
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "required_layers": list(self.required_layers),
            "min_vendors": self.min_vendors,
            "overall_target": self.overall_target,
            "dimension_target": self.dimension_target,
            "requires_human": self.requires_human,
            "blocks_downstream": self.blocks_downstream,
            "max_refine_cycles": self.max_refine_cycles,
            "updated_by": self.updated_by,
            "why": self.why,
        }


# Ordered as the pipeline runs. The board reads this, so a stage added here
# appears on it without a second list to keep in step.
DEFAULTS: tuple[Policy, ...] = (
    Policy(
        "ingest", required_layers=[], min_vendors=1,
        requires_human=False, blocks_downstream=True, max_refine_cycles=0,
        why="Reading the design document in. Nothing is authored, so there is "
            "no judgement to review — but everything downstream is wrong if "
            "this is, so it still blocks.",
    ),
    Policy(
        "strands", required_layers=[2], min_vendors=1,
        overall_target=85, dimension_target=80,
        requires_human=False, blocks_downstream=True, max_refine_cycles=2,
        why="Extraction from a table that is already correct. One reviewer is "
            "enough: invention is the risk, not judgement, and a second vendor "
            "would be asked the same easy question twice.",
    ),
    Policy(
        "substrands", required_layers=[2], min_vendors=1,
        overall_target=85, dimension_target=80,
        requires_human=False, blocks_downstream=True, max_refine_cycles=2,
        why="Also extraction, and the outcomes and rubrics it reads out are "
            "what every later stage is checked against.",
    ),
    Policy(
        "notes", required_layers=[2, 3], min_vendors=2,
        overall_target=90, dimension_target=85,
        requires_human=True, blocks_downstream=True, max_refine_cycles=3,
        why="The lesson plan reaches a classroom, and everything below is "
            "drawn from it. Two layers from two vendors, and a person signs — "
            "coverage counts approved work as taught-ready.",
    ),
    Policy(
        "material", required_layers=[2, 3], min_vendors=2,
        overall_target=92, dimension_target=88,
        requires_human=True, blocks_downstream=False, max_refine_cycles=3,
        why="The only stage whose product a child hears verbatim, so the bar "
            "is the highest here. It blocks nothing downstream because nothing "
            "is drawn from it — it is the deliverable.",
    ),
    Policy(
        "diagram", required_layers=[2], min_vendors=1,
        overall_target=88, dimension_target=80,
        requires_human=True, blocks_downstream=False, max_refine_cycles=2,
        why="A picture of the wrong lesson passes every check that judges the "
            "picture. A person seeing it beside the plan is the check that "
            "works.",
    ),
    Policy(
        "media", required_layers=[2], min_vendors=1,
        overall_target=85, dimension_target=80,
        requires_human=False, blocks_downstream=False, max_refine_cycles=2,
        why="A brief for a photograph or a video. Somebody reads it before "
            "spending money on the shoot, which is a later gate than this one.",
    ),
    Policy(
        "simulation", required_layers=[2], min_vendors=1,
        overall_target=88, dimension_target=80,
        requires_human=True, blocks_downstream=False, max_refine_cycles=2,
        why="It will be built and run. A person sees it work before it is "
            "put in front of a class.",
    ),
    Policy(
        "activity", required_layers=[2], min_vendors=1,
        overall_target=88, dimension_target=82,
        requires_human=True, blocks_downstream=False, max_refine_cycles=2,
        why="Children do these with their hands. Safety is judged by a person, "
            "not by a score.",
    ),
    Policy(
        "questions", required_layers=[2, 3], min_vendors=2,
        overall_target=90, dimension_target=85,
        requires_human=True, blocks_downstream=False, max_refine_cycles=3,
        why="These are marked, and a wrong answer key is wrong for every "
            "learner who sat the paper.",
    ),
)

STAGES: tuple[str, ...] = tuple(p.stage for p in DEFAULTS)
_BY_STAGE = {p.stage: p for p in DEFAULTS}


def default_for(stage: str) -> Policy:
    base = _BY_STAGE.get(stage)
    if base:
        return Policy(**{**base.to_dict(), "required_layers": list(base.required_layers)})
    # An unknown stage gets the strictest sensible default rather than none:
    # a stage nobody has configured should not be the one with no gate.
    return Policy(stage=stage, required_layers=[2], min_vendors=1,
                  why="No policy is defined for this stage, so the "
                      "conservative default applies.")


def all_policies() -> list[Policy]:
    """Every stage's gate, with whatever has been configured over the default."""
    stored: dict[str, dict[str, Any]] = {}
    try:
        from ..infra.db import fetch_all

        for row in fetch_all("SELECT * FROM stage_policies") or []:
            stored[str(row["stage"])] = dict(row)
    except Exception as exc:  # noqa: BLE001
        # A missing table is not a reason to refuse to show the board.
        logger.warning("Could not read stage policies (%s); using defaults.", exc)

    out = []
    for stage in STAGES:
        policy = default_for(stage)
        row = stored.get(stage)
        if row:
            policy.required_layers = [int(n) for n in (row.get("required_layers") or [])]
            policy.min_vendors = int(row.get("min_vendors") or 1)
            policy.overall_target = int(row.get("overall_target") or 90)
            policy.dimension_target = int(row.get("dimension_target") or 85)
            policy.requires_human = bool(row.get("requires_human"))
            policy.blocks_downstream = bool(row.get("blocks_downstream"))
            policy.max_refine_cycles = int(row.get("max_refine_cycles") or 0)
            policy.updated_by = str(row.get("updated_by") or "")
        out.append(policy)
    return out


def for_stage(stage: str) -> Policy:
    return next((p for p in all_policies() if p.stage == stage), default_for(stage))


def save(stage: str, changes: dict[str, Any], *, updated_by: str = "") -> Policy:
    """Change one stage's gate. Everything else is left where it was."""
    from ..errors import raise_api_error
    from ..infra.db import execute

    if stage not in STAGES:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{stage}' is not a pipeline stage. The stages are: "
            f"{', '.join(STAGES)}.",
        )

    policy = for_stage(stage)
    layers = changes.get("required_layers", policy.required_layers)
    layers = sorted({int(n) for n in layers if int(n) in (1, 2, 3)})

    values = {
        "stage": stage,
        "required_layers": layers,
        "min_vendors": max(1, min(3, int(changes.get("min_vendors", policy.min_vendors)))),
        "overall_target": max(0, min(100, int(changes.get("overall_target", policy.overall_target)))),
        "dimension_target": max(0, min(100, int(changes.get("dimension_target", policy.dimension_target)))),
        "requires_human": bool(changes.get("requires_human", policy.requires_human)),
        "blocks_downstream": bool(changes.get("blocks_downstream", policy.blocks_downstream)),
        "max_refine_cycles": max(0, min(6, int(changes.get("max_refine_cycles", policy.max_refine_cycles)))),
        "updated_by": updated_by,
    }
    if values["min_vendors"] > max(1, len(values["required_layers"])):
        raise_api_error(
            "VALIDATION_FAILED",
            f"{stage} asks for {values['min_vendors']} vendors across "
            f"{len(values['required_layers'])} required layer(s). A vendor "
            f"count above the layer count can never be satisfied, and the "
            f"stage would block for ever.",
        )

    execute(
        """
        INSERT INTO stage_policies
            (stage, required_layers, min_vendors, overall_target,
             dimension_target, requires_human, blocks_downstream,
             max_refine_cycles, updated_by, updated_at)
        VALUES
            (:stage, :required_layers, :min_vendors, :overall_target,
             :dimension_target, :requires_human, :blocks_downstream,
             :max_refine_cycles, :updated_by, NOW())
        ON CONFLICT (stage) DO UPDATE SET
            required_layers = EXCLUDED.required_layers,
            min_vendors = EXCLUDED.min_vendors,
            overall_target = EXCLUDED.overall_target,
            dimension_target = EXCLUDED.dimension_target,
            requires_human = EXCLUDED.requires_human,
            blocks_downstream = EXCLUDED.blocks_downstream,
            max_refine_cycles = EXCLUDED.max_refine_cycles,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW()
        """,
        values,
    )
    logger.info("Stage policy for %s changed by %s.", stage, updated_by or "?")
    return for_stage(stage)


def reset(stage: str) -> Policy:
    """Back to the default, so a stage can be un-fiddled with."""
    from ..infra.db import execute

    execute("DELETE FROM stage_policies WHERE stage = :stage", {"stage": stage})
    return default_for(stage)

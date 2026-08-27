"""Curriculum coverage measurement.

Progress used to be scored against four constants — 4 hours, 8 visuals, 4
activities, 10 questions — regardless of what a sub-strand's KICD design
actually required. A 10-hour sub-strand reported complete after 4 hours; a
2-hour one could never exceed 50%.

Requirements are now derived from the blueprint the curriculum extractor already
stores, and where a blueprint field is missing the fallback is marked
``estimated`` so the dashboard can distinguish a measurement from a guess.

The heaviest-weighted dimension is SLO coverage. Artifact counts say how much was
produced; only SLO coverage says whether the curriculum was actually taught.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Weights sum to 1.0. SLO coverage dominates because ten questions all testing
# the same outcome is not the same as ten questions covering the sub-strand.
WEIGHTS: dict[str, float] = {
    "notes": 0.18,
    "visuals": 0.12,
    # Photographs and videos were produced by the factory and counted by
    # nothing, so a sub-strand with a full media plan and a sub-strand with none
    # scored identically. What is not measured does not get made.
    "media": 0.08,
    "practicals": 0.12,
    "questions": 0.18,
    "slo_coverage": 0.24,
    # Produced is not the same as fit to teach. Without this a sub-strand could
    # read 100% while every artifact in it was still an unreviewed draft.
    "approved": 0.08,
}

# Media a sub-strand needs when the design does not say. Deliberately small:
# two strong assets beat six weak ones, and each costs money to produce.
FALLBACK_MEDIA = 2

# Used only when the blueprint is silent. Each one flips `estimated` to True.
FALLBACK_HOURS = 4
FALLBACK_VISUALS_PER_HOUR = 2
FALLBACK_ACTIVITIES_PER_HOUR = 1
ITEMS_PER_SLO = 3

_NUMBER = re.compile(r"\d+")


def parse_allocated_hours(raw: Any) -> tuple[int, bool]:
    """Read '4 hours', '10 Lessons', 8 or '' into an hour count.

    Returns ``(hours, estimated)`` — ``estimated`` is True when the blueprint
    gave nothing usable and the fallback was applied.
    """
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw), False
    if isinstance(raw, str):
        found = _NUMBER.findall(raw)
        if found:
            hours = int(found[0])
            if 0 < hours <= 60:
                return hours, False
    return FALLBACK_HOURS, True


@dataclass(slots=True)
class Requirement:
    """What a sub-strand needs, and whether we actually know that."""

    hours: int
    visuals: int
    practicals: int
    questions: int
    slos: int
    media: int = FALLBACK_MEDIA
    estimated: dict[str, bool] = field(default_factory=dict)

    @property
    def any_estimated(self) -> bool:
        return any(self.estimated.values())


def derive_requirement(node: dict[str, Any]) -> Requirement:
    """Turn a blueprint sub-strand row into its production requirement."""
    hours, hours_estimated = parse_allocated_hours(node.get("allocated_hours"))

    required_diagrams = node.get("required_diagrams") or []
    experiments = node.get("experiments") or []
    slos = node.get("slos") or []

    visuals = len(required_diagrams) if required_diagrams else hours * FALLBACK_VISUALS_PER_HOUR
    practicals = len(experiments) if experiments else hours * FALLBACK_ACTIVITIES_PER_HOUR
    questions = (len(slos) * ITEMS_PER_SLO) if slos else hours * ITEMS_PER_SLO

    required_media = node.get("required_media") or []
    media = len(required_media) if required_media else FALLBACK_MEDIA

    return Requirement(
        hours=max(1, hours),
        visuals=max(1, visuals),
        practicals=max(1, practicals),
        questions=max(1, questions),
        slos=len(slos),
        media=max(1, media),
        estimated={
            "hours": hours_estimated,
            "visuals": not bool(required_diagrams),
            "practicals": not bool(experiments),
            "questions": not bool(slos),
            "slo_coverage": not bool(slos),
            "media": not bool(required_media),
            # Approval is counted, never estimated: a guessed approval is the
            # one number that must never be guessed.
            "approved": False,
        },
    )


def _pct(generated: int, required: int) -> int:
    if required <= 0:
        return 0
    return min(100, round((generated / required) * 100))


def _slo_ids_in(items: list[Any]) -> set[str]:
    """Distinct SLOs actually addressed by a set of generated questions."""
    found: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        slo = (
            (item.get("curriculum") or {}).get("slo_id")
            or item.get("target_slo")
            or item.get("slo_id")
        )
        if slo and str(slo).strip():
            found.add(str(slo).strip().lower())
    return found


def _blueprint_slo_ids(slos: list[Any]) -> set[str]:
    ids: set[str] = set()
    for idx, slo in enumerate(slos or []):
        if isinstance(slo, dict):
            key = slo.get("slo_id") or slo.get("id") or slo.get("code") or f"slo-{idx + 1}"
        else:
            key = f"slo-{idx + 1}"
        ids.add(str(key).strip().lower())
    return ids


def compute_substrand_coverage(
    node: dict[str, Any],
    generated: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score one sub-strand against its own curriculum requirement."""
    requirement = derive_requirement(node)

    notes = (generated or {}).get("notes") or {}
    diagrams = (generated or {}).get("diagrams") or []
    activities_raw = (generated or {}).get("activities") or []
    questions = (generated or {}).get("questions") or []

    modules = notes.get("hour_modules") or notes.get("key_concepts") or [] if isinstance(notes, dict) else []
    hours_generated = (
        len(modules) if isinstance(modules, list) and modules
        else (requirement.hours if isinstance(notes, dict) and notes.get("full_lecture_notes") else 0)
    )

    visuals_generated = len(diagrams) if isinstance(diagrams, list) else 0

    if isinstance(activities_raw, dict):
        practicals_generated = len(activities_raw.get("activities") or []) + len(
            activities_raw.get("experiments") or []
        )
    else:
        practicals_generated = len(activities_raw) if isinstance(activities_raw, list) else 0

    questions_generated = len(questions) if isinstance(questions, list) else 0

    # Planning a photograph is not producing it, so only produced assets count.
    media_items = (generated or {}).get("media") or []
    media_generated = sum(
        1 for m in media_items
        if isinstance(m, dict) and str(m.get("status") or "") == "produced"
    ) if isinstance(media_items, list) else 0
    media_planned = len(media_items) if isinstance(media_items, list) else 0

    approved_items = (generated or {}).get("approved") or {}
    approved_count = int(approved_items.get("approved", 0)) if isinstance(approved_items, dict) else 0
    approvable_count = int(approved_items.get("total", 0)) if isinstance(approved_items, dict) else 0

    blueprint_slos = _blueprint_slo_ids(node.get("slos") or [])
    if blueprint_slos:
        addressed = _slo_ids_in(questions) & blueprint_slos
        slo_pct = _pct(len(addressed), len(blueprint_slos))
        slos_addressed, slos_total = len(addressed), len(blueprint_slos)
    else:
        # No blueprint SLOs to measure against: fall back to question volume so
        # the dimension still moves, and flag it as estimated.
        slo_pct = _pct(questions_generated, requirement.questions)
        slos_addressed, slos_total = 0, 0

    dimensions = {
        "notes": {
            "generated": hours_generated,
            "required": requirement.hours,
            "remaining": max(0, requirement.hours - hours_generated),
            "percentage": _pct(hours_generated, requirement.hours),
            "estimated": requirement.estimated["hours"],
        },
        "visuals": {
            "generated": visuals_generated,
            "required": requirement.visuals,
            "remaining": max(0, requirement.visuals - visuals_generated),
            "percentage": _pct(visuals_generated, requirement.visuals),
            "estimated": requirement.estimated["visuals"],
        },
        "practicals": {
            "generated": practicals_generated,
            "required": requirement.practicals,
            "remaining": max(0, requirement.practicals - practicals_generated),
            "percentage": _pct(practicals_generated, requirement.practicals),
            "estimated": requirement.estimated["practicals"],
        },
        "questions": {
            "generated": questions_generated,
            "required": requirement.questions,
            "remaining": max(0, requirement.questions - questions_generated),
            "percentage": _pct(questions_generated, requirement.questions),
            "estimated": requirement.estimated["questions"],
        },
        "slo_coverage": {
            "generated": slos_addressed,
            "required": slos_total,
            "remaining": max(0, slos_total - slos_addressed),
            "percentage": slo_pct,
            "estimated": requirement.estimated["slo_coverage"],
        },
        "media": {
            "generated": media_generated,
            "planned": media_planned,
            "required": requirement.media,
            "remaining": max(0, requirement.media - media_generated),
            "percentage": _pct(media_generated, requirement.media),
            "estimated": requirement.estimated["media"],
        },
        "approved": {
            "generated": approved_count,
            "required": max(1, approvable_count),
            "remaining": max(0, approvable_count - approved_count),
            "percentage": _pct(approved_count, approvable_count) if approvable_count else 0,
            "estimated": False,
        },
    }

    overall = round(sum(dimensions[name]["percentage"] * weight for name, weight in WEIGHTS.items()))

    # Production ready means every dimension is genuinely met, not that a few
    # thresholds were cleared.
    production_ready = all(dimensions[name]["percentage"] >= 100 for name in WEIGHTS)

    return {
        "dimensions": dimensions,
        "overall_percentage": overall,
        "production_ready": production_ready,
        "allocated_hours": node.get("allocated_hours") or f"{requirement.hours} hours",
        "weight_hours": requirement.hours,
        "estimated": requirement.any_estimated,
    }


def weighted_rollup(children: list[dict[str, Any]]) -> int:
    """Roll up child percentages weighted by teaching hours.

    A 10-hour sub-strand represents five times the curriculum of a 2-hour one, so
    averaging them equally understates how much work is left.
    """
    if not children:
        return 0
    total_weight = sum(max(1, c.get("weight_hours", 1)) for c in children)
    if total_weight <= 0:
        return 0
    return round(
        sum(c.get("overall_percentage", 0) * max(1, c.get("weight_hours", 1)) for c in children)
        / total_weight
    )


def next_action(node_report: dict[str, Any]) -> dict[str, Any] | None:
    """The single most valuable next step for a sub-strand.

    Ordered by pipeline dependency: notes gate diagrams and activities, which
    gate questions, which gate SLO coverage. Recommending a later stage before
    an earlier one is finished sends the operator to a station that cannot work.
    """
    dims = node_report["dimensions"]

    sequence = [
        ("notes", "high", "open_studio_station_1", "lesson hour(s) of notes"),
        ("visuals", "medium", "open_studio_station_2", "diagram(s)"),
        ("practicals", "medium", "open_studio_station_3", "practical activity/experiment(s)"),
        ("questions", "low", "open_studio_station_4", "assessment item(s)"),
        ("slo_coverage", "low", "open_studio_station_4", "uncovered learning outcome(s)"),
    ]

    for name, priority, action, noun in sequence:
        remaining = dims[name]["remaining"]
        if remaining > 0:
            return {
                "type": name,
                "priority": priority,
                "action": action,
                "remaining": remaining,
                "message": f"Generate {remaining} more {noun}.",
                "estimated_requirement": dims[name]["estimated"],
            }

    return None

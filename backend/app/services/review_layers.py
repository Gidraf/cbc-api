"""Three layers of review, scored per dimension rather than as one number.

A single "90%" says nothing about WHAT was 90%. Content can be beautifully
written and misaligned with the design, or exactly aligned and pitched at the
wrong age. Both used to score in the eighties. So each dimension is judged and
evidenced separately, and the overall figure is derived from them rather than
asserted by the model.

The layers are:

1. **Self-check** — the generating model reads its own output. Cheap, catches
   obvious breakage, and worth exactly what a marker grading their own paper is
   worth, which is why it cannot approve anything.
2. **Independent review** — a model from a DIFFERENT vendor. Two OpenAI models
   share training data, failure modes and blind spots; asking gpt-4o to check
   gpt-4o-mini is closer to asking twice than to a second opinion. The vendor is
   recorded on the row, so "independently reviewed" is verifiable.
3. **Approver** — the layer that can apply the `approved` label. It reads the
   artifact, both prior reviews, and any human comments.

A regeneration is reviewed as a DIFF against its parent. Re-reading the whole
thing invites a different score for unchanged content, which makes review look
unstable when it is the reading that moved.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-review")

# Each dimension answers a different question, and they fail independently.
DIMENSIONS: dict[str, dict[str, Any]] = {
    "curriculum_alignment": {
        "weight": 0.30,
        "question": "Does this match the KICD design for this grade and learning "
                    "area — its strands, sub-strands, outcomes and time allocation?",
    },
    "guideline_adherence": {
        "weight": 0.15,
        "question": "Does it follow the BECF: the core competencies, the values, "
                    "the PCIs and the assessment approach, named correctly?",
    },
    "factual_correctness": {
        "weight": 0.20,
        "question": "Is every factual claim true, and is every citation real and "
                    "correctly attributed?",
    },
    "level_appropriateness": {
        "weight": 0.20,
        "question": "Can a learner of this age and literacy actually do this, and "
                    "can a teacher deliver it in the time the design allocates?",
    },
    "faith_integrity": {
        "weight": 0.05,
        "question": "For a religious learning area: is it wholly within its own "
                    "faith, with scripture cited accurately and no other faith's "
                    "material mixed in? Score 100 and say 'not applicable' otherwise.",
    },
    "completeness": {
        "weight": 0.10,
        "question": "Is every required field present and substantive, with nothing "
                    "left as a placeholder or invented to fill a slot?",
    },
}

LAYERS: dict[int, dict[str, Any]] = {
    1: {"name": "self_check", "can_approve": False,
        "brief": "Read your own output and report what is wrong with it."},
    2: {"name": "independent_review", "can_approve": False,
        "brief": "You did not write this. Review it as a second opinion."},
    3: {"name": "approver", "can_approve": True,
        "brief": "Decide whether this is fit to publish to Kenyan classrooms."},
}

VERDICTS = ("pass", "revise", "reject")

# What a layer-3 approver must see before it may apply `approved`.
APPROVAL_FLOOR = 80
APPROVAL_DIMENSION_FLOOR = 70


@dataclass(slots=True)
class DimensionScore:
    name: str
    score: int = 0
    evidence: str = ""
    issues: list[str] = field(default_factory=list)
    not_applicable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "score": self.score, "evidence": self.evidence,
            "issues": self.issues, "not_applicable": self.not_applicable,
        }


@dataclass(slots=True)
class ReviewVerdict:
    review_id: str = ""
    artifact_id: str = ""
    artifact_key: str = ""
    layer: int = 1
    layer_name: str = ""
    provider: str = ""
    model: str = ""
    verdict: str = "revise"
    overall_confidence: int = 0
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    compared_with: str = ""
    diff_summary: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id, "artifact_id": self.artifact_id,
            "artifact_key": self.artifact_key, "layer": self.layer,
            "layer_name": self.layer_name, "provider": self.provider,
            "model": self.model, "verdict": self.verdict,
            "overall_confidence": self.overall_confidence,
            "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
            "issues": self.issues, "comments": self.comments,
            "compared_with": self.compared_with, "diff_summary": self.diff_summary,
            "usage": self.usage,
            "weakest": self.weakest(),
        }

    def weakest(self) -> str:
        applicable = [d for d in self.dimensions.values() if not d.not_applicable]
        if not applicable:
            return ""
        return min(applicable, key=lambda d: d.score).name


def score_dimensions(raw: dict[str, Any]) -> dict[str, DimensionScore]:
    """Read a model's dimension block, filling gaps rather than inventing scores.

    A dimension the reviewer did not answer scores 0 and says so. Defaulting it
    to a pass is how an unreviewed dimension becomes an approved one.
    """
    scores: dict[str, DimensionScore] = {}
    reported = raw if isinstance(raw, dict) else {}

    for name in DIMENSIONS:
        entry = reported.get(name)
        if not isinstance(entry, dict):
            scores[name] = DimensionScore(
                name=name, score=0,
                evidence="The reviewer did not report this dimension.",
                issues=["not assessed"],
            )
            continue

        not_applicable = bool(entry.get("not_applicable"))
        try:
            value = int(float(entry.get("score", 0)))
        except (TypeError, ValueError):
            value = 0
        scores[name] = DimensionScore(
            name=name,
            score=100 if not_applicable else max(0, min(100, value)),
            evidence=str(entry.get("evidence") or "")[:1200],
            issues=[str(i)[:400] for i in (entry.get("issues") or [])][:12],
            not_applicable=not_applicable,
        )
    return scores


def overall_from(dimensions: dict[str, DimensionScore]) -> int:
    """The weighted mean of what was actually assessed.

    Derived, never taken from the model: a model asked for both its dimensions
    and an overall will produce an overall that flatters its dimensions.
    """
    total_weight = 0.0
    total = 0.0
    for name, meta in DIMENSIONS.items():
        score = dimensions.get(name)
        if score is None or score.not_applicable:
            continue
        total += score.score * meta["weight"]
        total_weight += meta["weight"]
    return round(total / total_weight) if total_weight else 0


def decide(dimensions: dict[str, DimensionScore], overall: int) -> str:
    """pass / revise / reject, from the dimensions rather than the vibe."""
    applicable = [d for d in dimensions.values() if not d.not_applicable]
    if not applicable:
        return "revise"
    worst = min(d.score for d in applicable)
    if overall >= APPROVAL_FLOOR and worst >= APPROVAL_DIMENSION_FLOOR:
        return "pass"
    if overall < 50 or worst < 40:
        return "reject"
    return "revise"


def _schema_block() -> str:
    lines = ["{", '  "dimensions": {']
    for name, meta in DIMENSIONS.items():
        lines.append(f'    "{name}": {{')
        lines.append(f'      "//": "{meta["question"]}",')
        lines.append('      "score": 0,')
        lines.append('      "evidence": "What in the artifact makes this the score. Quote it.",')
        lines.append('      "issues": ["Specific, actionable defect"],')
        lines.append('      "not_applicable": false')
        lines.append("    },")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("  },")
    lines.append('  "issues": [{"severity": "high|medium|low", "where": "field or section",')
    lines.append('              "what": "the defect", "fix": "what to change"}],')
    lines.append('  "comments": ["Anything a human reviewer should read."]')
    lines.append("}")
    return "\n".join(lines)


def build_messages(
    artifact: Any, layer: int, *,
    design_extract: str = "", register: str = "", faith: str = "",
    prior_reviews: list[dict[str, Any]] | None = None,
    human_comments: list[str] | None = None,
    diff_summary: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """The review prompt. Assembled here so all three layers score alike."""
    meta = LAYERS.get(layer, LAYERS[1])

    system = [
        "You are a KICD curriculum reviewer for Kenyan basic education.",
        meta["brief"],
        "",
        "Score each dimension 0-100 SEPARATELY. They fail independently: content "
        "can be beautifully written and misaligned with the design, or exactly "
        "aligned and pitched at the wrong age.",
        "",
        "Every score needs evidence from the artifact itself. A score without "
        "evidence is an opinion, and an opinion cannot be checked.",
        "Do not report an overall figure — it is computed from your dimensions.",
        "Where a dimension does not apply, set not_applicable and say why in "
        "evidence. Do not give it a passing score to move on.",
        "Be specific and be hard. Approving weak content costs a Kenyan child a "
        "lesson; rejecting good content costs an author ten minutes.",
    ]
    if register:
        system += ["", "=== WHO THIS IS FOR ===", register]
    if faith:
        system += ["", faith]

    user: list[str] = []
    if diff_summary:
        user += [
            "=== THIS IS A REGENERATION ===",
            f"Version {diff_summary.get('previous_version')} → "
            f"{diff_summary.get('current_version')}.",
            "Review WHAT CHANGED. Unchanged content was reviewed before; "
            "re-litigating it produces a different score for the same text.",
            "State plainly whether each change is an improvement, a regression, "
            "or neither.",
            json.dumps(diff_summary, indent=2, default=str)[:6000],
            "",
        ]

    if design_extract:
        user += ["=== WHAT THE KICD DESIGN SAYS ===", design_extract, ""]

    user += [
        "=== THE ARTIFACT UNDER REVIEW ===",
        f"Kind: {getattr(artifact, 'kind', '')}",
        f"Grade: {getattr(artifact, 'grade', '')}",
        f"Subject: {getattr(artifact, 'subject', '')}",
        f"Strand: {getattr(artifact, 'strand_name', '')}",
        f"Sub-strand: {getattr(artifact, 'sub_strand_name', '')}",
        f"Version: {getattr(artifact, 'version', 1)}",
        "",
        json.dumps(getattr(artifact, "content", {}), indent=2, default=str)[:60_000],
        "",
    ]

    for prior in prior_reviews or []:
        user += [
            f"=== LAYER {prior.get('layer')} REVIEW "
            f"({prior.get('provider')}/{prior.get('model')}) ===",
            f"Verdict: {prior.get('verdict')} at {prior.get('overall_confidence')}%.",
            json.dumps(prior.get("dimensions") or {}, indent=2, default=str)[:6000],
            "You are not bound by it. Where you disagree, say so and why.",
            "",
        ]

    if human_comments:
        user += ["=== WHAT HUMAN REVIEWERS SAID ===",
                 *[f"- {c}" for c in human_comments[:20]], ""]

    user += ["Return ONLY valid JSON matching this schema:", _schema_block()]

    return [
        {"role": "system", "content": "\n".join(system)},
        {"role": "user", "content": "\n".join(user)},
    ]


def from_response(
    content: dict[str, Any], artifact: Any, layer: int, provider: str, model: str,
) -> ReviewVerdict:
    dimensions = score_dimensions(content.get("dimensions") or {})
    overall = overall_from(dimensions)
    seed = f"{getattr(artifact, 'artifact_id', '')}:{layer}:{provider}:{model}:{overall}"

    return ReviewVerdict(
        review_id=f"rev_{hashlib.sha256(seed.encode()).hexdigest()[:16]}",
        artifact_id=getattr(artifact, "artifact_id", ""),
        artifact_key=getattr(artifact, "artifact_key", ""),
        layer=layer,
        layer_name=LAYERS.get(layer, LAYERS[1])["name"],
        provider=provider,
        model=model,
        verdict=decide(dimensions, overall),
        overall_confidence=overall,
        dimensions=dimensions,
        issues=[i for i in (content.get("issues") or []) if isinstance(i, dict)][:40],
        comments=[str(c)[:600] for c in (content.get("comments") or [])][:20],
    )


def save(verdict: ReviewVerdict) -> None:
    from ..infra.db import execute, to_json

    execute(
        """
        INSERT INTO artifact_reviews (
            review_id, artifact_id, artifact_key, layer, layer_name, provider, model,
            verdict, overall_confidence, dimensions, issues, comments,
            compared_with, diff_summary, usage
        )
        VALUES (
            :review_id, :artifact_id, :artifact_key, :layer, :layer_name, :provider,
            :model, :verdict, :overall_confidence, CAST(:dimensions AS jsonb),
            CAST(:issues AS jsonb), CAST(:comments AS jsonb), :compared_with,
            CAST(:diff_summary AS jsonb), CAST(:usage AS jsonb)
        )
        ON CONFLICT (review_id) DO UPDATE SET
            verdict = EXCLUDED.verdict,
            overall_confidence = EXCLUDED.overall_confidence,
            dimensions = EXCLUDED.dimensions,
            issues = EXCLUDED.issues,
            comments = EXCLUDED.comments,
            created_at = NOW()
        """,
        {
            "review_id": verdict.review_id, "artifact_id": verdict.artifact_id,
            "artifact_key": verdict.artifact_key, "layer": verdict.layer,
            "layer_name": verdict.layer_name, "provider": verdict.provider,
            "model": verdict.model, "verdict": verdict.verdict,
            "overall_confidence": verdict.overall_confidence,
            "dimensions": to_json({k: v.to_dict() for k, v in verdict.dimensions.items()}),
            "issues": to_json(verdict.issues), "comments": to_json(verdict.comments),
            "compared_with": verdict.compared_with,
            "diff_summary": to_json(verdict.diff_summary),
            "usage": to_json(verdict.usage),
        },
    )


def reviews_for(artifact_id: str) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    return fetch_all(
        "SELECT * FROM artifact_reviews WHERE artifact_id = :id ORDER BY layer ASC, created_at DESC",
        {"id": artifact_id},
    ) or []


def approval_state(artifact_id: str) -> dict[str, Any]:
    """Whether this version may be approved, and precisely what is missing."""
    reviews = reviews_for(artifact_id)
    by_layer = {int(r["layer"]): r for r in reviews}

    blockers: list[str] = []
    for layer in (2, 3):
        if layer not in by_layer:
            blockers.append(f"layer {layer} ({LAYERS[layer]['name']}) has not run")

    vendors = {str(r.get("provider") or "") for r in reviews if int(r["layer"]) in (1, 2)}
    if len(by_layer) >= 2 and len(vendors) < 2:
        blockers.append(
            "layers 1 and 2 used the same vendor — two models from one vendor "
            "share failure modes, so that is one opinion asked twice"
        )

    for layer, review in by_layer.items():
        if review.get("verdict") == "reject":
            blockers.append(f"layer {layer} rejected it")
        elif layer == 3 and review.get("verdict") != "pass":
            blockers.append("the approver did not pass it")

    return {
        "artifact_id": artifact_id,
        "can_approve": not blockers,
        "blockers": blockers,
        "layers_run": sorted(by_layer),
        "vendors": sorted(v for v in vendors if v),
        "reviews": [
            {"layer": r["layer"], "verdict": r["verdict"],
             "confidence": r["overall_confidence"],
             "provider": r["provider"], "model": r["model"]}
            for r in reviews
        ],
    }

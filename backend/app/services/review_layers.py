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

# What each kind of artifact is actually FOR.
#
# Without this the dimensions are read as though every artifact should contain
# everything. A strand list came back scored 40 on completeness and 50 on
# guideline adherence for "lacking sub-strands, specific learning outcomes,
# core competencies, values and PCIs" — none of which a strand list carries.
# Those live on the sub-strand, one layer down, and the reviewer was marking
# content down for not being a different artifact.
#
# `holds` is what the kind must contain to be complete. `elsewhere` is what a
# reviewer will look for, not find, and must NOT penalise.
KIND_SCOPE: dict[str, dict[str, str]] = {
    "strand": {
        "is": "the list of strands KICD publishes for this learning area, with a "
              "one-line description of each.",
        "holds": "every published strand, named as the design names it, in the "
                 "design's own order, with nothing invented and nothing dropped.",
        "elsewhere": "sub-strands, specific learning outcomes, learning experiences, "
                     "key inquiry questions, core competencies, values, PCIs, "
                     "assessment rubrics and lesson counts. These belong to the "
                     "SUB-STRAND artifacts under each strand and their absence here "
                     "is correct.",
    },
    "sub_strand": {
        "is": "one sub-strand of a strand, as the design's table sets it out.",
        "holds": "its name, its lesson allocation, its specific learning outcomes, "
                 "the suggested learning experiences, the key inquiry question(s), "
                 "core competencies, values, PCIs, the link to other learning areas, "
                 "the assessment rubric, and the pages it was read from.",
        "elsewhere": "teaching notes, diagrams, activities and questions, which are "
                     "generated FROM this sub-strand and reviewed separately.",
    },
    "notes": {
        "is": "the teaching notes for one sub-strand, one module per lesson the "
              "design funds.",
        "holds": "a module per allocated lesson, each teaching the design's own "
                 "suggested learning experiences, at the register of this learner, "
                 "and making the sub-strand's assessment rubric achievable.",
        "elsewhere": "the sub-strand's own outcomes and rubric — those are the input "
                     "to these notes, shown above, not something the notes restate.",
    },
    "hour_module": {
        "is": "one lesson's worth of the teaching notes.",
        "holds": "what is taught in this lesson and how, for its stated duration.",
        "elsewhere": "the other lessons of the sub-strand.",
    },
    "diagram": {
        "is": "the visual plan for a sub-strand, or one diagram in it.",
        "holds": "visuals that a learner at this level can read, each tied to "
                 "something the notes actually teach.",
        "elsewhere": "the notes themselves, and any photograph or video, which are "
                     "separate artifacts.",
    },
    "photo_prompt": {
        "is": "the brief for a photograph to be taken or sourced — not the photo.",
        "holds": "what the image must show, the setting, who is in it, the alt text, "
                 "and any consent or dignity constraint.",
        "elsewhere": "the image file, and anything programmable — a photograph is "
                     "neither generated as code nor editable afterwards.",
    },
    "video_prompt": {
        "is": "the brief and shot list for a video — not the video.",
        "holds": "the shots, their order, the narration or dialogue, the duration, "
                 "and what a learner should take from it.",
        "elsewhere": "the video file itself.",
    },
    "simulation": {
        "is": "the build brief for one interactive simulation — not the code.",
        "holds": "the concept model with its equations and constants, the controls "
                 "with their ranges and units, what is drawn, what updates, the "
                 "predict and explain steps, the build instruction and the "
                 "acceptance criteria a built version must meet.",
        "elsewhere": "the running simulation itself. Judge whether this brief is "
                     "buildable and whether the model it states is CORRECT — a "
                     "simulation that is subtly wrong teaches the wrong thing more "
                     "convincingly than a wrong sentence.",
    },
    "experiment": {
        "is": "one practical investigation for a sub-strand.",
        "holds": "the materials a Kenyan classroom at this level actually has, the "
                 "steps, what learners should observe, and any REAL hazard.",
        "elsewhere": "invented hazards. Where an activity has none, saying so is "
                     "correct and must not be marked down.",
    },
    "activity": {
        "is": "the hands-on tasks planned for a sub-strand.",
        "holds": "tasks a teacher can run in the time available with what they have.",
        "elsewhere": "the notes and the assessment items.",
    },
    "question": {
        "is": "assessment items for a sub-strand.",
        "holds": "items that test the sub-strand's own outcomes, at this level, "
                 "each traceable to the outcome it assesses.",
        "elsewhere": "the teaching content the items assess.",
    },
    "answer": {
        "is": "the marking scheme for assessment items.",
        "holds": "what earns credit, and what a wrong answer reveals.",
        "elsewhere": "the questions themselves.",
    },
    "ingest": {
        "is": "the result of reading a curriculum design document.",
        "holds": "what the document says: the learning area, its grade, its essence "
                 "statement and the structure found in it.",
        "elsewhere": "anything generated from the design afterwards.",
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

# How much of an artifact fits in one review call.
MAX_ARTIFACT_CHARS = 60_000

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


def _repetition_block(artifact: Any) -> str:
    """What in this artifact is a copy of something else in it.

    A reviewer reads an artifact once, forwards. Lesson 6 reads perfectly well
    on its own and is only wrong beside lesson 5, a page and a half back — so
    padding is the defect reviewers miss most reliably. Measuring it costs
    nothing and cannot be overlooked.
    """
    from . import redundancy_check

    content = getattr(artifact, "content", None)
    if not content:
        return ""
    try:
        return redundancy_check.render(redundancy_check.inspect(content))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not measure repetition for this artifact: %s", exc)
        return ""


def _citation_block(artifact: Any, design_extract: str) -> str:
    """What the design actually says at each address the artifact cites.

    A reviewer was shown a summary of the design and then told to flag any
    address "not in the excerpt". There was no excerpt. It followed the
    instruction the only way it could — by guessing — and reported six real
    citations as fabricated.
    """
    from . import citation_evidence

    content = getattr(artifact, "content", None)
    if not isinstance(content, dict):
        return ""
    evidence = citation_evidence.resolve(content, design_extract or "")
    # An artifact that cites nothing needs no block at all — neither a listing
    # nor a warning that citations could not be checked.
    if not evidence.get("total") and not evidence.get("found"):
        return ""
    return citation_evidence.render(evidence)


def build_messages(
    artifact: Any, layer: int, *,
    design_extract: str = "", missing_design: str = "", descendants: str = "",
    # The page-addressed document, as distinct from the summary above. Only
    # this can settle whether "203:26" is real.
    design_source_text: str = "",
    register: str = "", faith: str = "",
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
        "",
        "CHECK EVERY CLAIM AGAINST THE DESIGN. An analogy is a teaching device "
        "and invents nothing — \"God cares for you the way your mother does\" is "
        "good teaching of a four-year-old and is not a claim. A CLAIM asserts "
        "something is true, and each one has to be traceable to the design in "
        "front of you.",
        "Look specifically for these, and report each one you find under "
        "factual_correctness with the exact text:",
        "  - a scripture reference the design does not name. The design names "
        "its own; anything else was invented, and a teacher will read it aloud "
        "to a class.",
        "  - a statistic, percentage or survey figure. Nothing external was "
        "retrieved for this sub-strand, so any number with a source attached "
        "came from nowhere.",
        "  - an authority named as a source — KNBS, KALRO, NEMA, a ministry, a "
        "report — that does not appear in the design.",
        "  - a page:line address the resolution block below marks as NOT "
        "found. Those addresses have been looked up mechanically for you; an "
        "address marked VERIFIED is real, and calling it fabricated is a false "
        "accusation that strips a correct citation out of good content.",
        "A fabricated citation is worse than a missing one: it survives "
        "inspection. Score factual_correctness low when you find one, and say "
        "which.",
        "",
        "CHECK THE LESSONS AGAINST EACH OTHER, NOT ONLY AGAINST THE DESIGN. "
        "You read forwards, and a padded lesson reads perfectly well on its "
        "own — it is wrong only beside the lesson it copies, which is by then "
        "a page back. This is the defect reviews miss most reliably: a guide "
        "that plans seven lessons by writing four and repeating three passes "
        "every check that measures length, because each copy is full length.",
        "Where the repetition block below reports duplicated lessons, "
        "duplicated exposition or a mirrored lesson list, you MUST raise it in "
        "`issues` naming the lessons, and reflect it in completeness and "
        "curriculum_alignment. Reporting nothing about it is not a pass — it "
        "is the finding going unrecorded.",
        "Repeating an ACTIVITY is not the defect: a song, a prayer or a "
        "routine repeated across lessons is how a young child learns it, and "
        "the design often asks for exactly that. The defect is repeated "
        "TEACHING — the same exposition, the same misconception, the same "
        "check, presented as a new lesson.",
        "Watch for the version of this that is REWRITTEN rather than copied. "
        "Three lessons that discuss how a parent does it, then invent a "
        "gesture, then sing a song — under three different titles, on the same "
        "outcome, citing the same line — are one lesson taught three times, "
        "however different the sentences are. The block below reports the "
        "shape as well as the words.",
        "Where a dimension does not apply, set not_applicable and say why in "
        "evidence. Do not give it a passing score to move on.",
        "Be specific and be hard. Approving weak content costs a Kenyan child a "
        "lesson; rejecting good content costs an author ten minutes.",
    ]
    if register:
        system += ["", "=== WHO THIS IS FOR ===", register]
    if faith:
        system += ["", faith]

    kind = getattr(artifact, "kind", "")
    scope = KIND_SCOPE.get(kind)
    if scope:
        system += [
            "",
            f"=== WHAT A '{kind}' ARTIFACT IS ===",
            f"It is {scope['is']}",
            f"It is COMPLETE when it holds {scope['holds']}",
            f"It does NOT hold: {scope['elsewhere']}",
            "",
            "Score `completeness` against that list and nothing else. A field that "
            "belongs to a different artifact is not missing — it is elsewhere, and "
            "marking this artifact down for it marks it down for not being something "
            "it was never meant to be.",
            "Likewise `guideline_adherence`: judge the BECF requirements THIS artifact "
            "is responsible for. Where core competencies, values and PCIs live on a "
            "different artifact, their absence here is correct.",
        ]

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
            "JUDGE THE NEW STATE, NOT THE FACT THAT IT CHANGED. A diff makes "
            "every removal look like a loss, and asking for removed text back "
            "is how a review turns into a loop: the next version restores it, "
            "the version after that is marked down for the padding it "
            "restored, and nothing improves while both reviews look "
            "reasonable.",
            "Before you object to a removal, read what stands in its place. "
            "Generic filler traded for something specific — \"Visual aids for "
            "singing\" replaced by \"audio clip of a song about God\" — is an "
            "improvement, and calling it a regression asks the author to make "
            "the content worse.",
            "Object to a removal only when the new version is MISSING "
            "something the design requires, and name what the design "
            "requires.",
            json.dumps(diff_summary, indent=2, default=str)[:6000],
            "",
        ]

    if design_extract:
        user += ["=== WHAT THE KICD DESIGN SAYS ===", design_extract, ""]

    repetition_block = _repetition_block(artifact)
    if repetition_block:
        user += [repetition_block, ""]

    citation_block = _citation_block(artifact, design_source_text)
    if citation_block:
        user += [citation_block, ""]
    else:
        user += [
            "=== NO DESIGN WAS AVAILABLE ===",
            missing_design or "The design text for this artifact could not be located.",
            "You are therefore NOT able to judge curriculum_alignment: mark that "
            "dimension not_applicable and say the design was unavailable. Scoring it "
            "anyway means scoring against your own recollection of a Kenyan "
            "curriculum, which is the failure this review exists to catch.",
            "",
        ]

    # `hour_modules` is a copy of `modules` that the notes station keeps for
    # older readers. Sending both doubled the artifact and pushed a seven-lesson
    # guide past the limit, so the reviewer was told the tail was missing when
    # the tail was a copy of the head.
    content = getattr(artifact, "content", {})
    if isinstance(content, dict) and content.get("modules") and content.get("hour_modules"):
        content = {k: v for k, v in content.items() if k != "hour_modules"}
    rendered = json.dumps(content, indent=2, default=str)
    body = rendered[:MAX_ARTIFACT_CHARS]
    truncated = len(rendered) > MAX_ARTIFACT_CHARS

    if descendants:
        user += [
            "=== WHAT ALREADY HANGS OFF THIS, FOR CONTEXT ===",
            "This is NOT under review. It is here so you can tell whether the "
            "artifact above is right in place — whether the counts add up, and "
            "whether anything sits under the wrong parent. Do not score it, and do "
            "not mark the artifact down for content that lives here.",
            descendants,
            "",
        ]

    user += [
        "=== THE ARTIFACT UNDER REVIEW ===",
        f"Kind: {getattr(artifact, 'kind', '')}",
        f"Grade: {getattr(artifact, 'grade', '')}",
        f"Subject: {getattr(artifact, 'subject', '')}",
        f"Strand: {getattr(artifact, 'strand_name', '')}",
        f"Sub-strand: {getattr(artifact, 'sub_strand_name', '')}",
        f"Version: {getattr(artifact, 'version', 1)}",
        "",
        body,
        "",
    ]
    if truncated:
        # Saying so is the whole point: judged silently, a cut-off artifact
        # scores well on completeness because nothing told the reviewer the
        # tail was missing.
        user += [
            f"!!! TRUNCATED: you have been shown {MAX_ARTIFACT_CHARS:,} of "
            f"{len(rendered):,} characters. Do NOT score `completeness` on what is "
            f"missing here — mark that dimension not_applicable and say it was "
            f"truncated. Every other dimension you may judge on what you can see.",
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


def normalise_usage(usage: Any) -> dict[str, Any]:
    """Token counts as a plain dict, whatever the provider client returned.

    Different providers return different shapes here — a dataclass, a pydantic
    model, a bare dict — and the review is worth keeping regardless of which.
    """
    if isinstance(usage, dict):
        return usage
    if usage is None:
        return {}
    for attr in ("model_dump", "to_dict"):
        method = getattr(usage, attr, None)
        if callable(method):
            try:
                return dict(method())
            except Exception:  # noqa: BLE001, S112
                continue
    from dataclasses import asdict, is_dataclass

    if is_dataclass(usage) and not isinstance(usage, type):
        return asdict(usage)
    return {
        field: getattr(usage, field)
        for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(getattr(usage, field, None), int)
    }


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
            "usage": to_json(normalise_usage(verdict.usage)),
        },
    )


def reviews_for(artifact_id: str) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    return fetch_all(
        "SELECT * FROM artifact_reviews WHERE artifact_id = :id ORDER BY layer ASC, created_at DESC",
        {"id": artifact_id},
    ) or []


def _worst(review: dict[str, Any]) -> str:
    """Which dimension held this review back, and by how much.

    "the approver did not pass it" named nothing and pointed nowhere. A
    blocker a person cannot act on is the same defect as a review finding
    nobody can act on.
    """
    raw = review.get("dimensions")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            raw = None
    if not isinstance(raw, dict) or not raw:
        return ""

    scored = [
        (int(d.get("score") or 0), str(d.get("name") or name))
        for name, d in raw.items()
        if isinstance(d, dict) and not d.get("not_applicable")
    ]
    if not scored:
        return ""
    score, name = min(scored)
    floor = APPROVAL_DIMENSION_FLOOR if score < APPROVAL_DIMENSION_FLOOR else APPROVAL_FLOOR
    detail = f" — {name.replace('_', ' ')} scored {score}, against a floor of {floor}"

    issues = (raw.get(name) or {}).get("issues") or []
    if issues:
        detail += f' ("{str(issues[0])[:140]}")'
    return detail


def approval_state(artifact_id: str) -> dict[str, Any]:
    """Whether this version may be approved, and precisely what is missing."""
    reviews = reviews_for(artifact_id)
    by_layer = {int(r["layer"]): r for r in reviews}

    blockers: list[str] = []
    for layer in (2, 3):
        if layer not in by_layer:
            blockers.append(f"layer {layer} ({LAYERS[layer]['name']}) has not run")

    # The vendors of the layers that ACTUALLY RAN. This used to read layers 1
    # and 2 while requiring layers 2 and 3, so an operator who ran 2 and 3 —
    # the two the gate asks for — was blocked by a rule about a layer 1 that
    # had never run, and told "layers 1 and 2 used the same vendor" about a
    # comparison with nothing on one side. There was no way to clear it.
    vendors = {str(r.get("provider") or "") for r in reviews if r.get("provider")}
    reviewing = str((by_layer.get(2) or {}).get("provider") or "")
    approving = str((by_layer.get(3) or {}).get("provider") or "")
    if reviewing and approving and reviewing == approving:
        blockers.append(
            f"layers 2 and 3 used the same vendor ({approving}) — two models "
            f"from one vendor share failure modes, so that is one opinion "
            f"asked twice. Re-run layer 3 with a different vendor."
        )

    # A model saying "revise" is not the same as a model saying "reject", and
    # neither is the same as a layer that never ran.
    #
    # BLOCKERS are facts about the process: a required layer is missing, the
    # same vendor reviewed and approved, a layer rejected it outright. A person
    # cannot sign those away, because signing would not make them untrue.
    #
    # WARNINGS are a model's judgement that a person may overrule. `decide()`
    # returns "revise" whenever ANY single dimension falls below 70, and this
    # pipeline has measured one model scoring the same unchanged artifact 40,
    # 70, 95 and 100 on factual_correctness — a 60-point spread. Treating that
    # as an absolute veto meant a guide a person had read and judged fit could
    # not be approved, with no way to say so and no way forward. That is not
    # rigour; it is a dead end wearing rigour's clothes.
    warnings: list[str] = []
    for layer, review in sorted(by_layer.items()):
        if review.get("verdict") == "reject":
            blockers.append(
                f"layer {layer} rejected it{_worst(review)}. A rejection is not "
                f"something to sign past: fix it, or regenerate."
            )
        elif layer == 3 and review.get("verdict") != "pass":
            warnings.append(
                f"the approver asked for revision rather than passing it"
                f"{_worst(review)}. If you have read this version and judge it "
                f"fit to teach, you may approve it over that objection — say "
                f"why, and it is recorded against the version."
            )

    # Approval is a person's decision, always. The layers narrow what reaches
    # them; they do not replace them. Progress counts approved work, so a
    # pipeline that could approve its own output would let a grade report
    # itself complete without anyone having read a line of it.
    return {
        "artifact_id": artifact_id,
        "can_approve": not blockers,
        "requires_human": True,
        "requires_override": bool(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "layers_run": sorted(by_layer),
        "vendors": sorted(v for v in vendors if v),
        "reviews": [
            {"layer": r["layer"], "verdict": r["verdict"],
             "confidence": r["overall_confidence"],
             "provider": r["provider"], "model": r["model"]}
            for r in reviews
        ],
    }

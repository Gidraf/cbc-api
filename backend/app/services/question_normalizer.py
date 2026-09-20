"""Turn raw model output into validated :class:`QuestionItem` objects.

Rejection is a first-class outcome. An item that cannot be made valid is
returned in ``batch.rejected`` with the reason, rather than being patched into
something that looks fine and is wrong — the previous behaviour, where a missing
answer key became "option A".
"""
from __future__ import annotations

import re

import logging
from typing import Any

from pydantic import ValidationError

from ..question_models import (
    AnswerOption,
    DiagramBinding,
    KicdRubric,
    QuestionBatch,
    QuestionCurriculum,
    QuestionItem,
    QuestionPedagogy,
    StructuredPart,
)
from .grade_order import grade_ordinal, grade_level, normalize_grade
from .ids import mint_question_id, mint_universal_id, subject_code

def _serves(raw: dict[str, Any], design_row: dict[str, Any] | None,
            item_slo: str) -> list[str]:
    """Which design elements this question records that it serves.

    Validated against the design's own numbered list, and an invented ref is
    DISCARDED rather than filed. A coverage report is read as a statement of
    fact — one element reading covered because a question claimed a ref that
    does not exist is the most expensive error it could make, and it would be
    invisible, because a fabricated ref looks exactly like a real one.

    With no design row there is nothing to validate against, so nothing is
    kept: a claim nobody can check is not evidence.
    """
    from .design_elements import valid_serves

    claimed = raw.get("serves") or raw.get("serves_refs") or []
    if isinstance(claimed, str):
        claimed = [claimed]
    if not design_row:
        return []
    keep, invented = valid_serves(claimed, design_row)
    if invented:
        logger.info("Discarded %d invented design ref(s) on %s: %s",
                    len(invented), raw.get("question_id") or "?",
                    ", ".join(invented[:5]))
    # The outcome a question names in `target_slo` is a ref like any other, and
    # it was already being recorded separately. Folding it in means a question
    # filed before `serves` existed still reports what it serves.
    if item_slo and item_slo not in keep:
        allowed, _ = valid_serves([item_slo], design_row)
        keep += allowed
    return keep


logger = logging.getLogger("cbc-question-normalizer")

_TYPE_ALIASES = {
    "mcq": "multiple_choice",
    "multiple choice": "multiple_choice",
    "multiplechoice": "multiple_choice",
    "structured": "structured_scenario",
    "scenario": "structured_scenario",
    "essay": "extended_essay",
    "calculation": "quantitative_calculation",
    "practical": "practical_performance_task",
    "experiment": "experiment_based",
    "diagram": "diagram_based",
    "truefalse": "true_false",
    "true/false": "true_false",
}


def _canonical_type(raw: Any) -> str:
    value = str(raw or "multiple_choice").strip().lower().replace("-", "_")
    return _TYPE_ALIASES.get(value.replace("_", " "), _TYPE_ALIASES.get(value, value))


def _normalize_options(raw: Any, stated_correct: str) -> list[AnswerOption]:
    """Accept the dict-keyed and list forms models produce, emit one shape."""
    if not raw:
        return []

    correct = {c.strip().upper() for c in str(stated_correct or "").split(",") if c.strip()}
    options: list[AnswerOption] = []

    if isinstance(raw, dict):
        for key, value in raw.items():
            opt_id = str(key).strip()
            if isinstance(value, dict):
                text = str(value.get("text", "")).strip()
                flagged = bool(value.get("is_correct", False))
                rationale = str(value.get("distractor_rationale", "") or "")
            else:
                text, flagged, rationale = str(value).strip(), False, ""
            options.append(
                AnswerOption(
                    id=opt_id,
                    text=text,
                    is_correct=flagged or opt_id.upper() in correct,
                    distractor_rationale=rationale,
                )
            )
    elif isinstance(raw, list):
        for idx, item in enumerate(raw):
            opt_id = chr(65 + idx)
            if isinstance(item, dict):
                opt_id = str(item.get("id") or opt_id).strip()
                text = str(item.get("text", "")).strip()
                flagged = bool(item.get("is_correct", False))
                rationale = str(item.get("distractor_rationale", "") or "")
            else:
                text, flagged, rationale = str(item).strip(), False, ""
            options.append(
                AnswerOption(
                    id=opt_id,
                    text=text,
                    is_correct=flagged or opt_id.upper() in correct,
                    distractor_rationale=rationale,
                )
            )

    return [o for o in options if o.text]


def scheme_text(raw: Any) -> str:
    """The marking scheme as lines of text, whatever shape the writer sent.

    A writer answered with an object — {"step_1": "M1: …", "step_2": "A1: …"}
    — and it was filed as its Python repr, so the printed scheme read
    "1. {'step_1': 'A1: Selects option B.', …}" braces, quotes and all.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        text = raw.strip()
        # The same object arriving as a JSON or Python literal in a string.
        if text[:1] in "{[" and text[-1:] in "}]":
            import ast
            import json

            for loader in (json.loads, ast.literal_eval):
                try:
                    parsed = loader(text)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(parsed, (dict, list)):
                    return scheme_text(parsed)
        return text
    if isinstance(raw, dict):
        lines = []
        for key, value in raw.items():
            line = scheme_text(value)
            if not line:
                continue
            label = str(key).replace("_", " ").strip()
            # "step 1" is the numbering the renderer adds; a named key such
            # as "part_a" is worth keeping.
            lines.append(line if label.lower().startswith("step") or label.isdigit() else f"{label}: {line}")
        return "\n".join(lines)
    if isinstance(raw, list):
        return "\n".join(l for l in (scheme_text(v) for v in raw) if l)
    return str(raw).strip()


_INLINE_PARTS = re.compile(r"\(\s*[a-h]\s*\)\s*.*?\(\s*\d+\s*marks?\s*\)", re.I | re.S)


def strip_inline_parts(text: str, parts: list["StructuredPart"]) -> str:
    """A stem that lists its parts — "(a) Write a signed expression … (2 marks)
    (b) Calculate … (3 marks)" — when the parts are also carried in
    `structured_parts`. The paper printed every part twice."""
    if not parts or not text:
        return text
    first = _INLINE_PARTS.search(text)
    if not first:
        return text
    # Only when what follows really is the part list, i.e. it mentions the
    # first part's own words; a "(a)" inside an expression is left alone.
    head = re.sub(r"\s+", " ", parts[0].sub_question.lower())[:30]
    tail = re.sub(r"\s+", " ", text[first.start():].lower())
    if head[:20] not in tail:
        return text
    head = text[:first.start()].rstrip(" ;:")
    return head if not head or head.endswith((".", "?", "!")) else head + "."


def _normalize_parts(raw: Any) -> list[StructuredPart]:
    if not isinstance(raw, list):
        return []
    parts: list[StructuredPart] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        question = str(item.get("sub_question") or item.get("question") or "").strip()
        if not question:
            continue
        try:
            marks = int(item.get("marks") or 1)
        except (TypeError, ValueError):
            marks = 1
        parts.append(
            StructuredPart(
                part_id=str(item.get("part_id") or f"({chr(97 + idx)})"),
                sub_question=question,
                marks=max(0, marks),
                model_answer=str(item.get("model_answer") or "").strip(),
            )
        )
    return parts


def _normalize_rubric(raw: Any, fallback_scheme: str = "") -> KicdRubric:
    if isinstance(raw, dict) and raw:
        return KicdRubric(
            exceeding=str(raw.get("exceeding") or raw.get("exceeding_expectations") or "").strip(),
            meeting=str(raw.get("meeting") or raw.get("meeting_expectations") or "").strip(),
            approaching=str(raw.get("approaching") or raw.get("approaching_expectations") or "").strip(),
            below=str(raw.get("below") or raw.get("below_expectations") or "").strip(),
        )
    if fallback_scheme:
        return KicdRubric(meeting=fallback_scheme.strip())
    return KicdRubric()


class QuestionNormalizer:
    def normalize_batch(
        self,
        raw_items: list[Any],
        *,
        grade: str,
        subject: str,
        strand: str,
        sub_strand: str,
        slo_id: str | None = None,
        level: str = "",
        subject_code_hint: str | None = None,
        default_difficulty: float = 0.5,
        diagram_resolver: Any = None,
        target_hour: int | None = None,
        target_hour_title: str = "",
        design_row: dict[str, Any] | None = None,
    ) -> QuestionBatch:
        batch = QuestionBatch(sub_strand=sub_strand)
        grade_slug = normalize_grade(grade)
        code = subject_code(subject, subject_code_hint)

        for idx, raw in enumerate(raw_items or []):
            if not isinstance(raw, dict):
                batch.rejected.append(
                    {"index": idx, "reason": "Item was not a JSON object", "raw": str(raw)[:400]}
                )
                continue

            label = str(raw.get("question_id") or f"Q{idx + 1}").strip()

            try:
                item = self._build_item(
                    raw,
                    index=idx,
                    display_label=label,
                    grade_slug=grade_slug,
                    subject=subject,
                    subject_code_str=code,
                    strand=strand,
                    sub_strand=sub_strand,
                    slo_id=slo_id,
                    level=level,
                    default_difficulty=default_difficulty,
                    diagram_resolver=diagram_resolver,
                    target_hour=target_hour,
                    target_hour_title=target_hour_title,
                    design_row=design_row or {},
                )
            except ValidationError as exc:
                reasons = "; ".join(
                    str(err.get("msg", "")).replace("Value error, ", "") for err in exc.errors()
                )
                logger.info("Rejected generated item %s (%s): %s", label, sub_strand, reasons)
                batch.rejected.append(
                    {
                        "index": idx,
                        "display_label": label,
                        "question_type": _canonical_type(raw.get("question_type")),
                        "reason": reasons,
                        "question_text": str(raw.get("question_text", ""))[:300],
                    }
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not normalize item %s: %s", label, exc)
                batch.rejected.append({"index": idx, "display_label": label, "reason": str(exc)})
                continue

            batch.items.append(item)

        return batch

    def _build_item(
        self,
        raw: dict[str, Any],
        *,
        index: int,
        display_label: str,
        grade_slug: str,
        subject: str,
        subject_code_str: str,
        strand: str,
        sub_strand: str,
        slo_id: str | None,
        level: str,
        default_difficulty: float,
        diagram_resolver: Any,
        target_hour: int | None,
        target_hour_title: str,
        design_row: dict[str, Any] | None = None,
    ) -> QuestionItem:
        q_type = _canonical_type(raw.get("question_type"))
        item_slo = str(raw.get("target_slo") or slo_id or "").strip()

        question_id = mint_question_id(
            grade=grade_slug,
            subject=subject,
            sub_strand=sub_strand,
            slo_id=item_slo,
            subject_code_hint=subject_code_str,
        )
        universal_id = mint_universal_id(
            grade=grade_slug,
            subject=subject,
            strand=strand,
            sub_strand=sub_strand,
            slo_id=item_slo,
            subject_code_hint=subject_code_str,
        )

        try:
            difficulty = float(raw.get("difficulty_index", default_difficulty))
        except (TypeError, ValueError):
            difficulty = default_difficulty
        try:
            max_marks = int(raw.get("max_marks") or 0)
        except (TypeError, ValueError):
            max_marks = 0
        try:
            minutes = int(raw.get("estimated_time_mins") or 0)
        except (TypeError, ValueError):
            minutes = 0

        source_hour = target_hour if target_hour else raw.get("source_hour")
        try:
            source_hour = int(source_hour) if source_hour else None
        except (TypeError, ValueError):
            source_hour = None

        curriculum = QuestionCurriculum(
            level=level or grade_level(grade_slug),
            grade=grade_slug,
            grade_ordinal=grade_ordinal(grade_slug),
            subject=subject,
            subject_code=subject_code_str,
            strand=strand,
            sub_strand=sub_strand,
            slo_id=item_slo,
            slo_text=str(raw.get("target_slo_text") or "").strip(),
            serves=_serves(raw, design_row, item_slo),
        )

        pedagogy = QuestionPedagogy(
            bloom_level=str(raw.get("bloom_level") or "Application").strip().title(),
            difficulty_index=min(1.0, max(0.0, difficulty)),
            max_marks=max(0, max_marks),
            estimated_time_mins=max(0, minutes),
            micro_concept=str(raw.get("micro_concept") or "").strip(),
            core_competency=str(raw.get("core_competency") or "").strip(),
            constitutional_value=str(raw.get("constitutional_value") or "").strip(),
            pertinent_issue=str(raw.get("pertinent_issue") or "").strip(),
            source_hour=source_hour,
            source_hour_title=target_hour_title or str(raw.get("source_hour_title") or "").strip(),
        )

        diagram: DiagramBinding | None = None
        if diagram_resolver is not None:
            diagram = diagram_resolver(raw, q_type)

        marking_scheme = scheme_text(raw.get("marking_scheme"))
        parts = _normalize_parts(raw.get("structured_parts"))

        return QuestionItem(
            question_id=question_id,
            universal_id=universal_id,
            display_label=display_label,
            question_type=q_type,
            curriculum=curriculum,
            pedagogy=pedagogy,
            stimulus_context=str(raw.get("stimulus_context") or raw.get("scenario_context") or "").strip(),
            question_text=strip_inline_parts(str(raw.get("question_text") or "").strip(), parts),
            options=_normalize_options(raw.get("options"), str(raw.get("correct_answer") or "")),
            correct_answer=str(raw.get("correct_answer") or "").strip() or None,
            structured_parts=parts,
            model_answer=str(raw.get("model_answer") or raw.get("explanation") or "").strip(),
            marking_scheme=marking_scheme,
            expression=str(raw.get("expression") or "").strip(),
            rubric=_normalize_rubric(raw.get("kicd_rubric") or raw.get("marking_guide"), marking_scheme),
            diagram=diagram,
            activity_ref=str(raw.get("activity_ref") or "").strip(),
            provenance_citation=str(raw.get("provenance_citation") or "").strip(),
            status="draft",
        )


question_normalizer = QuestionNormalizer()

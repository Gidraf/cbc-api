"""A second reader for the questions: answer each one cold, then compare.

The engine reads the arithmetic and only the arithmetic. A Social Studies
paper, a CRE paper, a Science paper with a wrong key has no engine to catch
it, and a Mathematics word problem the engine could not parse has none
either. The one check that reaches all of them is the check a marker
does: answer the question from the stem alone, then look at the key.

So one call per remediation pass hands the batch to the model with the
notes it was written from and asks, item by item: what is YOUR answer; is
the key right; is exactly one option right; does the marking scheme award
marks for the answer the question asks for; is the item answerable from
the lessons. What comes back is a list of the items that fail and why, in
the form the rewrite loop already acts on.

Deliberately narrow. It is not asked about style or difficulty — the
mechanical checks measure those more consistently. And a verdict on a
VALUE the engine has already verified does not stand: a reader that can be
wrong is held to the same standard as the writer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from . import question_check

logger = logging.getLogger("cbc-question-audit")

MAX_ITEMS = 40

_PROMPT = """You are moderating a batch of assessment items for a Kenyan CBC paper: {where}.

WHAT WAS TAUGHT (the lessons these items assess):
{notes}

For EACH item below: answer it yourself from the stem alone, write YOUR answer, then compare with the key or model answer.

An item FAILS only if one of these holds:
  - kind "key": your answer differs from the key or model answer as a FACT or VALUE — not in wording, not in units written differently, not in a sign convention for a change.
  - kind "ambiguous": more than one option is defensible, or the stem does not give enough to answer, or the question has no single answer as set.
  - kind "distractor": a distractor is not a mistake a learner makes — it is nonsense, or it is obviously wrong on sight, or two distractors say the same thing.
  - kind "scheme": the marking scheme awards marks for something the question did not ask, or omits the step the marks are for, or the parts' marks do not match their demand.
  - kind "untaught": the item needs knowledge the lessons above never taught and the design does not list — a Grade 6 item on a Grade 9 idea, or a fact from outside the sub-strand.
  - kind "wrong": the stem asserts something false (a false fact about Kenya, a wrong date, a misstated law or definition).

For an item that is a SITUATION to be worked (money, temperature, depth, scores, distances — a story with
numbers in it), also write "expression": ONE arithmetic expression that models the story exactly as told,
using every figure the story gives, in plain notation with brackets, e.g. "-250 + 600 - 180 + 120/4".
Read the words literally: a refund "shared among four members who each return their share" comes back
whole; "shared among four members" and kept by them does not. Leave "expression" empty for anything else.

Return ONLY JSON, one entry per item, pass or fail:
{{"verdicts": [{{"item": "Q3", "verdict": "fail", "kind": "key", "my_answer": "B", "expression": "", "reason": "one sentence"}}, ...]}}
For a passing item: "verdict": "pass", "kind": "", "my_answer": "<your answer>", "expression": "<or empty>", "reason": "".

ITEMS:
{items}"""


def _render(questions: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]]]:
    lines: list[str] = []
    by_label: dict[str, dict[str, Any]] = {}
    for index, question in enumerate(questions[:MAX_ITEMS], start=1):
        label = str(question.get("display_label") or f"Q{index}")
        by_label[label] = question
        lines.append(f"--- {label} [{question.get('question_type') or 'item'}] ---")
        stimulus = str(question.get("stimulus_context") or "").strip()
        if stimulus:
            lines.append(f"Context: {stimulus}")
        lines.append(f"Question: {str(question.get('question_text') or '').strip()}")
        for part in question.get("structured_parts") or []:
            if isinstance(part, dict):
                lines.append(f"  {part.get('part_id') or ''} {part.get('sub_question') or ''} "
                             f"[{part.get('marks') or 0} marks] → model answer: {part.get('model_answer') or ''}")
        options = [o for o in (question.get("options") or []) if isinstance(o, dict)]
        for option in options:
            lines.append(f"  ({option.get('id')}) {option.get('text')}"
                         + ("   ← KEY" if option.get("is_correct") else ""))
        if not options:
            lines.append(f"Model answer: {str(question.get('model_answer') or '').strip()}")
        scheme = str(question.get("marking_scheme") or "").strip()
        if scheme:
            lines.append(f"Marking scheme: {scheme[:600]}")
        lines.append(f"Marks: {(question.get('pedagogy') or {}).get('max_marks') or ''}")
    return "\n".join(lines), by_label


def _value_of(expression: str) -> float | None:
    """The engine's value for an expression, or None if it cannot work it."""
    from .worked_solutions import _as_number, _comparable, _is_a_value
    from .math_engine import solve_math_problem

    text = str(expression or "").strip().strip("$")
    if not text or len(text) > 200:
        return None
    try:
        trace = solve_math_problem(text)
    except Exception:  # noqa: BLE001
        return None
    if trace.unsolved or not trace.final_answer or not _is_a_value(trace.final_answer):
        return None
    return _as_number(_comparable(trace.final_answer))


def story_vs_expression(question: dict[str, Any], readers_expression: str) -> str:
    """Two independent translations of the story, worked by the engine.

    A club "receives a KSh 200 refund, shared equally among four members,
    and each member returns their share to the fund": the writer wrote
    `+ 200 / 4`, the engine blessed the arithmetic, and the key was 230 —
    for a fund that, as told, gained 200. The engine cannot read; a second
    reader can, and where the two sums differ in VALUE the item is held.
    Returns the finding text, or '' when they agree or nothing is workable.
    """
    theirs = str(question.get("expression") or "").strip()
    mine = str(readers_expression or "").strip()
    if not theirs or not mine:
        return ""
    a, b = _value_of(theirs), _value_of(mine)
    if a is None or b is None:
        return ""
    if abs(a - b) < 1e-9:
        return ""
    return (f"reads the story as `{mine[:80]}` = {b:g}, but the item's own expression "
            f"`{theirs[:80]}` = {a:g} — the sum and the story do not say the same thing.")


def _stands(kind: str, my_answer: str, question: dict[str, Any], reason: str) -> bool:
    """Whether a failing verdict survives what the engine already knows."""
    from .worked_solutions import _as_number, _comparable, check

    if kind in ("ambiguous", "distractor", "scheme", "untaught", "wrong"):
        return bool(reason)
    stem = question_check._stem(question)
    answer = question_check._answer_of(question)
    verified = check(stem, answer)
    if verified.get("checked") and verified.get("agrees"):
        return False
    key = question_check._key_option(question)
    if key is not None:
        mine = str(my_answer or "").strip().upper().rstrip(".)")
        if mine and mine == str(key.get("id") or "").strip().upper():
            return False  # "the answer is B" of an item keyed B
        mine_text = re.sub(r"\s+", " ", str(my_answer or "")).strip().lower()
        if mine_text and mine_text == re.sub(r"\s+", " ", str(key.get("text") or "")).strip().lower():
            return False
    mine_n, theirs_n = _as_number(_comparable(my_answer)), _as_number(_comparable(answer))
    if mine_n is not None and theirs_n is not None:
        if abs(mine_n - theirs_n) < 1e-9 or abs(abs(mine_n) - abs(theirs_n)) < 1e-9:
            return False
    return bool(reason)


def audit(questions: list[dict[str, Any]], *, generate: Any, model_config: Any,
          notes_text: str = "", grade: str = "", subject: str = "",
          sub_strand: str = "") -> list[question_check.Finding]:
    """Findings that name their item. Never raises."""
    items = [q for q in (questions or []) if isinstance(q, dict)]
    if not items or generate is None or model_config is None:
        return []
    rendered, by_label = _render(items)
    where = " · ".join(x for x in (grade, subject, sub_strand) if x) or "this sub-strand"
    prompt = _PROMPT.format(where=where, items=rendered,
                            notes=(notes_text or "(no lesson notes supplied)")[:12_000])
    try:
        try:
            response = generate(model_config, [{"role": "user", "content": prompt}],
                                temperature=0.0, effort="high")
        except TypeError:
            response = generate(model_config, [{"role": "user", "content": prompt}], temperature=0.0)
        content = response.content if hasattr(response, "content") else response
        if isinstance(content, str):
            content = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Question audit skipped: %s", exc)
        return []

    verdicts = content.get("verdicts") if isinstance(content, dict) else None
    if not isinstance(verdicts, list):
        return []

    findings: list[question_check.Finding] = []
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        label = str(verdict.get("item") or "").strip()
        question = by_label.get(label)
        if question is None:
            continue
        # The story against the sum, whatever the verdict says. The engine
        # proves the writer's arithmetic; nothing proved the writer's reading
        # of the story until a second reader wrote the sum from the words.
        disagreement = story_vs_expression(question, str(verdict.get("expression") or ""))
        if disagreement:
            findings.append(question_check.Finding(
                "story_expression_disagree",
                f"{label} {disagreement}",
                "Make the story and the sum say the same thing: either rewrite the situation so the "
                "expression models it exactly as told, or correct the expression and the key to what "
                "the words say.",
                [question_check._id(question)]))
        if str(verdict.get("verdict") or "").strip().lower() not in ("fail", "wrong"):
            continue
        kind = str(verdict.get("kind") or "").strip().lower()
        reason = re.sub(r"\s+", " ", str(verdict.get("reason") or "")).strip()[:300]
        my_answer = str(verdict.get("my_answer") or "").strip()
        if not _stands(kind, my_answer, question, reason):
            continue
        fix = {
            "key": "Re-work the item; the key must be the answer the question as set actually has.",
            "ambiguous": "Rewrite the stem so exactly one answer is right, and say what is given.",
            "distractor": "Every distractor is a wrong answer a learner reaches by a named mistake.",
            "scheme": "Award the marks for what the question asks, step by step.",
            "untaught": "Set the item on what the lessons taught, or drop it.",
            "wrong": "Correct the fact; check it against the design and the notes.",
        }.get(kind, "Fix what the reason names.")
        says = f"{label} fails a moderator's read ({kind or 'reader'}): {reason or 'the reader reached a different answer'}"
        if my_answer and kind == "key":
            says += f" (reader's answer: {my_answer[:60]})"
        findings.append(question_check.Finding(f"reader_{kind or 'fail'}", says + ".", fix,
                                               [question_check._id(question)]))
    return findings

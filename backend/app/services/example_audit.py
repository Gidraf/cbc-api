"""A second reader for the worked examples: solve each one independently.

Every mechanical check here reads the arithmetic. None of them reads the
STORY. A guide scored 94 with "expenses include KSh 1,500 for transportation"
worked as `... + 1500`, and with Nairobi dropping to −5°C at night — the
arithmetic of both was true, the badge said "arithmetic checked", and a
reader saw both on the first pass. An expense that is added, a change that
is worked as initial minus final, a "rises to" read as "rises by", a place
that never has the weather the example gives it: these are errors of
meaning, and only a reader catches errors of meaning.

So one call per remediation pass hands every worked example to the model
with the question a marker asks: solve it yourself, then say whether this
working is the right working for this question. What comes back is a list
of the examples that are wrong and why, in the form the rewrite loop already
acts on — a finding that names its lesson.

Deliberately narrow. It is not asked about style, depth or pedagogy; the
checks that measure those are cheaper and more consistent. It is asked the
one thing they cannot ask.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("cbc-example-audit")

MAX_EXAMPLES = 30

_PROMPT = """You are marking the worked examples of a Kenyan CBC teacher's guide: {where}.

For EACH example below, solve it yourself from the statement alone, write down YOUR answer, then compare.

Conventions this guide uses — do not mark an example wrong for following them:
  - A change from A to B is B − A. A drop from 5°C to −3°C is a change of −8°C; "−8°C" and "a drop of 8°C" are both right. Do not ask for an absolute difference.
  - Subtracting the initial value from the final value IS the method for a change.
  - Working shown one operation per line is right even if you would combine lines.

An example is WRONG only if one of these holds:
  - kind "answer": your answer differs from the example's answer as a VALUE (not in form, not in sign convention for a change).
  - kind "model": the working does not model the story — an expense, a cost, a withdrawal or a payment REDUCES a balance; a donation, a refund or a deposit INCREASES it; a debt is negative; "rises TO 5" is not "rises BY 5".
  - kind "context": the situation cannot be true — no Kenyan town has a night temperature below 0°C (Nairobi's record low is about 5°C; sub-zero belongs in a cold store, on Mount Kenya, or abroad).
  - kind "units": the question has a unit and the answer has none.

Return ONLY JSON of this shape, one entry per example, right or wrong:
{{"verdicts": [{{"lesson": 3, "example": 1, "verdict": "wrong", "kind": "model", "my_answer": "1500", "reason": "one sentence"}}, ...]}}
For a right example: "verdict": "right", "kind": "", "my_answer": "<your answer>", "reason": "".

{examples}"""


def _render(notes: dict[str, Any]) -> tuple[str, list[tuple[int, int]]]:
    lines: list[str] = []
    index: list[tuple[int, int]] = []
    for i, module in enumerate(notes.get("modules") or [], start=1):
        if not isinstance(module, dict):
            continue
        try:
            number = int(module.get("module_number") or i)
        except (TypeError, ValueError):
            number = i
        for k, example in enumerate(module.get("worked_examples") or [], start=1):
            if not isinstance(example, dict) or not example.get("statement"):
                continue
            if len(index) >= MAX_EXAMPLES:
                break
            index.append((number, k))
            steps = "; ".join(
                str(s.get("working") or "").strip()
                for s in (example.get("steps") or []) if isinstance(s, dict)
                and str(s.get("working") or "").strip())
            lines.append(
                f"LESSON {number}, EXAMPLE {k}\n"
                f"  Statement: {str(example.get('statement') or '').strip()}\n"
                f"  Working: {steps or '(none)'}\n"
                f"  Answer: {str(example.get('answer') or '').strip()}")
    return "\n\n".join(lines), index


def audit(notes: dict[str, Any], *, generate: Any, model_config: Any,
          grade: str = "", subject: str = "", sub_strand: str = "",
          ) -> tuple[list[str], list[int]]:
    """Findings that name a lesson, and the lessons to rewrite. Never raises."""
    rendered, index = _render(notes)
    if not index or generate is None or model_config is None:
        return [], []
    where = " · ".join(x for x in (grade, subject, sub_strand) if x) or "this sub-strand"
    prompt = _PROMPT.format(where=where, examples=rendered)
    try:
        try:
            response = generate(model_config, [{"role": "user", "content": prompt}],
                                temperature=0.0, effort="high")
        except TypeError:
            # A generate() that does not take `effort` — a test double, or an
            # older client.
            response = generate(model_config, [{"role": "user", "content": prompt}],
                                temperature=0.0)
        content = response.content if hasattr(response, "content") else response
        if isinstance(content, str):
            content = json.loads(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Example audit skipped: %s", exc)
        return [], []

    verdicts = content.get("verdicts") if isinstance(content, dict) else None
    if not isinstance(verdicts, list):
        return [], []

    examples = _examples_by_position(notes)
    findings: list[str] = []
    targets: list[int] = []
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        if str(verdict.get("verdict") or "").strip().lower() != "wrong":
            continue
        try:
            lesson, example = int(verdict.get("lesson")), int(verdict.get("example"))
        except (TypeError, ValueError):
            continue
        found = examples.get((lesson, example))
        if found is None:
            continue
        kind = str(verdict.get("kind") or "").strip().lower()
        reason = re.sub(r"\s+", " ", str(verdict.get("reason") or "")).strip()[:300]
        if not _stands(kind, str(verdict.get("my_answer") or ""), found, reason):
            continue
        findings.append(
            f"Lesson {lesson} worked example {example} is wrong: {reason or 'the working is not the working for the question'}. "
            f"Rewrite the example so that the working models the situation as stated "
            f"and the answer is what the question asks for.")
        if lesson not in targets:
            targets.append(lesson)
    return findings, targets


def _examples_by_position(notes: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for i, module in enumerate(notes.get("modules") or [], start=1):
        if not isinstance(module, dict):
            continue
        try:
            number = int(module.get("module_number") or i)
        except (TypeError, ValueError):
            number = i
        for k, example in enumerate(module.get("worked_examples") or [], start=1):
            if isinstance(example, dict) and example.get("statement"):
                out[(number, k)] = example
    return out


def _stands(kind: str, my_answer: str, example: dict[str, Any], reason: str) -> bool:
    """Whether a "wrong" verdict survives what the engine already knows.

    The reader's first outing marked "the correct answer is 10, not 10",
    marked −12 wrong for an expression the engine had verified as −12, and
    marked a temperature drop of −8 wrong for not being 8. A reader that can
    be wrong is held to the same standard as the writer: a verdict about the
    VALUE stands only where the engine could not read the statement, and
    only where the reader's own answer actually differs; a verdict about the
    story or the setting stands on its own, because those are the questions
    the engine cannot ask.
    """
    from .worked_solutions import _as_number, _comparable, check

    if kind in ("context", "model", "units"):
        return True
    statement = str(example.get("statement") or "")
    answer = str(example.get("answer") or "")
    verified = check(statement, answer)
    if verified.get("checked") and verified.get("agrees"):
        return False  # the engine read the statement and the answer is right
    mine = _as_number(_comparable(my_answer))
    theirs = _as_number(_comparable(answer))
    if mine is None or theirs is None:
        return bool(reason)
    if abs(mine - theirs) < 1e-9:
        return False  # "10, not 10"
    if abs(abs(mine) - abs(theirs)) < 1e-9:
        return False  # a sign convention on a change, not an error
    return True

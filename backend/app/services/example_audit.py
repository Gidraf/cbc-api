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

For EACH example below, solve it yourself from the statement alone, then compare.
An example is WRONG if any of these holds:
  - the answer is not what the statement asks for (a change from A to B is B − A; "rises TO 5" is not "rises BY 5");
  - the working does not model the story (an expense, a cost, a withdrawal or a payment REDUCES a balance; a donation, a refund or a deposit INCREASES it; a debt is negative);
  - a quantity is treated as the wrong kind (a list of expenses whose last item is added instead of subtracted);
  - the context cannot be true (no Kenyan town has a night temperature below 0°C — Nairobi's record low is about 5°C; sub-zero belongs in a cold store, on Mount Kenya, or abroad);
  - a step's arithmetic is false, or the answer has no unit where the question has one.
An example is RIGHT if the working is the right working for the question and the answer is correct, even if you would have written it differently.

Return ONLY JSON of this shape:
{{"verdicts": [{{"lesson": 3, "example": 1, "verdict": "wrong", "reason": "one sentence: what is wrong and what the right working is"}}, ...]}}
List every example, right or wrong. Keep each reason to one sentence.

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

    known = set(index)
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
        if (lesson, example) not in known:
            continue
        reason = re.sub(r"\s+", " ", str(verdict.get("reason") or "")).strip()[:300]
        findings.append(
            f"Lesson {lesson} worked example {example} is wrong: {reason or 'the working is not the working for the question'}. "
            f"Rewrite the example so that the working models the situation as stated "
            f"and the answer is what the question asks for.")
        if lesson not in targets:
            targets.append(lesson)
    return findings, targets

"""Turn a review's findings into instructions the next generation can follow.

A review that says what is wrong and then leaves a person to retype it into a
custom-instructions box is a review most of whose value is lost in transit.
The issues are already structured — severity, where, what, fix — so they can be
handed back to the generator directly.

Two rules shape what gets sent:

* Only UNRESOLVED findings. Carrying a fixed issue forward makes the generator
  "fix" something that is already right, and the next review then disagrees
  with the last one about content neither of them changed.
* The generator is told what to KEEP, not only what to change. A regeneration
  that rewrites everything loses the parts that passed, and its diff becomes
  unreadable — which defeats the diff review that a regeneration exists to get.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-revision")

# Findings weaker than this are noise in a regeneration instruction: the model
# spends its attention on them and the real defects get equal billing.
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MAX_ISSUES = 12


def _issues_from(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    collected: list[dict[str, Any]] = []

    for review in reviews:
        for issue in review.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            key = f"{issue.get('where', '')}|{issue.get('what', '')}".lower().strip()
            if not key.strip("|") or key in seen:
                continue
            seen.add(key)
            collected.append({
                "severity": str(issue.get("severity") or "medium").lower(),
                "where": str(issue.get("where") or ""),
                "what": str(issue.get("what") or ""),
                "fix": str(issue.get("fix") or ""),
                "layer": review.get("layer"),
                "reviewer": f"{review.get('provider', '')}/{review.get('model', '')}",
            })

    collected.sort(key=lambda i: _SEVERITY_ORDER.get(i["severity"], 1))
    return collected[:MAX_ISSUES]


def _weak_dimensions(reviews: list[dict[str, Any]], floor: int = 70) -> list[dict[str, Any]]:
    """Dimensions that scored badly, with the evidence given for the score.

    The issue list says what to change; the dimension evidence says why it
    mattered, which is what stops a fix that satisfies the letter of the issue
    and not the thing the issue was about.
    """
    worst: dict[str, dict[str, Any]] = {}
    for review in reviews:
        for name, scored in (review.get("dimensions") or {}).items():
            if not isinstance(scored, dict) or scored.get("not_applicable"):
                continue
            score = scored.get("score")
            if not isinstance(score, int) or score >= floor:
                continue
            if name not in worst or score < worst[name]["score"]:
                worst[name] = {
                    "dimension": name, "score": score,
                    "evidence": str(scored.get("evidence") or "")[:600],
                }
    return sorted(worst.values(), key=lambda d: d["score"])


def build(
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The directive block, and the findings it was built from."""
    issues = _issues_from(reviews)
    weak = _weak_dimensions(reviews)
    human = [
        str(c.get("body") or "")
        for c in (comments or []) if not c.get("resolved") and c.get("body")
    ]

    if not (issues or weak or human):
        return {"directives": "", "issues": [], "weak_dimensions": [], "human_comments": []}

    lines = [
        "=== REVISE THE PREVIOUS VERSION ===",
        "This is a regeneration, not a fresh start. Reviewers found specific "
        "defects in the last version; fix those and change nothing else.",
        "",
        "Keep every part that was not criticised exactly as it was. Rewriting "
        "the whole thing loses what already passed and makes the diff between "
        "the two versions unreadable, which is what the next review reads.",
        "",
    ]

    if issues:
        lines.append("DEFECTS TO FIX:")
        for issue in issues:
            fix = f" Fix: {issue['fix']}" if issue["fix"] else ""
            lines.append(
                f"- [{issue['severity']}] {issue['where']}: {issue['what']}{fix}"
            )
        lines.append("")

    if weak:
        lines.append("WHY THOSE MATTERED — the dimensions that scored badly:")
        for entry in weak:
            lines.append(f"- {entry['dimension'].replace('_', ' ')} scored "
                         f"{entry['score']}/100: {entry['evidence']}")
        lines.append("")

    if human:
        lines.append("WHAT A HUMAN REVIEWER SAID (this outranks the models above):")
        lines.extend(f"- {c}" for c in human)
        lines.append("")

    lines += [
        "Where a defect cannot be fixed from the curriculum design you have been "
        "given, leave that part as it is rather than inventing a value to clear "
        "the criticism. A fabricated fix is the same defect, now invisible.",
    ]

    return {
        "directives": "\n".join(lines),
        "issues": issues,
        "weak_dimensions": weak,
        "human_comments": human,
    }

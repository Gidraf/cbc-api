"""The defects a machine found, kept where a regeneration can read them.

A generation returns far more than its content. The notes station also returns
a quality gate, a consistency check, a repetition check and a coverage report —
and the console draws every one of them: "contradicts itself, 88/100
consistent", "the design suggests using IT tools and no lesson uses it",
"weakest measure: learner language fit at 0.31".

All of it lived in the response body and nowhere else. `_record_artifact` filed
the content and `{provider, model}`, so the moment that HTTP response was gone
the findings were gone with it. Reopening the version showed none of them, and
— the reason this file exists — a regeneration could not act on them either:
`revision_directives` is built from REVIEWS, comments and a redundancy scan, so
an operator looking straight at "contradicts itself" pressed regenerate and was
told "every reviewer passed this version with no issues raised".

So the measured findings are filed onto the artifact, as short actionable
sentences, and handed to the next regeneration alongside the reviewers' own.
"""
from __future__ import annotations

from typing import Any

# Enough to act on, bounded so provenance stays a record and not a payload.
MAX_FINDINGS = 40
MAX_CHARS = 400


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text[:MAX_CHARS]


def _from_gate(gate: dict[str, Any]) -> list[str]:
    """The gate's failing criteria, and whatever it said to do about them."""
    out: list[str] = []
    reviewer = gate.get("reviewer") or {}
    for item in (reviewer.get("feedback") or gate.get("feedback") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").lower() != "fail":
            continue
        aspect = _clean(item.get("aspect")).replace("_", " ")
        comment = _clean(item.get("comment"))
        if aspect or comment:
            out.append(f"{aspect}: {comment}" if aspect and comment else aspect or comment)

    # `next_actions` is the part written to be acted on rather than read.
    for action in (gate.get("next_actions") or []):
        text = _clean(action if isinstance(action, str) else action.get("action"))
        if text:
            out.append(text)
    return out


def collect(result: dict[str, Any]) -> list[str]:
    """Every machine-found defect in one generation result, as instructions.

    Reads defensively: a station that does not run one of these checks simply
    contributes nothing, and a check whose shape changes does not break filing.
    """
    if not isinstance(result, dict):
        return []

    found: list[str] = []

    gate = result.get("quality_gate")
    if isinstance(gate, dict) and not gate.get("passed", True):
        found += _from_gate(gate)
    elif isinstance(gate, dict):
        # A gate can pass and still name failing criteria — that is exactly the
        # 90/100 with a dimension at 0.31 that nobody acted on.
        found += _from_gate(gate)

    integrity = result.get("integrity")
    if isinstance(integrity, dict) and integrity.get("checked") and not integrity.get("clean", True):
        for finding in (integrity.get("findings") or []):
            text = _clean(finding if isinstance(finding, str) else finding.get("what"))
            if text:
                found.append(f"The guide contradicts itself: {text}")

    repetition = result.get("repetition")
    if isinstance(repetition, dict) and repetition.get("checked") and not repetition.get("clean", True):
        for finding in (repetition.get("findings") or []):
            text = _clean(finding if isinstance(finding, str) else finding.get("what"))
            if text:
                found.append(f"The guide repeats itself: {text}")

    coverage = result.get("lesson_coverage")
    if isinstance(coverage, dict) and not coverage.get("complete", True):
        thin = coverage.get("thin_modules") or []
        required = coverage.get("modules_required")
        got = coverage.get("modules_found")
        if required and got is not None and got != required:
            found.append(
                f"The design allocates {required} lesson(s) and this guide has "
                f"{got}. Write the missing lesson(s) rather than lengthening the "
                f"ones that are here."
            )
        if thin:
            names = ", ".join(_clean(t if isinstance(t, str) else t.get("title"))
                              for t in thin[:4] if t)
            if names:
                found.append(f"These lessons are too thin to teach from: {names}.")

    fabrication = result.get("fabrication")
    if isinstance(fabrication, dict) and fabrication.get("suspect"):
        for item in (fabrication.get("suspect") or [])[:4]:
            text = _clean(item if isinstance(item, str) else item.get("claim"))
            if text:
                found.append(f"Unsupported claim — check it against the design: {text}")

    # Order preserved, duplicates dropped: two checks often name one defect.
    seen: set[str] = set()
    unique: list[str] = []
    for item in found:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique[:MAX_FINDINGS]


def provenance_for(result: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """The provenance to file with an artifact, carrying what was measured."""
    out = dict(base or {})
    findings = collect(result)
    if findings:
        out["measured"] = findings
    gate = result.get("quality_gate")
    if isinstance(gate, dict):
        out["gate_score"] = gate.get("overall_score")
        out["gate_passed"] = bool(gate.get("passed"))
    return out


def stored(artifact: Any) -> list[str]:
    """What was measured when this version was filed."""
    provenance = getattr(artifact, "provenance", None)
    if not isinstance(provenance, dict):
        return []
    found = provenance.get("measured")
    return [str(f) for f in found if f] if isinstance(found, list) else []

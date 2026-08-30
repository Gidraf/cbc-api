"""Find content that was padded out by repeating itself.

A layer-2 reviewer passed a PP1 guide at 90% whose lessons 5 and 6 shared two
verbatim exposition segments, an identical misconception, identical
differentiation, an identical formative check and an identical homework task.
Three of seven lessons were substantially one lesson. It scored
level_appropriateness 90 and raised one issue, about a resource list.

Reviewers miss this because they read forwards. Lesson 6 reads perfectly well
on its own; it is only wrong beside lesson 5, and by the time a reader reaches
it the earlier text is a page and a half back. The same blindness let a
mirrored payload — `modules` and `hour_modules` holding the same seven lessons
— double an artifact past the truncation limit without anyone noticing that
half of it was a copy.

So the comparison is done mechanically and the result is handed to the reviewer
the way resolved citations are, under `citation_evidence`. A reviewer cannot
overlook what it has been shown.

This measures repetition, not quality. Deliberate repetition is sound teaching
at this level — a song sung in three lessons is a song they will remember. What
is reported is repetition of the TEACHER'S material: the same exposition, the
same misconception, the same check. Judging which is which is the reviewer's
job, and the block says so.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any

logger = logging.getLogger("cbc-redundancy")

# Lists that hold one entry per lesson. Anything else is not compared.
MODULE_KEYS = ("modules", "hour_modules", "lessons")

# Fields whose repetition across lessons means the lesson was padded, not that
# a concept was deliberately revisited.
TEACHING_FIELDS = (
    "teacher_exposition", "learning_intent", "formative_check",
    "homework_or_follow_up", "differentiation", "common_misconceptions",
    "key_questions",
)

# Two lessons this similar are one lesson. Below it, overlap is normal: lessons
# in a sub-strand share vocabulary, a register and a subject by design.
NEAR_DUPLICATE = 0.80

MAX_MODULES = 40
MAX_REPORTED = 12


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _text_of(value: Any, out: list[str] | None = None) -> list[str]:
    """Every string in a subtree, so two modules can be compared as prose."""
    acc = out if out is not None else []
    if isinstance(value, str):
        acc.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _text_of(v, acc)
    elif isinstance(value, list):
        for v in value:
            _text_of(v, acc)
    return acc


def _module_lists(content: Any, path: str = "",
                  out: list[tuple[str, list]] | None = None
                  ) -> list[tuple[str, list]]:
    found = out if out is not None else []
    if isinstance(content, dict):
        for key, value in content.items():
            here = f"{path}.{key}" if path else key
            if key in MODULE_KEYS and isinstance(value, list) and value:
                found.append((here, value))
            else:
                _module_lists(value, here, found)
    elif isinstance(content, list):
        for i, item in enumerate(content):
            _module_lists(item, f"{path}[{i}]", found)
    return found


def _label(module: Any, index: int) -> str:
    if isinstance(module, dict):
        for key in ("title", "heading", "name"):
            if module.get(key):
                return str(module[key])[:80]
    return f"entry {index + 1}"


def _mirrors(lists: list[tuple[str, list]]) -> list[dict[str, Any]]:
    """Two lists holding the same lessons under different names.

    Not a cosmetic duplication: it doubles the artifact, and the second copy is
    what pushes a guide past the reviewer's truncation limit — so the reviewer
    is told the tail is missing when the tail was a copy of the head.
    """
    out: list[dict[str, Any]] = []
    for i in range(len(lists)):
        for j in range(i + 1, len(lists)):
            (path_a, a), (path_b, b) = lists[i], lists[j]
            if len(a) != len(b) or not a:
                continue
            if _norm(" ".join(_text_of(a))) == _norm(" ".join(_text_of(b))):
                out.append({"a": path_a, "b": path_b, "count": len(a)})
    return out


def _repeated_segments(modules: list, path: str) -> list[dict[str, Any]]:
    """A block of exposition that appears under more than one lesson."""
    where: dict[str, list[str]] = {}
    for i, module in enumerate(modules):
        if not isinstance(module, dict):
            continue
        segments = module.get("exposition_segments")
        if not isinstance(segments, list):
            continue
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            body = str(segment.get("body") or "")
            # Short connective sentences repeat harmlessly.
            if len(body) < 120:
                continue
            topic = str(segment.get("topic") or "")
            label = _label(module, i)
            key = _norm(body)
            where.setdefault(key, []).append(
                (label, f"{label} → {topic}" if topic else label)
            )

    out = []
    for key, found in where.items():
        if len(found) > 1:
            out.append({"places": [p for _, p in found],
                        "modules": [m for m, _ in found],
                        "chars": len(key), "excerpt": key[:150]})
    out.sort(key=lambda r: -r["chars"])
    return out


def _identical_fields(a: dict, b: dict) -> list[str]:
    same = []
    for field in TEACHING_FIELDS:
        if field not in a or field not in b:
            continue
        left, right = a.get(field), b.get(field)
        if not left or not right:
            continue
        if _norm(" ".join(_text_of(left))) == _norm(" ".join(_text_of(right))):
            same.append(field)
    return same


def _near_duplicate_modules(modules: list, path: str) -> list[dict[str, Any]]:
    prose = []
    for i, module in enumerate(modules[:MAX_MODULES]):
        prose.append(_norm(" ".join(_text_of(module))))

    out = []
    for i in range(len(prose)):
        for j in range(i + 1, len(prose)):
            if not prose[i] or not prose[j]:
                continue
            matcher = difflib.SequenceMatcher(None, prose[i], prose[j])
            # quick_ratio is an upper bound and cheap; only pay for the real
            # comparison on pairs that could possibly clear the threshold.
            if matcher.quick_ratio() < NEAR_DUPLICATE:
                continue
            ratio = matcher.ratio()
            if ratio < NEAR_DUPLICATE:
                continue
            a, b = modules[i], modules[j]
            out.append({
                "a": _label(a, i), "b": _label(b, j),
                "similarity": round(ratio * 100),
                "identical_fields": (
                    _identical_fields(a, b)
                    if isinstance(a, dict) and isinstance(b, dict) else []
                ),
            })
    out.sort(key=lambda r: -r["similarity"])
    return out


# A mirrored payload is structural rather than pedagogical — it wastes the
# reviewer's context window, not the class's time — so it is a flat cost rather
# than part of the proportion below.
MIRROR_COST = 15.0

# A lesson that shares an exposition block with another lesson, but is not a
# duplicate of it outright, is half a wasted lesson.
PARTIAL_WEIGHT = 0.5


def _findings(report: dict[str, Any]) -> list[str]:
    """The same defects, in one line each, for a regeneration to act on.

    Written as instructions rather than observations: a directive block is read
    by the model that has to fix it, and "lesson 6 is 87% identical to lesson 5"
    tells it what is wrong without telling it what to do.
    """
    out: list[str] = []
    for mirror in report["mirrors"]:
        out.append(
            f"`{mirror['a']}` and `{mirror['b']}` hold the same "
            f"{mirror['count']} entries word for word. Emit the lessons once."
        )
    for pair in report["near_duplicates"]:
        fields = (", ".join(pair["identical_fields"])
                  if pair["identical_fields"] else "throughout")
        out.append(
            f"\"{pair['b']}\" is {pair['similarity']}% identical to "
            f"\"{pair['a']}\" ({fields}). Rewrite it to teach something the "
            f"earlier lesson does not, or say in `gaps` that the design does "
            f"not fund this many distinct lessons."
        )
    for seg in report["repeated_segments"]:
        out.append(
            f"The same block of exposition appears in {len(seg['places'])} "
            f"lessons ({'; '.join(seg['places'])}). Write each one fresh."
        )
    return out


def _score(report: dict[str, Any]) -> float:
    """How many of the funded lessons actually teach something, 0-100.

    Proportional rather than a running penalty. A guide of thirty lessons with
    six duplicated pairs is mostly sound; a guide of three lessons with two is
    barely a guide, and a flat per-defect penalty scored them the same — both
    saturated at zero.

    The lesson that gets COPIED is not the padding; the copy is. So only the
    later member of each pair is counted against the total.
    """
    total = report.get("modules") or 0
    if not total:
        return 100.0

    padded = {pair["b"] for pair in report["near_duplicates"]}

    # A lesson that shares exposition with another lesson which is ITSELF
    # already counted is not counted twice — and the original is not charged
    # for having been copied.
    partial = set()
    for seg in report["repeated_segments"]:
        standing = [m for m in seg["modules"] if m not in padded]
        if len(standing) > 1:
            partial.update(standing[1:])

    wasted = len(padded) + PARTIAL_WEIGHT * len(partial)
    distinct = max(0.0, 1.0 - wasted / total) * 100.0
    return round(max(0.0, distinct - MIRROR_COST * len(report["mirrors"])), 1)


def inspect(content: Any) -> dict[str, Any]:
    """What in this artifact is a copy of something else in it."""
    lists = _module_lists(content)
    if not lists:
        return {"checked": False, "reason": "No lesson list to compare.",
                "findings": []}

    mirrors = _mirrors(lists)
    mirrored = {m["b"] for m in mirrors}

    duplicates: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    counted = 0
    for path, modules in lists:
        # Compare one copy of a mirrored pair, not both — otherwise every
        # finding is reported twice.
        if path in mirrored:
            continue
        counted = max(counted, len(modules))
        duplicates += _near_duplicate_modules(modules, path)
        segments += _repeated_segments(modules, path)

    report = {
        "checked": True,
        "modules": counted,
        "mirrors": mirrors,
        "near_duplicates": duplicates[:MAX_REPORTED],
        "repeated_segments": segments[:MAX_REPORTED],
        "clean": not mirrors and not duplicates and not segments,
    }
    report["score"] = _score(report)
    report["findings"] = _findings(report)
    return report


def render(report: dict[str, Any]) -> str:
    """The block a reviewer reads instead of holding seven lessons in its head."""
    if not report.get("checked") or report.get("clean"):
        return ""

    lines = [
        "=== REPETITION IN THIS ARTIFACT, ALREADY MEASURED ===",
        "Every lesson was compared against every other lesson mechanically "
        "before you saw it. You read forwards; this does not.",
        "",
    ]

    for mirror in report.get("mirrors", []):
        lines += [
            f"  MIRRORED: `{mirror['a']}` and `{mirror['b']}` hold the same "
            f"{mirror['count']} entries, word for word.",
            "      The artifact is twice the size it needs to be, and the "
            "second copy is what pushes it past the truncation limit — so a "
            "tail reported as missing may only be a copy of the head.",
            "",
        ]

    for pair in report.get("near_duplicates", []):
        lines.append(
            f"  {pair['similarity']}% IDENTICAL: \"{pair['a']}\" and "
            f"\"{pair['b']}\""
        )
        if pair["identical_fields"]:
            lines.append(
                "      word-for-word in: " + ", ".join(pair["identical_fields"])
            )
        lines.append("")

    for seg in report.get("repeated_segments", []):
        lines.append("  THE SAME EXPOSITION APPEARS IN " +
                     str(len(seg["places"])) + " LESSONS:")
        for place in seg["places"]:
            lines.append(f"      {place}")
        lines.append(f"      \"{seg['excerpt']}…\"")
        lines.append("")

    lines += [
        "Judge what this means; do not just repeat it back. Repetition is "
        "sometimes right: a song, a prayer or a routine repeated across "
        "lessons is how a young child learns it, and the design may ask for "
        "exactly that.",
        "What is NOT right is a lesson padded to fill an allocation — the same "
        "teacher exposition, the same misconception, the same formative check "
        "delivered as though it were new teaching. That is a short sub-strand "
        "stretched to the lesson count, and it costs a class a lesson.",
        "Where you find it, say which lessons and score completeness and "
        "curriculum_alignment accordingly.",
    ]
    return "\n".join(lines)

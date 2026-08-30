"""Fix what the checks found, before the guide is offered for review.

Every mechanical check in this pipeline worked and none of them changed
anything. A PP1 guide came back with three lessons built to one template, an
`slo_map` naming a lesson that taught something else, and a learning experience
that was really an outcome. All three were detected, scored, reported — and the
operator's only move was to press the button again and hope.

A validator whose finding changes nothing is a comment.

Two kinds of defect, handled differently:

DETERMINISTIC. An `slo_map` is not an authored opinion — it is a summary of
which module carries which outcome, and the modules already say. Writing it
separately from the modules is what let the two disagree. So it is derived
rather than asked for, and cannot contradict. Likewise an entry in
`learning_experiences_used` that is not one of the design's experiences: it is
removed, because the design's list is the whole of what is allowed there. These
cost nothing and are always right.

MODEL. A lesson that repeats another's shape, or a design experience nobody
taught, needs the lesson rewritten. Those go back to the generator naming the
module and the finding, and the result is re-checked. Bounded, and stopping the
moment a pass fails to improve — a model that has not fixed something in two
attempts will not fix it in five, and each attempt is paid for.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from . import notes_integrity, redundancy_check, run_log

logger = logging.getLogger("cbc-notes-remediation")

MAX_PASSES = 2

# A pass has to clear this much of the outstanding score to be worth another.
MIN_GAIN = 3.0


@dataclass(slots=True)
class Pass:
    number: int
    before: float
    after: float
    deterministic: list[str] = field(default_factory=list)
    asked_of_model: list[int] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.number, "before": self.before, "after": self.after,
                "deterministic": self.deterministic,
                "asked_of_model": self.asked_of_model,
                "findings": self.findings}


@dataclass(slots=True)
class Report:
    attempted: bool = False
    passes: list[Pass] = field(default_factory=list)
    score_before: float = 100.0
    score_after: float = 100.0
    clean: bool = False
    stopped_because: str = ""
    outstanding: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"attempted": self.attempted,
                "score_before": self.score_before,
                "score_after": self.score_after,
                "clean": self.clean,
                "stopped_because": self.stopped_because,
                "outstanding": self.outstanding,
                "passes": [p.to_dict() for p in self.passes]}


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ",
                  re.sub(r"\s+", " ", str(text)).lower()).strip()


def _modules(notes: dict[str, Any]) -> list[dict[str, Any]]:
    found = notes.get("modules")
    if isinstance(found, list) and found:
        return [m for m in found if isinstance(m, dict)]
    return []


def _number(module: dict[str, Any], fallback: int) -> int:
    try:
        return int(module.get("module_number"))
    except (TypeError, ValueError):
        return fallback


# ── the repairs that need no model ──────────────────────────────────────────


def rebuild_slo_map(notes: dict[str, Any], slos: list[str]) -> str:
    """Derive the map from the modules, so the two cannot disagree.

    The model was asked for both and wrote them independently. It said prayer
    was taught in lesson 4; lesson 4 taught something else and contained no
    prayer. A scheme of work is built from the map.
    """
    modules = _modules(notes)
    if not modules:
        return ""

    ordered = [str(s) for s in (slos or []) if str(s).strip()]
    if not ordered:
        seen: list[str] = []
        for module in modules:
            for slo in (module.get("slos_covered") or []):
                if str(slo) not in seen:
                    seen.append(str(slo))
        ordered = seen
    if not ordered:
        return ""

    rows = []
    for slo in ordered:
        key = _norm(slo)
        taught = [
            _number(m, i) for i, m in enumerate(modules, start=1)
            if any(_norm(s) == key for s in (m.get("slos_covered") or []))
        ]
        if not taught:
            # Nothing to derive from. Left out rather than invented — an SLO
            # no lesson claims is a real gap, and the check below reports it.
            continue
        rows.append({"slo": slo, "taught_in": taught,
                     # Assessed where it was taught last: the module that can
                     # see all of it. Derived, so it cannot name a lesson that
                     # does not carry the outcome.
                     "assessed_in": [taught[-1]]})

    was = notes.get("slo_map")
    if rows == was:
        return ""
    notes["slo_map"] = rows
    return (f"Rebuilt `slo_map` from the modules' own `slos_covered` "
            f"({len(rows)} outcome(s) mapped). It is a summary of the modules, "
            f"not a separate opinion, so it is derived rather than authored.")


def strip_invented_experiences(notes: dict[str, Any],
                               design_experiences: list[str]) -> str:
    """Remove anything in `learning_experiences_used` the design never suggested.

    Three modules listed the sub-strand's OUTCOME there. The field is what the
    learner is guided to DO, and the design's seven bullets are the whole of
    what may appear in it — so an entry that matches none of them is removed
    rather than argued with.
    """
    allowed = [_norm(e) for e in (design_experiences or []) if str(e).strip()]
    if not allowed:
        return ""

    removed: list[str] = []
    for module in _modules(notes):
        used = module.get("learning_experiences_used")
        if not isinstance(used, list):
            continue
        keep = []
        for entry in used:
            key = _norm(entry)
            if key and any(key in bullet or bullet in key for bullet in allowed):
                keep.append(entry)
            elif key:
                removed.append(str(entry))
        if keep != used:
            module["learning_experiences_used"] = keep

    if not removed:
        return ""
    unique = sorted(set(removed))
    return (f"Removed {len(unique)} entr(y/ies) from "
            f"`learning_experiences_used` that the design does not suggest: "
            + "; ".join(f'"{r}"' for r in unique[:3])
            + (" …" if len(unique) > 3 else ""))


# ── what still needs the generator ──────────────────────────────────────────


def _inspect(notes: dict[str, Any],
             design_experiences: list[str]) -> tuple[float, list[str], list[int]]:
    """The score, the findings, and which modules a rewrite should target."""
    repetition = redundancy_check.inspect(notes)
    integrity = notes_integrity.check(notes, design_experiences)

    findings = list(repetition.get("findings") or []) + list(integrity.get("findings") or [])
    score = round(
        (float(repetition.get("score", 100.0)) + float(integrity.get("score", 100.0))) / 2, 1
    )

    # Which lessons to rewrite: the later member of each repeated pair. The
    # earlier one is the real lesson and rewriting it loses good work.
    by_title = {str(m.get("title") or ""): _number(m, i)
                for i, m in enumerate(_modules(notes), start=1)}
    targets: list[int] = []
    for pair in (repetition.get("near_duplicates") or []) + \
                (repetition.get("parallel_shapes") or []):
        number = by_title.get(pair.get("b", ""))
        if number and number not in targets:
            targets.append(number)
    return score, findings, targets


def _instruction(findings: list[str], targets: list[int],
                 sub_strand: str, allocation_phrase: str) -> str:
    return "\n".join([
        "=== REWRITE THESE LESSONS. THEY WERE CHECKED AND THEY FAILED. ===",
        f"You wrote a guide for '{sub_strand}' ({allocation_phrase}). It was "
        f"then compared against itself mechanically. These are not opinions "
        f"and they are not style notes:",
        "",
        *[f"  - {f}" for f in findings],
        "",
        f"Rewrite ONLY lesson(s) {', '.join(str(n) for n in targets)}. Return "
        f"the same JSON shape, with `modules` holding ONLY those lessons, each "
        f"keeping its own `module_number`.",
        "",
        "A rewritten lesson must not be the earlier lesson in new words. If two "
        "lessons discuss how a parent does something, then invent a gesture, "
        "then sing a song, they are one lesson however different the sentences "
        "are — change what the lesson DOES, not how it is worded.",
        "The design's own suggested learning experiences are the material. "
        "Where a lesson has run out of them, use one no other lesson has used "
        "yet. Where there are genuinely none left, say so in `gaps` rather "
        "than writing a seventh way to sing a song.",
        "Keep every other lesson exactly as it is; you are not being asked for "
        "them and rewriting them loses work that already passed.",
    ])


def _merge(notes: dict[str, Any], rewritten: Any) -> list[int]:
    """Put the rewritten lessons back, by number. Returns which landed."""
    if not isinstance(rewritten, dict):
        return []
    incoming = rewritten.get("modules")
    if not isinstance(incoming, list):
        return []

    modules = _modules(notes)
    by_number = {_number(m, i): i for i, m in enumerate(modules, start=1)}
    landed: list[int] = []
    for module in incoming:
        if not isinstance(module, dict):
            continue
        number = _number(module, 0)
        index = by_number.get(number)
        if index is None:
            continue
        # Merge rather than replace: a rewrite that omits a field the original
        # had would silently delete it.
        merged = {**modules[index - 1], **{k: v for k, v in module.items() if v}}
        modules[index - 1] = merged
        landed.append(number)

    if landed:
        notes["modules"] = modules
        if isinstance(notes.get("hour_modules"), list):
            notes["hour_modules"] = modules
    return landed


def run(
    notes: dict[str, Any],
    *,
    design_experiences: list[str],
    slos: list[str],
    generate: Any = None,
    model_config: Any = None,
    base_messages: list[dict[str, str]] | None = None,
    sub_strand: str = "",
    allocation_phrase: str = "",
    max_passes: int = MAX_PASSES,
) -> tuple[dict[str, Any], Report]:
    """Repair the guide until the checks pass, it stops improving, or passes run out."""
    report = Report()
    if not isinstance(notes, dict):
        return notes, report

    score, findings, targets = _inspect(notes, design_experiences)
    report.score_before = report.score_after = score
    report.clean = not findings
    if report.clean:
        run_log.step("Self-check", "the guide agrees with itself and repeats nothing")
        report.stopped_because = "clean"
        return notes, report

    run_log.step("Self-check", f"{len(findings)} finding(s) at {score}/100", "warn")
    report.attempted = True

    for number in range(1, max(1, max_passes) + 1):
        this = Pass(number=number, before=score, after=score)

        for repair in (rebuild_slo_map(notes, slos),
                       strip_invented_experiences(notes, design_experiences)):
            if repair:
                this.deterministic.append(repair)
                run_log.step(f"Repair {number}", repair)

        score, findings, targets = _inspect(notes, design_experiences)
        this.after = score

        if not findings:
            this.findings = []
            report.passes.append(this)
            report.stopped_because = "clean"
            run_log.step(f"Re-check {number}", f"clean at {score}/100")
            break

        # What is left needs the generator. Without one — a dry run, or a
        # caller that only wants the free repairs — stop here rather than
        # pretending a pass happened.
        # `base_messages` is checked for None, not for truth: an empty list is
        # a legitimate caller, and treating it as "no generator" silently
        # skipped every rewrite.
        if not (generate and model_config is not None
                and base_messages is not None and targets):
            this.findings = findings
            report.passes.append(this)
            report.stopped_because = (
                "no_generator" if not (generate and model_config is not None
                                       and base_messages is not None)
                else "nothing_to_rewrite")
            run_log.step(f"Re-check {number}",
                         f"{len(findings)} finding(s) left at {score}/100 — "
                         f"no rewrite attempted", "warn")
            break

        run_log.step(f"Rewrite {number}",
                     f"lesson(s) {', '.join(str(n) for n in targets)}: "
                     f"{findings[0][:120]}", "warn")
        this.asked_of_model = targets
        try:
            response = generate(
                model_config,
                (base_messages or []) + [{
                    "role": "user",
                    "content": _instruction(findings, targets, sub_strand,
                                            allocation_phrase),
                }],
                temperature=0.2,
            )
            landed = _merge(
                notes,
                response.content if hasattr(response, "content") else response,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remediation pass %d could not rewrite: %s", number, exc)
            run_log.step(f"Rewrite {number}", f"failed: {exc}", "fail")
            this.findings = findings
            report.passes.append(this)
            report.stopped_because = "rewrite_failed"
            break

        # The deterministic repairs run again over the new lessons, then the
        # whole guide is re-checked — a rewrite can introduce its own defects.
        for repair in (rebuild_slo_map(notes, slos),
                       strip_invented_experiences(notes, design_experiences)):
            if repair:
                this.deterministic.append(repair)

        after, findings, targets = _inspect(notes, design_experiences)
        this.after = after
        this.findings = findings
        report.passes.append(this)
        run_log.step(f"Re-check {number}",
                     f"{len(landed)} lesson(s) rewritten, "
                     f"{score}/100 → {after}/100"
                     + (f", {len(findings)} finding(s) left" if findings else ", clean"),
                     "ok" if after > score else "warn")

        if not findings:
            score = after
            report.stopped_because = "clean"
            break
        if after < score + MIN_GAIN:
            # A model that has not fixed this in one attempt will not fix it in
            # five, and each attempt is paid for.
            score = max(score, after)
            report.stopped_because = "no_improvement"
            break
        score = after
    else:
        report.stopped_because = "max_passes"

    report.score_after = score
    report.clean = not findings
    report.outstanding = findings
    run_log.step(
        "Self-check complete",
        f"{report.score_before}/100 → {report.score_after}/100"
        + (" — clean" if report.clean
           else f" — {len(findings)} finding(s) stand ({report.stopped_because})"),
        "ok" if report.clean else "warn",
    )
    return notes, report

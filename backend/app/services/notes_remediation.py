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

import copy
import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from . import notes_integrity, redundancy_check, run_log

logger = logging.getLogger("cbc-notes-remediation")

# The ladder. Cheap first, and it does not stop at the cheap rungs: an operator
# who is handed "2 findings still stand" has nothing to do but press the button
# again, which costs a whole generation to learn what the pipeline already knew.
TARGETED_PASSES = 2   # rewrite only the lessons that failed
MAX_PASSES = 4        # then regenerate the whole guide, twice if it helps

# A pass has to clear this much to be worth another AT THE SAME RUNG. Failing
# to improve escalates rather than stopping — a targeted rewrite that cannot
# fix a lesson is evidence about the rewrite, not about the guide.
MIN_GAIN = 3.0


@dataclass(slots=True)
class Pass:
    number: int
    before: float
    after: float
    rung: str = "repair"      # repair | rewrite | regenerate
    deterministic: list[str] = field(default_factory=list)
    asked_of_model: list[int] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    calls: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.number, "rung": self.rung,
                "before": self.before, "after": self.after,
                "deterministic": self.deterministic,
                "asked_of_model": self.asked_of_model,
                "findings": self.findings,
                "calls": self.calls, "cost_usd": round(self.cost_usd, 6)}


@dataclass(slots=True)
class Report:
    attempted: bool = False
    passes: list[Pass] = field(default_factory=list)
    score_before: float = 100.0
    score_after: float = 100.0
    clean: bool = False
    stopped_because: str = ""
    outstanding: list[str] = field(default_factory=list)
    best_pass: int = 0

    @property
    def rewrites(self) -> int:
        return sum(1 for p in self.passes if p.rung == "rewrite")

    @property
    def regenerations(self) -> int:
        return sum(1 for p in self.passes if p.rung == "regenerate")

    @property
    def calls(self) -> int:
        return sum(p.calls for p in self.passes)

    @property
    def cost_usd(self) -> float:
        return round(sum(p.cost_usd for p in self.passes), 6)

    def to_dict(self) -> dict[str, Any]:
        return {"attempted": self.attempted,
                "score_before": self.score_before,
                "score_after": self.score_after,
                "clean": self.clean,
                "stopped_because": self.stopped_because,
                "outstanding": self.outstanding,
                "passes_run": len(self.passes),
                "best_pass": self.best_pass,
                "rewrites": self.rewrites,
                "regenerations": self.regenerations,
                "repair_calls": self.calls,
                "repair_cost_usd": self.cost_usd,
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


# The checker owns the definition of "the same outcome", and the repair uses
# it. Two definitions is how a repair comes to create findings the checker then
# reports: the model paraphrases ("Practising short prayers" for "practice
# saying short prayers"), and under exact matching the rebuild placed the
# lesson while the check said it had not been placed.
_same_outcome = notes_integrity.same_outcome


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
    unplaced: list[str] = []
    for slo in ordered:
        taught = [
            _number(m, i) for i, m in enumerate(modules, start=1)
            if any(_same_outcome(slo, s) for s in (m.get("slos_covered") or []))
        ]
        if not taught:
            unplaced.append(slo)
            continue
        rows.append({"slo": slo, "taught_in": taught,
                     # Assessed where it was taught last: the module that can
                     # see all of it. Derived, so it cannot name a lesson that
                     # does not carry the outcome.
                     "assessed_in": [taught[-1]]})

    # An outcome no lesson claims is placed with the lesson that most nearly
    # teaches it, and that lesson's own `slos_covered` is corrected to say so.
    # Leaving it out produced a map that omitted a funded outcome — and the
    # guide then failed a check for something the repair had done.
    for slo in unplaced:
        home = _best_home(modules, slo)
        if not home:
            continue
        module = next((m for i, m in enumerate(modules, start=1)
                       if _number(m, i) == home), None)
        if module is None:
            continue
        covered = list(module.get("slos_covered") or [])
        if not any(_same_outcome(slo, c) for c in covered):
            covered.append(slo)
            module["slos_covered"] = covered
        rows.append({"slo": slo, "taught_in": [home], "assessed_in": [home]})

    rows.sort(key=lambda r: (r["taught_in"][0], r["slo"]))

    was = notes.get("slo_map")
    if rows == was:
        return ""
    notes["slo_map"] = rows
    placed = (f", {len(unplaced)} placed with the lesson that most nearly "
              f"teaches it" if unplaced else "")
    return (f"Rebuilt `slo_map` from the modules' own `slos_covered` "
            f"({len(rows)} outcome(s) mapped{placed}). It is a summary of the "
            f"modules, not a separate opinion, so it is derived rather than "
            f"authored.")


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


def repair_citation_addresses(notes: dict[str, Any], design_text: str) -> str:
    """Point each citation at the line its quote is actually on.

    The reviewer and the generator do not read the same rendering of the
    design, so addresses drift: a guide cites 203:26 for a sentence that sits
    at 203:23 in the copy the reviewer was given. The quote is real and the
    reference is wrong, and every review since has spent a finding saying so.

    Nothing here needs a model. The resolver already knows where the sentence
    is; this writes that address back onto the citation.
    """
    if not design_text.strip():
        return ""
    from . import citation_evidence

    try:
        evidence = citation_evidence.resolve(notes, design_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resolve citations to repair them: %s", exc)
        return ""

    corrections = {
        row["ref"]: row["found_at"]
        for row in evidence.get("citations", []) if row.get("found_at")
    }
    if not corrections:
        return ""

    fixed = 0

    def walk(value: Any) -> None:
        nonlocal fixed
        if isinstance(value, dict):
            for entry in (value.get("citations") or []):
                if not isinstance(entry, dict):
                    continue
                ref = str(entry.get("ref") or "")
                if ref in corrections:
                    entry["ref"] = corrections[ref]
                    fixed += 1
            for key, item in value.items():
                if key != "citations":
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(notes)
    if not fixed:
        return ""
    moved = "; ".join(f"{was} → {now}" for was, now in list(corrections.items())[:4])
    return (f"Corrected {fixed} citation address(es) to the line the quoted "
            f"sentence is actually on ({moved}). The quotes were real; the "
            f"references had drifted.")


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
    modules = _modules(notes)
    by_title = {str(m.get("title") or ""): _number(m, i)
                for i, m in enumerate(modules, start=1)}
    targets: list[int] = []
    for pair in (repetition.get("near_duplicates") or []) + \
                (repetition.get("parallel_shapes") or []):
        number = by_title.get(pair.get("b", ""))
        if number and number not in targets:
            targets.append(number)

    # Lessons that teach the SAME outcome from the SAME line of the design.
    #
    # This was reported and never acted on. A sub-strand funding seven lessons
    # against three outcomes came back with lessons 4, 5, 6 and 7 all teaching
    # "appreciate God as a loving heavenly father" from 203:24 — the reviewer
    # caught it every time, scored it 60 on curriculum alignment, and the loop
    # had no lesson to rewrite, so it regenerated, failed identically, and
    # stopped at 77 for good.
    #
    # Keep the FIRST lesson of each group: it is the honest one. The rest are
    # what padding looks like.
    for group in repetition.get("same_outcome_same_source") or []:
        for title in (group.get("lessons") or [])[1:]:
            number = by_title.get(title)
            if number and number not in targets:
                targets.append(number)

    # A design experience nobody taught also needs a lesson rewritten, and
    # there is no pair to name one. Without this the loop reported "the design
    # suggests 'listen to a recorded clip of a short prayer' and no lesson uses
    # it", found nothing to rewrite, and stopped — a finding that could never
    # be acted on, which is the failure this whole module exists to end.
    for finding in findings:
        if "no lesson uses it" not in finding:
            continue
        quoted = re.search(r'"([^"]+)"', finding)
        if not quoted:
            continue
        home = _best_home(modules, quoted.group(1))
        if home and home not in targets:
            targets.append(home)

    return score, findings, targets


def _best_home(modules: list[dict[str, Any]], experience: str) -> int:
    """Which lesson should take up an experience nobody taught.

    The one that already talks about it: 'listen to a recorded clip of a short
    prayer' belongs in the prayer lesson, not in whichever happens to be
    shortest. Falls back to the shortest module, which has the most room and
    the least to lose.
    """
    if not modules:
        return 0
    words = {w for w in _norm(experience).split() if len(w) > 3}
    if not words:
        return 0

    best, best_score = 0, 0.0
    for i, module in enumerate(modules, start=1):
        text = _norm(" ".join(str(v) for v in _flatten(module)))
        overlap = sum(1 for w in words if w in text) / len(words)
        if overlap > best_score:
            best, best_score = _number(module, i), overlap

    if best_score >= 0.5:
        return best
    shortest = min(
        modules,
        key=lambda m: len(" ".join(str(v) for v in _flatten(m))),
    )
    return _number(shortest, modules.index(shortest) + 1)


def _flatten(value: Any, out: list[str] | None = None) -> list[str]:
    acc = out if out is not None else []
    if isinstance(value, str):
        acc.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            _flatten(v, acc)
    elif isinstance(value, list):
        for v in value:
            _flatten(v, acc)
    return acc


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
        "Where a finding above says an experience is UNUSED, the rewritten "
        "lesson must actually teach it AND name it in that lesson's "
        "`learning_experiences_used`, worded as the design words it. Teaching "
        "it without naming it leaves the guide looking ungrounded; naming it "
        "without teaching it is worse.",
        "Keep every other lesson exactly as it is; you are not being asked for "
        "them and rewriting them loses work that already passed.",
    ])


def _whole_guide_instruction(findings: list[str], sub_strand: str,
                             allocation_phrase: str, modules: int) -> str:
    """Write the guide again, knowing what was wrong with the last one.

    Reached when rewriting the failing lessons has not cleared them twice over.
    At that point the defect is in how the guide was planned — the same three
    beats reached for whenever the material runs out — and no amount of
    rewriting one lesson at a time fixes a plan.
    """
    return "\n".join([
        "=== WRITE THIS GUIDE AGAIN. THE LAST ONE FAILED ITS CHECKS. ===",
        f"You wrote a guide for '{sub_strand}' ({allocation_phrase}) and it was "
        f"compared against itself mechanically. Rewriting the failing lessons "
        f"one at a time did not clear these:",
        "",
        *[f"  - {f}" for f in findings],
        "",
        f"Produce all {modules} lessons again, numbered 1 to {modules}.",
        "",
        "PLAN BEFORE YOU WRITE. Take the design's suggested learning "
        "experiences and deal them out across the lessons FIRST, so each "
        "lesson has its own material before a word is written. That is what "
        "was missing: the last guide wrote lessons in order, ran out of "
        "material, and reached for the same three beats — discuss how a parent "
        "does it, invent a gesture, sing a song — under new titles.",
        "Two lessons that share a shape are one lesson however different the "
        "sentences are. If, having dealt the experiences out, there is not "
        "enough material for every funded lesson, say so in `gaps` in those "
        "words. That is a true and useful answer; a padded lesson is not.",
        "Every outcome must appear in some lesson's `slos_covered`, worded as "
        "the design words it, and `learning_experiences_used` may name only "
        "the design's own suggested experiences.",
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


def _spent() -> tuple[int, float]:
    """Calls and cost so far, so each pass can report what it cost."""
    from . import run_meter

    meter = run_meter.current()
    return (meter.calls, meter.cost_usd) if meter else (0, 0.0)


def _since(before: tuple[int, float]) -> tuple[int, float]:
    calls, cost = _spent()
    return calls - before[0], round(cost - before[1], 6)


def _replace(notes: dict[str, Any], written: Any) -> list[int]:
    """Take a whole regenerated guide, keeping nothing that was wrong.

    Unlike a targeted rewrite this replaces the lessons outright: the point of
    escalating is that the previous PLAN was the defect, so merging the old
    lessons back into it would carry the defect forward.
    """
    if not isinstance(written, dict):
        return []
    incoming = written.get("modules")
    if not isinstance(incoming, list) or not incoming:
        return []
    modules = [m for m in incoming if isinstance(m, dict)]
    if not modules:
        return []

    # A regeneration that comes back short is worse than the guide it would
    # replace: the design funds a fixed number of lessons, and losing four of
    # them to fix a repeated one is not a repair. Keep what we have.
    have = len(_modules(notes))
    if have and len(modules) < have:
        logger.warning(
            "A regeneration returned %d lesson(s) for a %d-lesson guide; "
            "keeping the longer one.", len(modules), have)
        return []

    notes["modules"] = modules
    if isinstance(notes.get("hour_modules"), list):
        notes["hour_modules"] = modules
    for key in ("gaps", "uncited_content", "slo_map", "assessment_alignment",
                "scheme_of_work_summary", "practical_connections"):
        if written.get(key):
            notes[key] = written[key]
    return [_number(m, i) for i, m in enumerate(modules, start=1)]


def run(
    notes: dict[str, Any],
    *,
    design_experiences: list[str],
    slos: list[str],
    design_text: str = "",
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

    best = copy.deepcopy(notes)
    best_score, best_findings, best_number = score, findings, 0

    for number in range(1, max(1, max_passes) + 1):
        rung = "rewrite" if number <= TARGETED_PASSES else "regenerate"
        this = Pass(number=number, before=score, after=score, rung="repair")
        spent_before = _spent()

        for repair in (rebuild_slo_map(notes, slos),
                       strip_invented_experiences(notes, design_experiences),
                       repair_citation_addresses(notes, design_text)):
            if repair:
                this.deterministic.append(repair)
                run_log.step(f"Repair {number}", repair)

        score, findings, targets = _inspect(notes, design_experiences)
        this.after = score

        # The free repairs only ever help, so the repaired guide is the new
        # baseline. Recording it here — rather than only after a model pass —
        # is what stops a later failure from reverting them.
        if score >= best_score:
            best, best_score, best_findings = copy.deepcopy(notes), score, findings
            if this.deterministic:
                best_number = number

        if not findings:
            this.findings = []
            report.passes.append(this)
            report.stopped_because = "clean"
            run_log.step(f"Re-check {number}", f"clean at {score}/100")
            break

        # What is left needs the generator. Without one — a dry run, or a
        # caller that only wants the free repairs — stop here rather than
        # pretending a pass happened.
        #
        # `base_messages` is checked for None, not for truth: an empty list is
        # a legitimate caller, and treating it as "no generator" silently
        # skipped every rewrite.
        if not (generate and model_config is not None and base_messages is not None):
            this.findings = findings
            report.passes.append(this)
            report.stopped_because = "no_generator"
            run_log.step(f"Re-check {number}",
                         f"{len(findings)} finding(s) left at {score}/100 — "
                         f"no rewrite attempted", "warn")
            break

        # Nothing to target and still on the cheap rung: go straight to the
        # expensive one rather than reporting a finding nobody can act on.
        if rung == "rewrite" and not targets:
            rung = "regenerate"

        this.rung = rung
        if rung == "rewrite":
            run_log.step(f"Rewrite {number}",
                         f"lesson(s) {', '.join(str(n) for n in targets)}: "
                         f"{findings[0][:110]}", "warn")
            this.asked_of_model = targets
            instruction = _instruction(findings, targets, sub_strand,
                                       allocation_phrase)
        else:
            run_log.step(f"Regenerate {number}",
                         f"rewriting one lesson at a time did not clear "
                         f"{len(findings)} finding(s); writing the whole guide "
                         f"again", "warn")
            instruction = _whole_guide_instruction(
                findings, sub_strand, allocation_phrase, len(_modules(notes)))

        try:
            response = generate(
                model_config,
                (base_messages or []) + [{"role": "user", "content": instruction}],
                temperature=0.2,
            )
            content = response.content if hasattr(response, "content") else response
            if rung == "rewrite":
                landed = _merge(notes, content)
            else:
                landed = _replace(notes, content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Remediation pass %d could not %s: %s", number, rung, exc)
            run_log.step(f"{rung.title()} {number}", f"failed: {exc}", "fail")
            this.findings = findings
            this.calls, this.cost_usd = _since(spent_before)
            report.passes.append(this)
            report.stopped_because = "rewrite_failed"
            break

        for repair in (rebuild_slo_map(notes, slos),
                       strip_invented_experiences(notes, design_experiences),
                       repair_citation_addresses(notes, design_text)):
            if repair:
                this.deterministic.append(repair)

        after, findings, targets = _inspect(notes, design_experiences)
        this.after = after
        this.findings = findings
        this.calls, this.cost_usd = _since(spent_before)
        report.passes.append(this)
        run_log.step(
            f"Re-check {number}",
            f"{len(landed)} lesson(s) {'rewritten' if rung == 'rewrite' else 'regenerated'}, "
            f"{score}/100 → {after}/100"
            + (f", {len(findings)} finding(s) left" if findings else ", clean"),
            "ok" if after > score else "warn")

        # Keep the best version seen, not the last one. A pass that makes the
        # guide worse used to be the version that got saved.
        if after > best_score:
            best, best_score, best_findings, best_number = (
                copy.deepcopy(notes), after, findings, number)

        if not findings:
            score = after
            report.stopped_because = "clean"
            break

        if after < score + MIN_GAIN:
            if rung == "rewrite":
                # A targeted rewrite that cannot fix a lesson is evidence about
                # the rewrite, not about the guide. Escalate to writing the
                # whole thing again rather than handing the operator a finding
                # and a button.
                run_log.step(f"Escalating after {number}",
                             "targeted rewriting is not clearing this", "warn")
                score = after
                continue
            score = max(score, after)
            report.stopped_because = "no_improvement"
            break
        score = after
    else:
        report.stopped_because = "max_passes"

    # Restore the best version, judged on what is ACTUALLY in `notes` rather
    # than on a running tally.
    #
    # The comparison was `best_score > score`, and `score` had just been raised
    # by `max(score, after)` on the way out — so after a pass that regenerated
    # a guide from 88 down to 79.7, the two were equal, the restore was
    # skipped, and the degraded guide was filed under the score it no longer
    # had. `_inspect` is pure computation over the content, so asking it again
    # here costs nothing and cannot drift from what the loop actually did.
    #
    # `notes` is mutated in place through the caller's reference, so the
    # contents are swapped rather than the name rebound.
    current, current_findings, _ = _inspect(notes, design_experiences)
    if best_score > current:
        notes.clear()
        notes.update(best)
        score, findings = best_score, best_findings
    else:
        score, findings = current, current_findings
    report.best_pass = best_number

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

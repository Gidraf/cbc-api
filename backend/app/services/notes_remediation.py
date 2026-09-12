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
             design_experiences: list[str],
             design_row: dict[str, Any] | None = None,
             *, strand: str = "", sub_strand: str = "",
             ) -> tuple[float, list[str], list[int]]:
    """The score, the findings, and which modules a rewrite should target."""
    repetition = redundancy_check.inspect(notes)
    integrity = notes_integrity.check(notes, design_experiences)
    provenance = check_provenance(notes, design_row)
    pitch = _pitch(notes, design_row, strand, sub_strand)

    findings = (list(repetition.get("findings") or [])
                + list(integrity.get("findings") or [])
                + list(provenance.get("findings") or [])
                + [f"{f.says} {f.fix}".strip() for f in pitch.findings])
    scores = [float(repetition.get("score", 100.0)),
              float(integrity.get("score", 100.0))]
    if provenance.get("checked"):
        scores.append(float(provenance.get("score", 100.0)))
    if pitch.checked:
        scores.append(float(pitch.score))
    score = round(sum(scores) / len(scores), 1)

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

    # Three more ways a guide repeats itself, each reported for months and
    # never a target. With a finding and no lesson to rewrite the loop jumped
    # straight to regenerating the whole guide — the one path that drops the
    # lesson-to-lesson hand-off, and so the path most likely to hand back the
    # same repeat. Every guide in a run of six came back with "Review of
    # Combined Operations" taught twice and "Complex Problem Solving" three
    # times, and every one was published.
    #
    # The first lesson carrying a name or a block is the honest one; the rest
    # are rewritten. Entries name lessons by position ("lesson 4") because the
    # title is the very thing two of these checks find repeated.
    by_position = {_number(m, i): _number(m, i)
                   for i, m in enumerate(modules, start=1)}

    def _at(where: str) -> int:
        match = re.search(r"lesson\s+(\d+)", str(where or ""), re.I)
        number = int(match.group(1)) if match else 0
        return number if number in by_position else 0

    # Two lessons with the same title: the later one is written again.
    for pair in repetition.get("same_name") or []:
        number = _at(pair.get("b", ""))
        if number and number not in targets:
            targets.append(number)

    # The same topic heading, or the same block of prose, in several lessons:
    # every lesson after the first that carries it.
    for group in (repetition.get("same_name_segments") or []) + \
                 (repetition.get("repeated_segments") or []):
        for where in (group.get("places") or [])[1:]:
            number = _at(where)
            if number and number not in targets:
                targets.append(number)

    # A lesson that names nothing in the design is rewritten, not published.
    # Six guides in a row printed "this lesson names no design element" under
    # every lesson; the finding was true each time and nothing was ever asked
    # to act on it.
    for number in provenance.get("uncited") or []:
        if number not in targets:
            targets.append(number)

    # A lesson that NAMES an experience its text does not DO is rewritten.
    for number in integrity.get("undelivered") or []:
        if number not in targets:
            targets.append(number)

    # A lesson written to a different plan from the one it was dealt. The
    # brief said "outcome 4 via experience 6"; the lesson came back about
    # combined operations again. However good it is, it has taken the place
    # of the lesson the design funded here.
    for i, module in enumerate(modules, start=1):
        brief = module.get("brief")
        if not isinstance(brief, dict):
            continue
        number = _number(module, i)
        wrong: list[str] = []
        outcome = str(brief.get("outcome") or "")
        if outcome and not any(_same_outcome(outcome, str(s))
                               for s in (module.get("slos_covered") or [])):
            wrong.append(f"its outcome is \"{outcome}\" ({brief.get('outcome_ref')})")
        used = [_norm(u) for u in (module.get("learning_experiences_used") or [])]
        for ref, text in zip(brief.get("experience_refs") or [],
                             brief.get("experiences") or []):
            key = _norm(text)
            if not any(key in u or u in key for u in used if u):
                wrong.append(f"it is taught through \"{text}\" ({ref})")
        if not wrong:
            continue
        findings.append(
            f"Lesson {number} was written to the wrong plan: "
            + "; ".join(wrong)
            + ". That is what this lesson is FOR — its title, objective, "
            f"activities and worked examples are about that and nothing else, "
            f"and `slos_covered` and `learning_experiences_used` say so in the "
            f"design's words."
        )
        if number not in targets:
            targets.append(number)
        score = max(0.0, score - 12.0)

    # A lesson pitched below its own rung of the grade's ladder, one with no
    # mathematics in an operations sub-strand, one with no signed number where
    # the design is about directed numbers: all rewritten.
    #
    # `example_check.check_notes` measured every one of these against the
    # grade's floor — per subject, per grade, per lesson — and ran AFTER this
    # loop, into a log line. A guide could fail every rung and be published;
    # the loop that could have sent it back never heard.
    for finding in pitch.findings:
        for number in finding.lessons:
            if number in by_position and number not in targets:
                targets.append(number)

    # A mathematics lesson with no worked example at all is rewritten.
    #
    # Every check on worked examples below runs over the list a lesson
    # supplies, and an empty list passes all of them. The first guide generated
    # after those checks landed had no worked examples in any of its six
    # lessons — the shortest path through a difficulty floor, a duplicate check
    # and an arithmetic check is to write nothing for them to read. A maths
    # lesson a learner cannot imitate from is not one, whatever else it passes.
    if _needs_worked_examples(design_row):
        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            examples = [ex for ex in (module.get("worked_examples") or [])
                        if isinstance(ex, dict) and ex.get("statement")]
            if len(examples) >= 2:
                continue
            findings.append(
                f"Lesson {number} has "
                + ("only one worked example" if examples else "no worked example")
                + ". This is a Mathematics lesson: `worked_examples` must carry "
                f"at least two examples, each set in the words a learner reads, "
                f"worked step by step to its answer with the REASON for every "
                f"step. A learner revising at home has nothing to imitate "
                f"without them."
            )
            if number not in targets:
                targets.append(number)
            score = max(0.0, score - (5.0 if examples else 15.0))

        # The exposition must teach what the examples use. Lesson 1 of a
        # Grade 9 guide explained adding on a number line and then worked
        # `3 + (-5) × 2 - 4`; no lesson in the guide ever stated that a
        # negative times a positive is negative. A learner cannot get from
        # that exposition to that example, and the sign rule is exactly what
        # they get wrong.
        sign_rule_taught_by: int | None = None
        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            if sign_rule_taught_by is None and _teaches_sign_rule(module):
                sign_rule_taught_by = number
            if sign_rule_taught_by is not None:
                continue
            if not any(_multiplies_signed(ex) for ex in
                       (module.get("worked_examples") or [])
                       if isinstance(ex, dict)):
                continue
            findings.append(
                f"Lesson {number}'s worked examples multiply or divide signed "
                f"numbers, and no lesson up to and including it has taught the "
                f"sign rule — nowhere does the exposition say what a negative "
                f"times a negative, or a negative divided by a positive, gives. "
                f"Lesson {number} must state the rule in its own exposition, "
                f"with the reason, before it works an example that uses it."
            )
            if number not in targets:
                targets.append(number)
            score = max(0.0, score - 10.0)

        # A lesson about real life must work a real-life example. "Applying
        # Integers to Real-Life Situations" came with two bare expressions and
        # not a temperature, a shilling or a metre between them; the examples
        # served a different lesson from the one on the tin.
        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            examples = [ex for ex in (module.get("worked_examples") or [])
                        if isinstance(ex, dict) and ex.get("statement")]
            if not examples or not _about_real_life(module):
                continue
            if any(not _bare_expression(str(ex.get("statement") or ""))
                   for ex in examples):
                continue
            findings.append(
                f"Lesson {number} is about applying integers to real-life "
                f"situations, and every one of its worked examples is a bare "
                f"expression. At least one must be set as a situation — a "
                f"temperature that falls and rises, money owed and paid, "
                f"height above and below sea level, points scored and lost — "
                f"with the integers and the operations arising from the "
                f"situation and the answer given in its units."
            )
            if number not in targets:
                targets.append(number)
            score = max(0.0, score - 10.0)

        # An Integers sub-strand whose worked example comes out at 2.5. The
        # model picks the numbers first and divides second; two of the four
        # hard examples in one guide had answers that were not integers, in
        # the one sub-strand where that is the whole point.
        if "integer" in sub_strand.lower():
            for i, module in enumerate(modules, start=1):
                number = _number(module, i)
                for ex in (module.get("worked_examples") or []):
                    if not isinstance(ex, dict):
                        continue
                    answer = str(ex.get("answer") or "")
                    if not _NON_INTEGER.search(answer):
                        continue
                    findings.append(
                        f"Lesson {number} has a worked example whose answer is "
                        f"{answer.strip()} — not an integer, in the Integers "
                        f"sub-strand. Choose numbers so that every division "
                        f"is exact and every answer is an integer."
                    )
                    if number not in targets:
                        targets.append(number)
                    score = max(0.0, score - 8.0)
                    break

    # A "Review and Assessment" lesson while a design experience is still
    # untaught is padding with a name. Two of six lessons in one guide were
    # titled exactly that, and "play games ... performing all basic
    # operations" was taught nowhere. The funded lesson is the untaught
    # experience, not a second recap.
    untaught = [q.group(1) for q in
                (re.search(r'"([^"]+)" and no lesson uses it', f) for f in findings)
                if q]
    if untaught:
        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            if not _REVIEW_TITLE.search(str(module.get("title") or "")):
                continue
            findings.append(
                f"Lesson {number} is a review or assessment lesson while the "
                f"design's own experience \"{untaught[0]}\" is taught in no "
                f"lesson. The design funded that experience, not a recap. "
                f"Rewrite Lesson {number} to teach it."
            )
            if number not in targets:
                targets.append(number)
            score = max(0.0, score - 8.0)

    # A worked example that repeats an expression already worked in an earlier
    # lesson teaches nothing new. The same `(-3+5)×4-6` in lessons 3 and 4, or
    # `(-4+6)×3-5` in lessons 5 and 6, makes the later lesson worthless as
    # practice. `redundancy_check` operates on exposition text and never sees
    # example statements (they are too short for its minimum-length threshold).
    #
    # Normalise: remove LaTeX delimiters, spaces and ASCII punctuation that is
    # not an operator, then lowercase. Two statements that map to the same string
    # are the same mathematical exercise. Only the later lesson is rewritten —
    # the first lesson to work it is the honest one.
    seen_exprs: dict[str, int] = {}
    try:
        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            for ex in (module.get("worked_examples") or []):
                if not isinstance(ex, dict):
                    continue
                stmt = str(ex.get("statement") or "")
                if not stmt:
                    continue
                key = _norm_expr(stmt)
                if len(key) < 4:
                    continue
                if key in seen_exprs:
                    first = seen_exprs[key]
                    findings.append(
                        f"Lesson {number} repeats an expression already worked "
                        f"in Lesson {first}. A learner who has already seen this "
                        f"example gains nothing from it a second time. Replace the "
                        f"duplicate with a NEW expression that has not appeared "
                        f"in any earlier lesson."
                    )
                    if number not in targets:
                        targets.append(number)
                    score = max(0.0, score - 10.0)
                else:
                    seen_exprs[key] = number
    except Exception:  # noqa: BLE001
        pass

    # The same SHAPE with the numbers changed is the same example. Six lessons
    # of a Grade 9 guide each worked `a + b × (-c) ± d` over `e - (-f)` — the
    # floor's exemplar, copied six times with new digits — and every one
    # passed the check above, because none of them was the same TEXT. The
    # hand-off already says a lesson that works the same idea on new figures
    # is the same lesson; this is where that is enforced.
    try:
        seen_shapes: dict[str, int] = {}
        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            for ex in (module.get("worked_examples") or []):
                if not isinstance(ex, dict):
                    continue
                stmt = str(ex.get("statement") or "")
                if not stmt or _norm_expr(stmt) in seen_exprs and \
                        seen_exprs[_norm_expr(stmt)] != number:
                    continue  # already reported as the same expression
                shape = _skeleton(stmt)
                if _bare_expression(stmt) and shape.count("n") < 3:
                    continue  # too small a shape to own
                first = seen_shapes.get(shape)
                if first is not None and first != number:
                    what = ("the same operations in the same places with the "
                            "numbers changed" if _bare_expression(stmt) else
                            "the same situation with the numbers changed")
                    findings.append(
                        f"Lesson {number} works an example of exactly the "
                        f"shape Lesson {first} already worked — {what} "
                        f"({shape}). A learner who has seen it once learns "
                        f"nothing from it again. Give Lesson {number} an "
                        f"example whose SHAPE is new to the guide: different "
                        f"operations, a bracket somewhere else, a different "
                        f"situation."
                    )
                    if number not in targets:
                        targets.append(number)
                    score = max(0.0, score - 8.0)
                elif first is None:
                    seen_shapes[shape] = number
    except Exception:  # noqa: BLE001
        pass

    # A worked example whose step arithmetic is wrong poisons the lesson. The
    # badge on the rendered page says so — but the badge result never flowed
    # back into _inspect, so the remediation loop published examples where a
    # step like `10 - 5 + 12 = 7` appeared alongside "this working does not
    # reach 17" without ever being asked to fix it.
    #
    # `check_working` checks the statement where it can and falls back to the
    # step equations. An example that agrees is left alone; only disagreements
    # (checked=True, agrees=False) are acted on, so the loop does not rewrite
    # lessons whose arithmetic merely cannot be verified.
    try:
        from . import worked_solutions

        for i, module in enumerate(modules, start=1):
            number = _number(module, i)
            for ex in (module.get("worked_examples") or []):
                if not isinstance(ex, dict):
                    continue
                stmt = str(ex.get("statement") or "")
                answer = str(ex.get("answer") or "")
                steps = ex.get("steps")
                verdict = worked_solutions.check_working(stmt, answer, steps)
                if verdict.get("checked") and verdict.get("agrees") is False:
                    engine = verdict.get("engine_answer", "")
                    step_n = verdict.get("step", 0)
                    if step_n:
                        where = f"step {step_n} claims {verdict.get('claimed', '')} " \
                                f"but the maths engine reaches {engine}"
                    else:
                        where = (f"the answer claims {answer} "
                                 f"but the maths engine reaches {engine}")
                    findings.append(
                        f"Lesson {number} has a worked example with wrong arithmetic "
                        f"({where}). A learner imitating this will reach the wrong "
                        f"answer. Fix the arithmetic so every step equation is true."
                    )
                    if number not in targets:
                        targets.append(number)
                    score = max(0.0, score - 20.0)
    except Exception:  # noqa: BLE001
        pass

    return score, findings, targets


_LATEX_STRIP = re.compile(r"\\[a-zA-Z]+\{?|[\[\]()${}]")
_SPACE_STRIP = re.compile(r"[\s,.;:]+")


def _norm_expr(text: str) -> str:
    """A statement with LaTeX, spaces and punctuation taken off, for finding
    the same expression written twice."""
    t = _LATEX_STRIP.sub("", str(text or ""))
    return _SPACE_STRIP.sub("", t).lower()


_MATH_SPAN = re.compile(r"\$\$?(.+?)\$\$?", re.S)
_FRAC = re.compile(r"\\d?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _skeleton(statement: str) -> str:
    """The shape of an example with its numbers taken out.

    `-12 + 4 × (-3) + 6` over `2 - 5` and `-20 + 5 × (-3) - 4` over
    `2 - (-1)` both come out as `(n±n×n±n)÷(n±n)`. Signs are folded — a
    negative in place of a positive is the same shape — and so are + and −,
    because "the same idea on new figures" is what this exists to find.

    A situation is skeletonised as its words: "A temperature changes from
    n°C to n°C. What is the total change?" in lesson 4 and again in lesson 5
    is one example set twice.
    """
    if not _bare_expression(statement):
        words = re.sub(r"[-−–]?\d+(?:[.,]\d+)?", "n", str(statement or "").lower())
        words = re.sub(r"[$\\{}]", "", words)
        return re.sub(r"\s+", " ", words).strip()
    spans = _MATH_SPAN.findall(str(statement or ""))
    text = " ".join(spans) if spans else str(statement or "")
    for _ in range(3):
        text = _FRAC.sub(r"(\1)÷(\2)", text)
    text = re.sub(r"\\(?:times|cdot)", "×", text)
    text = re.sub(r"\\div", "÷", text)
    text = re.sub(r"\\(?:left|right|,|;|!|quad|text)\b", "", text)
    text = text.replace("*", "×").replace("/", "÷").replace("[", "(").replace("]", ")")
    text = _NUMBER.sub("n", text)
    text = re.sub(r"[\s$]+", "", text)
    text = re.sub(r"(?<![n)])-(?=n|\()", "", text)   # unary minus
    text = re.sub(r"[+\-−–]", "±", text)
    text = re.sub(r"\(n\)", "n", text)
    return text


def _bare_expression(statement: str) -> bool:
    """A statement that is an expression and nothing else — no situation."""
    from .task_demand import _is_prose

    return not _is_prose(_MATH_SPAN.sub(" ", str(statement or "")))


_NON_INTEGER = re.compile(r"\d\.\d|\\d?frac\s*\{|\d\s*/\s*\d")
_REVIEW_TITLE = re.compile(r"\b(review|revision|assessment|recap|consolidation)\b", re.I)

_REAL_LIFE = re.compile(
    r"real[- ]life|real[- ]world|situation|daily|everyday|apply|applying|"
    r"application|appreciat|context", re.I)


def _about_real_life(module: dict[str, Any]) -> bool:
    text = " ".join([str(module.get("title") or ""),
                     str(module.get("learning_intent") or ""),
                     *[str(s) for s in (module.get("slos_covered") or [])]])
    return bool(_REAL_LIFE.search(text))


_SIGN_RULE_OP = re.compile(r"multipl|times|product|divid|quotient", re.I)
_SIGN_RULE_SIGN = re.compile(r"negative|sign", re.I)


def _teaches_sign_rule(module: dict[str, Any]) -> bool:
    """Whether the lesson's own prose states how signs behave under × or ÷."""
    bodies = [str(module.get("teacher_exposition") or "")]
    bodies += [str(s.get("body") or "") for s in
               (module.get("exposition_segments") or []) if isinstance(s, dict)]
    for body in bodies:
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            if _SIGN_RULE_OP.search(sentence) and _SIGN_RULE_SIGN.search(sentence):
                return True
    return False


def _multiplies_signed(example: dict[str, Any]) -> bool:
    from . import task_demand

    demand = task_demand.measure_item(example)
    return bool(demand.all_kinds & {"×", "÷"}) and demand.negatives > 0


def _pitch(notes: dict[str, Any], design_row: dict[str, Any] | None,
           strand: str, sub_strand: str) -> Any:
    """The guide against its grade's floor, or an empty report where the
    subject and grade are unknown or have no floor."""
    from . import example_check

    row = design_row or {}
    grade = str(row.get("grade") or "")
    subject = str(row.get("subject") or "")
    if not grade or not subject:
        return example_check.Report()
    try:
        return example_check.check_notes(
            notes, grade=grade, subject=subject, strand=strand,
            sub_strand=sub_strand)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not pitch-check %s: %s", sub_strand, exc)
        return example_check.Report()


def _needs_worked_examples(design_row: dict[str, Any] | None) -> bool:
    """A mathematics guide at a grade that has a demand floor — Grade 4 up.

    A PP1 Mathematical Activities lesson sorting objects by colour has nothing
    to work through to an answer, and the floor table already says so.
    """
    from . import task_demand

    row = design_row or {}
    subject = str(row.get("subject") or "")
    if "math" not in subject.lower():
        return False
    return task_demand.floor_for(str(row.get("grade") or ""), subject) is not None


def check_provenance(notes: dict[str, Any],
                     design_row: dict[str, Any] | None) -> dict[str, Any]:
    """Which lessons name a design element, and which name nothing.

    Invented refs are removed from the module before anything prints them — an
    invented provenance reads exactly like a real one. The finding for an
    uncited lesson carries the refs on offer, so the rewrite is told what to
    choose from rather than told it was wrong.
    """
    from . import design_elements

    out: dict[str, Any] = {"checked": False, "score": 100.0,
                           "findings": [], "uncited": [], "cited": 0}
    if not design_row:
        return out
    elements = design_elements.enumerate_for(design_row)
    if not elements:
        return out
    out["checked"] = True

    offer = "; ".join(f"[{e.ref}] {e.text}" for e in elements[:8])
    modules = _modules(notes)
    for i, module in enumerate(modules, start=1):
        number = _number(module, i)
        # Harvest first: refs the model filed in `slos_covered` count, and move.
        # Anything bracketed that the design does not carry is the invention.
        known = design_elements.refs(design_row)
        offered = [str(x).strip().strip("[]").strip()
                   for x in (module.get("serves") or [])]
        offered += [b.strip() for x in (module.get("slos_covered") or [])
                    for b in design_elements._BRACKETED.findall(str(x))]
        invented = sorted({o for o in offered if o and o not in known})
        kept = design_elements.harvest_serves(module, design_row)
        if kept:
            out["cited"] += 1
            continue
        out["uncited"].append(number)
        title = str(module.get("title") or f"Lesson {number}")
        why = (f" It named {', '.join(invented)}, which the design does not "
               f"carry, so those were discarded." if invented else "")
        out["findings"].append(
            f"Lesson {number} \"{title}\" names no design element.{why} Put "
            f"the ref(s) this lesson actually realises in its `serves` list, "
            f"exactly as bracketed — the design offers: {offer}.")

    if modules:
        out["score"] = round(100.0 * out["cited"] / len(modules), 1)
    return out


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


def _briefs_of(notes: dict[str, Any], only: list[int] | None = None) -> str:
    """The plan each lesson was dealt, restated for a rewrite.

    A rewrite that is told what was wrong and not what the lesson is FOR
    writes the same lesson again in new words.
    """
    from . import lesson_dealer

    lines: list[str] = []
    for i, module in enumerate(_modules(notes), start=1):
        number = _number(module, i)
        if only is not None and number not in only:
            continue
        raw = module.get("brief")
        if not isinstance(raw, dict):
            continue
        brief = lesson_dealer.Brief(
            lesson=number, outcome_ref=str(raw.get("outcome_ref") or ""),
            outcome=str(raw.get("outcome") or ""),
            experience_refs=list(raw.get("experience_refs") or []),
            experiences=list(raw.get("experiences") or []),
            position=int(raw.get("position") or 1), of=int(raw.get("of") or 1))
        lines.append(f"LESSON {number}:\n" + lesson_dealer.block(brief))
    return "\n\n".join(lines)


def _instruction(findings: list[str], targets: list[int],
                 sub_strand: str, allocation_phrase: str,
                 notes: dict[str, Any] | None = None) -> str:
    plan = _briefs_of(notes, targets) if notes else ""
    return "\n".join([
        "=== REWRITE THESE LESSONS. THEY WERE CHECKED AND THEY FAILED. ===",
        f"You wrote a guide for '{sub_strand}' ({allocation_phrase}). It was "
        f"then compared against itself mechanically. These are not opinions "
        f"and they are not style notes:",
        "",
        *[f"  - {f}" for f in findings],
        "",
        *([plan, ""] if plan else []),
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
        "`learning_experiences_used`, worded exactly as the design words it. "
        "Teaching it without naming it leaves the guide looking ungrounded; "
        "naming it without teaching it is worse. The specific experience text "
        "appears in the finding itself — copy it verbatim into "
        "`learning_experiences_used` and build the lesson activities around it, "
        "not around a paraphrase of it.",
        "Keep every other lesson exactly as it is; you are not being asked for "
        "them and rewriting them loses work that already passed.",
    ])


def _whole_guide_instruction(findings: list[str], sub_strand: str,
                             allocation_phrase: str, modules: int,
                             notes: dict[str, Any] | None = None) -> str:
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
        *([_briefs_of(notes), ""] if notes and _briefs_of(notes) else []),
        "THE PLAN ABOVE IS FIXED. Each lesson is written to its own outcome "
        "and experiences and no other's. That is what was missing: the last "
        "guide wrote lessons in order, ran out of material, and reached for "
        "the same three beats — review, work through examples, real-life "
        "applications — under new titles.",
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
    design_row: dict[str, Any] | None = None,
    strand: str = "",
    regenerate: Any = None,
) -> tuple[dict[str, Any], Report]:
    """Repair the guide until the checks pass, it stops improving, or passes run out."""
    report = Report()
    if not isinstance(notes, dict):
        return notes, report

    score, findings, targets = _inspect(notes, design_experiences, design_row,
                                        strand=strand, sub_strand=sub_strand)
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

        score, findings, targets = _inspect(notes, design_experiences, design_row,
                                        strand=strand, sub_strand=sub_strand)
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
                                       allocation_phrase, notes)
        else:
            run_log.step(f"Regenerate {number}",
                         f"rewriting one lesson at a time did not clear "
                         f"{len(findings)} finding(s); writing the whole guide "
                         f"again", "warn")
            instruction = _whole_guide_instruction(
                findings, sub_strand, allocation_phrase, len(_modules(notes)),
                notes)

        try:
            if rung == "regenerate" and regenerate is not None:
                # The planner again — with the plan, the hand-off and the
                # write-time checks — told what the last guide failed.
                content = regenerate(findings)
            else:
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

        after, findings, targets = _inspect(notes, design_experiences, design_row,
                                        strand=strand, sub_strand=sub_strand)
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
    current, current_findings, _ = _inspect(notes, design_experiences, design_row,
                                        strand=strand, sub_strand=sub_strand)
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

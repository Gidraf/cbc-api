"""Repair a batch of questions until its checks pass, or say why not.

The notes station has had this since the guides started selling: inspect,
rewrite what the findings name, inspect again, keep the best. The questions
station had a structure gate that held malformed items and a review cycle
that regenerated the WHOLE batch with the reviewer's prose as instructions —
a loop that threw away eight good items to fix two, and came back with two
new faults in the eight.

This aims the rewrite. An item the engine proved wrong is rewritten on its
own, with the finding that names it; an item that repeats the guide is
replaced; a copy within the batch is dropped without a model call; an
outcome nobody assessed gets an item written for it. Everything not named
is kept byte for byte, which is the only way a pass can be guaranteed not
to lose ground.

The batch leaves with a `self_check` on it — score, findings, what was
repaired, what is still outstanding — and the layer gate honours it the
way it honours the guide's: a set whose own checks failed does not pass on
the strength of a reviewer who never ran the arithmetic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import question_check, run_log

logger = logging.getLogger("cbc-questions-remediation")

MAX_PASSES = 3
# Set-level findings a rewrite can act on by ADDING items.
_WANTS_ITEMS = {"outcome_not_assessed", "figures_unused", "nothing_above_recall",
                "below_the_grade", "missing_operations"}


@dataclass
class Report:
    attempted: bool = False
    passes: int = 0
    score_before: float = 0.0
    score_after: float = 0.0
    findings_before: list[str] = field(default_factory=list)
    outstanding: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)
    added: int = 0
    stopped_because: str = ""
    engine: dict[str, int] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.outstanding

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted, "passes": self.passes,
            "score_before": self.score_before, "score_after": self.score_after,
            "clean": self.clean, "score": self.score_after,
            "findings_before": list(self.findings_before),
            "outstanding": list(self.outstanding),
            "repaired": list(self.repaired), "dropped": list(self.dropped),
            "rewritten": list(self.rewritten), "added": self.added,
            "stopped_because": self.stopped_because, "engine": dict(self.engine),
        }


def _id(question: dict[str, Any]) -> str:
    return str(question.get("question_id") or question.get("display_label") or "")


def _drop_copies(questions: list[dict[str, Any]], report: question_check.Report,
                 out: Report) -> list[dict[str, Any]]:
    """A copy within the batch, or an item already in the bank, goes without
    a model call — there is nothing to rewrite it INTO."""
    doomed = {i for f in report.findings
              if f.kind in ("duplicate_in_batch", "already_in_the_bank") for i in f.items}
    if not doomed:
        return questions
    kept = [q for q in questions if _id(q) not in doomed]
    out.dropped += sorted(doomed)
    report.findings = [f for f in report.findings
                       if f.kind not in ("duplicate_in_batch", "already_in_the_bank")]
    return kept


def instruction(questions: list[dict[str, Any]], findings: list[question_check.Finding],
                targets: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """What to rewrite, why, and what to add.

    Returns the items to rewrite, one line per item naming its faults, and
    the set-level asks (an outcome with no item, a figure nobody used).
    """
    by_item: dict[str, list[str]] = {}
    asks: list[str] = []
    for found in findings:
        if found.items:
            for qid in found.items:
                by_item.setdefault(qid, []).append(
                    found.says + (f" Fix: {found.fix}" if found.fix else ""))
        elif found.kind in _WANTS_ITEMS:
            asks.append(found.says + (f" Fix: {found.fix}" if found.fix else ""))
    items = [q for q in questions if _id(q) in targets]
    lines = []
    for question in items:
        label = str(question.get("display_label") or _id(question))
        for why in by_item.get(_id(question), []):
            lines.append(f"{label}: {why}")
    return items, lines, asks


def run(
    questions: list[dict[str, Any]],
    *,
    grade: str,
    subject: str,
    strand: str = "",
    sub_strand: str = "",
    notes: Any = None,
    design_row: dict[str, Any] | None = None,
    existing: list[dict[str, Any]] | None = None,
    diagrams: list[Any] | None = None,
    rewrite: Any = None,
    max_passes: int = MAX_PASSES,
) -> tuple[list[dict[str, Any]], Report]:
    """Check, repair what can be repaired without a model, rewrite what the
    findings name, check again. Returns the best batch seen and the report.

    `rewrite(items, reasons, asks) -> list[dict]` is the model call: it gets
    the items to redo with one reason line each and the set-level asks, and
    returns NORMALISED replacement items (plus any added). Each replacement
    carries `replaces` naming the question_id it stands in for; one without
    it is an addition.
    """
    out = Report()
    items = [q for q in (questions or []) if isinstance(q, dict)]

    def inspect(batch: list[dict[str, Any]]) -> question_check.Report:
        return question_check.check(batch, grade=grade, subject=subject, strand=strand,
                                    sub_strand=sub_strand, notes=notes, design_row=design_row,
                                    existing=existing, diagrams=diagrams)

    report = inspect(items)
    out.repaired += report.repaired
    trimmed = _drop_copies(items, report, out)
    if trimmed is not items:
        # A copy gone changes what the set-level checks see; read it again.
        items = trimmed
        report = inspect(items)
    out.score_before = out.score_after = report.score
    out.findings_before = [f.says for f in report.findings]
    out.engine = {"checked": report.engine_checked, "agreed": report.engine_agreed}
    if report.clean:
        run_log.step("Self-check", f"{len(items)} item(s) agree with the engine and repeat nothing")
        out.stopped_because = "clean"
        return items, out

    run_log.step("Self-check", f"{len(report.findings)} finding(s) at {report.score}/100", "warn")
    out.attempted = True
    best, best_report = list(items), report

    for number in range(1, max_passes + 1):
        if rewrite is None:
            out.stopped_because = "no rewriter"
            break
        targets = sorted(report.faulty_items)
        to_redo, reasons, asks = instruction(items, report.findings, targets)
        if not to_redo and not asks:
            out.stopped_because = "nothing the rewrite can act on"
            break
        out.passes = number
        run_log.step(f"Rewrite pass {number}",
                     f"{len(to_redo)} item(s) to redo" + (f", {len(asks)} to add for" if asks else ""))
        try:
            replacements = rewrite(to_redo, reasons, asks) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Question rewrite pass %d failed: %s", number, exc)
            out.stopped_because = f"rewrite failed: {exc}"
            break

        by_replaced: dict[str, dict[str, Any]] = {}
        added: list[dict[str, Any]] = []
        for item in replacements:
            if not isinstance(item, dict):
                continue
            target = str(item.pop("replaces", "") or "")
            if target and target in targets:
                by_replaced[target] = item
            else:
                added.append(item)
        merged = []
        for question in items:
            swap = by_replaced.get(_id(question))
            if swap is not None:
                # The label stays, so the console and the rewrite can still
                # call it Q4; the id is minted fresh like every other item's.
                swap.setdefault("display_label", question.get("display_label"))
                out.rewritten.append(_id(question))
                merged.append(swap)
            else:
                merged.append(question)
        merged += added
        out.added += len(added)

        previous = report
        report = inspect(merged)
        out.repaired += report.repaired
        trimmed = _drop_copies(merged, report, out)
        if trimmed is not merged:
            merged = trimmed
            report = inspect(merged)
        items = merged
        if report.score >= best_report.score:
            best, best_report = list(items), report
        if report.clean:
            run_log.step("Self-check", f"clean after pass {number}")
            out.stopped_because = "clean"
            break
        if report.score <= previous.score and len(report.findings) >= len(previous.findings):
            run_log.step("Self-check", f"pass {number} did not improve the batch; keeping the best", "warn")
            out.stopped_because = "no improvement"
            break
        run_log.step("Self-check", f"{len(report.findings)} finding(s) at {report.score}/100", "warn")
    else:
        out.stopped_because = "passes exhausted"

    out.score_after = best_report.score
    out.outstanding = [f.says for f in best_report.findings]
    out.engine = {"checked": best_report.engine_checked, "agreed": best_report.engine_agreed}
    return best, out

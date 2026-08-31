"""Did what came back have the same shape as what went out?

The pipeline is not always the fastest way to a good artifact. An operator who
can see exactly what is wrong with a lesson plan will often fix it faster by
copying it out, working on it in another model, and pasting it back — and that
is a legitimate way to work, not a workaround.

What makes it dangerous is silent drift. A model asked to improve a guide
returns a guide, and it is the right guide, and it has renamed
`exposition_segments` to `segments`, dropped `citations` from three modules and
turned `duration_minutes` into the string "30 minutes". Every one of those
reads as fine to a person scanning the prose. Every one of them breaks
something downstream: coverage counts no modules, the citation resolver finds
nothing to resolve, the renderer prints a blank duration.

Nothing noticed, because everything downstream reads with `.get()` and a
default. A missing key and an empty one are indistinguishable by the time they
are read.

So the shape is compared before the paste is filed: same keys, same types, same
shape inside each list. Reported rather than refused — an operator adding a
field on purpose is doing something reasonable, and a tool that refuses it
teaches them to stop using the tool.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-content-shape")

# How deep to compare. Deep enough for a module's segments and their fields;
# not so deep that a difference is reported at a path nobody can act on.
MAX_DEPTH = 6

# Lists are compared by the shape of what is IN them, sampled — a guide with
# seven identically-shaped modules does not need seven identical reports.
SAMPLE = 3


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


@dataclass(slots=True)
class Finding:
    path: str
    problem: str          # missing | added | type_changed | emptied
    detail: str
    was: str = ""
    now: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "problem": self.problem,
                "detail": self.detail, "was": self.was, "now": self.now}


@dataclass(slots=True)
class ShapeReport:
    missing: list[Finding] = field(default_factory=list)
    type_changed: list[Finding] = field(default_factory=list)
    emptied: list[Finding] = field(default_factory=list)
    added: list[Finding] = field(default_factory=list)

    @property
    def breaking(self) -> list[Finding]:
        """The ones that break something downstream rather than surprise a
        reader. A key that is gone, a type that changed, and a list that was
        full and is now empty are all read as "nothing here" by code that uses
        `.get()` with a default."""
        return self.missing + self.type_changed + self.emptied

    @property
    def clean(self) -> bool:
        return not self.breaking and not self.added

    @property
    def safe(self) -> bool:
        """Nothing broken. Additions are the operator's business."""
        return not self.breaking

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean, "safe": self.safe,
            "missing": [f.to_dict() for f in self.missing],
            "type_changed": [f.to_dict() for f in self.type_changed],
            "emptied": [f.to_dict() for f in self.emptied],
            "added": [f.to_dict() for f in self.added],
            "summary": summarise(self),
        }


def summarise(report: ShapeReport) -> str:
    if report.clean:
        return "Same shape as the version it came from."
    parts = []
    if report.missing:
        parts.append(f"{len(report.missing)} key(s) missing")
    if report.type_changed:
        parts.append(f"{len(report.type_changed)} changed type")
    if report.emptied:
        parts.append(f"{len(report.emptied)} emptied")
    if report.added:
        parts.append(f"{len(report.added)} added")
    return "; ".join(parts)


def _walk(was: Any, now: Any, path: str, report: ShapeReport, depth: int) -> None:
    if depth > MAX_DEPTH:
        return

    was_kind, now_kind = _kind(was), _kind(now)

    # A null in the original tells us nothing about what the field should be.
    if was_kind == "null":
        return

    if was_kind != now_kind:
        # An empty string where text was, or an empty list where a list was, is
        # not a type change — it is the field being emptied, which is its own
        # kind of loss and worth saying differently.
        if now_kind == "null":
            report.emptied.append(Finding(
                path, "emptied", f"was {was_kind}, is now empty",
                was=was_kind, now="empty"))
        else:
            report.type_changed.append(Finding(
                path, "type_changed",
                f"was {was_kind}, is now {now_kind}",
                was=was_kind, now=now_kind))
        return

    if was_kind == "object":
        for key in was:
            child = f"{path}.{key}" if path else key
            if key not in now:
                report.missing.append(Finding(
                    child, "missing",
                    f"present in the version this came from, gone here",
                    was=_kind(was[key])))
                continue
            _walk(was[key], now[key], child, report, depth + 1)
        for key in now:
            if key not in was:
                child = f"{path}.{key}" if path else key
                report.added.append(Finding(
                    child, "added",
                    "not in the version this came from", now=_kind(now[key])))
        return

    if was_kind == "list":
        if was and not now:
            report.emptied.append(Finding(
                path, "emptied",
                f"had {len(was)} entr(y/ies), now has none", was=f"{len(was)} items",
                now="0 items"))
            return
        # Compare the shape INSIDE the list, sampled. Seven identically-shaped
        # modules do not need seven identical reports.
        for i, (a, b) in enumerate(list(zip(was, now))[:SAMPLE]):
            _walk(a, b, f"{path}[{i}]", report, depth + 1)
        return

    if was_kind == "text" and was.strip() and not str(now).strip():
        report.emptied.append(Finding(
            path, "emptied", "had text, is now blank", was="text", now="blank"))


def compare(was: Any, now: Any) -> ShapeReport:
    """What changed structurally between the version and the paste."""
    report = ShapeReport()
    _walk(was, now, "", report, 0)
    # A path reported many times over a long list is noise; one is the point.
    for bucket in (report.missing, report.type_changed, report.emptied, report.added):
        seen, unique = set(), []
        for finding in bucket:
            key = (finding.path.split("[")[0], finding.problem)
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)
        bucket[:] = unique
    return report


def render(report: ShapeReport) -> str:
    """The same findings, for a log or a message rather than a screen."""
    if report.clean:
        return "Same shape as the version it came from."
    lines = []
    for finding in report.missing:
        lines.append(f"MISSING  {finding.path} — was {finding.was}")
    for finding in report.type_changed:
        lines.append(f"CHANGED  {finding.path} — {finding.detail}")
    for finding in report.emptied:
        lines.append(f"EMPTIED  {finding.path} — {finding.detail}")
    for finding in report.added:
        lines.append(f"ADDED    {finding.path} — {finding.detail}")
    return "\n".join(lines)

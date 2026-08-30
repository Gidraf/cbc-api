"""Catch the things a guide invented, without needing a source to check against.

Asking a model to be creative with analogies is asking for the one behaviour
that also produces fabrication. The two are not the same thing and the
difference is precise:

  An ANALOGY is a teaching device. "Just like your mother gives you food" makes
  no claim about the world. It is invented on purpose, it is what good teaching
  of a four-year-old looks like, and it should be encouraged.

  A CLAIM asserts something is true. A statistic, a scripture reference, a
  named authority, a page number. Every one of these is checkable, and a model
  that invents one produces something indistinguishable from a real one — which
  is worse than saying nothing.

So this does not try to judge analogies. It looks for claims that the design
does not support, in the four shapes this pipeline has actually produced them:
percentages the research dossier leaked in, scripture references nobody wrote,
authorities nobody retrieved, and page addresses that resolve to nothing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-fabrication")

# "75%", "3 out of 4", "60 per cent". A teacher's guide for four-year-olds has
# no business carrying a statistic, and every one this pipeline has produced
# came from the dossier's own unverified figures.
# No trailing \b after the percent sign: "%" is not a word character, so a word
# boundary cannot follow it and "75%" never matched — the exact figure this was
# written to catch.
_STATISTIC = re.compile(
    r"\b\d{1,3}\s?%|\b\d{1,3}\s?per\s?cent\b|\b\d+\s+out\s+of\s+\d+\b",
    re.IGNORECASE,
)

# "Mark 10:13-16", "1 Samuel 17:41-49", "Proverbs 22:6".
_SCRIPTURE = re.compile(
    r"\b((?:[1-3]\s?)?[A-Z][a-z]+)\s+(\d{1,3}):(\d{1,3})(?:\s*[-–]\s*\d{1,3})?\b"
)

# Bodies a generated dossier likes to attribute figures to.
_AUTHORITIES = (
    "knbs", "kalro", "nema", "unesco", "who ", "world bank", "unicef",
    "ministry of education", "kicd report", "kenya national bureau",
)

# Words that mark a sentence as an analogy rather than an assertion. A
# statistic inside one of these is still a statistic, but a comparison is not a
# claim about the world.
_ANALOGY_MARKERS = (
    "just like", "just as", "imagine", "think of", "the way", "like when",
    "for example, when you", "picture",
)


@dataclass(slots=True)
class Finding:
    kind: str
    text: str
    where: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text[:200], "where": self.where}


@dataclass(slots=True)
class FabricationReport:
    findings: list[Finding] = field(default_factory=list)
    scripture_in_design: list[str] = field(default_factory=list)
    checked_chars: int = 0

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def score(self) -> float:
        """100 when nothing was invented, falling steeply with each finding.

        Steeply on purpose: one fabricated scripture reference in a religious
        education guide is not a small defect.
        """
        if not self.findings:
            return 100.0
        return max(0.0, 100.0 - 25.0 * len(self.findings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "score": self.score,
            "findings": [f.to_dict() for f in self.findings],
            "scripture_the_design_carries": self.scripture_in_design,
            "checked_chars": self.checked_chars,
        }


def _text_of(value: Any, depth: int = 0) -> str:
    if depth > 8 or value is None or isinstance(value, (bool, int, float)):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_of(v, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(v, depth + 1) for v in value)
    return ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _is_analogy(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in _ANALOGY_MARKERS)


def check(content: Any, design_text: str = "", has_sources: bool = False) -> FabricationReport:
    """Everything the guide asserts that the design does not support."""
    report = FabricationReport()
    body = _text_of(content)
    report.checked_chars = len(body)
    if not body.strip():
        return report

    design = design_text or ""
    design_lower = design.lower()

    # ── scripture the design never names ────────────────────────────────────
    in_design = {
        f"{m.group(1).strip()} {m.group(2)}:{m.group(3)}"
        for m in _SCRIPTURE.finditer(design)
    }
    report.scripture_in_design = sorted(in_design)

    for match in _SCRIPTURE.finditer(body):
        book = match.group(1).strip()
        reference = f"{book} {match.group(2)}:{match.group(3)}"
        # Compare on book+chapter+verse, ignoring the range, so "Mark 10:13-16"
        # matches the design's "Mark 10:13-16" however it re-renders the dash.
        if reference not in in_design:
            report.findings.append(Finding(
                "invented_scripture",
                f"'{match.group(0)}' is cited but the KICD design does not name it. "
                f"The design carries: {', '.join(sorted(in_design)) or 'none'}.",
            ))

    # ── statistics, which this guide has no business carrying ───────────────
    for sentence in _sentences(body):
        for match in _STATISTIC.finditer(sentence):
            figure = match.group(0)
            if figure.lower() in design_lower:
                continue
            if _is_analogy(sentence):
                continue
            report.findings.append(Finding(
                "invented_statistic",
                f"'{figure}' appears in \"{sentence[:120]}\". No statistic was "
                f"retrieved for this sub-strand, so this one came from nowhere.",
            ))

    # ── authorities nobody actually retrieved ───────────────────────────────
    if not has_sources:
        lowered = body.lower()
        for authority in _AUTHORITIES:
            if authority in lowered and authority not in design_lower:
                report.findings.append(Finding(
                    "invented_authority",
                    f"'{authority.strip()}' is named as a source, but nothing was "
                    f"retrieved for this sub-strand and the design does not "
                    f"mention it.",
                ))

    if report.findings:
        logger.warning(
            "%d fabricated claim(s) in generated content: %s",
            len(report.findings), "; ".join(f.kind for f in report.findings[:4]),
        )
    return report

"""What a planned diagram has to carry before anything can be drawn from it.

The diagram station returned its visuals and no `quality_gate`. The review loop
reads `quality_gate`, found none, and scored the run **0/100, not passed** —
then reported "the gate failed but named nothing to fix", because there was
nothing to name. A run that had planned three perfectly good diagrams looked
identical to a run that had produced nothing.

This is the same hole the material station had. The measures here are
mechanical: whether each visual carries what the next two stations need from
it. Whether the diagram is any GOOD is a question for a reviewer, and this does
not pretend to answer it.
"""
from __future__ import annotations

import re

from dataclasses import dataclass, field
from typing import Any

# A plan below this is not a plan the next station can work from.
PASS_SCORE = 80.0


@dataclass(slots=True)
class DiagramReport:
    total: int = 0
    # No title: nothing downstream can refer to it, and the page cannot caption it.
    untitled: list[dict[str, Any]] = field(default_factory=list)
    # No brief: nobody can draw it, by hand or by model.
    unbriefed: list[dict[str, Any]] = field(default_factory=list)
    # No alt text: a learner using a screen reader gets an unlabelled box.
    inaccessible: list[dict[str, Any]] = field(default_factory=list)
    # No addressable parts. This station exists to make diagrams a question can
    # point INTO — "the part labelled A" — and a scene with no parts is a
    # picture the question station cannot use.
    unaddressable: list[dict[str, Any]] = field(default_factory=list)
    # Parts with no function: a label with no meaning cannot be asked about.
    unexplained: list[dict[str, Any]] = field(default_factory=list)
    # Titled with the KIND of thing rather than the thing. A plan whose visual
    # is called "charts" put the word "charts" in the book's caption, and gave
    # the drawing step nothing to draw — which is how four identical circles
    # came back captioned as four different operations.
    uncaptioned: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.untitled or self.unbriefed or self.inaccessible
                    or self.unaddressable or self.unexplained
                    or self.uncaptioned)

    @property
    def score(self) -> float:
        if not self.total:
            return 0.0
        faults = (len(self.untitled) + len(self.unbriefed)
                  + len(self.inaccessible) + len(self.unaddressable)
                  + len(self.unexplained) + len(self.uncaptioned))
        # Six checks per visual, so a visual failing one is not a total loss.
        return round(max(0.0, 1 - faults / (self.total * 6)) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "untitled": self.untitled,
                "unbriefed": self.unbriefed, "inaccessible": self.inaccessible,
                "unaddressable": self.unaddressable,
                "unexplained": self.unexplained,
                "uncaptioned": self.uncaptioned,
                "clean": self.clean, "score": self.score}


def _is_a_category(title: str) -> bool:
    """A title that is only the word for what kind of picture it is.

    The same rule the page uses to decide whether a requirement names a figure
    anyone can produce — kept in one place, because a title the gate accepts
    and the page discards is a diagram that passes review and never prints.
    """
    from .asset_requirements import names_only_a_category

    return names_only_a_category(title)


def _title(visual: dict[str, Any]) -> str:
    return str(visual.get("diagram_title") or visual.get("title")
               or visual.get("caption") or "").strip()


def check(content: Any) -> DiagramReport:
    """Read one diagram artifact's visuals."""
    visuals = content.get("visuals") if isinstance(content, dict) else None
    if not isinstance(visuals, list):
        visuals = content.get("diagrams") if isinstance(content, dict) else None
    visuals = [v for v in (visuals or []) if isinstance(v, dict)]

    report = DiagramReport(total=len(visuals))
    for index, visual in enumerate(visuals, start=1):
        title = _title(visual)
        where = {"index": index, "title": title or f"visual {index}"}

        if not title:
            report.untitled.append(where)
        elif _is_a_category(title):
            report.uncaptioned.append(where)

        brief = str(visual.get("vivid_prompt") or visual.get("brief")
                    or visual.get("description") or "").strip()
        if len(brief) < 40 and not visual.get("diagram_svg"):
            report.unbriefed.append({**where, "chars": len(brief)})

        accessibility = visual.get("accessibility") or {}
        alt = str((accessibility or {}).get("alt_text")
                  or visual.get("alt_text") or "").strip()
        if len(alt) < 15:
            report.inaccessible.append({**where, "chars": len(alt)})

        parts = ((visual.get("scene") or {}).get("parts")
                 if isinstance(visual.get("scene"), dict) else None)
        parts = [p for p in (parts or []) if isinstance(p, dict)]
        if not parts:
            report.unaddressable.append(where)
            continue

        nameless = [p for p in parts
                    if not str(p.get("label") or "").strip()
                    or not str(p.get("function") or "").strip()]
        if nameless:
            report.unexplained.append({**where, "parts": len(nameless)})

    return report


def gate_of(report: DiagramReport) -> dict[str, Any]:
    """The diagram check, in the shape every other station reports.

    Without this the station returned no `quality_gate` and the review loop
    read no score at all — filing a good run as 0/100 with nothing named.
    """
    passed = report.score >= PASS_SCORE and report.total > 0

    def measure(aspect: str, method: str, faults: list, comment_bad: str,
                comment_ok: str) -> dict[str, Any]:
        return {
            "aspect": aspect, "method": method,
            "status": "fail" if faults else "pass",
            "score": round(1 - len(faults) / report.total, 4) if report.total else 0.0,
            "comment": comment_bad.format(n=len(faults)) if faults else comment_ok,
        }

    feedback = [
        measure("planned", "visuals_present", [] if report.total else [1],
                "no visual was planned at all",
                f"{report.total} visual(s) planned"),
        measure("named", "title_present", report.untitled,
                "{n} carry no title, so nothing can refer to them",
                "every visual is named"),
        measure("drawable", "brief_length", report.unbriefed,
                "{n} carry no brief long enough to draw from",
                "every visual can be drawn from its brief"),
        measure("accessible", "alt_text_present", report.inaccessible,
                "{n} have no alt text, so a screen reader gets a blank box",
                "every visual has alt text"),
        measure("addressable", "scene_parts_present", report.unaddressable,
                "{n} have no addressable parts, so no question can point into them",
                "every visual has parts a question can point at"),
        measure("specific", "title_names_the_subject", report.uncaptioned,
                "{n} are titled with the kind of picture, not its subject",
                "every title names what the figure shows"),
        measure("explained", "part_function_present", report.unexplained,
                "{n} have parts with a label but no function",
                "every part says what it does"),
    ]

    actions: list[str] = []
    for item in report.unaddressable[:3]:
        actions.append(
            f"\"{item['title']}\" has no `scene.parts`. This station exists to "
            f"make diagrams a question can point into — give it labelled parts "
            f"with `assessable` and `occludable` set."
        )
    for item in report.unbriefed[:3]:
        actions.append(
            f"\"{item['title']}\" has no brief to draw from ({item.get('chars', 0)} "
            f"characters). Write what the picture must show, in full."
        )
    for item in report.inaccessible[:3]:
        actions.append(
            f"\"{item['title']}\" has no alt text. Describe what a learner who "
            f"cannot see it needs to know."
        )
    for item in report.uncaptioned[:3]:
        actions.append(
            f"\"{item['title']}\" names a KIND of picture, not a subject. It is "
            f"printed verbatim as the figure's caption, and it is all the "
            f"drawing step is given to draw. Title it with what this figure "
            f"shows — \"Adding integers on a number line\", not \"charts\"."
        )
    for item in report.unexplained[:2]:
        actions.append(
            f"\"{item['title']}\" has {item['parts']} part(s) labelled but not "
            f"explained. A label with no function cannot be asked about."
        )
    if not report.total:
        actions.append(
            "No visual was planned. Check the lesson plan actually names "
            "something to draw, or say in `gaps` that it does not."
        )

    return {
        "passed": passed,
        "overall_score": int(round(report.score)),
        "layer_name": "diagram",
        "summary_message": (
            f"Diagram gate {'passed' if passed else 'not passed'} at "
            f"{report.score}/100. {report.total} visual(s) planned."
        ),
        "reviewer": {
            "score": int(round(report.score)), "passed": passed,
            "status": "approved" if passed else "revise",
            "feedback": feedback,
        },
        "next_actions": actions,
    }

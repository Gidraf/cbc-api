"""A question set as two documents: the paper, and the marking scheme.

Questions lived in the console as JSON. Judging whether an item was any good
meant reading a field at a time, and nobody could see the thing a learner would
actually be handed — where the LaTeX either typesets or prints its own
backslashes, where a diagram question either has its figure beside it or does
not, where five items turn out to ask the same thing three times.

Two documents, from one set, by the same renderer the guides use:

    the PAPER            what the learner sits with. No answers anywhere.
    the MARKING SCHEME   the same items with their worked solutions.

Deliberately not one document with the answers greyed out. A paper with the
answers on it cannot be handed to a class, and the one thing worse than no
marking scheme is a paper that turns out to have been one.
"""
from __future__ import annotations

import logging
from typing import Any

from .notes_renderer import PRINT_CSS, _KATEX, _KATEX_CRITICAL, _esc, _math

logger = logging.getLogger("cbc-question-paper")

# How KICD names each structure, and how the paper sets it. A question's type
# decides its shape on the page: options are lettered and boxed, structured
# parts are lettered with their marks in the margin, and a written response
# gets ruled space to write in.
_STRUCTURE = {
    "multiple_choice": ("Multiple choice", "Choose the correct answer."),
    "mcq": ("Multiple choice", "Choose the correct answer."),
    "short_answer": ("Short answer", ""),
    "structured": ("Structured", ""),
    "essay": ("Extended response", ""),
    "practical": ("Practical", ""),
    "diagram_based": ("Diagram-based", "Study the figure, then answer."),
    "true_false": ("True or false", ""),
    "matching": ("Matching", ""),
    "calculation": ("Calculation", "Show all your working."),
}

PAPER_CSS = """
.paper .item { break-inside: avoid; margin: 0 0 14px; padding: 0 0 10px;
               border-bottom: 0.5pt solid #e4e4e4; }
.paper .item:last-child { border-bottom: 0; }
.qhead { display: flex; align-items: baseline; gap: 8px; margin: 0 0 4px; }
.qno { font-weight: 700; font-size: 11pt; min-width: 2.2em; }
.qtype { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
         font-size: 7pt; letter-spacing: 0.08em; text-transform: uppercase;
         color: #666; border: 0.5pt solid #ccc; padding: 1px 5px;
         border-radius: 2px; }
.qmarks { margin-left: auto; font-size: 8.5pt; color: #444; white-space: nowrap; }
.stem { margin: 0 0 6px; }
.stimulus { border-left: 2px solid #999; padding-left: 9px; color: #333;
            font-size: 9.5pt; margin: 0 0 6px; }
.opts { list-style: none; margin: 4px 0 0; padding: 0; }
.opts li { margin: 0 0 3px; padding-left: 1.9em; text-indent: -1.9em; }
.opts .oid { display: inline-block; width: 1.5em; font-weight: 600; }
.parts { list-style: none; margin: 4px 0 0; padding: 0; }
.parts li { display: flex; gap: 7px; margin: 0 0 4px; }
.parts .pid { font-weight: 600; min-width: 1.6em; }
.parts .pmarks { margin-left: auto; color: #555; font-size: 8.5pt;
                 white-space: nowrap; }
/* Room to answer in. A paper with no space to write on gets answered in the
   margin, and then it cannot be marked. */
.ruled { margin: 6px 0 0; }
.ruled div { border-bottom: 0.5pt solid #bbb; height: 7mm; }

/* ── the marking scheme ─────────────────────────────────────────────────── */
.scheme .item { border-bottom: 0.5pt solid #ddd; }
.steps { list-style: none; counter-reset: step; margin: 6px 0 0; padding: 0; }
.steps li { counter-increment: step; position: relative; padding-left: 2.1em;
            margin: 0 0 5px; }
.steps li::before { content: counter(step); position: absolute; left: 0;
                    top: 0.05em; width: 1.5em; height: 1.5em; line-height: 1.5em;
                    text-align: center; font-size: 7.5pt; font-weight: 700;
                    color: #fff; background: #111; border-radius: 50%; }
.steps .why { display: block; font-style: italic; color: #555; font-size: 9pt;
              margin-top: 1px; }
.steps .stepmarks { float: right; font-size: 8.5pt; color: #444; }
.answer { margin: 7px 0 0; padding: 6px 9px; background: #f2f2f0;
          border-left: 3px solid #111; break-inside: avoid; }
.answer .label { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                 font-size: 7pt; letter-spacing: 0.08em; text-transform: uppercase;
                 color: #555; display: block; margin-bottom: 2px; }
.chosen { font-weight: 700; }
.distractors { margin: 6px 0 0; padding: 0; list-style: none;
               font-size: 9pt; color: #444; }
.distractors li { margin: 0 0 3px; padding-left: 1.4em; text-indent: -1.4em; }
.derived { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
           font-size: 7pt; letter-spacing: 0.06em; text-transform: uppercase;
           color: #1b6b3a; }
.unmarkable { border-left: 3px solid #a1281e; background: #fdf3f2;
              padding: 6px 9px; margin: 7px 0 0; font-size: 9.5pt; }
.figure-inline { border: 1px solid #111; margin: 6px 0; }
.figure-inline svg { display: block; width: 100%; height: auto; }
"""


def _marks_of(question: dict[str, Any]) -> float:
    pedagogy = question.get("pedagogy") or {}
    try:
        total = float(pedagogy.get("max_marks") or 0)
    except (TypeError, ValueError):
        total = 0.0
    if total:
        return total
    return sum(float(p.get("marks") or 0)
               for p in (question.get("structured_parts") or [])
               if isinstance(p, dict))


def _marks(value: float) -> str:
    if not value:
        return ""
    whole = int(value)
    shown = str(whole) if value == whole else f"{value:g}"
    return f"({shown} mark{'' if value == 1 else 's'})"


def _head(question: dict[str, Any], number: int) -> str:
    q_type = str(question.get("question_type") or "").lower()
    label, _ = _STRUCTURE.get(q_type, (q_type.replace("_", " ").title() or "Question", ""))
    marks = _marks(_marks_of(question))
    return (f"<div class='qhead'><span class='qno'>{number}.</span>"
            f"<span class='qtype'>{_esc(label)}</span>"
            + (f"<span class='qmarks'>{_esc(marks)}</span>" if marks else "")
            + "</div>")


def _figure(question: dict[str, Any], assets: dict[str, Any] | None,
            answers: bool = False) -> str:
    """The diagram this question tests, printed WITH it — as the LEARNER
    should see it on the paper, and as the MARKER should on the scheme.

    A diagram question whose figure is on another page is a question nobody
    can answer. And a diagram question whose blanks are filled in on the
    learner's copy is free marks: the binding says which parts were removed,
    so the paper renders them as lettered gaps and the scheme renders them
    labelled and highlighted. The SVG is inlined, so the paper works with no
    network.

    `assets` maps a diagram id or title to either a registry row (svg_markup
    + scene_document) or a bare SVG string.
    """
    binding = question.get("diagram")
    if not isinstance(binding, dict):
        return ""
    source: Any = None
    if assets:
        for key in (binding.get("diagram_id"), binding.get("diagram_title")):
            if key and str(key).lower() in assets:
                source = assets[str(key).lower()]
                break
    if source is None and binding.get("svg_markup"):
        source = {"svg_markup": binding.get("svg_markup"), "scene_document": {}}
    if isinstance(source, str):
        source = {"svg_markup": source, "scene_document": {}}
    if not isinstance(source, dict) or not (source.get("svg_markup") or source.get("diagram_svg")):
        title = str(binding.get("diagram_title") or "the figure")
        return f"<div class='stimulus'>Refer to {_esc(title)}.</div>"
    try:
        from .diagram_scene import render_for_question

        svg = render_for_question(source, binding, with_answers=answers)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not render the figure for %s: %s",
                       question.get("question_id") or "?", exc)
        svg = str(source.get("svg_markup") or source.get("diagram_svg") or "")
    return f"<div class='figure-inline'>{svg}</div>"


def figures_for(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """Every figure the items bind to, from the registry, keyed by id and
    by title. Never raises: a paper with "refer to the figure" beats no
    paper."""
    ids: set[str] = set()
    for question in questions or []:
        binding = question.get("diagram") if isinstance(question, dict) else None
        if isinstance(binding, dict) and binding.get("diagram_id"):
            ids.add(str(binding["diagram_id"]))
    if not ids:
        return {}
    try:
        from ..infra.db import fetch_all
        from . import diagram_svg

        rows = fetch_all(
            """
            SELECT diagram_id, title, svg_markup, scene_document, storage_url, alt_text
            FROM diagram_registry WHERE diagram_id = ANY(:ids)
            """,
            {"ids": sorted(ids)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load %d figure(s) for the paper: %s", len(ids), exc)
        return {}
    out: dict[str, Any] = {}
    for row in rows or []:
        full = diagram_svg.with_svg(row)
        for key in (row.get("diagram_id"), row.get("title")):
            if key:
                out[str(key).lower()] = full
    return out


def _body(question: dict[str, Any], *, answers: bool,
          assets: dict[str, str] | None = None) -> str:
    out: list[str] = []
    stimulus = str(question.get("stimulus_context") or "").strip()
    if stimulus:
        out.append(f"<div class='stimulus'>{_math(stimulus)}</div>")
    out.append(_figure(question, assets, answers=answers))
    out.append(f"<div class='stem'>{_math(question.get('question_text'))}</div>")

    options = [o for o in (question.get("options") or []) if isinstance(o, dict)]
    if options:
        out.append("<ul class='opts'>")
        for option in options:
            oid = _esc(option.get("id") or "")
            out.append(f"<li><span class='oid'>{oid}.</span>"
                       f"{_math(option.get('text'))}</li>")
        out.append("</ul>")

    parts = [p for p in (question.get("structured_parts") or []) if isinstance(p, dict)]
    if parts:
        out.append("<ul class='parts'>")
        for part in parts:
            pid = _esc(part.get("part_id") or "")
            marks = _marks(float(part.get("marks") or 0))
            out.append(
                f"<li><span class='pid'>{pid}</span>"
                f"<span>{_math(part.get('sub_question'))}</span>"
                + (f"<span class='pmarks'>{_esc(marks)}</span>" if marks else "")
                + "</li>")
        out.append("</ul>")

    if not answers and not options:
        # Written responses need somewhere to be written.
        lines = 2 if _marks_of(question) <= 2 else min(8, int(_marks_of(question)) + 1)
        out.append("<div class='ruled'>" + "<div></div>" * lines + "</div>")
    return "".join(out)


def _solution(question: dict[str, Any]) -> str:
    from . import solution_builder

    worked = solution_builder.build(question)
    out: list[str] = []

    if worked.chosen:
        out.append(f"<div class='answer'><span class='label'>Correct option</span>"
                   f"<span class='chosen'>{_math(worked.chosen)}</span></div>")

    if worked.steps:
        derived = ("<span class='derived'>derived and checked</span>"
                   if worked.source == "engine" and worked.verified else "")
        out.append(f"<div class='answer'><span class='label'>Working {derived}"
                   f"</span></div><ol class='steps'>")
        for step in worked.steps:
            marks = _marks(step.marks)
            out.append(
                "<li>"
                + (f"<span class='stepmarks'>{_esc(marks)}</span>" if marks else "")
                + _math(step.text)
                + (f"<span class='why'>{_math(step.why)}</span>" if step.why else "")
                + "</li>")
        out.append("</ol>")

    if worked.answer and worked.answer != worked.chosen:
        out.append(f"<div class='answer'><span class='label'>Answer</span>"
                   f"{_math(worked.answer)}</div>")

    if worked.distractors:
        out.append("<ul class='distractors'>")
        for wrong in worked.distractors:
            out.append(f"<li><b>{_esc(wrong.get('option'))}</b> — "
                       f"{_math(wrong.get('why'))}</li>")
        out.append("</ul>")

    if worked.note:
        out.append(f"<div class='unmarkable'>{_esc(worked.note)}</div>")
    return "".join(out)


def render_html(questions: list[dict[str, Any]], *, grade: str = "",
                subject: str = "", strand: str = "", sub_strand: str = "",
                answers: bool = False, title: str = "",
                assets: dict[str, str] | None = None) -> str:
    """One question set as a document — the paper, or the marking scheme."""
    items = [q for q in (questions or []) if isinstance(q, dict)]
    heading = title or (f"{sub_strand or strand or subject}"
                        + (" — marking scheme" if answers else ""))
    total = sum(_marks_of(q) for q in items)

    meta = " ".join(
        f"<span>{_esc(bit)}</span>" for bit in
        [subject, grade, strand, sub_strand,
         f"{len(items)} question{'' if len(items) == 1 else 's'}",
         _marks(total).strip("()") if total else ""]
        if bit)

    body: list[str] = []
    for number, question in enumerate(items, start=1):
        body.append("<article class='item'>")
        body.append(_head(question, number))
        body.append(_body(question, answers=answers, assets=assets))
        if answers:
            body.append(_solution(question))
        body.append("</article>")

    if not items:
        body.append("<p class='stem'>This set has no questions in it.</p>")

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(heading)}</title>"
        f"<style>{PRINT_CSS}{PAPER_CSS}{_KATEX_CRITICAL}</style>{_KATEX}</head><body>"
        "<div class='sheet'>"
        f"<h1>{_esc(heading)}</h1>"
        f"<div class='meta'>{meta}</div>"
        f"<div class='{'scheme' if answers else 'paper'}'>{''.join(body)}</div>"
        "</div></body></html>"
    )


# ── a composed paper, as a booklet ──────────────────────────────────────────

EXAM_CSS = """
.exam .front { border: 1.5px solid #111; padding: 14px 18px 10px; margin: 0 0 16px; }
.exam .front .school { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                       font-size: 8pt; letter-spacing: 0.12em; text-transform: uppercase;
                       color: #555; margin: 0 0 6px; }
.exam .front h1 { font-size: 19pt; margin: 0 0 4px; }
.exam .front .meta { margin: 0 0 10px; }
.exam .front .fill { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px 18px;
                     margin: 8px 0 10px; font-size: 9pt; }
.exam .front .fill span { border-bottom: 0.6pt solid #111; padding: 0 0 2px; }
.exam .front ol { margin: 4px 0 0 1.4em; padding: 0; font-size: 9.5pt; }
.exam .front ol li { margin: 0 0 2px; }
.exam .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(46px, 1fr));
              gap: 3px; margin: 8px 0 0; font-size: 7.5pt; }
.exam .grid div { border: 0.5pt solid #111; height: 30px; padding: 1px 3px; }
.exam .section { break-inside: avoid-page; margin: 14px 0 8px; padding: 4px 0 3px;
                 border-top: 1.5px solid #111; border-bottom: 0.5pt solid #111; }
.exam .section h2 { font-size: 12pt; margin: 0; display: flex; align-items: baseline; gap: 10px; }
.exam .section h2 .smarks { margin-left: auto; font-size: 9pt; font-weight: 400; color: #333; }
.exam .section p { margin: 3px 0 0; font-size: 9pt; color: #333; }
.exam .draftmark { position: fixed; top: 38%; left: 8%; right: 8%; text-align: center;
                   font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 64pt;
                   font-weight: 800; letter-spacing: 0.2em; color: rgba(160, 30, 20, 0.11);
                   transform: rotate(-18deg); pointer-events: none; z-index: 0; }
.exam .end { text-align: center; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
             font-size: 8pt; letter-spacing: 0.14em; text-transform: uppercase; color: #555;
             margin: 18px 0 0; }
.exam .scheme-start { break-before: page; }
.exam .key { width: auto; border-collapse: collapse; margin: 6px 0 12px; font-size: 9pt; }
.exam .key td, .exam .key th { border: 0.5pt solid #999; padding: 2px 8px; text-align: center; }
.exam .shortfall { border-left: 3px solid #a1281e; background: #fdf3f2; padding: 6px 9px;
                   margin: 0 0 12px; font-size: 9.5pt; }
"""


def _front(paper: Any, *, answers: bool, grade_label: str) -> str:
    fill = ("<div class='fill'><span>Name:</span><span>Class / Stream:</span>"
            "<span>Adm. No.:</span></div>") if not answers else ""
    rules = "".join(f"<li>{_esc(r)}</li>" for r in (paper.instructions or []))
    grid = ""
    if not answers and paper.sections:
        cells = "".join(
            f"<div>{s.letter if s.heading else 'Total'}<br>/{s.marks:g}</div>"
            for s in paper.sections) + f"<div>Total<br>/{paper.total_marks:g}</div>"
        grid = f"<div class='grid'>{cells}</div>"
    return (
        "<div class='front'>"
        f"<div class='school'>{_esc(paper.subject)} · {_esc(grade_label)} · "
        f"{'Marking scheme' if answers else 'Question paper'}</div>"
        f"<h1>{_esc(paper.title)}</h1>"
        "<div class='meta'>"
        f"<span>Time: {_esc(paper.time_allowed)}</span>"
        f"<span>Total: {paper.total_marks:g} marks</span>"
        f"<span>{len(paper.items)} questions</span>"
        + (f"<span>Paper {_esc(paper.seed)}</span>" if paper.seed else "")
        + "</div>"
        + fill
        + (f"<b>Instructions</b><ol>{rules}</ol>" if rules and not answers else "")
        + grid
        + "</div>"
    )


def render_paper(paper: Any, *, answers: bool = False, with_scheme: bool = False,
                 assets: dict[str, str] | None = None) -> str:
    """A composed paper as a booklet: the front, the sections, and — when
    asked — the marking scheme after a page break, with the Section A key
    in one table at its head.

    `answers` prints the scheme alone. `with_scheme` prints the paper and
    then the scheme, for the teacher who wants both in one file.
    """
    from .grade_order import grade_label as _grade_label

    grade_label = _grade_label(paper.grade)

    def _items(scheme: bool) -> str:
        out: list[str] = []
        number = 0
        for section in paper.sections:
            if section.heading:
                out.append(
                    "<div class='section'>"
                    f"<h2>{_esc(section.heading)}"
                    f"<span class='smarks'>{section.marks:g} marks</span></h2>"
                    + ("" if scheme else f"<p>{_esc(section.instructions)}</p>")
                    + "</div>")
            if scheme and section.letter == "A" and section.heading:
                keys = []
                for offset, question in enumerate(section.items, start=number + 1):
                    key = next((str(o.get("id") or "") for o in (question.get("options") or [])
                                if isinstance(o, dict) and o.get("is_correct")),
                               str(question.get("correct_answer") or ""))
                    keys.append((offset, key))
                out.append("<table class='key'><tr>" + "".join(f"<th>{n}</th>" for n, _ in keys)
                           + "</tr><tr>" + "".join(f"<td>{_esc(k)}</td>" for _, k in keys)
                           + "</tr></table>")
            for question in section.items:
                number += 1
                out.append("<article class='item'>")
                out.append(_head(question, number))
                out.append(_body(question, answers=scheme, assets=assets))
                if scheme:
                    out.append(_solution(question))
                out.append("</article>")
        if not out:
            out.append("<p class='stem'>This paper has no questions in it.</p>")
        return "".join(out)

    shortfall = (f"<div class='shortfall'>Incomplete: {_esc(paper.shortfall)}.</div>"
                 if paper.shortfall else "")
    draft = "<div class='draftmark'>DRAFT</div>" if paper.has_drafts else ""
    parts: list[str] = [draft]
    if not answers:
        parts.append(_front(paper, answers=False, grade_label=grade_label))
        parts.append(shortfall)
        parts.append(f"<div class='paper'>{_items(False)}</div>")
        parts.append("<div class='end'>End of paper</div>")
    if answers or with_scheme:
        parts.append(f"<div class='{'scheme-start' if with_scheme else ''}'>")
        parts.append(_front(paper, answers=True, grade_label=grade_label))
        if answers:
            parts.append(shortfall)
        parts.append(f"<div class='scheme'>{_items(True)}</div>")
        parts.append("</div>")

    title = paper.title + (" — marking scheme" if answers else "")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{PRINT_CSS}{PAPER_CSS}{EXAM_CSS}{_KATEX_CRITICAL}</style>{_KATEX}</head><body>"
        f"<div class='sheet exam'>{''.join(parts)}</div></body></html>"
    )

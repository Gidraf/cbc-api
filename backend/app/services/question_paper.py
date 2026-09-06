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


def _figure(question: dict[str, Any], assets: dict[str, str] | None) -> str:
    """The diagram this question tests, printed WITH it.

    A diagram question whose figure is on another page is a question nobody can
    answer. The SVG is inlined, so the paper works with no network.
    """
    binding = question.get("diagram")
    if not isinstance(binding, dict):
        return ""
    svg = str(binding.get("svg_markup") or "")
    if not svg and assets:
        for key in (binding.get("diagram_id"), binding.get("diagram_title")):
            if key and str(key).lower() in assets:
                svg = str(assets[str(key).lower()] or "")
                break
    if not svg:
        title = str(binding.get("diagram_title") or "the figure")
        return (f"<div class='stimulus'>Refer to {_esc(title)}.</div>")
    return f"<div class='figure-inline'>{svg}</div>"


def _body(question: dict[str, Any], *, answers: bool,
          assets: dict[str, str] | None = None) -> str:
    out: list[str] = []
    stimulus = str(question.get("stimulus_context") or "").strip()
    if stimulus:
        out.append(f"<div class='stimulus'>{_math(stimulus)}</div>")
    out.append(_figure(question, assets))
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

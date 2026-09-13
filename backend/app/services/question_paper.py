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
import re
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


# ── a composed paper, as the national paper prints it ────────────────────────
#
# Two columns, the masthead the samples carry (series, assessment, grade and
# year, subject, time), the candidate lines, the instructions, and — where
# the format has a written section — the "for official use" marks table. The
# marking scheme is a separate document reached from the paper by a QR code
# and a short link, so the learner's copy never carries an answer, and it is
# set as densely as a marker can read: the key in a grid, one line of reason
# per item, worked steps only where there is working.

EXAM_CSS = """
@page { size: A4; margin: 12mm 12mm 14mm;
  @bottom-left { content: string(paper-foot); font-family: Georgia, serif; font-size: 7.5pt; color: #444; }
  @bottom-center { content: counter(page); font-family: Georgia, serif; font-size: 8pt; color: #444; }
  @bottom-right { content: string(paper-subject); font-family: Georgia, serif; font-size: 7.5pt; color: #444; } }
.exam body, .exam { font-size: 9.6pt; line-height: 1.32; text-align: left; hyphens: none; }
.exam .sheet { padding: 0; }
.exam .mast { string-set: paper-subject content(); text-align: center; border-bottom: 2px solid #111;
              padding: 0 0 5px; margin: 0 0 6px; position: relative; }
.exam .mast .series { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 8pt;
                      letter-spacing: 0.14em; text-transform: uppercase; color: #333; margin: 0 0 2px; }
.exam .mast .assessment { font-size: 14pt; font-weight: 700; text-decoration: underline;
                          text-underline-offset: 3px; letter-spacing: 0.02em; margin: 0; }
.exam .mast .gradeline { font-size: 12pt; font-weight: 700; margin: 2px 0 0; text-decoration: underline; }
.exam .mast .subject { font-size: 13pt; font-weight: 700; margin: 2px 0 0; text-decoration: underline; }
.exam .mast .time { position: absolute; right: 0; bottom: 6px; font-size: 9pt; font-weight: 600; }
.exam .mast .code { position: absolute; left: 0; top: 4px; width: 30px; height: 30px; border: 1.5px solid #111;
                    border-radius: 50%; display: flex; align-items: center; justify-content: center;
                    font-size: 10pt; font-weight: 700; font-family: Helvetica, Arial, sans-serif; }
.exam .mast .paperno { position: absolute; right: 0; top: 4px; border: 1.5px solid #111; border-radius: 50%;
                       width: 30px; height: 30px; display: flex; align-items: center; justify-content: center;
                       font-size: 12pt; font-weight: 700; font-family: Helvetica, Arial, sans-serif; }
.exam .cand { display: grid; grid-template-columns: 1.1fr 1.3fr 1fr; gap: 4px 14px; font-size: 8.5pt;
              margin: 0 0 5px; }
.exam .cand span { border-bottom: 0.6pt solid #111; padding: 0 0 1px; white-space: nowrap; }
.exam .rules { font-size: 8.4pt; margin: 0 0 6px; display: flex; gap: 10px; align-items: flex-start; }
.exam .rules .txt { flex: 1; }
.exam .rules h3 { font-size: 8.8pt; margin: 0 0 1px; text-decoration: underline; font-style: italic;
                  font-family: Georgia, serif; }
.exam .rules ol { margin: 0 0 0 1.3em; padding: 0; }
.exam .rules ol li { margin: 0; }
.exam .qr { flex: 0 0 auto; text-align: center; font-size: 6.8pt; line-height: 1.15; width: 76px; }
.exam .qr svg { width: 64px; height: 64px; display: block; margin: 0 auto 1px; }
.exam .qr .lnk { font-family: Helvetica, Arial, sans-serif; word-break: break-all; color: #333; }
.exam .official { font-size: 7.6pt; margin: 0 0 6px; border-collapse: collapse; width: 100%; }
.exam .official th, .exam .official td { border: 0.6pt solid #111; padding: 1px 3px; text-align: center; }
.exam .official th:first-child, .exam .official td:first-child { text-align: left; width: 26%; }
.exam .official caption { font-style: italic; font-size: 7.6pt; text-align: center; caption-side: top; }
.exam .cols { column-count: 2; column-gap: 7mm; column-rule: 0.5pt solid #999; }
.exam .cols.one { column-count: 1; }
.exam .sec { column-span: all; border-top: 1.2px solid #111; border-bottom: 0.6pt solid #111;
             margin: 4px 0 4px; padding: 2px 0; font-weight: 700; font-size: 10pt; text-align: center; }
.exam .sec small { display: block; font-weight: 400; font-size: 8.2pt; font-style: italic; }
.exam .q { break-inside: avoid; margin: 0 0 6px; display: grid; grid-template-columns: 1.6em 1fr; gap: 0 3px; }
.exam .q .n { font-weight: 700; }
.exam .q .body { min-width: 0; }
.exam .q .marks { float: right; font-size: 8pt; color: #333; margin-left: 6px; }
.exam .q .stim { font-style: italic; margin: 0 0 2px; }
.exam .q .stem { margin: 0 0 2px; }
.exam .opts { list-style: none; margin: 1px 0 0; padding: 0; }
.exam .opts.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 8px; }
.exam .opts li { padding-left: 1.5em; text-indent: -1.5em; margin: 0; }
.exam .opts .oid { font-weight: 600; display: inline-block; width: 1.5em; text-indent: 0; }
.exam .parts { list-style: none; margin: 2px 0 0; padding: 0; }
.exam .parts li { display: flex; gap: 5px; margin: 0 0 2px; }
.exam .parts .pid { font-weight: 600; min-width: 1.4em; }
.exam .parts .pm { margin-left: auto; font-size: 8pt; white-space: nowrap; color: #333; }
.exam .lines { margin: 3px 0 0; }
.exam .lines div { border-bottom: 0.5pt solid #999; height: 5.2mm; }
.exam .fig { break-inside: avoid; margin: 2px 0 6px; }
.exam .fig .lead { font-weight: 600; margin: 0 0 2px; }
.exam .fig .box { border: 0.8pt solid #111; padding: 2px; }
.exam .fig svg { width: 100%; height: auto; max-height: 64mm; display: block; }
.exam .end { column-span: all; text-align: center; font-size: 8pt; letter-spacing: 0.12em;
             text-transform: uppercase; color: #333; margin: 8px 0 0; border-top: 0.6pt solid #111;
             padding-top: 3px; }
.exam .draftmark { position: fixed; top: 40%; left: 10%; right: 10%; text-align: center;
                   font-family: Helvetica, Arial, sans-serif; font-size: 60pt; font-weight: 800;
                   letter-spacing: 0.2em; color: rgba(160, 30, 20, 0.10); transform: rotate(-18deg);
                   pointer-events: none; z-index: 0; }
.exam .shortfall { border-left: 3px solid #a1281e; background: #fdf3f2; padding: 4px 8px;
                   margin: 0 0 6px; font-size: 8.6pt; column-span: all; }

/* ── the marking scheme ── */
.exam .scheme { font-size: 8.6pt; line-height: 1.28; }
.exam .keygrid { border-collapse: collapse; margin: 0 0 6px; width: 100%; font-size: 8.4pt; column-span: all; }
.exam .keygrid td, .exam .keygrid th { border: 0.6pt solid #111; padding: 1px 2px; text-align: center; }
.exam .keygrid th { font-weight: 400; background: #eee; }
.exam .keygrid td { font-weight: 700; }
.exam .a { break-inside: avoid; margin: 0 0 4px; display: grid; grid-template-columns: 1.6em 1fr; gap: 0 3px; }
.exam .a .n { font-weight: 700; }
.exam .a .ans { font-weight: 700; }
.exam .a .why { color: #222; }
.exam .a .why .m { font-weight: 600; color: #444; }
.exam .a ol.w { margin: 1px 0 0 1.2em; padding: 0; }
.exam .a ol.w li { margin: 0; }
.exam .a ol.w .r { color: #555; font-style: italic; }
.exam .a .sc { color: #333; }
"""


def _short(options: list[dict[str, Any]]) -> bool:
    return all(len(re.sub(r"\$[^$]*\$", "xxxx", str(o.get("text") or ""))) <= 16 for o in options)


def _figure_key(question: dict[str, Any]) -> str:
    binding = question.get("diagram")
    if isinstance(binding, dict):
        return str(binding.get("diagram_id") or binding.get("diagram_title") or "")
    return ""


def _item(question: dict[str, Any], number: int, *, answers: bool, written_space: bool) -> str:
    out = [f"<div class='q'><span class='n'>{number}.</span><div class='body'>"]
    marks = _marks_of(question)
    q_type = str(question.get("question_type") or "").lower()
    if marks and q_type not in ("multiple_choice", "true_false", "matching", "assertion_reason"):
        out.append(f"<span class='marks'>({marks:g} {'mark' if marks == 1 else 'marks'})</span>")
    stimulus = str(question.get("stimulus_context") or "").strip()
    if stimulus:
        out.append(f"<div class='stim'>{_math(stimulus)}</div>")
    out.append(f"<div class='stem'>{_math(question.get('question_text'))}</div>")
    options = [o for o in (question.get("options") or []) if isinstance(o, dict)]
    if options:
        out.append(f"<ul class='opts{' grid' if _short(options) else ''}'>")
        for option in options:
            out.append(f"<li><span class='oid'>{_esc(option.get('id') or '')}.</span>"
                       f"{_math(option.get('text'))}</li>")
        out.append("</ul>")
    parts = [p for p in (question.get("structured_parts") or []) if isinstance(p, dict)]
    if parts:
        out.append("<ul class='parts'>")
        for part in parts:
            pm = _marks(float(part.get("marks") or 0))
            out.append(f"<li><span class='pid'>{_esc(part.get('part_id') or '')}</span>"
                       f"<span>{_math(part.get('sub_question'))}</span>"
                       + (f"<span class='pm'>{_esc(pm)}</span>" if pm else "") + "</li>")
        out.append("</ul>")
    if written_space and not options and not answers:
        lines = 2 if marks <= 2 else min(6, int(marks) + 1)
        out.append("<div class='lines'>" + "<div></div>" * lines + "</div>")
    out.append("</div></div>")
    return "".join(out)


def _figure_block(question: dict[str, Any], first: int, last: int, assets: dict[str, Any] | None,
                  answers: bool) -> str:
    figure = _figure(question, assets, answers=answers)
    if not figure:
        return ""
    binding = question.get("diagram") or {}
    what = "map" if re.search(r"\bmap\b", str(binding.get("diagram_title") or ""), re.I) else "figure"
    span = f"question {first}" if first == last else f"questions {first} to {last}"
    return (f"<div class='fig'><div class='lead'>Study the {what} below and answer {span}.</div>"
            f"<div class='box'>{figure}</div></div>")


def _qr_svg(url: str) -> str:
    try:
        import segno

        return segno.make(url, error="m").svg_inline(scale=2, border=1, dark="#111")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not draw the QR code: %s", exc)
        return ""


def _reason_for(question: dict[str, Any]) -> tuple[str, str, list[Any], str]:
    """The answer, one line of why, the worked steps, and the scheme."""
    from . import solution_builder

    worked = solution_builder.build(question)
    answer = worked.chosen or worked.answer or str(question.get("model_answer") or "")
    why = ""
    key = next((o for o in (question.get("options") or []) if isinstance(o, dict) and o.get("is_correct")), None)
    if key is not None:
        why = str(key.get("distractor_rationale") or key.get("rationale") or "").strip()
    if not why:
        why = str(question.get("model_answer") or "").strip() if key is not None else ""
    scheme = str(question.get("marking_scheme") or "").strip()
    if not why and scheme and key is not None:
        why = scheme
    return answer, why, worked.steps, scheme


def _scheme_item(question: dict[str, Any], number: int) -> str:
    answer, why, steps, scheme = _reason_for(question)
    out = [f"<div class='a'><span class='n'>{number}.</span><div>"]
    parts = [p for p in (question.get("structured_parts") or []) if isinstance(p, dict)]
    options = question.get("options")
    if options:
        out.append(f"<span class='ans'>{_math(answer)}</span>")
        if why:
            out.append(f" <span class='why'>— {_math(why[:360])}</span>")
    elif parts:
        for part in parts:
            pm = _marks(float(part.get("marks") or 0))
            out.append(f"<div><span class='ans'>{_esc(part.get('part_id') or '')}</span> "
                       f"{_math(part.get('model_answer') or '')}"
                       + (f" <span class='m'>{_esc(pm)}</span>" if pm else "") + "</div>")
        if scheme:
            out.append(f"<div class='sc'>{_math(scheme[:500])}</div>")
    else:
        out.append(f"<span class='ans'>{_math(answer)}</span>")
        if scheme:
            out.append(f"<div class='sc'>{_math(scheme[:500])}</div>")
    if steps:
        out.append("<ol class='w'>")
        for step in steps[:8]:
            out.append(f"<li>{_math(step.text)}"
                       + (f" <span class='r'>{_math(step.why)}</span>" if step.why else "") + "</li>")
        out.append("</ol>")
    out.append("</div></div>")
    return "".join(out)


def render_paper(paper: Any, *, answers: bool = False, with_scheme: bool = False,
                 assets: dict[str, Any] | None = None, scheme_url: str = "",
                 series: str = "") -> str:
    """A composed paper as the national paper prints it, or its marking
    scheme. `with_scheme` prints both, the scheme after a page break."""
    from .grade_order import grade_label as _grade_label

    grade_label = _grade_label(paper.grade)
    mast = dict(getattr(paper, "masthead", {}) or {})
    fmt = dict(getattr(paper, "format", {}) or {})
    columns = int(fmt.get("columns") or 2)
    series = series or mast.get("series") or ""
    scheme_url = scheme_url or getattr(paper, "scheme_url", "") or ""
    written_section = any(not s.get("marks_each") for s in fmt.get("sections") or [])

    def masthead(scheme: bool) -> str:
        code = "".join(w[:1] for w in str(paper.subject).split()[:3]).upper()
        return (
            "<div class='mast'>"
            f"<div class='code'>{_esc(code[:3])}</div>"
            + (f"<div class='series'>{_esc(series)}</div>" if series else "")
            + f"<div class='assessment'>{_esc(mast.get('assessment') or paper.title)}</div>"
            f"<div class='gradeline'>{_esc(mast.get('grade_line') or grade_label.upper())}</div>"
            f"<div class='subject'>{_esc(mast.get('subject') or paper.subject.upper())}"
            + (" — MARKING SCHEME" if scheme else "") + "</div>"
            + (f"<div class='time'>{_esc(mast.get('time') or 'Time: ' + paper.time_allowed)}</div>" if not scheme else "")
            + "</div>"
        )

    def candidate_lines() -> str:
        return ("<div class='cand'><span>(i) Your name</span><span>(ii) Name of your school</span>"
                "<span>(iii) Assessment number</span></div>")

    def rules() -> str:
        items = "".join(f"<li>{_esc(r)}</li>" for r in (paper.instructions or []))
        qr = ""
        if scheme_url:
            qr = (f"<div class='qr'>{_qr_svg(scheme_url)}<div>Marking scheme</div>"
                  f"<div class='lnk'>{_esc(scheme_url.replace('https://', '').replace('http://', ''))}</div></div>")
        return (f"<div class='rules'><div class='txt'><h3>READ THESE INSTRUCTIONS CAREFULLY</h3>"
                f"<ol>{items}</ol></div>{qr}</div>")

    def official() -> str:
        if not written_section:
            return ""
        rows_q, rows_m = [], []
        number = 0
        for section in paper.sections:
            if any(o for o in (section.items[:1] or [{}])[0].get("options") or []) if section.items else False:
                number += len(section.items)
                continue
            for question in section.items:
                number += 1
                rows_q.append(f"<th>{number}</th>")
                rows_m.append(f"<td>{_marks_of(question):g}</td>")
        if not rows_q:
            return ""
        return ("<table class='official'><caption>For official use only</caption>"
                "<tr><th>Question</th>" + "".join(rows_q) + "<th>Total</th></tr>"
                "<tr><td>Maximum score</td>" + "".join(rows_m)
                + f"<td>{sum(_marks_of(q) for s in paper.sections for q in s.items if not q.get('options')):g}</td></tr>"
                "<tr><td>Candidate's score</td>" + "<td></td>" * (len(rows_q) + 1) + "</tr></table>")

    def body(scheme: bool) -> str:
        out: list[str] = []
        number = 0
        for section in paper.sections:
            if section.heading:
                out.append(f"<div class='sec'>{_esc(section.heading.upper())}"
                           + (f" ({section.marks:g} MARKS)" if section.marks and not section.items[0].get('options') else "")
                           + (f"<small>{_esc(section.instructions)}</small>" if section.instructions and not scheme else "")
                           + "</div>")
            items = section.items
            if scheme and items and items[0].get("options"):
                # The key in a grid, ten to a row.
                keys = []
                for offset, question in enumerate(items, start=number + 1):
                    key = next((str(o.get("id") or "") for o in (question.get("options") or [])
                                if isinstance(o, dict) and o.get("is_correct")),
                               str(question.get("correct_answer") or ""))
                    keys.append((offset, key))
                for row in range(0, len(keys), 10):
                    chunk = keys[row:row + 10]
                    out.append("<table class='keygrid'><tr>" + "".join(f"<th>{n}</th>" for n, _ in chunk)
                               + "</tr><tr>" + "".join(f"<td>{_esc(k)}</td>" for _, k in chunk) + "</tr></table>")
            i = 0
            covered = -1        # the last index whose figure is already printed
            while i < len(items):
                question = items[i]
                number += 1
                figure = _figure_key(question)
                if figure and not scheme and i > covered:
                    j = i
                    while j + 1 < len(items) and _figure_key(items[j + 1]) == figure:
                        j += 1
                    covered = j
                    out.append(_figure_block(question, number, number + (j - i), assets, answers=False))
                if scheme:
                    out.append(_scheme_item(question, number))
                else:
                    out.append(_item(question, number, answers=False, written_space=True))
                i += 1
        if not out:
            out.append("<p>This paper has no questions in it.</p>")
        return "".join(out)

    draft = "<div class='draftmark'>DRAFT</div>" if paper.has_drafts else ""
    shortfall = f"<div class='shortfall'>Incomplete: {_esc(paper.shortfall)}.</div>" if paper.shortfall else ""
    parts: list[str] = [draft]
    if not answers:
        parts.append(masthead(False) + candidate_lines() + rules() + official() + shortfall)
        parts.append(f"<div class='cols{' one' if columns == 1 else ''}'>{body(False)}"
                     "<div class='end'>This is the last printed page</div></div>")
    if answers or with_scheme:
        parts.append("<div style='break-before: page'>" if with_scheme else "<div>")
        parts.append(masthead(True) + (shortfall if answers else ""))
        parts.append(f"<div class='cols scheme'>{body(True)}</div></div>")

    title = paper.title + (" — marking scheme" if answers else "")
    foot = _esc(f"Printed by {series}" if series else paper.title)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{PRINT_CSS}{PAPER_CSS}{EXAM_CSS}{_KATEX_CRITICAL}</style>{_KATEX}</head>"
        f"<body class='exam'><span style='string-set: paper-foot \"{foot}\"; position:absolute; left:-9999px'>{foot}</span>"
        f"<div class='sheet exam'>{''.join(parts)}</div></body></html>"
    )

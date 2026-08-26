"""Render a composed exam into printable output.

The previous export built two markdown strings and never touched the diagram
fields, so a ``diagram_based`` question printed as "Study the diagram below"
followed by nothing.

Diagrams are inlined here as SVG, and the question paper and marking scheme are
rendered from one composition so they cannot drift. The learner's copy hides the
layers the question expects them to supply; the marking scheme shows them.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from .diagram_scene import render_svg
from .grade_order import grade_label

logger = logging.getLogger("cbc-exam-renderer")

DEFAULT_INSTRUCTIONS = [
    "Answer ALL questions in the spaces provided.",
    "Check that this paper contains all the printed questions.",
    "All answers must be written in English.",
    "Show all working where calculations are required.",
]


def _esc(value: Any) -> str:
    return html.escape(str(value or ""))


def _diagram_svg(question: dict[str, Any], diagrams: dict[str, dict], with_answers: bool) -> str:
    """The diagram for a question, rendered for this audience."""
    binding = question.get("diagram") or (question.get("content") or {}).get("diagram")
    if not binding:
        return ""

    diagram_id = binding.get("diagram_id")
    source = diagrams.get(diagram_id) if diagram_id else None
    if not source:
        return ""

    svg = str(source.get("svg_markup") or source.get("diagram_svg") or "")
    if not svg:
        return ""

    scene = source.get("scene_document") or {}
    return render_svg(
        svg,
        scene if isinstance(scene, dict) else {},
        hide_layers=[] if with_answers else list(binding.get("hide_layers") or []),
        region_id=binding.get("region_id"),
        highlight_part_ids=list(binding.get("part_ids") or []),
    )


def _question_fields(question: dict[str, Any]) -> dict[str, Any]:
    """Read either the API shape or the stored ``content`` shape."""
    content = question.get("content") if isinstance(question.get("content"), dict) else {}
    pedagogy = question.get("pedagogy") or question.get("pedagogical_dna") or {}
    merged = {**content, **{k: v for k, v in question.items() if k != "content"}}
    return {
        "question_type": merged.get("question_type", ""),
        "question_text": merged.get("question_text", ""),
        "stimulus_context": merged.get("stimulus_context", ""),
        "options": merged.get("options") or [],
        "structured_parts": merged.get("structured_parts") or [],
        "correct_answer": merged.get("correct_answer"),
        "model_answer": merged.get("model_answer", ""),
        "marking_scheme": merged.get("marking_scheme", ""),
        "rubric": merged.get("rubric") or merged.get("marking_guide") or {},
        "provenance_citation": merged.get("provenance_citation", ""),
        "max_marks": pedagogy.get("max_marks", merged.get("max_marks", 1)),
        "bloom_level": pedagogy.get("bloom_level", ""),
        "diagram": merged.get("diagram"),
        "question_id": question.get("question_id", ""),
        "dna_id": question.get("dna_id", ""),
        "universal_id": question.get("universal_id", ""),
        "curriculum": question.get("curriculum") or question.get("curriculum_link") or {},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Markdown
# ─────────────────────────────────────────────────────────────────────────────


def render_markdown(exam: dict[str, Any], questions: list[dict], diagrams: dict[str, dict]) -> dict[str, str]:
    grade = grade_label(exam.get("grade"))
    head = (
        f"# {exam.get('title', 'Assessment')}\n\n"
        f"**Subject:** {exam.get('subject', '')}  \n"
        f"**Level:** {grade}  \n"
        f"**Time allowed:** {exam.get('time_allowed', '')}  \n"
        f"**Total marks:** {exam.get('total_marks', 0)}\n\n"
    )

    instructions = exam.get("instructions") or DEFAULT_INSTRUCTIONS
    paper = head + "---\n\n## Instructions to candidates\n\n"
    paper += "".join(f"{i + 1}. {line}\n" for i, line in enumerate(instructions))
    paper += "\n---\n\n"

    scheme = (
        f"# {exam.get('title', 'Assessment')} — Marking Scheme\n\n"
        f"**Subject:** {exam.get('subject', '')} · {grade}\n\n---\n\n"
    )

    for index, question in enumerate(questions, start=1):
        f = _question_fields(question)
        paper += f"### Question {index} ({f['max_marks']} marks)\n\n"
        if f["stimulus_context"]:
            paper += f"> {f['stimulus_context']}\n\n"

        svg = _diagram_svg(f, diagrams, with_answers=False)
        if svg:
            # Inline SVG survives markdown-to-HTML rendering, unlike an image link
            # to a file the consumer may not be able to reach.
            paper += f"{svg}\n\n"
        elif f["diagram"]:
            paper += "*[Diagram unavailable — regenerate this question's visual before printing.]*\n\n"

        paper += f"{f['question_text']}\n\n"

        for option in f["options"]:
            paper += f"- **{option.get('id', '')}.** {option.get('text', '')}\n"
        if f["options"]:
            paper += "\n"

        for part in f["structured_parts"]:
            paper += f"**{part.get('part_id', '')}** {part.get('sub_question', '')} *({part.get('marks', 1)} marks)*\n\n"

        paper += "---\n\n"

        scheme += f"### Question {index} ({f['max_marks']} marks)\n\n"
        answer_svg = _diagram_svg(f, diagrams, with_answers=True)
        if answer_svg:
            scheme += f"{answer_svg}\n\n"
        if f["correct_answer"]:
            scheme += f"**Correct answer:** `{f['correct_answer']}`\n\n"
        for option in f["options"]:
            rationale = option.get("distractor_rationale")
            if rationale:
                mark = "✓" if option.get("is_correct") else "✗"
                scheme += f"- {mark} **{option.get('id')}** — {rationale}\n"
        if f["options"]:
            scheme += "\n"
        if f["model_answer"]:
            scheme += f"**Model answer**\n\n{f['model_answer']}\n\n"
        for part in f["structured_parts"]:
            if part.get("model_answer"):
                scheme += f"**{part.get('part_id')}** ({part.get('marks', 1)} marks) — {part['model_answer']}\n\n"
        if f["marking_scheme"]:
            scheme += f"**Marks breakdown**\n\n{f['marking_scheme']}\n\n"

        rubric = f["rubric"]
        if rubric:
            scheme += "| Performance level | Indicator |\n|---|---|\n"
            for key in ("exceeding", "meeting", "approaching", "below"):
                scheme += f"| {key.title()} expectations | {rubric.get(key, '')} |\n"
            scheme += "\n"

        curriculum = f["curriculum"]
        scheme += (
            f"*Traceability — SLO: {curriculum.get('slo_id', 'n/a')} · "
            f"Question DNA: `{f['dna_id'] or f['question_id']}`*\n\n"
        )
        if f["provenance_citation"]:
            scheme += f"*Source: {f['provenance_citation']}*\n\n"
        scheme += "---\n\n"

    return {"question_paper": paper, "marking_scheme": scheme}


# ─────────────────────────────────────────────────────────────────────────────
# Print-ready HTML
# ─────────────────────────────────────────────────────────────────────────────

_PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11.5pt; line-height: 1.5;
       color: #111; margin: 0; padding: 0; }
.masthead { text-align: center; border-bottom: 2.5px solid #111; padding-bottom: 10px; margin-bottom: 14px; }
.masthead h1 { font-size: 15pt; margin: 0 0 6px; letter-spacing: 0.01em; }
.meta { display: flex; justify-content: center; flex-wrap: wrap; gap: 6px 18px;
        font-size: 9.5pt; text-transform: uppercase; letter-spacing: 0.06em; }
.instructions { border: 1px solid #999; padding: 10px 14px; margin-bottom: 18px; font-size: 10.5pt; }
.instructions h2 { font-size: 10.5pt; margin: 0 0 6px; text-transform: uppercase; letter-spacing: 0.08em; }
.instructions ol { margin: 0; padding-left: 18px; }
.q { margin-bottom: 20px; page-break-inside: avoid; }
.q-head { display: flex; justify-content: space-between; align-items: baseline;
          border-bottom: 1px solid #ccc; padding-bottom: 3px; margin-bottom: 8px; }
.q-num { font-weight: bold; font-size: 12pt; }
.q-marks { font-size: 10pt; font-style: italic; }
.stimulus { border-left: 3px solid #666; padding: 6px 0 6px 12px; margin-bottom: 10px;
            font-size: 10.5pt; background: #f7f7f7; }
.figure { margin: 10px 0; text-align: center; page-break-inside: avoid; }
.figure svg { max-width: 100%; max-height: 220px; height: auto; }
.figure figcaption { font-size: 9pt; font-style: italic; color: #555; margin-top: 4px; }
ol.options { list-style: upper-alpha; margin: 8px 0 0 0; padding-left: 26px; }
ol.options li { margin-bottom: 4px; }
.part { margin: 8px 0 8px 12px; }
.part-id { font-weight: bold; }
.answer-space { border-bottom: 1px dotted #bbb; height: 20px; margin-top: 5px; }
.scheme-block { background: #f4f6f5; border-left: 3px solid #0B6E5F; padding: 8px 12px; margin-top: 8px; font-size: 10.5pt; }
.scheme-block h4 { margin: 0 0 4px; font-size: 10pt; text-transform: uppercase; letter-spacing: 0.06em; color: #0B6E5F; }
table.rubric { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 9.5pt; }
table.rubric th, table.rubric td { border: 1px solid #bbb; padding: 4px 7px; text-align: left; vertical-align: top; }
table.rubric th { background: #eee; width: 26%; }
.correct { color: #0B6E5F; font-weight: bold; }
.incorrect { color: #8a8a8a; }
.trace { font-size: 8.5pt; color: #666; margin-top: 6px; font-family: ui-monospace, Menlo, monospace; }
.page-break { page-break-before: always; }
@media print { .no-print { display: none; } }
"""


def render_html(
    exam: dict[str, Any],
    questions: list[dict],
    diagrams: dict[str, dict],
    include_answers: bool = False,
) -> str:
    """A single print-ready document.

    With ``include_answers`` the marking scheme is appended after a page break,
    so one file gives an invigilator both halves.
    """
    grade = grade_label(exam.get("grade"))
    title = exam.get("title", "Assessment")
    instructions = exam.get("instructions") or DEFAULT_INSTRUCTIONS

    out: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        f"<style>{_PRINT_CSS}</style></head><body>",
        "<div class='masthead'>",
        f"<h1>{_esc(title)}</h1>",
        "<div class='meta'>",
        f"<span>{_esc(exam.get('subject', ''))}</span>",
        f"<span>{_esc(grade)}</span>",
        f"<span>Time: {_esc(exam.get('time_allowed', ''))}</span>",
        f"<span>Total: {_esc(exam.get('total_marks', 0))} marks</span>",
        "</div></div>",
        "<div class='instructions'><h2>Instructions to candidates</h2><ol>",
        "".join(f"<li>{_esc(line)}</li>" for line in instructions),
        "</ol></div>",
    ]

    for index, question in enumerate(questions, start=1):
        f = _question_fields(question)
        out.append("<div class='q'>")
        out.append(
            f"<div class='q-head'><span class='q-num'>Question {index}</span>"
            f"<span class='q-marks'>({_esc(f['max_marks'])} marks)</span></div>"
        )

        if f["stimulus_context"]:
            out.append(f"<div class='stimulus'>{_esc(f['stimulus_context'])}</div>")

        svg = _diagram_svg(f, diagrams, with_answers=False)
        if svg:
            binding = f["diagram"] or {}
            caption = binding.get("diagram_title") or ""
            out.append(f"<figure class='figure'>{svg}")
            if caption:
                out.append(f"<figcaption>Figure {index}: {_esc(caption)}</figcaption>")
            out.append("</figure>")
        elif f["diagram"]:
            out.append(
                "<p class='stimulus'><em>Diagram unavailable. Regenerate this "
                "question's visual before printing.</em></p>"
            )

        out.append(f"<p>{_esc(f['question_text'])}</p>")

        if f["options"]:
            out.append("<ol class='options'>")
            out.extend(f"<li>{_esc(o.get('text', ''))}</li>" for o in f["options"])
            out.append("</ol>")

        for part in f["structured_parts"]:
            out.append(
                f"<div class='part'><span class='part-id'>{_esc(part.get('part_id', ''))}</span> "
                f"{_esc(part.get('sub_question', ''))} "
                f"<em>({_esc(part.get('marks', 1))} marks)</em>"
                + "".join("<div class='answer-space'></div>" for _ in range(max(1, int(part.get("marks", 1)))))
                + "</div>"
            )

        if not f["options"] and not f["structured_parts"]:
            lines = max(2, int(f["max_marks"] or 1) * 2)
            out.extend("<div class='answer-space'></div>" for _ in range(lines))

        out.append("</div>")

    if include_answers:
        out.append("<div class='page-break'></div>")
        out.append(f"<div class='masthead'><h1>{_esc(title)} — Marking Scheme</h1>")
        out.append(f"<div class='meta'><span>{_esc(exam.get('subject', ''))}</span><span>{_esc(grade)}</span></div></div>")

        for index, question in enumerate(questions, start=1):
            f = _question_fields(question)
            out.append("<div class='q'>")
            out.append(
                f"<div class='q-head'><span class='q-num'>Question {index}</span>"
                f"<span class='q-marks'>({_esc(f['max_marks'])} marks)</span></div>"
            )

            answer_svg = _diagram_svg(f, diagrams, with_answers=True)
            if answer_svg:
                out.append(f"<figure class='figure'>{answer_svg}<figcaption>Labelled answer figure</figcaption></figure>")

            if f["correct_answer"]:
                out.append(f"<p><span class='correct'>Correct answer: {_esc(f['correct_answer'])}</span></p>")

            if f["options"]:
                out.append("<ul>")
                for option in f["options"]:
                    cls = "correct" if option.get("is_correct") else "incorrect"
                    rationale = option.get("distractor_rationale") or ""
                    out.append(
                        f"<li class='{cls}'><strong>{_esc(option.get('id'))}</strong> "
                        f"{_esc(option.get('text'))}{f' — {_esc(rationale)}' if rationale else ''}</li>"
                    )
                out.append("</ul>")

            if f["model_answer"]:
                out.append(f"<div class='scheme-block'><h4>Model answer</h4><p>{_esc(f['model_answer'])}</p></div>")

            for part in f["structured_parts"]:
                if part.get("model_answer"):
                    out.append(
                        f"<div class='scheme-block'><h4>{_esc(part.get('part_id'))} "
                        f"({_esc(part.get('marks', 1))} marks)</h4>"
                        f"<p>{_esc(part['model_answer'])}</p></div>"
                    )

            if f["marking_scheme"]:
                out.append(f"<div class='scheme-block'><h4>Marks breakdown</h4><p>{_esc(f['marking_scheme'])}</p></div>")

            rubric = f["rubric"]
            if rubric:
                out.append("<table class='rubric'>")
                for key in ("exceeding", "meeting", "approaching", "below"):
                    out.append(
                        f"<tr><th>{key.title()} expectations</th><td>{_esc(rubric.get(key, ''))}</td></tr>"
                    )
                out.append("</table>")

            curriculum = f["curriculum"]
            out.append(
                f"<div class='trace'>SLO {_esc(curriculum.get('slo_id', 'n/a'))} · "
                f"DNA {_esc(f['dna_id'] or f['question_id'])}"
                + (f" · {_esc(f['provenance_citation'])}" if f["provenance_citation"] else "")
                + "</div>"
            )
            out.append("</div>")

    out.append("</body></html>")
    return "".join(out)

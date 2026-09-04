from __future__ import annotations

import html
import re
from typing import Any

from .document_schema import EducationalDocument

PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.5;
    color: #111827;
    margin: 0;
    padding: 0;
}
.masthead {
    border-bottom: 2.5px solid #0B6E5F;
    padding-bottom: 10px;
    margin-bottom: 16px;
    text-align: center;
}
.masthead h1 {
    font-size: 16pt;
    margin: 0 0 6px;
    color: #064E3B;
}
.meta {
    font-size: 9.5pt;
    color: #4B5563;
    display: flex;
    justify-content: center;
    gap: 16px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
}
.badge-teacher {
    background: #FEF3C7;
    color: #92400E;
    border: 1px solid #F59E0B;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 8pt;
    font-weight: bold;
    display: inline-block;
}
.block {
    margin-bottom: 14px;
    page-break-inside: avoid;
}
.block-heading h2 {
    font-size: 13pt;
    color: #064E3B;
    border-bottom: 1px solid #E5E7EB;
    padding-bottom: 4px;
    margin-top: 18px;
}
.block-heading h3 {
    font-size: 11.5pt;
    color: #1F2937;
    margin-top: 12px;
}
.formula-box {
    background: #F0FDF4;
    border: 1px solid #86EFAC;
    border-left: 4px solid #0B6E5F;
    padding: 8px 14px;
    margin: 10px 0;
    border-radius: 4px;
}
.worked-example {
    background: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
}
.step-row {
    margin: 6px 0 6px 12px;
    font-size: 10.5pt;
}
.step-num {
    font-weight: bold;
    color: #0B6E5F;
}
.question-card {
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 14px;
    background: #FFFFFF;
}
.q-header {
    display: flex;
    justify-content: space-between;
    font-weight: bold;
    border-bottom: 1px solid #F3F4F6;
    padding-bottom: 4px;
    margin-bottom: 8px;
}
.answer-line {
    border-bottom: 1px dotted #9CA3AF;
    height: 22px;
    margin: 4px 0;
}
.marking-guide {
    background: #FFFBEB;
    border-left: 3px solid #F59E0B;
    padding: 6px 10px;
    margin-top: 8px;
    font-size: 9.5pt;
}
.trace-tag {
    font-size: 8pt;
    color: #6B7280;
    font-family: monospace;
    margin-top: 6px;
}
.figure {
    text-align: center;
    margin: 12px 0;
}
.figure svg {
    max-width: 100%;
    height: auto;
}
"""

KATEX_HEAD = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
    onload="document.documentElement.dataset.katex='ready';
    renderMathInElement(document.body, {
        delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false}
        ]
    });"></script>
<style>
    .katex-warning { display: none; }
    html:not([data-katex="ready"]) .katex-warning {
        display: block;
        background: #FFFBEB;
        border: 1px solid #F59E0B;
        color: #92400E;
        padding: 6px 10px;
        margin-bottom: 12px;
        font-size: 9.5pt;
        border-radius: 4px;
    }
</style>
"""


def _esc(val: Any) -> str:
    return html.escape(str(val or ""))


# LaTeX cannot go through html.escape: `a < b` becomes `a &lt; b` and KaTeX
# renders the entity instead of the inequality. It cannot go through raw
# either — this HTML is served from the API, and the document comes from the
# caller. So strip the two characters that can open a tag and leave the rest of
# the mathematics untouched.
_TAG_CHARS = str.maketrans({"<": " \\lt ", ">": " \\gt "})


def _latex(val: Any) -> str:
    """LaTeX that cannot open an HTML tag."""
    return str(val or "").translate(_TAG_CHARS)


# An SVG the caller supplied is markup we are about to inline. Scripts and
# event handlers have no place in a figure.
_SCRIPT = re.compile(r"<\s*script\b.*?<\s*/\s*script\s*>", re.I | re.S)
_OPEN_SCRIPT = re.compile(r"<\s*/?\s*(?:script|iframe|object|embed|foreignObject)\b[^>]*>", re.I)
_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(?:\"[^\"]*\"|\'[^\']*\'|[^\s>]+)", re.I)
_HREF_JS = re.compile(r"(?:xlink:)?href\s*=\s*(?:\"|\')?\s*javascript:[^\"\'>]*", re.I)


def _safe_svg(markup: Any) -> str:
    """A caller-supplied figure, with anything executable removed."""
    out = str(markup or "")
    if "<" not in out:
        return ""
    out = _SCRIPT.sub("", out)
    out = _OPEN_SCRIPT.sub("", out)
    out = _ON_ATTR.sub("", out)
    out = _HREF_JS.sub("", out)
    return out


def render_educational_document_html(
    doc: EducationalDocument | dict[str, Any],
    audience: str = "student",
) -> str:
    """Render an EducationalDocument into standalone print-ready HTML with KaTeX."""
    d = doc.to_dict() if isinstance(doc, EducationalDocument) else doc
    title = d.get("title", "CBC Mathematics Assessment")
    curr = d.get("curriculum") or {}
    blocks = d.get("blocks") or []
    effective_audience = audience or d.get("audience", "student")
    is_teacher = (effective_audience == "teacher")

    out: list[str] = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'/>",
        f"<title>{_esc(title)}</title>",
        f"<style>{PRINT_CSS}</style>",
        KATEX_HEAD,
        "</head>",
        "<body>",
        # Only visible when the KaTeX script did not load — an offline school
        # gets raw LaTeX, and should be told rather than left to wonder.
        "<div class='katex-warning'>Mathematical notation could not be typeset "
        "(no connection when this page was opened). Formulas below are shown in "
        "their source form. Reopen this page online before printing it for a class.</div>",
        "<div class='masthead'>",
        f"<h1>{_esc(title)}</h1>",
        "<div class='meta'>",
        f"<span>{_esc(curr.get('grade', ''))}</span>",
        f"<span>{_esc(curr.get('subject', 'Mathematics'))}</span>",
        f"<span>{_esc(curr.get('strand_name', ''))}</span>",
        f"<span>{_esc(curr.get('sub_strand_name', ''))}</span>",
        f"{'<span class=\"badge-teacher\">TEACHER COPY & MARKING SCHEME</span>' if is_teacher else ''}",
        "</div>",
        "</div>",
    ]

    for b in blocks:
        b_type = b.get("block_type")
        payload = b.get("payload") or {}

        if b_type == "heading":
            try:
                level = min(6, max(1, int(payload.get("level", 2))))
            except (TypeError, ValueError):
                level = 2
            tag = f"h{level}"
            out.append(f"<div class='block block-heading'><{tag}>{_esc(payload.get('text', ''))}</{tag}></div>")

        elif b_type == "paragraph":
            out.append(f"<div class='block block-paragraph'><p>{_esc(payload.get('text', ''))}</p></div>")

        elif b_type == "formula":
            latex = payload.get("latex", "")
            name = payload.get("name", "Formula")
            out.append(
                f"<div class='block formula-box'>"
                f"<strong>{_esc(name)}:</strong> $${_latex(latex)}$$"
                f"</div>"
            )

        elif b_type == "worked_example":
            steps = payload.get("steps") or []
            out.append("<div class='block worked-example'>")
            out.append(f"<strong>Worked Example:</strong> {_esc(payload.get('problem', ''))}")
            for st in steps:
                st_lat = st.get("latex", "")
                st_exp = st.get("explanation", "")
                out.append(f"<div class='step-row'><span class='step-num'>Step {_esc(st.get('step_number', ''))}:</span> $${_latex(st_lat)}$$ <em>{_esc(st_exp)}</em></div>")
            out.append(f"<div class='step-row' style='font-weight:bold;'>Answer: $${_latex(payload.get('final_answer', ''))}$$</div>")
            out.append("</div>")

        elif b_type == "diagram":
            svg = payload.get("svg", "")
            cap = payload.get("caption", "")
            out.append(f"<div class='block figure'>{_safe_svg(svg)}")
            if cap:
                out.append(f"<figcaption style='font-size:9pt;font-style:italic;'>{_esc(cap)}</figcaption>")
            out.append("</div>")

        elif b_type == "question":
            q_text = payload.get("question_text", "")
            marks = payload.get("marks", 1)
            q_num = payload.get("question_number", 1)
            out.append("<div class='block question-card'>")
            out.append(f"<div class='q-header'><span>Question {q_num}</span><span>({marks} marks)</span></div>")
            out.append(f"<p>{_esc(q_text)}</p>")

            if is_teacher:
                trace = payload.get("solution_trace") or {}
                sol_steps = trace.get("steps") or []
                out.append("<div class='marking-guide'><strong>Worked Solution & Marking Scheme:</strong>")
                for s in sol_steps:
                    out.append(f"<div>Step {_esc(s.get('step_number'))}: $${_latex(s.get('latex'))}$$ {_esc(s.get('explanation'))}</div>")
                if payload.get("marking_scheme"):
                    out.append(f"<div style='margin-top:6px;font-style:italic;'>Criteria: {_esc(payload.get('marking_scheme'))}</div>")
                out.append("</div>")
            else:
                # Student answer lines
                num_lines = max(2, marks * 2)
                for _ in range(num_lines):
                    out.append("<div class='answer-line'></div>")

            slo = payload.get("slo_id") or curr.get("slo_id")
            if slo:
                out.append(f"<div class='trace-tag'>SLO: {_esc(slo)}</div>")
            out.append("</div>")

    out.append("</body></html>")
    return "\n".join(out)

"""A teacher's guide as a document a teacher can hold.

The guide existed as JSON, as a score and as a review verdict, and — since the
reader was added — as a page in a browser tab. None of those is what a Kenyan
teacher takes into a classroom with no screen in it.

So this renders it for paper: A4, serif, one lesson per page, the teacher's own
words in the order the children live through them. The same shape as the exam
renderer next to it, because the two are printed on the same machine and read
by the same person.
"""
from __future__ import annotations

import html
import logging
from typing import Any

logger = logging.getLogger("cbc-notes-renderer")


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt;
       line-height: 1.55; color: #111; margin: 0; }
.masthead { border-bottom: 2.5px solid #111; padding-bottom: 10px; margin-bottom: 16px; }
.masthead h1 { font-size: 16pt; margin: 0 0 6px; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 9pt;
        text-transform: uppercase; letter-spacing: 0.06em; color: #444; }
.intro { font-size: 10.5pt; color: #333; margin-bottom: 18px; }
.gaps { border: 1px solid #b45309; padding: 10px 14px; margin-bottom: 18px;
        font-size: 10pt; }
.gaps h2 { font-size: 10pt; margin: 0 0 6px; text-transform: uppercase;
           letter-spacing: 0.06em; }

/* One lesson per page: a teacher carries the page for the lesson they are
   about to teach, not a stapled block they have to hunt through. */
.lesson { page-break-before: always; page-break-inside: auto; }
.lesson:first-of-type { page-break-before: avoid; }
.lesson h2 { font-size: 13pt; margin: 0 0 4px; }
.slos { font-size: 9pt; text-transform: uppercase; letter-spacing: 0.05em;
        color: #444; margin-bottom: 8px; }
.intent { font-size: 10.5pt; margin: 0 0 14px; }

.seg { margin-bottom: 14px; page-break-inside: avoid; }
.seg h3 { font-size: 11pt; margin: 0 0 4px; }
.seg .mins { font-weight: normal; color: #666; font-size: 9.5pt; }
.seg p { margin: 0 0 6px; }
.bridge { border-left: 2px solid #bbb; padding-left: 10px; color: #444;
          font-style: italic; margin: 0; }

.aside { margin-top: 10px; font-size: 10pt; page-break-inside: avoid; }
.aside h4 { font-size: 9pt; text-transform: uppercase; letter-spacing: 0.06em;
            color: #444; margin: 0 0 3px; }
.aside ol, .aside ul { margin: 0; padding-left: 18px; }
.aside p { margin: 0 0 4px; }
.foot { margin-top: 22px; border-top: 1px solid #ccc; padding-top: 6px;
        font-size: 8.5pt; color: #666; }
"""


def _modules(notes: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "lessons"):
        found = notes.get(key)
        if isinstance(found, list) and found:
            return [m for m in found if isinstance(m, dict)]
    return []


def _aside(title: str, body: str) -> str:
    return f"<div class='aside'><h4>{_esc(title)}</h4>{body}</div>" if body else ""


def _lesson(module: dict[str, Any], n: int) -> str:
    out = ["<section class='lesson'>"]
    out.append(f"<h2>{_esc(module.get('title') or f'Lesson {n}')}</h2>")

    bits = []
    if module.get("duration_minutes"):
        bits.append(f"{_esc(module['duration_minutes'])} minutes")
    bits += [_esc(s) for s in (module.get("slos_covered") or [])]
    if bits:
        out.append(f"<div class='slos'>{' · '.join(bits)}</div>")

    if module.get("learning_intent"):
        out.append(f"<p class='intent'><strong>By the end:</strong> "
                   f"{_esc(module['learning_intent'])}</p>")

    segments = [s for s in (module.get("exposition_segments") or [])
                if isinstance(s, dict)]
    if segments:
        for i, seg in enumerate(segments, start=1):
            mins = (f" <span class='mins'>{_esc(seg.get('minutes'))} min</span>"
                    if seg.get("minutes") else "")
            out.append("<div class='seg'>")
            out.append(f"<h3>{i}. {_esc(seg.get('topic') or f'Part {i}')}{mins}</h3>")
            out.append(f"<p>{_esc(seg.get('body'))}</p>")
            if seg.get("bridge"):
                out.append(f"<p class='bridge'>{_esc(seg['bridge'])}</p>")
            out.append("</div>")
    elif module.get("teacher_exposition"):
        out.append(f"<p>{_esc(module['teacher_exposition'])}</p>")

    questions = [q for q in (module.get("key_questions") or []) if str(q).strip()]
    if questions:
        out.append(_aside("Ask, in this order",
                          "<ol>" + "".join(f"<li>{_esc(q)}</li>" for q in questions) + "</ol>"))

    resources = [r for r in (module.get("resources_needed") or []) if str(r).strip()]
    if resources:
        out.append(_aside("Have ready", "<p>" + " · ".join(_esc(r) for r in resources) + "</p>"))

    misconceptions = [m for m in (module.get("common_misconceptions") or [])
                      if isinstance(m, dict)]
    if misconceptions:
        body = "".join(
            f"<p><strong>{_esc(m.get('misconception'))}</strong>"
            + (f" — {_esc(m.get('why_it_happens'))}" if m.get("why_it_happens") else "")
            + (f" Correct it by: {_esc(m.get('how_to_correct_it'))}"
               if m.get("how_to_correct_it") else "")
            + "</p>"
            for m in misconceptions
        )
        out.append(_aside("What goes wrong", body))

    d = module.get("differentiation") or {}
    if isinstance(d, dict) and any(d.get(k) for k in ("struggling", "confident", "sne")):
        body = "".join(
            f"<p><strong>{label}:</strong> {_esc(d[key])}</p>"
            for key, label in (("struggling", "Stuck"), ("confident", "Ahead"),
                               ("sne", "Special needs"))
            if d.get(key)
        )
        out.append(_aside("If a learner is stuck, ahead, or needs support", body))

    if module.get("formative_check"):
        out.append(_aside("How you know it worked",
                          f"<p>{_esc(module['formative_check'])}</p>"))
    if module.get("homework_or_follow_up"):
        out.append(_aside("After the lesson",
                          f"<p>{_esc(module['homework_or_follow_up'])}</p>"))

    out.append("</section>")
    return "".join(out)


def render_html(notes: dict[str, Any], *, grade: str = "", subject: str = "",
                strand: str = "", sub_strand: str = "", version: int = 0) -> str:
    """The whole guide as one print-ready document."""
    modules = _modules(notes)
    title = str(notes.get("title") or f"Teacher's Guide: {sub_strand or 'Lesson notes'}")

    meta = [p for p in (subject, grade, strand, sub_strand) if p]
    if notes.get("allocated_time"):
        meta.append(str(notes["allocated_time"]))
    if version:
        meta.append(f"version {version}")

    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        f"<style>{PRINT_CSS}</style></head><body>",
        "<div class='masthead'>",
        f"<h1>{_esc(title)}</h1>",
        "<div class='meta'>" + "".join(f"<span>{_esc(m)}</span>" for m in meta) + "</div>",
        "</div>",
    ]
    if notes.get("intro"):
        out.append(f"<p class='intro'>{_esc(notes['intro'])}</p>")

    gaps = [g for g in (notes.get("gaps") or []) if str(g).strip()]
    if gaps:
        # On the first page, not buried: it is what the teacher has to supply
        # themselves, and the design did not.
        out.append("<div class='gaps'><h2>What the design did not supply</h2><ul>"
                   + "".join(f"<li>{_esc(g)}</li>" for g in gaps) + "</ul></div>")

    if not modules:
        out.append("<p>This guide holds no lessons.</p>")
    for i, module in enumerate(modules, start=1):
        out.append(_lesson(module, i))

    out.append(
        "<div class='foot'>Generated from the KICD curriculum design. "
        "Check it before you teach from it.</div>"
    )
    out.append("</body></html>")
    return "".join(out)


# ── the material: the words themselves ──────────────────────────────────────


def render_material_html(material: dict[str, Any], *, grade: str = "",
                         subject: str = "", strand: str = "",
                         sub_strand: str = "", version: int = 0) -> str:
    """The words, laid out to be read aloud from.

    Deliberately unlike the plan's document. The plan is scanned before a
    lesson; this is read DURING one, off a page held in one hand while the
    other holds up a picture. So the spoken words are set large, and the
    instruction that produced them is small and grey above — there for
    reference, never competing with what the teacher is about to say.
    """
    pieces = [p for p in (material.get("material") or []) if isinstance(p, dict)]
    title = f"Lesson material: {sub_strand or 'this sub-strand'}"

    meta = [p for p in (subject, grade, strand, sub_strand) if p]
    if version:
        meta.append(f"version {version}")
    plan = material.get("from_plan") or {}
    if isinstance(plan, dict) and plan.get("version"):
        meta.append(f"from plan version {plan['version']}")

    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        f"<style>{PRINT_CSS}{_MATERIAL_CSS}</style></head><body>",
        "<div class='masthead'>",
        f"<h1>{_esc(title)}</h1>",
        "<div class='meta'>" + "".join(f"<span>{_esc(m)}</span>" for m in meta) + "</div>",
        "</div>",
    ]

    if not pieces:
        out.append("<p>No material has been written for this sub-strand yet.</p>")

    last_module = None
    for piece in pieces:
        number = piece.get("module_number")
        if number != last_module:
            out.append(f"<h2 class='lessonhead'>"
                       f"{_esc(piece.get('module_title') or f'Lesson {number}')}</h2>")
            last_module = number

        out.append("<section class='piece'>")
        head = _esc(piece.get("topic") or "")
        if piece.get("minutes"):
            head += f" <span class='mins'>{_esc(piece['minutes'])} min</span>"
        if piece.get("form"):
            head += f" <span class='form'>{_esc(piece['form'])}</span>"
        out.append(f"<h3>{head}</h3>")

        if piece.get("instruction"):
            out.append(f"<p class='directive'>{_esc(piece['instruction'])}</p>")
        if piece.get("title"):
            out.append(f"<p class='piecetitle'>{_esc(piece['title'])}</p>")

        said = str(piece.get("say") or "").strip()
        if said:
            # Line breaks are meaningful here: a verse is a verse.
            body = "".join(f"<p>{_esc(line)}</p>" for line in said.splitlines() if line.strip())
            out.append(f"<div class='say'>{body}</div>")
        else:
            out.append("<p class='missing'>No words were written for this part. "
                       "The teacher must supply them.</p>")

        for key, label in (("learner_does", "The children"),
                           ("notes_for_the_teacher", "While you say it"),
                           ("attribution", "Where these words come from")):
            if piece.get(key):
                out.append(f"<div class='aside'><h4>{label}</h4>"
                           f"<p>{_esc(piece[key])}</p></div>")
        out.append("</section>")

    out.append("<div class='foot'>Written from the lesson plan for this "
               "sub-strand. Read it before you read it aloud.</div>")
    out.append("</body></html>")
    return "".join(out)


_MATERIAL_CSS = """
.lessonhead { font-size: 13pt; margin: 22px 0 8px; padding-top: 10px;
              border-top: 1.5px solid #111; page-break-after: avoid; }
.piece { margin-bottom: 18px; page-break-inside: avoid; }
.piece h3 { font-size: 11pt; margin: 0 0 4px; }
.piece .mins, .piece .form { font-weight: normal; color: #666; font-size: 9pt; }
/* The instruction is reference, not script: small, grey, and never competing
   with the words the teacher is about to say. */
.directive { font-size: 8.5pt; color: #777; font-style: italic;
             margin: 0 0 6px; border-left: 2px solid #ddd; padding-left: 8px; }
.piecetitle { font-weight: bold; margin: 0 0 4px; }
.say { font-size: 12.5pt; line-height: 1.7; margin: 0 0 8px; }
.say p { margin: 0 0 4px; }
.missing { color: #b45309; font-style: italic; }
"""

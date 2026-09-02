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
/* A textbook, not a printout.
 *
 * The guide read as a wall of one-column prose at 11pt across a full A4
 * measure — about 100 characters a line, which is roughly twice what the eye
 * tracks comfortably and why a teacher scanning it under time pressure loses
 * their place. A publisher solves that with a narrower measure, and on A4 that
 * means two columns.
 *
 * Everything else here follows from printing: it will be photocopied in
 * greyscale on a machine in a shop, so nothing carries meaning by colour
 * alone, and it will be read a lesson at a time, so a lesson starts on its own
 * page and no box is ever split across one.
 */
@page {
  size: A4;
  margin: 20mm 16mm 18mm;
  /* The running head is what makes a stapled block navigable once it is on a
     desk with three other things on it. */
  @top-left  { content: string(guide-title); font-family: Georgia, serif;
               font-size: 8pt; color: #555; letter-spacing: 0.04em; }
  @top-right { content: string(lesson-head); font-family: Georgia, serif;
               font-size: 8pt; color: #555; }
  @bottom-center { content: counter(page); font-family: Georgia, serif;
                   font-size: 9pt; color: #444; }
}
* { box-sizing: border-box; }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 10.5pt;
  line-height: 1.5;
  color: #111;
  margin: 0;
  hyphens: auto;
  -webkit-hyphens: auto;
  orphans: 3;
  widows: 3;
  text-align: justify;
}
h1, h2, h3, h4, .label, .meta, .figure figcaption {
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
  text-align: left;
  hyphens: none;
}
h2, h3, h4 { break-after: avoid; }

/* ── the title page ─────────────────────────────────────────────────────── */
.masthead {
  string-set: guide-title content();
  border-bottom: 3px solid #111;
  padding-bottom: 12px;
  margin-bottom: 20px;
  break-after: avoid;
}
.masthead h1 { font-size: 21pt; line-height: 1.15; margin: 0 0 8px;
               letter-spacing: -0.01em; }
.meta { display: flex; flex-wrap: wrap; gap: 3px 16px; font-size: 8pt;
        text-transform: uppercase; letter-spacing: 0.09em; color: #555; }
.intro { font-size: 11.5pt; line-height: 1.55; color: #222; margin: 0 0 18px;
         column-span: all; }
/* The opening paragraph is set wider and larger, the way a chapter opener is. */
.intro::first-line { font-variant: small-caps; letter-spacing: 0.02em; }

.gaps { border: 1.5px solid #111; border-left-width: 5px; padding: 10px 14px;
        margin-bottom: 20px; font-size: 9.5pt; break-inside: avoid; }
.gaps h2 { font-size: 8.5pt; margin: 0 0 5px; text-transform: uppercase;
           letter-spacing: 0.09em; }
.gaps ul { margin: 0; padding-left: 16px; }

/* ── a lesson ───────────────────────────────────────────────────────────── */
.lesson { break-before: page; }
.lesson:first-of-type { break-before: avoid; }
.lesson-head { string-set: lesson-head content(); border-bottom: 1px solid #111;
               padding-bottom: 7px; margin-bottom: 12px; break-after: avoid; }
.lesson h2 { font-size: 15pt; margin: 0 0 3px; line-height: 1.2; }
.lesson .n { display: block; font-size: 8pt; letter-spacing: 0.16em;
             text-transform: uppercase; color: #666; margin-bottom: 3px; }
.slos { font-size: 8pt; text-transform: uppercase; letter-spacing: 0.07em;
        color: #555; margin: 0; }
.intent { font-size: 10.5pt; margin: 0 0 12px; padding: 8px 12px;
          background: #f2f2f0; border-left: 3px solid #111; break-inside: avoid;
          column-span: all; }

/* THE COLUMNS. Two on A4 gives about 62 characters a line — the measure a
   book is set to, and the reason this reads as a book rather than a memo. */
.body { column-count: 2; column-gap: 8mm; column-rule: 0.5pt solid #ddd; }

.seg { margin: 0 0 12px; break-inside: avoid; }
.seg h3 { font-size: 10.5pt; margin: 0 0 3px; }
.seg h3 .mins { font-weight: normal; color: #777; font-size: 8.5pt;
                letter-spacing: 0.04em; }
.seg p { margin: 0 0 6px; }
/* The first line of a topic is indented the way a book indents a paragraph
   after a heading's first — a small thing that reads as typeset. */
.seg p + p { text-indent: 1.2em; margin-top: -3px; }
.bridge { border-left: 2px solid #999; padding-left: 9px; color: #444;
          font-style: italic; font-size: 9.5pt; margin: 0; text-indent: 0; }

/* ── figures: where a picture goes, whether or not it exists yet ────────── */
.figure { break-inside: avoid; margin: 0 0 12px; border: 1px solid #111;
          padding: 0; background: #fff; }
.figure .plate {
  /* The empty plate. A teacher photocopying this needs to SEE the space the
     picture will occupy, or they discover at the copier that the page has no
     room for it. */
  height: 46mm; border-bottom: 1px solid #111;
  background:
    repeating-linear-gradient(45deg, #fafafa 0 6px, #f0f0f0 6px 12px);
  display: flex; align-items: center; justify-content: center;
  text-align: center; padding: 8px;
}
.figure .plate span { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                      font-size: 8pt; letter-spacing: 0.08em;
                      text-transform: uppercase; color: #666; }
.figure img, .figure svg { display: block; width: 100%; height: auto;
                           border-bottom: 1px solid #111; }
.figure figcaption { font-size: 8.5pt; line-height: 1.35; padding: 6px 8px;
                     color: #222; }
.figure figcaption b { letter-spacing: 0.06em; text-transform: uppercase;
                       font-size: 7.5pt; color: #444; display: block;
                       margin-bottom: 2px; }
/* A video or a recording has no plate to show — it has a cue. */
.figure.cue .plate { height: 20mm;
  background: repeating-linear-gradient(90deg, #f7f7f7 0 8px, #efefef 8px 16px); }

/* ── asides ─────────────────────────────────────────────────────────────── */
.aside { font-size: 9.5pt; break-inside: avoid; margin: 0 0 12px;
         padding: 8px 10px; background: #f7f7f5; border-top: 2px solid #111; }
.aside h4 { font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.1em;
            color: #333; margin: 0 0 4px; }
.aside ol, .aside ul { margin: 0; padding-left: 15px; }
.aside li { margin-bottom: 3px; }
.aside p { margin: 0 0 4px; }
.aside p:last-child { margin-bottom: 0; }

.foot { column-span: all; margin-top: 18px; border-top: 1px solid #999;
        padding-top: 6px; font-size: 8pt; color: #666; text-align: left; }

@media screen {
  /* On a screen it is still a book: a page-width sheet on a desk, so what the
     operator reviews is what the teacher will hold. */
  body { background: #6b6b6b; padding: 24px 0; }
  .sheet { width: 210mm; min-height: 297mm; margin: 0 auto 24px;
           padding: 20mm 16mm 18mm; background: #fff;
           box-shadow: 0 2px 14px rgba(0,0,0,0.35); }
}
@media print { .sheet { width: auto; min-height: 0; margin: 0; padding: 0;
                        box-shadow: none; } }
"""


def _modules(notes: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "hour_modules", "lessons"):
        found = notes.get(key)
        if isinstance(found, list) and found:
            return [m for m in found if isinstance(m, dict)]
    return []


# What each kind of asset is called on the page, and what the empty plate says
# when nobody has produced it yet.
_PLATE: dict[str, tuple[str, str]] = {
    "diagram": ("Diagram", "diagram to be placed here"),
    "image": ("Picture", "picture to be placed here"),
    "video": ("Video", "play the clip at this point"),
    "audio": ("Recording", "play the recording at this point"),
    "simulation": ("Activity screen", "interactive activity at this point"),
}


def _figures(module: dict[str, Any], n: int, assets: dict[str, str] | None = None) -> str:
    """The pictures this lesson asks for, as places on the page.

    A guide that says "observe pictures of Adam and Eve" and prints no space
    for them is a guide the teacher has to re-lay-out by hand at the
    photocopier. So every visual the plan names gets a numbered plate at the
    size it will occupy — filled where the asset exists, hatched and captioned
    where it does not.

    An empty plate is not a defect to hide. It is the production list: it says
    which picture is still to be made, in the lesson that needs it.
    """
    from . import asset_requirements

    wanted = [r for r in asset_requirements.read({"modules": [module]}).items
              if r.kind in _PLATE]
    if not wanted:
        return ""

    assets = assets or {}
    out = []
    for i, req in enumerate(wanted, start=1):
        label, empty = _PLATE[req.kind]
        found = assets.get(req.what.lower())
        cue = " cue" if req.kind in ("video", "audio") else ""
        plate = (f"<img src='{_esc(found)}' alt='{_esc(req.what)}'>" if found
                 else f"<div class='plate'><span>{_esc(empty)}</span></div>")
        where = f" · {_esc(req.topic)}" if req.topic else ""
        out.append(
            f"<figure class='figure{cue}'>{plate}"
            f"<figcaption><b>{label} {n}.{i}{where}</b>{_esc(req.what)}</figcaption>"
            f"</figure>"
        )
    return "".join(out)


def _aside(title: str, body: str) -> str:
    return f"<div class='aside'><h4>{_esc(title)}</h4>{body}</div>" if body else ""


def _lesson(module: dict[str, Any], n: int,
            assets: dict[str, str] | None = None) -> str:
    title = str(module.get("title") or f"Lesson {n}")
    out = ["<section class='lesson'>"]

    # The head sets the running head for every page this lesson spills onto.
    out.append("<div class='lesson-head'>")
    out.append(f"<h2><span class='n'>Lesson {n}</span>{_esc(title)}</h2>")
    bits = []
    if module.get("duration_minutes"):
        bits.append(f"{_esc(module['duration_minutes'])} minutes")
    bits += [_esc(s) for s in (module.get("slos_covered") or [])]
    if bits:
        out.append(f"<div class='slos'>{' · '.join(bits)}</div>")
    out.append("</div>")

    if module.get("learning_intent"):
        out.append(f"<p class='intent'><strong>By the end:</strong> "
                   f"{_esc(module['learning_intent'])}</p>")

    # Everything below runs in two columns, and the figures flow with the
    # teaching that asks for them rather than being collected at the end.
    out.append("<div class='body'>")
    out.append(_figures(module, n, assets))

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

    out.append("</div>")
    out.append("</section>")
    return "".join(out)


def render_html(notes: dict[str, Any], *, grade: str = "", subject: str = "",
                strand: str = "", sub_strand: str = "", version: int = 0,
                assets: dict[str, str] | None = None) -> str:
    """The whole guide as one print-ready document.

    `assets` maps what the plan ASKED FOR, lowercased, to a URL for the thing
    that was produced. Anything unmatched prints as a captioned empty plate at
    the size the picture will occupy, which is what turns the guide into its
    own production list.
    """
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
        "<div class='sheet'>",
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
        out.append(_lesson(module, i, assets))

    out.append(
        "<div class='foot'>Generated from the KICD curriculum design. "
        "Check it before you teach from it.</div>"
    )
    out.append("</div></body></html>")
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
        "<div class='sheet'>",
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

        # "The children" for every grade: a Grade 6 Arabic page told its
        # teacher what "the children" do. Neutral across the ladder.
        for key, label in (("learner_does", "The learners"),
                           ("notes_for_the_teacher", "While you say it"),
                           ("attribution", "Where these words come from")):
            if piece.get(key):
                out.append(f"<div class='aside'><h4>{label}</h4>"
                           f"<p>{_esc(piece[key])}</p></div>")
        out.append("</section>")

    out.append("<div class='foot'>Written from the lesson plan for this "
               "sub-strand. Read it before you read it aloud.</div>")
    out.append("</div></body></html>")
    return "".join(out)


_MATERIAL_CSS = """
/* Read ALOUD, off a page held in one hand. So: one column at a large size,
   ragged right, and no hyphenation — a word broken across a line is a word the
   teacher stumbles on in front of the class, which is the one place the
   typography of the plan's document would actively hurt. */
body { text-align: left; hyphens: none; -webkit-hyphens: none; font-size: 11pt; }
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

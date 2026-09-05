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
import re
from typing import Any

logger = logging.getLogger("cbc-notes-renderer")


_MATH_SPAN = re.compile(r"\$\$([\s\S]*?)\$\$|\$([^$\n]+?)\$")

# What makes a `$…$` span mathematics rather than two prices in a sentence.
# "if you have $50 and you spend $20" has a perfectly good `$…$` in it, and
# typesetting it produced "50andyouspend20" in the middle of a Grade 9 lesson.
_MATHISH = re.compile(r"[\\^_{}=<>+*/]|\\frac|\\times|\bcdot\b|[0-9]\s*[-−]\s*[0-9]")

# A LaTeX command loose in the prose, with no dollars around it at all. The
# model writes `-5^\text{°C}` inside an ordinary sentence, and a renderer that
# only looks between dollars prints the backslash on the page.
_BARE_LATEX = re.compile(
    r"(?:[A-Za-z0-9()\[\]+\-−.,]+\s*)?"          # what the command applies to
    r"(?:[\^_]\s*)?"                              # a superscript or subscript
    r"\\(?:frac|sqrt|text|times|div|cdot|pm|leq|geq|neq|approx|circ|degree)"
    r"(?:\s*\{[^{}]*\}){0,2}"                     # its arguments
)


def _is_maths(body: str) -> bool:
    """Whether what sat between two dollars was mathematics.

    Conservative on purpose. A false positive eats a sentence; a false negative
    prints a dollar sign, which a reader can live with.
    """
    if not body or body != body.strip():
        # LaTeX does not pad its delimiters with spaces. Currency in a sentence
        # nearly always does: `$50 and you spend $` ends with one.
        return False
    if _MATHISH.search(body):
        return True
    # A bare symbol or number: `$x$`, `$-3$`, `$12$`.
    return len(body) <= 12 and len(body.split()) == 1


def _math(value: Any) -> str:
    """Text with its `$…$` spans marked for typesetting, everything else escaped.

    The guide is authored with LaTeX in it — `$\\frac{2}{3}$` — and the page
    printed that verbatim, dollars and backslashes, because nothing here ever
    looked for it. Escaping happens per SEGMENT rather than over the whole
    string: escaping first would turn the maths into entities, and typesetting
    first would trust prose we did not write.
    """
    text = str(value or "")
    out: list[str] = []
    last = 0
    for match in _MATH_SPAN.finditer(text):
        display = match.group(1) is not None
        body = match.group(1) if display else match.group(2)
        if not display and not _is_maths(body):
            continue  # two prices in a sentence, not an expression
        out.append(_bare(text[last:match.start()]))
        tag = "div" if display else "span"
        out.append(f"<{tag} class='math' data-display='{str(display).lower()}'>"
                   f"{_esc(body)}</{tag}>")
        last = match.end()
    out.append(_bare(text[last:]))
    return "".join(out)


# Markdown, applied AFTER escaping so a model cannot write markup that becomes
# markup. The page was printing `**Addition**:` and `**Example**:` with the
# asterisks showing, all down a Grade 9 lesson — the model writes Markdown
# because that is how models write emphasis, and nothing here converted it.
_MD_CODE = re.compile(r"`([^`\n]+)`")
_MD_BOLD = re.compile(r"\*\*(?!\s)([^*\n]+?)(?<!\s)\*\*")
_MD_BOLD_ALT = re.compile(r"__(?!\s)([^_\n]+?)(?<!\s)__")
# One asterisk, but not one that is part of `**` — and not a bare `*` used as
# a multiplication sign, which is why a space on either side disqualifies it.
_MD_ITALIC = re.compile(r"(?<!\*)\*(?!\s|\*)([^*\n]+?)(?<![\s*])\*(?!\*)")
_MD_ITALIC_ALT = re.compile(r"(?<![A-Za-z0-9_])_(?!\s)([^_\n]+?)(?<!\s)_(?![A-Za-z0-9_])")


def _inline_markdown(escaped: str) -> str:
    """Bold, italic and code, on text that is already HTML-escaped.

    Code spans are lifted out before the other rules run and put back after.
    Wrapping them first is not enough — the bold rule still matches inside the
    tags, so "`**not bold**`" came back as code containing bold, which is the
    one thing a code span is for preventing.
    """
    held: list[str] = []

    def hold(match: re.Match[str]) -> str:
        held.append(match.group(1))
        return f"\x00code{len(held) - 1}\x00"

    out = _MD_CODE.sub(hold, escaped)
    out = _MD_BOLD.sub(r"<strong>\1</strong>", out)
    out = _MD_BOLD_ALT.sub(r"<strong>\1</strong>", out)
    out = _MD_ITALIC.sub(r"<em>\1</em>", out)
    out = _MD_ITALIC_ALT.sub(r"<em>\1</em>", out)

    for index, literal in enumerate(held):
        out = out.replace(f"\x00code{index}\x00", f"<code>{literal}</code>")
    return out


def _bare(text: str) -> str:
    """Escaped prose, with its Markdown rendered and any loose LaTeX typeset.

    The schema asks for `$…$`. Models write `-5^\text{°C}` in the middle of a
    sentence about the weather, and that reached the page with the backslash
    and the braces showing — and they write `**Addition**` for a heading,
    which reached it with the asterisks showing.
    """
    if "\\" not in text:
        return _inline_markdown(_esc(text))
    out: list[str] = []
    last = 0
    for match in _BARE_LATEX.finditer(text):
        out.append(_inline_markdown(_esc(text[last:match.start()])))
        out.append(f"<span class='math' data-display='false'>"
                   f"{_esc(match.group(0).strip())}</span>")
        last = match.end()
    out.append(_inline_markdown(_esc(text[last:])))
    return "".join(out)


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
  /* 50mm, because the column is 85mm and a drawing built to the brief is
     340 × 200 — so a plate that fills does not reflow the column around it. */
  height: 50mm; border-bottom: 1px solid #111;
  background:
    repeating-linear-gradient(45deg, #fafafa 0 6px, #f0f0f0 6px 12px);
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; gap: 10px;
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
/* The brief for a figure nobody has drawn yet. On screen it is a disclosure;
   on paper it prints in full, because the person commissioning the drawing is
   often working from the printout. */
.figure .plate button.copy-brief {
  font: inherit; font-size: 8pt; letter-spacing: 0.04em;
  text-transform: uppercase; padding: 4px 10px; cursor: pointer;
  background: #111; color: #fff; border: none; border-radius: 3px;
}
/* ── the practical work ───────────────────────────────────────────────────
   Read separately from the teaching: materials the night before, the steps at
   the bench, the safety line before anything is handed out. */
.activity { break-inside: avoid; border: 1px solid #111; border-radius: 3px;
  padding: 8px 10px; margin: 10px 0; }
.activity h4 { margin: 0 0 4px; font-size: 9pt; letter-spacing: 0.06em;
  text-transform: uppercase; }
.activity .intent { margin: 0 0 6px; font-style: italic; }
.activity .hazard { border-left: 3px solid #111; background: #f4f4f4;
  padding: 5px 8px; margin: 0 0 6px; font-size: 9pt; }
.activity .hazard strong { display: block; font-size: 8pt; letter-spacing: 0.06em;
  text-transform: uppercase; }
.activity .hazard p { margin: 2px 0 0; }
.activity .materials { margin: 0 0 6px; font-size: 9pt; }
.activity .materials span, .activity .aside-line span {
  font-size: 8pt; letter-spacing: 0.06em; text-transform: uppercase;
  color: #555; margin-right: 6px; }
.activity ol.procedure { margin: 0 0 6px; padding-left: 20px; }
.activity ol.procedure > li { margin-bottom: 4px; }
.activity .aside-line { margin: 0 0 4px; font-size: 9pt; }
.figure figcaption .why { display: block; font-style: italic; color: #555;
  margin-top: 2px; }

/* ── worked examples ─────────────────────────────────────────────────────
   Set apart from the teaching prose, because a learner revising scans for
   them. Numbered per lesson so a teacher can say "look at Example 2.1". */
.examples { break-inside: avoid; margin: 10px 0 14px; }
.example { border-left: 3px solid #111; padding: 8px 0 8px 10px; margin-bottom: 10px; }
.example h4 { margin: 0 0 5px; font-size: 8.5pt; letter-spacing: 0.08em;
  text-transform: uppercase; }
.example .statement { margin: 0 0 6px; font-weight: 600; }
.example ol.working { margin: 0 0 6px; padding-left: 18px; }
.example ol.working li { margin-bottom: 4px; }
.example ol.working .w { display: block; }
.example ol.working .why { display: block; font-size: 8.5pt; color: #444;
  font-style: italic; }
.example .answer { margin: 0; padding-top: 5px; border-top: 1px solid #ddd; }
.example .answer span { font-size: 8pt; letter-spacing: 0.08em;
  text-transform: uppercase; margin-right: 8px; }

/* Maths that has not been typeset yet still has to be readable — a reader
   offline sees the source rather than a blank. */
.math { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.95em; }
.math.katex-done, .katex { font-family: inherit; }
div.math { display: block; text-align: center; margin: 6px 0; }

/* ── the exercise set ────────────────────────────────────────────────────
   Drawn from the question bank, so what a learner practises on is what was
   reviewed and approved. */
.exercise { break-inside: avoid; margin-top: 16px; padding-top: 10px;
  border-top: 2px solid #111; }
.exercise h3 { margin: 0 0 2px; font-size: 11pt; }
.exercise .from { margin: 0 0 8px; font-size: 8pt; color: #555;
  letter-spacing: 0.04em; text-transform: uppercase; }
.exercise ol { margin: 0; padding-left: 20px; }
.exercise > ol > li { break-inside: avoid; }
.exercise ol > li { margin-bottom: 7px; }
.exercise ol.options { margin: 4px 0 0; padding-left: 18px; font-size: 9pt; }
.exercise .marks { font-size: 8pt; color: #555; }
.exercise.none p { font-size: 9pt; color: #555; font-style: italic; }

/* ── worked solutions ─────────────────────────────────────────────────────
   Set like a mathematics textbook: the working centred and given room, the
   reason for each line small beside it, and the whole thing numbered against
   the exercise so a learner can find their own question. */
.solutions { margin-top: 14px; padding-top: 10px; border-top: 1px solid #111; }
/* Two columns, like the answer section at the back of a textbook. A single
   673px row with a 20px number on the left and the working centred in the
   remaining 614px leaves the two unrelatable — the eye cannot carry a number
   that far to its working. */
.solutions, .exercise > ol { column-count: 2; column-gap: 9mm; }
.solutions h3, .solutions > .from, .solutions > .unworked { column-span: all; }
.solutions h3 { margin: 0 0 2px; font-size: 11pt; }
.solution { display: flex; gap: 8px; break-inside: avoid;
  page-break-inside: avoid; -webkit-column-break-inside: avoid;
  padding: 7px 0; border-bottom: 0.4pt solid #eee; }
.solution:last-of-type { border-bottom: 0; }
.solution .sn { flex: 0 0 20px; font-weight: 700; font-size: 10pt;
  padding-top: 2px; }
.solution .sn .ok { display: block; font-size: 6.5pt; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; color: #0a7; }
.solution .work { flex: 1 1 auto; min-width: 0; }
.solution .line { margin: 2px 0; }
/* A long expression must never be clipped: on screen it scrolls, and in print
   it is set smaller rather than cut off mid-equation. */
.solution .math { overflow-x: auto; max-width: 100%; }
@media print { .solution .math { font-size: 0.9em; overflow: visible; } }
.solution .why { margin: 0; font-size: 8pt; color: #555; font-style: italic;
  text-align: center; }
.solution .ans { margin: 5px 0 0; padding-top: 4px; border-top: 0.4pt solid #ddd;
  text-align: center; }
.solution .ans span:first-child { font-size: 7.5pt; letter-spacing: 0.08em;
  text-transform: uppercase; color: #666; margin-right: 7px; }
.solutions .unworked { margin: 8px 0 0; font-size: 8.5pt; color: #666;
  font-style: italic; }

.seg .learners { margin: 4px 0 0; font-size: 9pt; color: #333; }
.seg .learners span { font-size: 8pt; letter-spacing: 0.06em;
  text-transform: uppercase; color: #666; margin-right: 6px; }

.figure .brief { font-size: 8pt; border-top: 1px solid #ddd; }
.figure .brief summary { padding: 5px 8px; cursor: pointer; letter-spacing: 0.04em;
  text-transform: uppercase; }
.figure .brief pre { white-space: pre-wrap; margin: 0; padding: 0 8px 8px;
  font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 7.5pt;
  line-height: 1.45; }
@media print {
  .figure .plate button.copy-brief { display: none; }
  .figure .brief[open] pre, .figure .brief pre { display: block; }
}

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


def _plate(req: Any, label_no: str, assets: dict[str, str], *,
           brief: str = "") -> str:
    """One figure: the picture if it exists, the brief for it if it does not.

    An empty plate used to say "diagram to be placed here" and stop. Whoever
    read that then had to reconstruct what the diagram was for before they
    could commission it — from a page that already knows the grade, the
    sub-strand, the lesson and the sentence the figure sits beside. So the
    plate carries the prompt, and a button that copies it.
    """
    label, empty = _PLATE.get(req.kind, ("Figure", "to be placed here"))
    found = assets.get(str(req.what).lower())
    cue = " cue" if req.kind in ("video", "audio") else ""

    if found:
        # `assets` used to map a description straight to a URL. It now carries
        # the matched asset, so an SVG can be inlined rather than fetched —
        # which is what makes the printed page work with no network.
        if isinstance(found, dict):
            svg = str(found.get("svg") or "")
            url = str(found.get("url") or "")
            alt = str(found.get("alt") or req.what)
            body = svg if svg else f"<img src='{_esc(url)}' alt='{_esc(alt)}'>"
        else:
            body = f"<img src='{_esc(found)}' alt='{_esc(req.what)}'>"
    else:
        body = (
            f"<div class='plate'><span>{_esc(empty)}</span>"
            f"<button type='button' class='copy-brief' "
            f"data-brief='{_esc(brief)}'>Copy the prompt</button>"
            f"</div>"
        )
        if brief:
            # Kept in the page so it survives printing and works with no
            # JavaScript — the button is a convenience, not the only route.
            body += (f"<details class='brief'><summary>What this figure must show"
                     f"</summary><pre>{_esc(brief)}</pre></details>")

    where = f" · {_esc(req.topic)}" if req.topic else ""
    return (f"<figure class='figure{cue}{'' if found else ' empty'}'>{body}"
            f"<figcaption><b>{label} {label_no}{where}</b>{_esc(req.what)}</figcaption>"
            f"</figure>")


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
    return "".join(html for _, html in _placed(module, n, assets).get(0, []))


def _placed(module: dict[str, Any], n: int, assets: dict[str, str] | None = None,
            *, grade_label: str = "", subject: str = "", strand: str = "",
            sub_strand: str = "") -> dict[int, list[tuple[int, str]]]:
    """Every figure this lesson asks for, keyed by the segment it belongs to.

    Segment 0 means nothing in the teaching text named it, and it renders at
    the top of the lesson as figures always used to. Everything else sits
    beside the paragraph that calls for it — because a page that says "as shown
    below" and shows it three hundred words earlier has broken its own promise.
    """
    from . import asset_requirements, figure_anchor

    wanted = [r for r in asset_requirements.read({"modules": [module]}).items
              if r.kind in _PLATE]
    if not wanted:
        return {}

    assets = assets or {}
    segments = _segments(module)
    anchors = figure_anchor.anchor(wanted, segments)
    lesson_title = str(module.get("title") or f"Lesson {n}")

    out: dict[int, list[tuple[int, str]]] = {}
    for i, item in enumerate(anchors, start=1):
        seg_index = item.segment_index
        nearby = ""
        if 1 <= seg_index <= len(segments):
            nearby = str(segments[seg_index - 1].get("body") or "")
        brief = figure_anchor.brief_for(
            item.requirement, grade_label=grade_label, subject=subject,
            strand=strand, sub_strand=sub_strand, lesson_title=lesson_title,
            nearby_text=nearby,
        )
        html = _plate(item.requirement, f"{n}.{i}", assets, brief=brief)
        out.setdefault(seg_index, []).append((i, html))
    return out


def _aside(title: str, body: str) -> str:
    return f"<div class='aside'><h4>{_esc(title)}</h4>{body}</div>" if body else ""


def _segments(module: dict[str, Any]) -> list[dict[str, Any]]:
    """The teaching text, in the order it happens.

    The renderer read `exposition_segments`. The schema has never produced
    that: a guide comes back with `lesson_flow` — Introduction, Development,
    Conclusion — and a single `teacher_exposition` blob. So the segment path
    was dead code for every real guide, every figure fell into the "nothing
    named it" bucket, and the whole lesson rendered as one column of prose.
    """
    explicit = [seg for seg in (module.get("exposition_segments") or [])
                if isinstance(seg, dict)]
    if explicit:
        return explicit

    out: list[dict[str, Any]] = []
    for phase in (module.get("lesson_flow") or []):
        if not isinstance(phase, dict):
            continue
        body = " ".join(x for x in (
            str(phase.get("what_the_teacher_does") or "").strip(),
        ) if x)
        out.append({
            "topic": str(phase.get("phase") or "").strip() or "Part",
            "minutes": phase.get("minutes"),
            "body": body,
            "learners": str(phase.get("what_learners_do") or "").strip(),
        })
    if out:
        return out

    if module.get("teacher_exposition"):
        return [{"topic": "", "body": str(module["teacher_exposition"])}]
    return []


def _worked_examples(module: dict[str, Any], n: int) -> str:
    """The examples, set and worked, with their mathematics typeset.

    A guide that explains a procedure and shows none of it worked leaves the
    learner with nothing to imitate — and "the teacher demonstrates on the
    board" is a board nobody kept.
    """
    examples = [e for e in (module.get("worked_examples") or []) if isinstance(e, dict)]
    if not examples:
        return ""

    out = ["<div class='examples'>"]
    for i, example in enumerate(examples, start=1):
        out.append("<div class='example'>")
        out.append(f"<h4>Example {n}.{i}</h4>")
        if example.get("statement"):
            out.append(f"<p class='statement'>{_math(example['statement'])}</p>")

        steps = [st for st in (example.get("steps") or []) if isinstance(st, dict)]
        if steps:
            out.append("<ol class='working'>")
            for step in steps:
                line = f"<span class='w'>{_math(step.get('working'))}</span>"
                if step.get("because"):
                    line += f"<span class='why'>{_math(step['because'])}</span>"
                out.append(f"<li>{line}</li>")
            out.append("</ol>")

        if example.get("answer"):
            out.append(f"<p class='answer'><span>Answer</span>"
                       f"{_math(example['answer'])}</p>")
        out.append("</div>")
    out.append("</div>")
    return "".join(out)


def _activity(item: dict[str, Any], number: str) -> str:
    """One practical activity, as the activity station wrote it.

    Set apart from the teaching prose because a teacher preparing a lesson
    reads it separately — materials the night before, the steps at the bench,
    and the safety line before anything is handed out.
    """
    name = str(item.get("activity_name") or item.get("title") or "Activity")
    out = [f"<div class='activity'><h4>Activity {_esc(number)} · {_esc(name)}</h4>"]

    if item.get("objective"):
        out.append(f"<p class='intent'>{_math(item['objective'])}</p>")

    hazard = str(item.get("hazard_level") or "").strip().lower()
    warnings = [w for w in (item.get("hazard_warnings")
                            or item.get("safety_protocols") or []) if str(w).strip()]
    if warnings or hazard in ("medium", "high"):
        # First, not last. A safety line under the procedure is a safety line
        # read after the thing it was meant to prevent.
        out.append("<div class='hazard'><strong>Before you start</strong>"
                   + "".join(f"<p>{_math(w)}</p>" for w in warnings) + "</div>")

    materials = [m for m in (item.get("materials") or []) if str(m).strip()]
    if materials:
        out.append("<p class='materials'><span>Have ready</span>"
                   + " · ".join(_esc(m) for m in materials) + "</p>")

    steps = [st for st in (item.get("procedure_steps") or item.get("procedure") or [])
             if str(st).strip()]
    if steps:
        out.append("<ol class='procedure'>"
                   + "".join(f"<li>{_math(st)}</li>" for st in steps) + "</ol>")

    if item.get("grouping_mode"):
        out.append(f"<p class='aside-line'><span>Working</span>"
                   f"{_esc(item['grouping_mode'])}</p>")

    observables = [o for o in (item.get("assessment_observables") or [])
                   if str(o).strip()]
    if observables:
        out.append("<div class='aside'><h4>What to watch for</h4><ul>"
                   + "".join(f"<li>{_math(o)}</li>" for o in observables)
                   + "</ul></div>")

    adaptations = item.get("inclusion_adaptations") or []
    if isinstance(adaptations, dict):
        adaptations = [f"{k}: {v}" for k, v in adaptations.items() if v]
    adaptations = [a for a in adaptations if str(a).strip()]
    if adaptations:
        out.append("<div class='aside'><h4>So everyone can do it</h4>"
                   + "".join(f"<p>{_math(a)}</p>" for a in adaptations) + "</div>")

    out.append("</div>")
    return "".join(out)


def _media_cue(item: dict[str, Any], number: str) -> str:
    """A photograph or a clip: shown where it exists, cued where it does not."""
    kind = str(item.get("kind") or "photo").lower()
    label = "Video" if "video" in kind else "Picture"
    title = str(item.get("title") or "")
    url = str(item.get("storage_url") or "")

    body = ""
    if url and label == "Picture":
        body = f"<img src='{_esc(url)}' alt='{_esc(item.get('alt_text') or title)}'>"
    elif url:
        body = (f"<div class='plate'><span>Play the clip at this point</span>"
                f"<a href='{_esc(url)}'>{_esc(url)}</a></div>")
    else:
        body = ("<div class='plate'><span>"
                + ("clip to be filmed" if label == "Video" else "picture to be made")
                + "</span></div>")

    caption = f"<b>{label} {_esc(number)}</b>{_math(title)}"
    if item.get("purpose"):
        caption += f"<span class='why'>{_math(item['purpose'])}</span>"
    return f"<figure class='figure'>{body}<figcaption>{caption}</figcaption></figure>"


def _lesson(module: dict[str, Any], n: int,
            assets: dict[str, str] | None = None, *,
            grade_label: str = "", subject: str = "",
            strand: str = "", sub_strand: str = "",
            extras: dict[str, Any] | None = None) -> str:
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
    placed = _placed(module, n, assets, grade_label=grade_label, subject=subject,
                     strand=strand, sub_strand=sub_strand)
    # Figures no segment claimed lead the lesson, as they always did.
    out += [html for _, html in placed.get(0, [])]

    segments = _segments(module)
    if segments:
        for i, seg in enumerate(segments, start=1):
            mins = (f" <span class='mins'>{_esc(seg.get('minutes'))} min</span>"
                    if seg.get("minutes") else "")
            out.append("<div class='seg'>")
            out.append(f"<h3>{i}. {_esc(seg.get('topic') or f'Part {i}')}{mins}</h3>")
            # `_math`, not `_esc`: the guide is authored with LaTeX in it, and
            # escaping it printed the dollars and backslashes on the page.
            out.append(f"<p>{_math(seg.get('body'))}</p>")
            # The figure this paragraph promised, immediately under it.
            out += [html for _, html in placed.get(i, [])]
            if seg.get("learners"):
                out.append(f"<p class='learners'><span>The learners</span>"
                           f"{_math(seg['learners'])}</p>")
            if seg.get("bridge"):
                out.append(f"<p class='bridge'>{_math(seg['bridge'])}</p>")
            out.append("</div>")
    elif module.get("teacher_exposition"):
        out.append(f"<p>{_math(module['teacher_exposition'])}</p>")

    # Worked examples sit under the teaching that explains them, before the
    # asides — a learner looking for something to imitate finds it in the flow
    # of the lesson, not in a box at the end.
    out.append(_worked_examples(module, n))

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

    # What the other stations made for THIS lesson. A guide was rendered from
    # the lesson plan alone, so the activity KICD funded — written, reviewed
    # and filed — was not in the book a teacher printed.
    for i, item in enumerate((extras or {}).get("activities", []), start=1):
        out.append(_activity(item, f"{n}.{i}"))
    for i, item in enumerate((extras or {}).get("media", []), start=1):
        out.append(_media_cue(item, f"{n}.{i}"))

    out.append("</div>")
    out.append("</section>")
    return "".join(out)



# The button on an empty plate. Everything it copies is already in the page as
# a <details> block, so a reader with scripting off loses the convenience and
# nothing else.
# KaTeX writes the expression TWICE — once as MathML for a screen reader, once
# as styled HTML for the eye — and relies on its stylesheet to hide the first.
# On a server with no route to the CDN that stylesheet never arrives, both
# copies show, and every expression on the page reads "−3−3". These few rules
# are inlined so the page is correct with no network at all; the CDN sheet is
# still linked, and improves the typesetting when it does load.
_KATEX_CRITICAL = """
.katex-mathml {
  position: absolute; clip: rect(1px, 1px, 1px, 1px);
  padding: 0; border: 0; height: 1px; width: 1px; overflow: hidden;
}
"""


_KATEX = """
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"
  onload="document.querySelectorAll('.math').forEach(function (el) {
    try {
      katex.render(el.textContent, el, {
        displayMode: el.dataset.display === 'true', throwOnError: false
      });
      el.classList.add('katex-done');
    } catch (err) {}
  });"></script>
"""


_COPY_SCRIPT = """<script>
document.addEventListener('click', function (event) {
  var button = event.target.closest('.copy-brief');
  if (!button) return;
  var brief = button.getAttribute('data-brief') || '';
  var done = function () {
    var was = button.textContent;
    button.textContent = 'Copied';
    setTimeout(function () { button.textContent = was; }, 1600);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(brief).then(done, function () {});
    return;
  }
  var area = document.createElement('textarea');
  area.value = brief;
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try { document.execCommand('copy'); done(); } catch (err) {}
  document.body.removeChild(area);
});
</script>"""

def _exercises(grade: str, subject: str, strand: str, sub_strand: str,
               limit: int = 8) -> str:
    """The practice set, taken from the questions this system has approved.

    A textbook ends its topic with exercises. Writing fresh ones into the guide
    would mean two pools of questions for the same sub-strand — one reviewed,
    versioned and searchable, and one buried in a lesson plan — which is how a
    learner ends up practising on an item that was rejected.

    So the page draws from the bank: approved items only, easiest first, and it
    says plainly when the bank has nothing yet rather than inventing filler.
    """
    try:
        from .question_dna import question_dna_service

        rows = question_dna_service.list_questions(
            grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
            status="approved", limit=limit, order="curriculum",
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the question bank for %s/%s: %s",
                       grade, subject, exc)
        return ""

    if not rows:
        return ("<div class='exercise none'><h3>Exercise</h3>"
                "<p>No approved questions have been generated for this "
                "sub-strand yet. Run the questions station, and they will "
                "appear here.</p></div>")

    out = ["<div class='exercise'><h3>Exercise</h3>",
           "<p class='from'>From the question bank for this sub-strand.</p>",
           "<ol>"]
    asked: list[str] = []
    for row in rows:
        content = row.get("content") or {}
        text = str(content.get("question_text") or content.get("text") or "").strip()
        if not text:
            continue
        asked.append(text)
        marks = content.get("max_marks") or content.get("marks")
        tail = ""
        if marks:
            word = "mark" if str(marks).strip() in ("1", "1.0") else "marks"
            tail = f" <span class='marks'>({_esc(marks)} {word})</span>"
        out.append(f"<li>{_math(text)}{tail}")
        options = [o for o in (content.get("options") or []) if str(o).strip()]
        if options:
            out.append("<ol class='options' type='a'>"
                       + "".join(f"<li>{_math(o)}</li>" for o in options)
                       + "</ol>")
        out.append("</li>")
    out.append("</ol></div>")
    out.append(_solutions(asked))
    return "".join(out)


def _solutions(questions: list[str]) -> str:
    """The worked solutions, computed by the maths engine.

    A textbook ends with the working, not just the answers — a learner who got
    it wrong needs the line where their own working diverged. Every line here
    is computed by a deterministic solver and every reason is the rule that
    produced it, so nothing on this page is a model's opinion about arithmetic.

    Exercises the engine cannot work are LISTED as unworked rather than left
    out, because a numbered gap in a solutions section is what sends a learner
    hunting for a page that does not exist.
    """
    from . import worked_solutions

    if not questions:
        return ""

    solved = worked_solutions.solve_all(questions)
    if not any(s.solved for s in solved):
        return ""

    out = ["<div class='solutions'>",
           "<h3>Worked solutions</h3>",
           "<p class='from'>Every line below is computed and checked, not "
           "written out. Follow it against your own working and find the line "
           "where they part.</p>"]

    unworked: list[int] = []
    for n, solution in enumerate(solved, start=1):
        if not solution.solved:
            unworked.append(n)
            continue
        out.append("<div class='solution'>")
        out.append(f"<div class='sn'>{n}"
                   + ("<span class='ok' title='checked by the maths engine'>"
                      "checked</span>" if solution.verified else "")
                   + "</div>")
        out.append("<div class='work'>")
        out.append(f"<div class='math' data-display='true'>{_esc(solution.statement)}</div>")
        for line in solution.lines:
            out.append("<div class='line'>")
            out.append(f"<div class='math' data-display='true'>{_esc(line.latex)}</div>")
            if line.because:
                out.append(f"<p class='why'>{_esc(line.because)}</p>")
            out.append("</div>")
        out.append(f"<p class='ans'><span>Answer</span>"
                   f"<span class='math' data-display='false'>"
                   f"{_esc(solution.answer)}</span></p>")
        out.append("</div></div>")

    if unworked:
        numbers = ", ".join(str(n) for n in unworked)
        out.append(
            f"<p class='unworked'>Question{'s' if len(unworked) > 1 else ''} "
            f"{_esc(numbers)} {'are' if len(unworked) > 1 else 'is'} not a "
            f"calculation this engine works — mark "
            f"{'them' if len(unworked) > 1 else 'it'} by hand.</p>")

    out.append("</div>")
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
        f"<style>{PRINT_CSS}{_KATEX_CRITICAL}</style>{_KATEX}</head><body>",
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
    # Everything the other stations filed for this sub-strand. Read once for
    # the whole guide rather than per lesson: it is the same two queries either
    # way, and a guide with six lessons made twelve of them.
    from . import lesson_extras

    extras = lesson_extras.gather(grade, subject, sub_strand)
    by_lesson_activities = extras["activities_by_lesson"]
    by_lesson_media = lesson_extras.by_lesson(extras["media"])

    for i, module in enumerate(modules, start=1):
        number = module.get("module_number", i)
        # The curriculum reaches the figure briefs through here: a prompt that
        # does not name the grade and sub-strand is a prompt somebody has to
        # come back and ask about.
        out.append(_lesson(
            module, i, assets, grade_label=grade, subject=subject,
            strand=strand, sub_strand=sub_strand,
            extras={
                "activities": by_lesson_activities.get(number, []),
                "media": by_lesson_media.get(number, []),
            },
        ))

    # Anything filed against no particular lesson still belongs in the book.
    loose_activities = by_lesson_activities.get(0, [])
    loose_media = by_lesson_media.get(0, [])
    if loose_activities or loose_media:
        out.append("<section class='lesson'><div class='lesson-head'>"
                   "<h2><span class='n'>Also</span>For this sub-strand</h2>"
                   "<div class='slos'>Filed without a lesson number</div>"
                   "</div><div class='body'>")
        for i, item in enumerate(loose_activities, start=1):
            out.append(_activity(item, str(i)))
        for i, item in enumerate(loose_media, start=1):
            out.append(_media_cue(item, str(i)))
        out.append("</div></section>")

    out.append(_exercises(grade, subject, strand, sub_strand))
    out.append(
        "<div class='foot'>Generated from the KICD curriculum design. "
        "Check it before you teach from it.</div>"
    )
    out.append(_COPY_SCRIPT)
    out.append("</div></body></html>")
    return "".join(out)


# ── the material: the words themselves ──────────────────────────────────────


def _material_figures(plan: dict[str, Any], assets: dict[str, Any], *,
                      grade: str = "", subject: str = "", strand: str = "",
                      sub_strand: str = "") -> dict[Any, list[str]]:
    """The pictures each lesson needs, keyed by lesson number.

    Filled where the thing has been made, and a captioned plate carrying the
    prompt to make it where it has not — the same production list the plan
    carries, on the page the teacher actually holds.
    """
    from . import asset_requirements, figure_anchor

    modules = [m for m in (plan.get("modules") or []) if isinstance(m, dict)]
    if not modules:
        return {}

    out: dict[Any, list[str]] = {}
    for n, module in enumerate(modules, start=1):
        wanted = [r for r in asset_requirements.read({"modules": [module]}).items
                  if r.kind in _PLATE]
        if not wanted:
            continue
        number = module.get("module_number", n)
        plates: list[str] = []
        for i, req in enumerate(wanted, start=1):
            brief = figure_anchor.brief_for(
                req, grade_label=grade, subject=subject, strand=strand,
                sub_strand=sub_strand,
                lesson_title=str(module.get("title") or f"Lesson {n}"),
            )
            plates.append(_plate(req, f"{n}.{i}", assets, brief=brief))
        out[number] = plates
    return out


# "1. Calculate -3 + 5. 2. What is 7 - 9? 3. Find the product of -4 and 3."
# — an exercise set the model ran into one paragraph, which is how it printed:
# a wall of prose a learner cannot work down.
_NUMBERED_RUN = re.compile(r"(?:(?<=^)|(?<=[.?!\s]))(\d{1,2})[.)]\s+")


def _numbered_items(text: str) -> list[str]:
    """The numbered questions in a run of text, in order, or [].

    Only where they are actually a SET — three or more, counting up. A single
    "1." is a sentence that happens to start with a digit.

    The markers cannot simply be taken in order: "Calculate -3 + 5. 2. What
    is..." puts a "5." right before the "2.", because the answer to one
    question ends the sentence before the next one starts. So the ascending
    RUN is picked out of the candidates and the rest ignored.
    """
    marks = list(_NUMBERED_RUN.finditer(text))
    if len(marks) < 3:
        return []

    run: list[Any] = []
    expected = int(marks[0].group(1))
    for mark in marks:
        if int(mark.group(1)) == expected:
            run.append(mark)
            expected += 1
    if len(run) < 3:
        return []

    items: list[str] = []
    for i, mark in enumerate(run):
        end = run[i + 1].start() if i + 1 < len(run) else len(text)
        item = text[mark.end():end].strip()
        if item:
            items.append(item)
    return items


# Block-level Markdown. Models write it because that is how models write
# structure, and every one of these reached the page as literal characters.
_MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_BULLET = re.compile(r"^\s{0,3}[-*\u2022]\s+(.+)$")
_MD_RULE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")

# A line that is nothing but a calculation — "-2 + 3 = 1.", "-4 × 2 = -8." —
# written without dollars because the model was writing prose. Set as
# mathematics rather than left in the paragraph font.
_BARE_SUM = re.compile(r"^[-+(]?\s*\d[\d\s+\-*/×÷=().,]*\.?$")


def _is_a_calculation(line: str) -> bool:
    stripped = line.strip()
    if not _BARE_SUM.match(stripped):
        return False
    # An operator AND an equals: "1." and "2024." are not calculations, and a
    # bare list marker must never be swallowed as one.
    return bool(re.search(r"[-+*/×÷]", stripped[1:])) and "=" in stripped


def _spoken(said: str) -> str:
    """The words, with their Markdown rendered and their structure kept.

    A teacher reading aloud needs the prose; a learner working the questions
    needs them one to a line. And neither needs to read `**Example**:` with
    the asterisks still on it, which is what a whole Grade 9 lesson printed.
    """
    blocks: list[str] = []
    bullets: list[str] = []

    def flush() -> None:
        if bullets:
            blocks.append("<ul class='points'>"
                          + "".join(f"<li>{item}</li>" for item in bullets)
                          + "</ul>")
            bullets.clear()

    for line in said.splitlines():
        if not line.strip():
            flush()
            continue

        heading = _MD_HEADING.match(line)
        if heading:
            flush()
            level = min(6, 3 + len(heading.group(1)))   # h4 and below: h1-h3 are the page's
            blocks.append(f"<h{level} class='mdh'>{_math(heading.group(2))}</h{level}>")
            continue

        if _MD_RULE.match(line):
            flush()
            blocks.append("<hr class='mdr'>")
            continue

        bullet = _MD_BULLET.match(line)
        if bullet:
            bullets.append(_math(bullet.group(1)))
            continue

        flush()
        items = _numbered_items(line)
        if items:
            blocks.append("<ol class='practice'>"
                          + "".join(f"<li>{_math(i)}</li>" for i in items)
                          + "</ol>")
        elif _is_a_calculation(line):
            # Its own line, set as mathematics: this is a worked step, and in
            # the paragraph font it reads as a sentence that happens to have
            # numbers in it.
            blocks.append(f"<div class='math' data-display='true'>"
                          f"{_esc(line.strip().rstrip('.'))}</div>")
        else:
            blocks.append(f"<p>{_math(line)}</p>")

    flush()
    return "".join(blocks)


def _practice(said: str, piece: dict[str, Any]) -> str:
    """Worked solutions for the questions this piece sets.

    The material's own exercise sets had no working anywhere — a learner could
    find out they were wrong and not where. These are computed by the solvers,
    so a question the engine cannot work simply gets no solution rather than an
    invented one.
    """
    from . import worked_solutions

    questions: list[str] = []
    for line in said.splitlines():
        questions += _numbered_items(line)
    if not questions:
        return ""

    solved = [s for s in worked_solutions.solve_all(questions) if s.solved]
    if not solved:
        return ""

    out = ["<details class='answers'><summary>Worked answers</summary>"]
    for solution in solved:
        out.append("<div class='solution'>")
        out.append("<div class='sn'>"
                   + str(questions.index(solution.question) + 1)
                   + ("<span class='ok'>checked</span>" if solution.verified else "")
                   + "</div><div class='work'>")
        for line in solution.lines:
            out.append(f"<div class='math' data-display='true'>{_esc(line.latex)}</div>")
            if line.because:
                out.append(f"<p class='why'>{_esc(line.because)}</p>")
        out.append(f"<p class='ans'><span>Answer</span>"
                   f"<span class='math' data-display='false'>{_esc(solution.answer)}</span></p>")
        out.append("</div></div>")
    out.append("</details>")
    return "".join(out)


def _echoed(value: Any) -> bool:
    """Whether this value is the schema's own description of the field."""
    from . import placeholder_echo

    return placeholder_echo.is_echo(value)


def _citation(piece: dict[str, Any], *, grade: str = "", subject: str = "",
              strand: str = "", sub_strand: str = "") -> str:
    """Where in the KICD design this content comes from.

    The page said "Where these words come from: written here for this lesson",
    which tells a teacher challenged on a lesson precisely nothing. A citation
    is an address they can turn to — the curriculum line, the page and line in
    the design, and the design's own words at it.
    """
    from . import placeholder_echo

    # Anything copied from the schema is removed before it reaches the page. A
    # citation reading "The design's exact words at that address, verbatim" at
    # "page 202, line 14" is a fabricated reference, and it survives inspection
    # precisely because it looks like a citation.
    cleaned = placeholder_echo.clean_citation(piece.get("citation"))
    ref = cleaned["ref"]
    quote = cleaned["quote"]
    attribution = str(piece.get("attribution") or "").strip()
    if placeholder_echo.is_echo(attribution):
        attribution = ""

    if not (ref or quote or attribution):
        return ""

    where = " · ".join(x for x in (grade, subject, strand, sub_strand) if x)
    out = ["<div class='aside citation'><h4>Where this comes from</h4>"]
    if where:
        out.append(f"<p class='curriculum'>{_esc(where)}</p>")
    if ref:
        out.append(f"<p class='ref'>KICD design, page {_esc(ref.split(':')[0])}"
                   + (f", line {_esc(ref.split(':')[1])}" if ':' in ref else "")
                   + "</p>")
    if quote:
        out.append(f"<blockquote>{_esc(quote)}</blockquote>")
    if attribution and not quote:
        # No design address: these words are the model's own, and the page
        # should say so rather than implying the curriculum asked for them.
        out.append(f"<p class='own'>Not quoted from the design — "
                   f"{_esc(attribution)}</p>")
    elif attribution:
        out.append(f"<p class='own'>{_esc(attribution)}</p>")
    out.append("</div>")
    return "".join(out)


def render_material_html(material: dict[str, Any], *, grade: str = "",
                         subject: str = "", strand: str = "",
                         sub_strand: str = "", version: int = 0,
                         assets: dict[str, Any] | None = None,
                         plan: dict[str, Any] | None = None) -> str:
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
    # NOT `plan`: that is the parameter holding the plan's CONTENT, and
    # reassigning it here silently emptied it — every figure vanished from the
    # material page while the plan's own page still showed them.
    plan_ref = material.get("from_plan") or {}
    if isinstance(plan_ref, dict) and plan_ref.get("version"):
        meta.append(f"from plan version {plan_ref['version']}")

    out = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_esc(title)}</title>",
        f"<style>{PRINT_CSS}{_MATERIAL_CSS}{_KATEX_CRITICAL}</style>{_KATEX}</head><body>",
        "<div class='sheet'>",
        "<div class='masthead'>",
        f"<h1>{_esc(title)}</h1>",
        "<div class='meta'>" + "".join(f"<span>{_esc(m)}</span>" for m in meta) + "</div>",
        "</div>",
    ]

    if not pieces:
        out.append("<p>No material has been written for this sub-strand yet.</p>")

    # Figures belong on this page too. The material is what a teacher reads
    # while holding up the picture, so a page with no place kept for it is a
    # page that sends them back to the plan to find out what to hold up.
    by_module = _material_figures(plan or {}, assets or {}, grade=grade,
                                 subject=subject, strand=strand,
                                 sub_strand=sub_strand)

    last_module = None
    for piece in pieces:
        number = piece.get("module_number")
        if number != last_module:
            out.append(f"<h2 class='lessonhead'>"
                       f"{_esc(piece.get('module_title') or f'Lesson {number}')}</h2>")
            out += by_module.get(number, [])
            last_module = number

        out.append("<section class='piece'>")
        head = _esc(piece.get("topic") or "")
        if piece.get("minutes"):
            head += f" <span class='mins'>{_esc(piece['minutes'])} min</span>"
        form = str(piece.get("form") or "")
        if form and not _echoed(form):
            head += f" <span class='form'>{_esc(form)}</span>"
        out.append(f"<h3>{head}</h3>")

        if piece.get("instruction"):
            out.append(f"<p class='directive'>{_math(piece['instruction'])}</p>")
        if piece.get("title"):
            out.append(f"<p class='piecetitle'>{_math(piece['title'])}</p>")

        said = str(piece.get("say") or "").strip()
        if said:
            # Line breaks are meaningful here: a verse is a verse.
            #
            # `_math`, not `_esc`: a mathematics lesson's spoken words carry
            # LaTeX, and escaping it printed the dollars and the backslashes on
            # the page a teacher reads aloud from.
            out.append(f"<div class='say'>{_spoken(said)}</div>")
            out.append(_practice(said, piece))
        else:
            out.append("<p class='missing'>No words were written for this part. "
                       "The teacher must supply them.</p>")

        # The worked examples belong here as much as in the plan: this is the
        # page the mathematics is actually on, and a learner with nothing to
        # imitate has the explanation and no model of the working.
        out.append(_worked_examples(piece, number or 1))

        # "The children" for every grade: a Grade 6 Arabic page told its
        # teacher what "the children" do. Neutral across the ladder.
        for key, label in (("learner_does", "The learners"),
                           ("notes_for_the_teacher", "While you say it")):
            if piece.get(key):
                out.append(f"<div class='aside'><h4>{label}</h4>"
                           f"<p>{_math(piece[key])}</p></div>")
        out.append(_citation(piece, grade=grade, subject=subject,
                             strand=strand, sub_strand=sub_strand))
        out.append("</section>")

    # The exercise set and its worked solutions belong on THIS page too. They
    # were added to the plan's booklet and not to the material — so the page a
    # teacher actually hands out, the one the mathematics is for, ended at the
    # last thing the teacher says and offered nothing to work.
    out.append(_exercises(grade, subject, strand, sub_strand))

    out.append("<div class='foot'>Written from the lesson plan for this "
               "sub-strand. Read it before you read it aloud.</div>")
    out.append("</div></body></html>")
    return "".join(out)


_MATERIAL_CSS = """
/* Two columns, like the plan's document and like a textbook. It was one wide
   column because this page is read aloud from — but a 190mm measure is 110
   characters, which is where a reader loses their place returning to the left
   edge, and losing your place is exactly what must not happen mid-sentence in
   front of a class. */
.sheet .piece, .sheet .lessonhead { break-inside: avoid; }
.sheet { column-count: 2; column-gap: 9mm; column-rule: 0.4pt solid #ddd; }
.sheet .masthead { column-span: all; }
.sheet .foot { column-span: all; }
.sheet .lessonhead { column-span: all; }

/* The exercise and its solutions carry their OWN two columns. Nested inside
   the sheet's two they became four, each 84px wide — narrow enough that
   `(-3) × (-4) + 10` overflowed its column and a fraction bar stretched past
   its numerator. They span the sheet and divide themselves. */
.sheet .exercise, .sheet .solutions { column-span: all; }

/* Where this comes from — the curriculum line, the page and line in the KICD
   design, and the design's own words. */
.aside.citation .curriculum { font-size: 8pt; letter-spacing: 0.06em;
  text-transform: uppercase; color: #555; margin: 0 0 3px; }
.aside.citation .ref { font-size: 8.5pt; font-weight: 600; margin: 0 0 4px; }
.aside.citation blockquote { margin: 0; padding-left: 8px;
  border-left: 2px solid #999; font-style: italic; font-size: 9pt;
  color: #333; }
.aside.citation .own { font-size: 8.5pt; color: #666; margin: 4px 0 0;
  font-style: italic; }

/* An exercise set, one question to a line with room to answer beside it —
   rather than the wall of prose a run-on paragraph makes of it. */
/* Structure the model wrote in Markdown. */
h4.mdh, h5.mdh, h6.mdh { margin: 10px 0 3px; font-size: 10pt; }
ul.points { margin: 5px 0; padding-left: 20px; }
ul.points > li { margin-bottom: 4px; }
hr.mdr { border: 0; border-top: 0.4pt solid #ccc; margin: 8px 0; }
code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.92em;
  background: #f4f4f4; padding: 0 3px; border-radius: 2px; }

ol.practice { margin: 6px 0; padding-left: 22px; }
ol.practice > li { margin-bottom: 7px; break-inside: avoid; }
details.answers { margin: 6px 0 0; border-top: 0.4pt solid #ddd; }
details.answers > summary { font-size: 8pt; letter-spacing: 0.06em;
  text-transform: uppercase; color: #555; cursor: pointer; padding: 4px 0; }
@media print {
  details.answers { display: block; }
  details.answers > summary { list-style: none; }
  details.answers > div { display: block !important; }
}
details.answers[open] > summary { color: #111; }

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

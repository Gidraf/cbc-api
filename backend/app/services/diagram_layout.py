"""Whether a drawn SVG will actually READ in the book's column.

A model asked for "a diagram" returns something that looks fine at 800×600 in
a browser tab and is illegible on the page. The first drawing this station
produced put all eight of its text elements on top of a shape, and set them at
a size that resolves to 5.9 css pixels once the figure is scaled into the
column. Nobody reviewing a thumbnail catches either.

So the geometry is measured rather than trusted. The numbers here are not
taste; they are read off the page the renderer actually builds:

    sheet 210mm, padding 16mm each side          -> 178mm of content
    .body { column-count: 2; column-gap: 8mm }   -> (178 - 8) / 2 = 85mm
    .figure svg { width: 100%; height: auto }    -> the viewBox aspect ratio
                                                    ALONE sets the height
    .figure .plate { height: 50mm }              -> the space the page
                                                    reserves when undrawn

A drawing that is not about 85 × 50 reflows the column the moment it lands,
so the operator reviewing the empty plate was reviewing a different page.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

COLUMN_MM = 85.0          # the figure's true width on the page
PLATE_MM = 50.0           # the height the plate reserves for it
IDEAL_ASPECT = COLUMN_MM / PLATE_MM        # 1.70 — i.e. a 340 × 200 viewBox
ASPECT_RANGE = (1.4, 2.4)

# The caption beside the figure is 8.5pt ≈ 3.0mm. A label smaller than its own
# caption is not a label. 3.0mm of 85mm is 3.5% of the viewBox width.
MIN_FONT_FRACTION = 0.035

# Helvetica's average advance width, near enough to catch a line that runs off
# the canvas. The brief quotes this same figure so the model can do the sum.
CHAR_WIDTH = 0.55

MIN_FILL = 0.70           # of each axis, or the canvas is mostly empty


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    what: str = ""

    def hits(self, other: "Box") -> bool:
        return not (self.x1 <= other.x0 or self.x0 >= other.x1
                    or self.y1 <= other.y0 or self.y0 >= other.y1)

    def inside(self, other: "Box") -> bool:
        return (self.x0 >= other.x0 and self.x1 <= other.x1
                and self.y0 >= other.y0 and self.y1 <= other.y1)

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass
class Fit:
    findings: list[str] = field(default_factory=list)
    aspect: float = 0.0
    collisions: int = 0
    texts: int = 0
    smallest_font_fraction: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.findings


def _translate(transform: str) -> tuple[float, float]:
    """Only translate. A rotate or a matrix makes the boxes below wrong, and a
    wrong overlap report is worse than none — those are reported instead."""
    found = re.search(r"translate\(\s*(-?[\d.]+)[\s,]+(-?[\d.]+)?", transform or "")
    if not found:
        return 0.0, 0.0
    return float(found.group(1)), float(found.group(2) or 0.0)


def _number(el: ET.Element, name: str, fallback: float = 0.0) -> float:
    raw = (el.get(name) or "").strip()
    try:
        return float(re.sub(r"[a-z%]+$", "", raw) or fallback)
    except ValueError:
        return fallback


def _inherited_font(el: ET.Element, stack: list[float]) -> float:
    size = _number(el, "font-size", 0.0)
    if not size:
        style = el.get("style") or ""
        found = re.search(r"font-size\s*:\s*([\d.]+)", style)
        size = float(found.group(1)) if found else 0.0
    return size or (stack[-1] if stack else 16.0)


def _text_boxes(el: ET.Element, dx: float, dy: float, font: float,
                texts: list[tuple[Box, float, str]]) -> None:
    """Every line a <text> puts on the page, as its own box.

    SVG text positioning has three forms and a drawing mixes them: the parent's
    own x/y, a <tspan> with absolute x/y, and a <tspan> carrying only `dy` and
    inheriting x from the line before it.
    """
    anchor = (el.get("text-anchor") or "start").strip()
    base_x, base_y = _number(el, "x") + dx, _number(el, "y") + dy

    def place(body: str, x: float, y: float, size: float, how: str) -> None:
        body = body.strip()
        if not body:
            return
        width = len(body) * size * CHAR_WIDTH
        if how == "middle":
            x -= width / 2
        elif how == "end":
            x -= width
        # y is the baseline: the glyphs sit above it.
        texts.append((Box(x, y - size * 0.8, x + width, y + size * 0.2, body),
                      size, body))

    spans = [c for c in el if c.tag.split("}")[-1] == "tspan"]
    if not spans:
        place("".join(el.itertext()), base_x, base_y, font, anchor)
        return

    # Text sitting directly on the parent, before the first <tspan>.
    place(el.text or "", base_x, base_y, font, anchor)

    x, y = base_x, base_y
    for span in spans:
        size = _inherited_font(span, [font])
        how = (span.get("text-anchor") or anchor).strip()
        x = _number(span, "x") + dx if span.get("x") is not None else x
        if span.get("y") is not None:
            y = _number(span, "y") + dy
        else:
            y += _number(span, "dy", 0.0)
        place("".join(span.itertext()), x, y, size, how)
        # A line that only shifted by `dy` keeps the x it inherited, which is
        # how the next line lands under this one rather than at the origin.
        place(span.tail or "", x, y, font, how)


def _walk(el: ET.Element, dx: float, dy: float, font: float,
          texts: list[tuple[Box, float, str]], shapes: list[Box],
          unmeasurable: list[str]) -> None:
    tag = el.tag.split("}")[-1]
    tdx, tdy = _translate(el.get("transform", ""))
    transform = el.get("transform", "")
    if transform and not re.fullmatch(r"\s*translate\([^)]*\)\s*", transform):
        unmeasurable.append(transform.strip()[:40])
    dx, dy = dx + tdx, dy + tdy
    font = _inherited_font(el, [font])

    if tag == "text":
        # A <text> holding <tspan> lines is SEVERAL boxes, not one. Measuring
        # only the parent collapsed every wrapped label onto the parent's own
        # x/y — so the check passed drawings whose second and third lines ran
        # off the canvas, which is precisely the wrapping the brief asks for.
        _text_boxes(el, dx, dy, font, texts)
    elif tag == "circle":
        cx, cy, r = _number(el, "cx") + dx, _number(el, "cy") + dy, _number(el, "r")
        if r:
            shapes.append(Box(cx - r, cy - r, cx + r, cy + r, "circle"))
    elif tag == "ellipse":
        cx, cy = _number(el, "cx") + dx, _number(el, "cy") + dy
        rx, ry = _number(el, "rx"), _number(el, "ry")
        if rx and ry:
            shapes.append(Box(cx - rx, cy - ry, cx + rx, cy + ry, "ellipse"))
    elif tag == "rect":
        x, y = _number(el, "x") + dx, _number(el, "y") + dy
        w, h = _number(el, "width"), _number(el, "height")
        if w and h:
            shapes.append(Box(x, y, x + w, y + h, "rect"))
    elif tag == "line":
        x1, y1 = _number(el, "x1") + dx, _number(el, "y1") + dy
        x2, y2 = _number(el, "x2") + dx, _number(el, "y2") + dy
        shapes.append(Box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2), "line"))
    elif tag in ("path", "polyline", "polygon"):
        points = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?",
                                               el.get("d") or el.get("points") or "")]
        xs, ys = points[0::2], points[1::2]
        if xs and ys:
            shapes.append(Box(min(xs) + dx, min(ys) + dy,
                              max(xs) + dx, max(ys) + dy, tag))

    for child in el:
        _walk(child, dx, dy, font, texts, shapes, unmeasurable)


def measure(svg: str) -> Fit:
    """Read the geometry of a drawn SVG against the column it has to fit.

    A finding is a sentence the drawing step can be handed back verbatim, so a
    redraw is told what was wrong rather than asked to try again.
    """
    fit = Fit()
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        fit.findings.append(f"It does not parse as XML: {exc}.")
        return fit

    view_box = [float(n) for n in re.findall(r"-?[\d.]+", root.get("viewBox") or "")]
    if len(view_box) != 4 or not view_box[2] or not view_box[3]:
        fit.findings.append(
            "It has no usable viewBox, so the page cannot scale it into the "
            "85mm column. Give it viewBox=\"0 0 340 200\".")
        return fit
    _, _, width, height = view_box
    fit.aspect = width / height

    if root.get("width") and not str(root.get("width")).endswith("%"):
        fit.findings.append(
            f"It fixes width=\"{root.get('width')}\". A fixed width overrides "
            f"the column. Set only the viewBox.")

    texts: list[tuple[Box, float, str]] = []
    shapes: list[Box] = []
    unmeasurable: list[str] = []
    _walk(root, 0.0, 0.0, 16.0, texts, shapes, unmeasurable)
    fit.texts = len(texts)

    low, high = ASPECT_RANGE
    if not low <= fit.aspect <= high:
        drawn_mm = COLUMN_MM / fit.aspect
        fit.findings.append(
            f"Its viewBox is {width:.0f}×{height:.0f} — {fit.aspect:.2f}:1. In "
            f"the 85mm column that renders {drawn_mm:.0f}mm tall where the page "
            f"reserves {PLATE_MM:.0f}mm, so the column reflows around it. Use "
            f"{IDEAL_ASPECT:.2f}:1 — viewBox=\"0 0 340 200\".")

    # Legibility. font-size is in viewBox units, and the viewBox is squeezed
    # into 85mm, so a label's real size is font/width × 85mm.
    if texts:
        smallest, worst = min((font, body) for _, font, body in texts)
        fit.smallest_font_fraction = smallest / width
        if fit.smallest_font_fraction < MIN_FONT_FRACTION:
            on_page = smallest / width * COLUMN_MM
            need = MIN_FONT_FRACTION * width
            fit.findings.append(
                f"Its smallest label is font-size {smallest:.0f} in a {width:.0f}-"
                f"wide viewBox, which prints at {on_page:.1f}mm — smaller than "
                f"the caption beside it. Nothing may be under font-size "
                f"{need:.0f}. (\"{worst[:40]}\")")

    # Overflow, and the empty half of the canvas.
    boxes = shapes + [box for box, _, _ in texts]
    if boxes:
        x0 = min(b.x0 for b in boxes); x1 = max(b.x1 for b in boxes)
        y0 = min(b.y0 for b in boxes); y1 = max(b.y1 for b in boxes)
        if x1 > width + 1 or y1 > height + 1 or x0 < -1 or y0 < -1:
            fit.findings.append(
                f"Content runs from ({x0:.0f},{y0:.0f}) to ({x1:.0f},{y1:.0f}), "
                f"outside the {width:.0f}×{height:.0f} viewBox. Everything "
                f"outside is clipped away on the page.")
        elif (x1 - x0) / width < MIN_FILL or (y1 - y0) / height < MIN_FILL:
            fit.findings.append(
                f"The drawing fills {(x1-x0)/width*100:.0f}% of the width and "
                f"{(y1-y0)/height*100:.0f}% of the height; the rest is blank. "
                f"Scaled into 85mm that empty margin is what shrinks the "
                f"drawing. Spread it across the whole viewBox.")

    # The fault that made the first drawing unreadable.
    #
    # Not every intersection is one. A label sitting INSIDE a panel — a titled
    # box, a tinted region — is how every atlas and every textbook sets a
    # label, and rejecting it would reject the good drawings along with the
    # bad. What is unreadable is a label crossing an EDGE, or lying over
    # line-work. So containment in a fillable region is allowed, unless that
    # region is the whole canvas: a background rectangle absolving everything
    # drawn on top of it is the one thing this must not do.
    canvas = width * height
    panels = [s for s in shapes
              if s.what in ("rect", "circle", "ellipse") and s.area < canvas * 0.9]
    collided: list[str] = []
    for box, _, body in texts:
        if any(box.inside(panel) for panel in panels):
            # Still not licence to sit on the line-work inside that panel.
            if not any(box.hits(s) for s in shapes
                       if s.what in ("line", "path", "polyline", "polygon")):
                continue
        for other in shapes:
            if box.hits(other) and not box.inside(other):
                collided.append(body[:34])
                break
            if box.hits(other) and other.what in ("line", "path", "polyline",
                                                  "polygon"):
                collided.append(body[:34])
                break
    for i, (box, _, body) in enumerate(texts):
        if body[:34] in collided:
            continue
        for other_box, _, _ in texts[i + 1:]:
            if box.hits(other_box):
                collided.append(body[:34])
                break
    fit.collisions = len(collided)
    if collided:
        named = "; ".join(f'"{c}"' for c in collided[:3])
        fit.findings.append(
            f"{len(collided)} of {len(texts)} labels sit on top of a shape or "
            f"another label — {named}. Text over line-work is unreadable at "
            f"85mm. Move each label into clear space and point at its part "
            f"with a leader line.")

    if not texts and shapes:
        fit.findings.append("It has no <text> at all, so nothing in it is labelled.")
    if unmeasurable:
        fit.findings.append(
            f"It positions parts with {unmeasurable[0]}…, which this check "
            f"cannot measure. Place parts at plain coordinates, or with "
            f"translate() only, so the layout can be verified.")
    return fit


def corrections(fit: Fit) -> str:
    """The findings as an instruction to hand back for a redraw."""
    if fit.ok:
        return ""
    return ("\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Every one of these was "
            "measured on the drawing you returned; fix all of them:\n"
            + "\n".join(f"  {i}. {f}" for i, f in enumerate(fit.findings, 1)))


# A label and the sentence explaining it, joined by a dash. Every failing
# drawing this station has produced has had them: "Addition — combines two
# integers", "-10 — represents the smallest value shown", "Negative Integers —
# indicates numbers less than zero". The head is the label; the tail is the
# part's FUNCTION, which the plan already carries and the book already prints
# in the caption. On the drawing it is what overflows the canvas and lies
# across the neighbouring label.
_EXPLAINED = re.compile(
    r"^\s*(?P<head>.{1,24}?)\s*[—–-]{1,2}\s+(?P<tail>\S+(?:\s+\S+){2,})\s*$")

# `<text>` and `<tspan>` holding nothing but words — no nested markup to lose.
_LEAF_TEXT = re.compile(r"(<(text|tspan)\b[^>]*>)([^<>]*)(</\2>)")


def trim_labels(svg: str) -> tuple[str, list[str]]:
    """Cut the explanation off each label, keeping the label.

    Told three times over that a label names a part and does not define it,
    the model writes the definition anyway. Asking again is not a strategy:
    the description belongs in the caption, so it is simply removed from the
    drawing, and what is left is the name a question can point at.

    Nothing else is touched — the match is applied to the text of leaf
    elements only, in place, so no attribute, path or namespace is rewritten.
    """
    trimmed: list[str] = []

    def cut(match: re.Match[str]) -> str:
        body = match.group(3)
        found = _EXPLAINED.match(body)
        if not found:
            return match.group(0)
        head = found.group("head").strip(" :;,")
        if not head:
            return match.group(0)
        trimmed.append(" ".join(body.split()))
        return f"{match.group(1)}{head}{match.group(4)}"

    return _LEAF_TEXT.sub(cut, svg), trimmed


_FONT_ATTR = re.compile(r'font-size\s*=\s*"(\d+(?:\.\d+)?)"')


def enlarge_labels(svg: str, view_width: float) -> tuple[str, int]:
    """Raise anything under the legible floor up to it.

    Only ever makes text bigger, so it cannot push a label off the canvas it
    already fitted — but it can make two labels touch, which is why the caller
    measures the result rather than trusting it.
    """
    floor = MIN_FONT_FRACTION * view_width
    raised = 0

    def up(match: re.Match[str]) -> str:
        size = float(match.group(1))
        if size >= floor:
            return match.group(0)
        nonlocal raised
        raised += 1
        return f'font-size="{floor:.0f}"'

    return _FONT_ATTR.sub(up, svg), raised


def repair(svg: str) -> tuple[str, list[str]]:
    """Fix mechanically what the model would not fix when asked.

    Three attempts, each told exactly what was measured on the last, and the
    labels still came back as "-10 — represents the smallest value shown"
    lying across their neighbours. At that point asking a fourth time is not a
    strategy. Both repairs are safe and reversible in the sense that matters:
    each is measured, and one is kept only if the drawing reads better with it
    than without.
    """
    best, notes = svg, []
    score = len(measure(svg).findings)
    if not score:
        return svg, notes

    trimmed, cut = trim_labels(svg)
    if cut and len(measure(trimmed).findings) <= score:
        best, score = trimmed, len(measure(trimmed).findings)
        notes.append(f"Cut the explanation off {len(cut)} label(s); the caption "
                     f"carries it.")

    view = [float(n) for n in re.findall(r"-?[\d.]+",
                                         re.search(r'viewBox\s*=\s*"([^"]*)"', best).group(1))] \
        if re.search(r'viewBox\s*=\s*"([^"]*)"', best) else []
    if len(view) == 4 and view[2]:
        bigger, raised = enlarge_labels(best, view[2])
        if raised and len(measure(bigger).findings) <= score:
            best = bigger
            notes.append(f"Raised {raised} label(s) to the legible floor.")
    return best, notes

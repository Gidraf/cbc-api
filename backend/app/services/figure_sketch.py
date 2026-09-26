"""The figure a question needs, drawn from the data the question gives.

Half of a KPSEA Mathematics paper is set on figures — a triangle with its
sides marked, a bar graph of rainfall, a clock face, a number line, a
shaded fraction — and none of those is a lesson diagram. They belong to
the question: the triangle's sides are the question's own numbers, and a
question about a different triangle needs a different figure. The
diagram station draws what the teacher's guide asked for; the question
writer had no way to draw at all, so "study the figure below" was written
above nothing, or was never written.

This draws them, deterministically, from data the writer attaches to the
item as `figure`. The writer decides the numbers; the renderer decides the
geometry, so the 8 cm side is longer than the 5 cm side and the 40% slice
is 144 degrees. Every label is a `<text>` the scene builder can address,
so "the length marked x" is a part the marking scheme knows.

Kinds:
  number_line   {"min", "max", "step", "marks": [{"value", "label"}], "arrow_from", "arrow_to"}
  bar_chart     {"title", "categories", "values", "x_label", "y_label", "unit"}
  pie_chart     {"title", "slices": [{"label", "value"}], "show": "percent|value|none"}
  line_graph    {"title", "x_label", "y_label", "points": [[x, y], ...]}
  table         {"title", "columns", "rows"}
  clock         {"hour", "minute"}
  thermometer   {"min", "max", "reading", "unit"}
  shape         {"shape": "rectangle|square|triangle|right_triangle|circle|parallelogram|trapezium",
                 "dimensions": {"length", "width", "base", "height", "side", "radius", "top", "bottom"},
                 "labels": {"vertices": ["A","B","C"]}, "unit", "shaded": true, "angle_marks": ...}
  fraction      {"parts", "shaded", "form": "bar|circle"}
  angle         {"degrees", "label"}
  atom          {"element", "protons", "neutrons" | "mass_number", "electrons", "show_counts"}
  circuit       {"source": [...], "branches": [[...], ...], "voltmeters": [{"across", "label"}]}
  flow          {"nodes", "layout": "chain|cycle", "edge_labels"}  (also food_chain, cycle)
  population_pyramid {"age_groups", "male", "female", "unit"}
  map           {"extent", "title", "features"}: drawn by map_sketch from its gazetteer
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger("cbc-figure-sketch")

W, H = 480, 300
_FONT = "font-family='Helvetica, Arial, sans-serif'"


def _esc(text: Any) -> str:
    return (str(text if text is not None else "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _text(x: float, y: float, s: Any, *, size: float = 12, anchor: str = "middle",
          weight: str = "normal", fill: str = "#111", rotate: float = 0) -> str:
    rot = f" transform='rotate({rotate} {x:.1f} {y:.1f})'" if rotate else ""
    return (f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' text-anchor='{anchor}' "
            f"font-weight='{weight}' fill='{fill}' {_FONT}{rot}>{_esc(s)}</text>")


def _svg(body: str, title: str, width: float = W, height: float = H) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width:.0f} {height:.0f}' role='img' "
            f"aria-label='{_esc(title)}'><rect width='{width:.0f}' height='{height:.0f}' fill='#fff'/>{body}</svg>")


# ── kinds ──────────────────────────────────────────────────────────────────

def _number_line(f: dict[str, Any]) -> tuple[str, str]:
    lo, hi = _num(f.get("min"), -10), _num(f.get("max"), 10)
    if hi <= lo:
        lo, hi = -10, 10
    step = _num(f.get("step"), 1) or 1
    x0, x1, y = 40, W - 40, 120
    scale = (x1 - x0) / (hi - lo)
    px = lambda v: x0 + (v - lo) * scale  # noqa: E731
    out = [f"<line x1='{x0 - 20}' y1='{y}' x2='{x1 + 20}' y2='{y}' stroke='#111' stroke-width='2' "
           f"marker-end='url(#ah)' marker-start='url(#ah2)'/>",
           "<defs><marker id='ah' markerWidth='8' markerHeight='8' refX='6' refY='4' orient='auto'>"
           "<path d='M0,0 L8,4 L0,8 z' fill='#111'/></marker>"
           "<marker id='ah2' markerWidth='8' markerHeight='8' refX='2' refY='4' orient='auto-start-reverse'>"
           "<path d='M0,0 L8,4 L0,8 z' fill='#111'/></marker></defs>"]
    v = lo
    while v <= hi + 1e-9:
        x = px(v)
        out.append(f"<line x1='{x:.1f}' y1='{y - 7}' x2='{x:.1f}' y2='{y + 7}' stroke='#111' stroke-width='1.5'/>")
        out.append(_text(x, y + 24, _fmt(v), size=11))
        v += step
    for mark in f.get("marks") or []:
        if not isinstance(mark, dict):
            continue
        x = px(_num(mark.get("value")))
        out.append(f"<circle cx='{x:.1f}' cy='{y}' r='5' fill='#c0392b'/>")
        if mark.get("label"):
            out.append(_text(x, y - 16, mark["label"], size=13, weight="bold"))
    if f.get("arrow_from") is not None and f.get("arrow_to") is not None:
        a, b = px(_num(f["arrow_from"])), px(_num(f["arrow_to"]))
        out.append(f"<path d='M{a:.1f},{y - 30} Q{(a + b) / 2:.1f},{y - 70} {b:.1f},{y - 30}' fill='none' "
                   f"stroke='#2f6fb0' stroke-width='2' marker-end='url(#ah)'/>")
    return _svg("".join(out), f.get("title") or "Number line", W, 180), str(f.get("title") or "Number line")


def _bar_chart(f: dict[str, Any]) -> tuple[str, str]:
    cats = [str(c) for c in (f.get("categories") or [])]
    vals = [_num(v) for v in (f.get("values") or [])]
    n = min(len(cats), len(vals))
    cats, vals = cats[:n], vals[:n]
    if not n:
        raise ValueError("a bar chart needs categories and values")
    top = max(vals + [1])
    nice = 10 ** math.floor(math.log10(top)) if top > 0 else 1
    ymax = math.ceil(top / nice) * nice
    steps = 5
    left, right, bottom, topy = 70, W - 20, H - 50, 40
    out = [_text(W / 2, 22, f.get("title") or "", size=13, weight="bold")]
    out.append(f"<line x1='{left}' y1='{topy}' x2='{left}' y2='{bottom}' stroke='#111' stroke-width='1.5'/>")
    out.append(f"<line x1='{left}' y1='{bottom}' x2='{right}' y2='{bottom}' stroke='#111' stroke-width='1.5'/>")
    for i in range(steps + 1):
        v = ymax * i / steps
        y = bottom - (bottom - topy) * i / steps
        out.append(f"<line x1='{left - 4}' y1='{y:.1f}' x2='{right}' y2='{y:.1f}' stroke='#ddd' stroke-width='0.6'/>")
        out.append(_text(left - 8, y + 4, _fmt(v), size=10, anchor="end"))
    slot = (right - left) / n
    for i, (c, v) in enumerate(zip(cats, vals)):
        bw = slot * 0.6
        x = left + slot * i + (slot - bw) / 2
        h = (bottom - topy) * (v / ymax if ymax else 0)
        out.append(f"<rect x='{x:.1f}' y='{bottom - h:.1f}' width='{bw:.1f}' height='{h:.1f}' fill='#7f9cc4' stroke='#1f3b63'/>")
        out.append(_text(x + bw / 2, bottom + 16, c, size=10))
    out.append(_text((left + right) / 2, H - 8, f.get("x_label") or "", size=10))
    ylab = str(f.get("y_label") or "") + (f" ({f['unit']})" if f.get("unit") else "")
    out.append(_text(18, (topy + bottom) / 2, ylab, size=10, rotate=-90))
    return _svg("".join(out), f.get("title") or "Bar chart"), str(f.get("title") or "Bar chart")


def _pie_chart(f: dict[str, Any]) -> tuple[str, str]:
    slices = [(str(s.get("label") or ""), _num(s.get("value"))) for s in (f.get("slices") or []) if isinstance(s, dict)]
    slices = [s for s in slices if s[1] > 0]
    if not slices:
        raise ValueError("a pie chart needs slices")
    total = sum(v for _, v in slices)
    cx, cy, r = 170, 160, 110
    fills = ["#7f9cc4", "#e6b85c", "#8fbf8f", "#d98a8a", "#b39ddb", "#a0a0a0", "#f0c27f", "#88c9d0"]
    out = [_text(W / 2, 22, f.get("title") or "", size=13, weight="bold")]
    angle = -math.pi / 2
    show = str(f.get("show") or "percent")
    for i, (label, v) in enumerate(slices):
        sweep = 2 * math.pi * v / total
        x1, y1 = cx + r * math.cos(angle), cy + r * math.sin(angle)
        x2, y2 = cx + r * math.cos(angle + sweep), cy + r * math.sin(angle + sweep)
        large = 1 if sweep > math.pi else 0
        out.append(f"<path d='M{cx},{cy} L{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} z' "
                   f"fill='{fills[i % len(fills)]}' stroke='#111' stroke-width='1'/>")
        mid = angle + sweep / 2
        lx, ly = cx + r * 0.62 * math.cos(mid), cy + r * 0.62 * math.sin(mid)
        if show == "percent":
            out.append(_text(lx, ly + 4, f"{100 * v / total:.0f}%", size=11, weight="bold"))
        elif show == "value":
            out.append(_text(lx, ly + 4, _fmt(v), size=11, weight="bold"))
        angle += sweep
    for i, (label, v) in enumerate(slices):
        y = 70 + i * 22
        out.append(f"<rect x='320' y='{y - 11}' width='14' height='14' fill='{fills[i % len(fills)]}' stroke='#111'/>")
        out.append(_text(342, y, label, size=11, anchor="start"))
    return _svg("".join(out), f.get("title") or "Pie chart"), str(f.get("title") or "Pie chart")


def _line_graph(f: dict[str, Any]) -> tuple[str, str]:
    pts = []
    for p in f.get("points") or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            pts.append((_num(p[0]), _num(p[1])))
        elif isinstance(p, dict):
            pts.append((_num(p.get("x")), _num(p.get("y"))))
    if len(pts) < 2:
        raise ValueError("a line graph needs two or more points")
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(0.0, min(ys)), max(ys) or 1
    left, right, bottom, topy = 70, W - 20, H - 50, 40
    sx = (right - left) / ((xhi - xlo) or 1)
    sy = (bottom - topy) / ((yhi - ylo) or 1)
    px = lambda x: left + (x - xlo) * sx  # noqa: E731
    py = lambda y: bottom - (y - ylo) * sy  # noqa: E731
    out = [_text(W / 2, 22, f.get("title") or "", size=13, weight="bold"),
           f"<line x1='{left}' y1='{topy}' x2='{left}' y2='{bottom}' stroke='#111' stroke-width='1.5'/>",
           f"<line x1='{left}' y1='{bottom}' x2='{right}' y2='{bottom}' stroke='#111' stroke-width='1.5'/>"]
    for i in range(6):
        y = ylo + (yhi - ylo) * i / 5
        out.append(f"<line x1='{left - 4}' y1='{py(y):.1f}' x2='{right}' y2='{py(y):.1f}' stroke='#ddd' stroke-width='0.6'/>")
        out.append(_text(left - 8, py(y) + 4, _fmt(round(y, 2)), size=10, anchor="end"))
    for x in sorted(set(xs)):
        out.append(_text(px(x), bottom + 16, _fmt(x), size=10))
    path = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}" for i, (x, y) in enumerate(pts))
    out.append(f"<path d='{path}' fill='none' stroke='#1f3b63' stroke-width='2'/>")
    for x, y in pts:
        out.append(f"<circle cx='{px(x):.1f}' cy='{py(y):.1f}' r='3.5' fill='#1f3b63'/>")
    out.append(_text((left + right) / 2, H - 8, f.get("x_label") or "", size=10))
    out.append(_text(18, (topy + bottom) / 2, f.get("y_label") or "", size=10, rotate=-90))
    return _svg("".join(out), f.get("title") or "Line graph"), str(f.get("title") or "Line graph")


def _table(f: dict[str, Any]) -> tuple[str, str]:
    cols = [str(c) for c in (f.get("columns") or [])]
    rows = [[str(c) for c in r] for r in (f.get("rows") or []) if isinstance(r, (list, tuple))]
    if not cols or not rows:
        raise ValueError("a table needs columns and rows")
    n = len(cols)
    cw = (W - 40) / n
    rh = 26
    height = 40 + rh * (len(rows) + 1) + 16
    out = [_text(W / 2, 22, f.get("title") or "", size=13, weight="bold")]
    y = 36
    out.append(f"<rect x='20' y='{y}' width='{W - 40}' height='{rh}' fill='#e8e8e8' stroke='#111'/>")
    for i, c in enumerate(cols):
        out.append(_text(20 + cw * i + cw / 2, y + 17, c, size=11, weight="bold"))
    for r in rows:
        y += rh
        out.append(f"<rect x='20' y='{y}' width='{W - 40}' height='{rh}' fill='#fff' stroke='#111'/>")
        for i in range(n):
            out.append(_text(20 + cw * i + cw / 2, y + 17, r[i] if i < len(r) else "", size=11))
    for i in range(1, n):
        out.append(f"<line x1='{20 + cw * i:.1f}' y1='36' x2='{20 + cw * i:.1f}' y2='{y + rh}' stroke='#111'/>")
    return _svg("".join(out), f.get("title") or "Table", W, height), str(f.get("title") or "Table")


def _clock(f: dict[str, Any]) -> tuple[str, str]:
    hour, minute = int(_num(f.get("hour"), 3)) % 12, int(_num(f.get("minute"), 0)) % 60
    cx, cy, r = 150, 150, 120
    out = [f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='#fff' stroke='#111' stroke-width='3'/>"]
    for i in range(60):
        a = math.radians(i * 6 - 90)
        inner = r - (14 if i % 5 == 0 else 6)
        out.append(f"<line x1='{cx + inner * math.cos(a):.1f}' y1='{cy + inner * math.sin(a):.1f}' "
                   f"x2='{cx + (r - 2) * math.cos(a):.1f}' y2='{cy + (r - 2) * math.sin(a):.1f}' "
                   f"stroke='#111' stroke-width='{2 if i % 5 == 0 else 1}'/>")
    for n in range(1, 13):
        a = math.radians(n * 30 - 90)
        out.append(_text(cx + (r - 30) * math.cos(a), cy + (r - 30) * math.sin(a) + 5, n, size=15, weight="bold"))
    ha = math.radians((hour + minute / 60) * 30 - 90)
    ma = math.radians(minute * 6 - 90)
    out.append(f"<line x1='{cx}' y1='{cy}' x2='{cx + r * 0.55 * math.cos(ha):.1f}' y2='{cy + r * 0.55 * math.sin(ha):.1f}' stroke='#111' stroke-width='6' stroke-linecap='round'/>")
    out.append(f"<line x1='{cx}' y1='{cy}' x2='{cx + r * 0.82 * math.cos(ma):.1f}' y2='{cy + r * 0.82 * math.sin(ma):.1f}' stroke='#111' stroke-width='3.5' stroke-linecap='round'/>")
    out.append(f"<circle cx='{cx}' cy='{cy}' r='5' fill='#111'/>")
    return _svg("".join(out), "Clock", 300, 300), "Clock face"


def _thermometer(f: dict[str, Any]) -> tuple[str, str]:
    lo, hi = _num(f.get("min"), -20), _num(f.get("max"), 50)
    if hi <= lo:
        lo, hi = -20, 50
    reading = min(hi, max(lo, _num(f.get("reading"), 0)))
    unit = str(f.get("unit") or "°C")
    x, top, bottom = 120, 30, 240
    py = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)  # noqa: E731
    out = [f"<rect x='{x - 12}' y='{top - 10}' width='24' height='{bottom - top + 10}' rx='12' fill='#fff' stroke='#111' stroke-width='2'/>",
           f"<circle cx='{x}' cy='{bottom + 18}' r='22' fill='#c0392b' stroke='#111' stroke-width='2'/>",
           f"<rect x='{x - 6}' y='{py(reading):.1f}' width='12' height='{bottom + 4 - py(reading):.1f}' fill='#c0392b'/>"]
    step = 10 if hi - lo > 40 else 5
    v = math.ceil(lo / step) * step
    while v <= hi:
        y = py(v)
        out.append(f"<line x1='{x + 12}' y1='{y:.1f}' x2='{x + 24}' y2='{y:.1f}' stroke='#111' stroke-width='1.5'/>")
        out.append(_text(x + 30, y + 4, f"{_fmt(v)}", size=11, anchor="start"))
        v += step
    out.append(_text(x + 60, top - 12, unit, size=11, anchor="start"))
    return _svg("".join(out), "Thermometer", 240, 300), "Thermometer"


def _shape(f: dict[str, Any]) -> tuple[str, str]:
    kind = str(f.get("shape") or "rectangle").lower().replace("-", "_")
    d = {k: _num(v) for k, v in (f.get("dimensions") or {}).items() if isinstance(v, (int, float, str)) and str(v).strip()}
    unit = str(f.get("unit") or "cm")
    verts = [str(v) for v in ((f.get("labels") or {}).get("vertices") or [])] if isinstance(f.get("labels"), dict) else []
    fill = "#c9d7ea" if f.get("shaded") else "#fff"
    out: list[str] = []
    lab = lambda v: f"{_fmt(v)} {unit}"  # noqa: E731

    def vlabel(i: int, x: float, y: float, dx: float, dy: float) -> None:
        if i < len(verts):
            out.append(_text(x + dx, y + dy, verts[i], size=13, weight="bold"))

    if kind in ("rectangle", "square"):
        length = d.get("length") or d.get("side") or 8
        width = d.get("width") or (length if kind == "square" else 5)
        scale = min(300 / max(length, 1), 180 / max(width, 1))
        wpx, hpx = length * scale, width * scale
        x0, y0 = (W - wpx) / 2, (H - hpx) / 2
        out.append(f"<rect x='{x0:.1f}' y='{y0:.1f}' width='{wpx:.1f}' height='{hpx:.1f}' fill='{fill}' stroke='#111' stroke-width='2'/>")
        out.append(_text(x0 + wpx / 2, y0 + hpx + 20, lab(length), size=12))
        out.append(_text(x0 + wpx + 8, y0 + hpx / 2 + 4, lab(width), size=12, anchor="start"))
        for i, (x, y, dx, dy) in enumerate([(x0, y0, -12, -6), (x0 + wpx, y0, 12, -6), (x0 + wpx, y0 + hpx, 12, 16), (x0, y0 + hpx, -12, 16)]):
            vlabel(i, x, y, dx, dy)
    elif kind in ("triangle", "right_triangle"):
        base = d.get("base") or 8
        height = d.get("height") or 6
        scale = min(300 / base, 200 / height)
        bpx, hpx = base * scale, height * scale
        x0, y0 = (W - bpx) / 2, (H + hpx) / 2
        apex_x = x0 if kind == "right_triangle" else x0 + bpx / 2
        out.append(f"<polygon points='{x0:.1f},{y0:.1f} {x0 + bpx:.1f},{y0:.1f} {apex_x:.1f},{y0 - hpx:.1f}' fill='{fill}' stroke='#111' stroke-width='2'/>")
        out.append(_text(x0 + bpx / 2, y0 + 20, lab(base), size=12))
        if kind == "right_triangle":
            out.append(f"<polyline points='{x0 + 14:.1f},{y0:.1f} {x0 + 14:.1f},{y0 - 14:.1f} {x0:.1f},{y0 - 14:.1f}' fill='none' stroke='#111' stroke-width='1.2'/>")
            out.append(_text(x0 - 8, y0 - hpx / 2 + 4, lab(height), size=12, anchor="end"))
        else:
            out.append(f"<line x1='{apex_x:.1f}' y1='{y0 - hpx:.1f}' x2='{apex_x:.1f}' y2='{y0:.1f}' stroke='#555' stroke-width='1' stroke-dasharray='4 3'/>")
            out.append(_text(apex_x + 6, y0 - hpx / 2 + 4, lab(height), size=12, anchor="start"))
        if d.get("hypotenuse") or d.get("side"):
            out.append(_text(x0 + bpx * 0.78, y0 - hpx * 0.55, lab(d.get("hypotenuse") or d.get("side")), size=12, anchor="start"))
        for i, (x, y, dx, dy) in enumerate([(x0, y0, -12, 16), (x0 + bpx, y0, 12, 16), (apex_x, y0 - hpx, 0, -8)]):
            vlabel(i, x, y, dx, dy)
    elif kind == "circle":
        radius = d.get("radius") or (d.get("diameter") / 2 if d.get("diameter") else 7)
        r = 110
        cx, cy = W / 2, H / 2
        out.append(f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='{fill}' stroke='#111' stroke-width='2'/>")
        out.append(f"<circle cx='{cx}' cy='{cy}' r='3' fill='#111'/>")
        if d.get("diameter"):
            out.append(f"<line x1='{cx - r}' y1='{cy}' x2='{cx + r}' y2='{cy}' stroke='#111' stroke-width='1.5'/>")
            out.append(_text(cx, cy - 8, lab(d["diameter"]), size=12))
        else:
            out.append(f"<line x1='{cx}' y1='{cy}' x2='{cx + r}' y2='{cy}' stroke='#111' stroke-width='1.5'/>")
            out.append(_text(cx + r / 2, cy - 8, lab(radius), size=12))
    elif kind in ("parallelogram", "trapezium", "trapezoid"):
        bottom = d.get("bottom") or d.get("base") or 10
        top = d.get("top") or (bottom if kind == "parallelogram" else 6)
        height = d.get("height") or 5
        scale = min(280 / max(bottom, top), 180 / height)
        bpx, tpx, hpx = bottom * scale, top * scale, height * scale
        x0, y0 = (W - bpx) / 2, (H + hpx) / 2
        off = 50 if kind == "parallelogram" else (bpx - tpx) / 2
        out.append(f"<polygon points='{x0:.1f},{y0:.1f} {x0 + bpx:.1f},{y0:.1f} {x0 + off + tpx:.1f},{y0 - hpx:.1f} {x0 + off:.1f},{y0 - hpx:.1f}' fill='{fill}' stroke='#111' stroke-width='2'/>")
        out.append(_text(x0 + bpx / 2, y0 + 20, lab(bottom), size=12))
        out.append(_text(x0 + off + tpx / 2, y0 - hpx - 8, lab(top), size=12))
        hx = x0 + off + 20
        out.append(f"<line x1='{hx:.1f}' y1='{y0 - hpx:.1f}' x2='{hx:.1f}' y2='{y0:.1f}' stroke='#555' stroke-width='1' stroke-dasharray='4 3'/>")
        out.append(_text(hx + 6, y0 - hpx / 2 + 4, lab(height), size=12, anchor="start"))
    else:
        raise ValueError(f"unknown shape {kind}")
    title = str(f.get("title") or kind.replace("_", " ").title())
    return _svg("".join(out), title), title


def _fraction(f: dict[str, Any]) -> tuple[str, str]:
    parts = max(1, int(_num(f.get("parts"), 4)))
    shaded = max(0, min(parts, int(_num(f.get("shaded"), 1))))
    form = str(f.get("form") or "bar")
    out: list[str] = []
    if form == "circle":
        cx, cy, r = 150, 150, 110
        for i in range(parts):
            a0, a1 = math.radians(360 * i / parts - 90), math.radians(360 * (i + 1) / parts - 90)
            large = 1 if (a1 - a0) > math.pi else 0
            out.append(f"<path d='M{cx},{cy} L{cx + r * math.cos(a0):.1f},{cy + r * math.sin(a0):.1f} "
                       f"A{r},{r} 0 {large} 1 {cx + r * math.cos(a1):.1f},{cy + r * math.sin(a1):.1f} z' "
                       f"fill='{'#7f9cc4' if i < shaded else '#fff'}' stroke='#111' stroke-width='1.5'/>")
        return _svg("".join(out), "Fraction", 300, 300), f"{shaded}/{parts} shaded"
    x0, y0, wpx, hpx = 30, 100, W - 60, 70
    cw = wpx / parts
    for i in range(parts):
        out.append(f"<rect x='{x0 + cw * i:.1f}' y='{y0}' width='{cw:.1f}' height='{hpx}' "
                   f"fill='{'#7f9cc4' if i < shaded else '#fff'}' stroke='#111' stroke-width='1.5'/>")
    return _svg("".join(out), "Fraction", W, 270), f"{shaded}/{parts} shaded"


def _angle(f: dict[str, Any]) -> tuple[str, str]:
    deg = _num(f.get("degrees"), 60) % 360
    label = str(f.get("label") or "")
    cx, cy, r = 120, 200, 150
    a = math.radians(-deg)
    out = [f"<line x1='{cx}' y1='{cy}' x2='{cx + r}' y2='{cy}' stroke='#111' stroke-width='2'/>",
           f"<line x1='{cx}' y1='{cy}' x2='{cx + r * math.cos(a):.1f}' y2='{cy + r * math.sin(a):.1f}' stroke='#111' stroke-width='2'/>",
           f"<path d='M{cx + 40},{cy} A40,40 0 {1 if deg > 180 else 0} 0 {cx + 40 * math.cos(a):.1f},{cy + 40 * math.sin(a):.1f}' fill='none' stroke='#c0392b' stroke-width='2'/>"]
    mid = math.radians(-deg / 2)
    out.append(_text(cx + 58 * math.cos(mid), cy + 58 * math.sin(mid) + 4, label or f"{_fmt(deg)}°", size=13, weight="bold"))
    return _svg("".join(out), "Angle", 320, 260), "Angle"


def _emoji(f: dict[str, Any]) -> tuple[str, str]:
    """Groups of things to count, compare or share — drawn as large glyphs.

    Lower primary counts mangoes and chickens; a photograph of eleven
    mangoes does not exist and a drawn mango is a blob. The system's own
    emoji font prints the same on every page. `items`: [{"glyph": "🥭",
    "count": 7, "label": "mangoes"}, …]; `per_row` optional."""
    items = [i for i in (f.get("items") or []) if isinstance(i, dict) and i.get("glyph")]
    if not items:
        raise ValueError("an emoji figure needs items with a glyph")
    per_row = max(1, min(12, int(_num(f.get("per_row"), 6))))
    size = 34
    gap = 6
    out: list[str] = []
    y = 20
    for item in items[:6]:
        glyph = str(item.get("glyph"))[:4]
        count = max(1, min(60, int(_num(item.get("count"), 1))))
        label = str(item.get("label") or "")
        if label:
            out.append(_text(12, y + 14, label, size=13, anchor="start", weight="bold"))
            y += 22
        for n in range(count):
            row, col = divmod(n, per_row)
            out.append(f"<text x='{12 + col * (size + gap)}' y='{y + size + row * (size + gap)}' "
                       f"font-size='{size}'>{_esc(glyph)}</text>")
        y += ((count - 1) // per_row + 1) * (size + gap) + 12
    width = max(W, 12 + per_row * (size + gap) + 12)
    title = str(f.get("title") or ", ".join(f"{i.get('count', 1)} {i.get('label') or i.get('glyph')}" for i in items[:3]))
    return _svg("".join(out), title, width=width, height=max(120, y + 10)), title


def _image(f: dict[str, Any]) -> tuple[str, str]:
    """A photograph from Wikimedia Commons, credited. `query` names it:
    {"kind": "image", "query": "maize plant Kenya farm"}. Fetched once and
    filed; a query with nothing reusable fails like any figure that will
    not draw, and the item goes on without it."""
    from . import open_images, platform_settings

    if not platform_settings.get("open_images_enabled", True):
        raise ValueError("open images are switched off in Settings")
    query = str(f.get("query") or f.get("title") or "").strip()
    if not query:
        raise ValueError("an image figure needs a query")
    got = open_images.fetch(query)
    if not got:
        raise ValueError(f"no reusable photograph on Commons for {query!r}")
    f["_credit"] = got["credit"]
    f["_source"] = got["source"]
    return got["svg"], str(f.get("title") or query)


# ── subject figures ────────────────────────────────────────────────────────
#
# The kinds above are a Mathematics paper's. A science or Social Studies item
# had only "table" and "photo" to choose from, so 62 of the bank's 89 figures
# were tables — whichever model wrote them. These draw what those papers set:
# the writer gives the facts, the geometry is computed, so an atom drawn from
# 16 protons can only show 2.8.6.

_ARROW = ("<defs><marker id='arrow' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' "
          "markerHeight='7' orient='auto-start-reverse'><path d='M0,0 L10,5 L0,10 z' fill='#111'/>"
          "</marker></defs>")

_ELEMENTS = ("H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca").split()


def shells_for(electrons: int) -> list[int]:
    """The arrangement taught for the first twenty elements: 2, 8, 8, then 2."""
    if not 1 <= electrons <= 20:
        raise ValueError("an atom figure covers 1 to 20 electrons, the elements this level teaches")
    out, left = [], electrons
    for cap in (2, 8, 8, 2):
        take = min(cap, left)
        if take:
            out.append(take)
        left -= take
    return out


def _atom(f: dict[str, Any]) -> tuple[str, str]:
    """{"protons", "neutrons", "electrons" (default: protons), "element",
    "symbol", "show_counts": true, "show_arrangement": false}"""
    protons = int(_num(f.get("protons") or f.get("atomic_number")))
    if not 1 <= protons <= 20:
        raise ValueError("an atom figure needs 1 to 20 protons")
    neutrons = f.get("neutrons")
    if neutrons is None and f.get("mass_number") is not None:
        neutrons = int(_num(f.get("mass_number"))) - protons
    neutrons = int(_num(neutrons, -1))
    if neutrons < 0:
        raise ValueError("an atom figure needs neutrons or a mass number at least the atomic number")
    electrons = int(_num(f.get("electrons"), protons))
    shells = shells_for(electrons)
    symbol = str(f.get("symbol") or _ELEMENTS[protons - 1])
    charge = protons - electrons
    ion = "" if charge == 0 else f"{abs(charge) if abs(charge) > 1 else ''}{'+' if charge > 0 else '−'}"
    name = str(f.get("element") or symbol)
    title = str(f.get("title") or (f"{name} ion, {symbol}{ion}" if ion else f"{name} atom"))

    cx, cy = 200, 165
    out = [_text(W / 2, 22, title, size=13, weight="bold")]
    for n, count in enumerate(shells, start=1):
        r = 38 + n * 30
        out.append(f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='none' stroke='#555' stroke-width='1.2'/>")
        for i in range(count):
            a = math.radians(-90 + 360 * i / count + (n * 17))
            ex, ey = cx + r * math.cos(a), cy + r * math.sin(a)
            out.append(f"<circle cx='{ex:.1f}' cy='{ey:.1f}' r='5' fill='#1f5fa8' stroke='#0d2f55'/>")
    out.append(f"<circle cx='{cx}' cy='{cy}' r='34' fill='#f3d9b1' stroke='#8a5a1a' stroke-width='1.5'/>")
    if f.get("show_counts", True):
        out.append(_text(cx, cy - 4, f"{protons}p", size=13, weight="bold"))
        out.append(_text(cx, cy + 13, f"{neutrons}n", size=13, weight="bold"))
    else:
        out.append(_text(cx, cy + 5, "nucleus", size=11))
    # A key, so the dots and the nucleus are read, not guessed.
    kx = 370
    out.append(f"<circle cx='{kx}' cy='120' r='5' fill='#1f5fa8' stroke='#0d2f55'/>")
    out.append(_text(kx + 12, 124, "electron", size=11, anchor="start"))
    out.append(f"<circle cx='{kx}' cy='145' r='7' fill='#f3d9b1' stroke='#8a5a1a'/>")
    out.append(_text(kx + 12, 149, "nucleus", size=11, anchor="start"))
    if f.get("show_counts", True):
        out.append(_text(kx - 6, 172, "p = proton", size=11, anchor="start"))
        out.append(_text(kx - 6, 188, "n = neutron", size=11, anchor="start"))
    if f.get("show_arrangement"):
        out.append(_text(kx - 6, 214, "Arrangement: " + ".".join(map(str, shells)), size=11, anchor="start"))
    return _svg("".join(out), title, W, 330), title


# Circuit symbols, drawn in a slot of width 50 centred on (x, y) on a
# horizontal wire. Each returns the SVG; the wire is broken around the slot.
def _sym_cell(x: float, y: float, n: int = 1) -> str:
    out = []
    start = x - 8 * n + 4
    for i in range(n):
        px = start + i * 16
        out.append(f"<line x1='{px - 4:.1f}' y1='{y - 16}' x2='{px - 4:.1f}' y2='{y + 16}' stroke='#111' stroke-width='2'/>")
        out.append(f"<line x1='{px + 4:.1f}' y1='{y - 8}' x2='{px + 4:.1f}' y2='{y + 8}' stroke='#111' stroke-width='4'/>")
    left, right = start - 4, start + (n - 1) * 16 + 4
    out.append(f"<line x1='{x - 25}' y1='{y}' x2='{left:.1f}' y2='{y}' stroke='#111' stroke-width='2'/>")
    out.append(f"<line x1='{right:.1f}' y1='{y}' x2='{x + 25}' y2='{y}' stroke='#111' stroke-width='2'/>")
    out.append(_text(left - 4, y - 20, "+", size=12, weight="bold"))
    return "".join(out)


def _sym_bulb(x: float, y: float) -> str:
    d = 9
    return (f"<line x1='{x - 25}' y1='{y}' x2='{x - 13}' y2='{y}' stroke='#111' stroke-width='2'/>"
            f"<line x1='{x + 13}' y1='{y}' x2='{x + 25}' y2='{y}' stroke='#111' stroke-width='2'/>"
            f"<circle cx='{x}' cy='{y}' r='13' fill='#fff' stroke='#111' stroke-width='2'/>"
            f"<line x1='{x - d}' y1='{y - d}' x2='{x + d}' y2='{y + d}' stroke='#111' stroke-width='1.6'/>"
            f"<line x1='{x - d}' y1='{y + d}' x2='{x + d}' y2='{y - d}' stroke='#111' stroke-width='1.6'/>")


def _sym_switch(x: float, y: float, closed: bool) -> str:
    end = f"x2='{x + 14}' y2='{y}'" if closed else f"x2='{x + 12}' y2='{y - 16}'"
    return (f"<line x1='{x - 25}' y1='{y}' x2='{x - 14}' y2='{y}' stroke='#111' stroke-width='2'/>"
            f"<circle cx='{x - 14}' cy='{y}' r='3' fill='#111'/>"
            f"<line x1='{x - 14}' y1='{y}' {end} stroke='#111' stroke-width='2'/>"
            f"<circle cx='{x + 14}' cy='{y}' r='3' fill='#111'/>"
            f"<line x1='{x + 14}' y1='{y}' x2='{x + 25}' y2='{y}' stroke='#111' stroke-width='2'/>")


def _sym_resistor(x: float, y: float) -> str:
    return (f"<line x1='{x - 25}' y1='{y}' x2='{x - 16}' y2='{y}' stroke='#111' stroke-width='2'/>"
            f"<rect x='{x - 16}' y='{y - 7}' width='32' height='14' fill='#fff' stroke='#111' stroke-width='2'/>"
            f"<line x1='{x + 16}' y1='{y}' x2='{x + 25}' y2='{y}' stroke='#111' stroke-width='2'/>")


def _sym_meter(x: float, y: float, letter: str) -> str:
    return (f"<line x1='{x - 25}' y1='{y}' x2='{x - 13}' y2='{y}' stroke='#111' stroke-width='2'/>"
            f"<line x1='{x + 13}' y1='{y}' x2='{x + 25}' y2='{y}' stroke='#111' stroke-width='2'/>"
            f"<circle cx='{x}' cy='{y}' r='13' fill='#fff' stroke='#111' stroke-width='2'/>"
            + _text(x, y + 5, letter, size=13, weight="bold"))


_COMPONENTS = ("cell", "battery", "bulb", "lamp", "switch", "resistor", "ammeter")


def _component(c: dict[str, Any], x: float, y: float) -> str:
    kind = str(c.get("kind") or "").lower()
    if kind == "cell":
        return _sym_cell(x, y, 1)
    if kind == "battery":
        return _sym_cell(x, y, max(2, min(3, int(_num(c.get("cells"), 2)))))
    if kind in ("bulb", "lamp"):
        return _sym_bulb(x, y)
    if kind == "switch":
        return _sym_switch(x, y, str(c.get("state") or "closed").lower() == "closed")
    if kind == "resistor":
        return _sym_resistor(x, y)
    if kind == "ammeter":
        return _sym_meter(x, y, "A")
    raise ValueError(f"a circuit component must be one of {', '.join(_COMPONENTS)}, not {kind!r}")


def _wire_with(components: list[dict[str, Any]], x0: float, x1: float, y: float,
               labels_below: bool) -> tuple[list[str], dict[str, tuple[float, float]]]:
    """A horizontal wire from x0 to x1 with the components spaced along it."""
    out: list[str] = []
    where: dict[str, tuple[float, float]] = {}
    n = len(components)
    if not n:
        return [f"<line x1='{x0}' y1='{y}' x2='{x1}' y2='{y}' stroke='#111' stroke-width='2'/>"], where
    xs = [x0 + (x1 - x0) * (i + 1) / (n + 1) for i in range(n)]
    edge = x0
    for c, x in zip(components, xs):
        out.append(f"<line x1='{edge:.1f}' y1='{y}' x2='{x - 25:.1f}' y2='{y}' stroke='#111' stroke-width='2'/>")
        out.append(_component(c, x, y))
        label = str(c.get("label") or "")
        if label:
            out.append(_text(x, y + (30 if labels_below else -22), label, size=11, weight="bold"))
            where[label] = (x, y)
        edge = x + 25
    out.append(f"<line x1='{edge:.1f}' y1='{y}' x2='{x1}' y2='{y}' stroke='#111' stroke-width='2'/>")
    return out, where


def _circuit(f: dict[str, Any]) -> tuple[str, str]:
    """{"source": [components on the supply wire], "branches": [[...], [...]],
    "voltmeters": [{"across": "L1", "label": "V1"}], "title"}

    One branch is a series circuit; two or more are parallel branches between
    the same two junctions. Components: cell, battery (cells: 2|3), bulb,
    switch (state: open|closed), resistor, ammeter. A voltmeter is drawn
    ACROSS the component it names — never in line, which is how a learner
    is taught to connect one."""
    source = [c for c in (f.get("source") or []) if isinstance(c, dict)]
    branches = [[c for c in b if isinstance(c, dict)] for b in (f.get("branches") or []) if isinstance(b, list)]
    if not branches and isinstance(f.get("components"), list):
        branches = [[c for c in f["components"] if isinstance(c, dict)]]
    if not any(str(c.get("kind")).lower() in ("cell", "battery") for c in source + sum(branches, [])):
        raise ValueError("a circuit needs a cell or a battery")
    if not branches:
        branches = [[]]
    if len(branches) > 3 or any(len(b) > 4 for b in branches) or len(source) > 4:
        raise ValueError("a circuit figure takes at most 3 branches of 4 components")
    x0, x1 = 60, 420
    gap = 78
    top = 100
    rungs = [top + i * gap for i in range(len(branches))]
    bottom = rungs[-1] + gap + 10
    title = str(f.get("title") or ("Series circuit" if len(branches) == 1 else "Parallel circuit"))
    out = [_text(W / 2, 22, title, size=13, weight="bold")]
    where: dict[str, tuple[float, float]] = {}
    for y, branch in zip(rungs, branches):
        parts, placed = _wire_with(branch, x0, x1, y, labels_below=True)
        out += parts
        where.update(placed)
    parts, placed = _wire_with(source, x0, x1, bottom, labels_below=True)
    out += parts
    where.update(placed)
    out.append(f"<line x1='{x0}' y1='{rungs[0]}' x2='{x0}' y2='{bottom}' stroke='#111' stroke-width='2'/>")
    out.append(f"<line x1='{x1}' y1='{rungs[0]}' x2='{x1}' y2='{bottom}' stroke='#111' stroke-width='2'/>")
    if len(branches) > 1:
        for y in rungs[1:]:
            out.append(f"<circle cx='{x0}' cy='{y}' r='3.5' fill='#111'/><circle cx='{x1}' cy='{y}' r='3.5' fill='#111'/>")
    for v in (f.get("voltmeters") or []):
        target = where.get(str((v or {}).get("across") or ""))
        if not target:
            raise ValueError(f"a voltmeter is drawn across a labelled component; {v!r} names none")
        x, y = target
        up = -1 if y != bottom else 1
        vy = y + up * 42
        out.append(f"<polyline points='{x - 30},{y} {x - 30},{vy} {x - 13},{vy}' fill='none' stroke='#111' stroke-width='1.6'/>")
        out.append(f"<polyline points='{x + 13},{vy} {x + 30},{vy} {x + 30},{y}' fill='none' stroke='#111' stroke-width='1.6'/>")
        out.append(f"<circle cx='{x - 30}' cy='{y}' r='3' fill='#111'/><circle cx='{x + 30}' cy='{y}' r='3' fill='#111'/>")
        out.append(f"<circle cx='{x}' cy='{vy}' r='13' fill='#fff' stroke='#111' stroke-width='2'/>" + _text(x, vy + 5, "V", size=13, weight="bold"))
        if v.get("label"):
            out.append(_text(x, vy + (-18 if up < 0 else 28), str(v["label"]), size=11, weight="bold"))
    return _svg("".join(out), title, W, bottom + 55), title


def _flow(f: dict[str, Any]) -> tuple[str, str]:
    """{"nodes": ["Grass", "Grasshopper", "Frog"], "layout": "chain|cycle",
    "edge_labels": ["eaten by", ...], "title"} — a food chain, a cycle, a
    process or a chain of causes. Arrows run from each node to the next;
    in a food chain that is the direction the energy flows."""
    nodes = [str(n) for n in (f.get("nodes") or []) if str(n).strip()]
    if not 2 <= len(nodes) <= 8:
        raise ValueError("a flow diagram needs 2 to 8 nodes")
    layout = str(f.get("layout") or ("cycle" if str(f.get("kind")).lower() == "cycle" else "chain")).lower()
    labels = [str(x) for x in (f.get("edge_labels") or [])]
    title = str(f.get("title") or ("Cycle" if layout == "cycle" else "Flow diagram"))
    out = [_ARROW, _text(W / 2, 22, title, size=13, weight="bold")]
    bw, bh = 88, 38
    centres: list[tuple[float, float]] = []
    if layout == "cycle":
        cx, cy, r = W / 2, 175, 110
        for i in range(len(nodes)):
            a = math.radians(-90 + 360 * i / len(nodes))
            centres.append((cx + r * 1.35 * math.cos(a), cy + r * 0.95 * math.sin(a)))
        height = 330
    else:
        per_row = 4
        for i in range(len(nodes)):
            row, col = divmod(i, per_row)
            col = col if row % 2 == 0 else per_row - 1 - col
            centres.append((60 + col * 120, 80 + row * 95))
        height = 80 + ((len(nodes) - 1) // per_row) * 95 + 60
    pairs = list(zip(range(len(nodes)), range(1, len(nodes))))
    if layout == "cycle":
        pairs.append((len(nodes) - 1, 0))
    for k, (i, j) in enumerate(pairs):
        (xa, ya), (xb, yb) = centres[i], centres[j]
        dx, dy = xb - xa, yb - ya
        dist = math.hypot(dx, dy) or 1
        # leave the box edge: scale to where the line crosses each box
        sa = min(bw / 2 / abs(dx) if dx else 9e9, bh / 2 / abs(dy) if dy else 9e9)
        sx, sy = xa + dx * sa + dx / dist * 3, ya + dy * sa + dy / dist * 3
        ex, ey = xb - dx * sa - dx / dist * 5, yb - dy * sa - dy / dist * 5
        out.append(f"<line x1='{sx:.1f}' y1='{sy:.1f}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='#111' "
                   f"stroke-width='1.8' marker-end='url(#arrow)'/>")
        if k < len(labels) and labels[k]:
            out.append(_text((sx + ex) / 2, (sy + ey) / 2 - 6, labels[k], size=10, fill="#444"))
    for (x, y), name in zip(centres, nodes):
        out.append(f"<rect x='{x - bw / 2:.1f}' y='{y - bh / 2:.1f}' width='{bw}' height='{bh}' rx='8' "
                   f"fill='#eef4ea' stroke='#2f6b2f' stroke-width='1.5'/>")
        words = name.split()
        if len(name) > 14 and len(words) > 1:
            half = len(words) // 2
            out.append(_text(x, y - 3, " ".join(words[:half]), size=11))
            out.append(_text(x, y + 11, " ".join(words[half:]), size=11))
        else:
            out.append(_text(x, y + 4, name, size=11))
    return _svg("".join(out), title, W, height), title


def _population_pyramid(f: dict[str, Any]) -> tuple[str, str]:
    """{"age_groups": ["0-14", "15-29", ...] youngest first, "male": [...],
    "female": [...], "unit": "thousands|%", "title"}"""
    groups = [str(g) for g in (f.get("age_groups") or [])]
    male = [_num(v) for v in (f.get("male") or [])]
    female = [_num(v) for v in (f.get("female") or [])]
    if not groups or len(male) != len(groups) or len(female) != len(groups):
        raise ValueError("a population pyramid needs one male and one female value per age group")
    if any(v < 0 for v in male + female):
        raise ValueError("a population cannot be negative")
    biggest = max(male + female) or 1
    unit = str(f.get("unit") or "")
    title = str(f.get("title") or "Population pyramid")
    cx, half, top = W / 2, 170, 48
    bar = min(28, 210 / len(groups))
    out = [_text(W / 2, 22, title, size=13, weight="bold"),
           _text(cx - half / 2 - 20, top - 6, "Male", size=12, weight="bold"),
           _text(cx + half / 2 + 20, top - 6, "Female", size=12, weight="bold")]
    for i, g in enumerate(groups):
        y = top + (len(groups) - 1 - i) * bar
        wm, wf = (male[i] / biggest) * (half - 24), (female[i] / biggest) * (half - 24)
        out.append(f"<rect x='{cx - 22 - wm:.1f}' y='{y:.1f}' width='{wm:.1f}' height='{bar - 3:.1f}' fill='#5b8fd1' stroke='#1f4f8a'/>")
        out.append(f"<rect x='{cx + 22:.1f}' y='{y:.1f}' width='{wf:.1f}' height='{bar - 3:.1f}' fill='#e39a9a' stroke='#9a3b3b'/>")
        out.append(_text(cx, y + bar / 2 + 2, g, size=10))
    base = top + len(groups) * bar + 6
    out.append(f"<line x1='{cx - half}' y1='{base}' x2='{cx + half}' y2='{base}' stroke='#111'/>")
    for frac in (0, 0.5, 1):
        v = biggest * frac
        for sign in (-1, 1):
            x = cx + sign * (22 + frac * (half - 24))
            out.append(f"<line x1='{x:.1f}' y1='{base}' x2='{x:.1f}' y2='{base + 5}' stroke='#111'/>")
            out.append(_text(x, base + 18, _fmt(round(v, 1)), size=10))
    out.append(_text(cx, base + 36, f"Population{f' ({unit})' if unit else ''}", size=11))
    out.append(_text(cx, top - 6, "Age", size=11, weight="bold"))
    return _svg("".join(out), title, W, base + 48), title


def _map(f: dict[str, Any]) -> tuple[str, str]:
    """A map from the platform's own gazetteer: {"extent", "title",
    "features": [...]}, as the maps fragment specifies it."""
    from . import map_sketch

    drawn = map_sketch.render_from_model({"map": {k: v for k, v in f.items() if k != "kind"}})
    if not drawn:
        raise ValueError("the map could not be drawn from those features")
    f["_scene"] = drawn.get("scene")
    return drawn["svg"], str(f.get("title") or "Map")


_KINDS = {
    "number_line": _number_line, "bar_chart": _bar_chart, "bar_graph": _bar_chart,
    "pie_chart": _pie_chart, "line_graph": _line_graph, "table": _table, "clock": _clock,
    "thermometer": _thermometer, "shape": _shape, "fraction": _fraction, "angle": _angle,
    "emoji": _emoji, "image": _image, "photo": _image,
    "atom": _atom, "circuit": _circuit, "flow": _flow, "flow_diagram": _flow,
    "food_chain": _flow, "cycle": _flow, "population_pyramid": _population_pyramid,
    "map": _map,
}


def render(figure: dict[str, Any]) -> dict[str, Any] | None:
    """The SVG and its scene for one figure spec, or None where the spec is
    not one this draws. Never raises."""
    if not isinstance(figure, dict):
        return None
    kind = str(figure.get("kind") or figure.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
    draw = _KINDS.get(kind)
    if draw is None:
        return None
    try:
        svg, title = draw(figure)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not draw a %s figure: %s", kind, exc)
        return None
    labels = re.findall(r"<text[^>]*>([^<]+)</text>", svg)
    if isinstance(figure.get("_scene"), dict):
        # A map knows what each feature is; keep that for the marking scheme.
        return {"svg": svg, "scene": figure.pop("_scene"), "title": str(figure.get("title") or title),
                "kind": kind, "alt_text": str(figure.get("alt_text") or title)}
    # A question figure's labels are the givens: shown, never blanked.
    scene = {"title": title, "parts": [
        {"label": t, "role": "label", "assessable": False, "occludable": False, "function": "", "alt_text": t}
        for t in labels]}
    return {"svg": svg, "scene": scene, "title": str(figure.get("title") or title), "kind": kind,
            "alt_text": str(figure.get("alt_text") or title)}


# The figures each family's papers actually read. The list used to be the
# Mathematics one for everybody — number lines, thermometers, a shape with its
# dimensions — and a Social Studies batch sent back for "too few figures"
# came back as totals and percentages with a table round them.
FIGURES_BY_FAMILY: dict[str, str] = {
    "mathematics": "a number line or thermometer for directed numbers, a table of prices or "
                   "readings, a bar or line graph, a shape with its dimensions, a clock",
    "science": "an atom model, an electric circuit, a food chain or a cycle as a flow diagram, a "
               "line graph of readings, a photograph of a specimen or apparatus, and a results table "
               "only for data",
    "social": "a map, a population pyramid, a flow diagram of causes and effects, a bar chart of "
              "census or survey data, a photograph of a landform or a place",
    "other": "a photograph of the tool, plant or object the topic is about, a flow diagram of a "
             "process, a table of observations",
}


def figure_examples(subject: str) -> str:
    """The figures this subject's papers read, or nothing where its papers do
    not ask for figures at all (the languages)."""
    from .subject_checks import family_of

    return FIGURES_BY_FAMILY.get(family_of(subject), "")


def prompt_block(subject: str = "") -> str:
    """How the writer asks for a figure — seeded, so it can be edited in
    Langfuse like every other prompt. The share it must reach, and the kinds
    of figure that count, only for a subject whose papers carry figures."""
    from .langfuse_seed import SEED_PROMPT_BLOCKS
    from .prompt_store import render

    block = render("question-figures", SEED_PROMPT_BLOCKS["question-figures"])
    examples = figure_examples(subject) if subject else FIGURES_BY_FAMILY["mathematics"]
    if examples:
        block += "\n" + render("question-figures-share", SEED_PROMPT_BLOCKS["question-figures-share"],
                                examples=examples)
    return block

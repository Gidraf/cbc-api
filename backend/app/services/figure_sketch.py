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


_KINDS = {
    "number_line": _number_line, "bar_chart": _bar_chart, "bar_graph": _bar_chart,
    "pie_chart": _pie_chart, "line_graph": _line_graph, "table": _table, "clock": _clock,
    "thermometer": _thermometer, "shape": _shape, "fraction": _fraction, "angle": _angle,
    "emoji": _emoji, "image": _image, "photo": _image,
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
    # A question figure's labels are the givens: shown, never blanked.
    scene = {"title": title, "parts": [
        {"label": t, "role": "label", "assessable": False, "occludable": False, "function": "", "alt_text": t}
        for t in labels]}
    return {"svg": svg, "scene": scene, "title": str(figure.get("title") or title), "kind": kind,
            "alt_text": str(figure.get("alt_text") or title)}


def prompt_block() -> str:
    """How the writer asks for a figure — seeded, so it can be edited in
    Langfuse like every other prompt."""
    from .langfuse_seed import SEED_PROMPT_BLOCKS
    from .prompt_store import render

    return render("question-figures", SEED_PROMPT_BLOCKS["question-figures"])

from __future__ import annotations

import html
from typing import Any


def _esc(val: Any) -> str:
    return html.escape(str(val or ""))


def render_graph_svg(spec: dict[str, Any]) -> str:
    """Generate standalone SVG markup for charts and coordinate graphs."""
    kind = spec.get("type", "bar")
    width = spec.get("width", 500)
    height = spec.get("height", 300)
    title = spec.get("title", "")

    if kind == "number_line":
        min_v = int(spec.get("min", -5))
        max_v = int(spec.get("max", 5))
        points = spec.get("points", [])
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 120" width="{width}" height="120" style="background:#ffffff;font-family:sans-serif;">',
            f'<text x="{width/2}" y="25" text-anchor="middle" font-size="14" font-weight="bold">{_esc(title)}</text>',
            f'<line x1="40" y1="70" x2="{width-40}" y2="70" stroke="#111827" stroke-width="2.5"/>',
            f'<polygon points="{width-40},65 {width-30},70 {width-40},75" fill="#111827"/>',
            f'<polygon points="40,65 30,70 40,75" fill="#111827"/>',
        ]
        step_px = (width - 100) / (max_v - min_v) if max_v > min_v else 20
        for val in range(min_v, max_v + 1):
            x = 50 + (val - min_v) * step_px
            svg_parts.append(f'<line x1="{x}" y1="63" x2="{x}" y2="77" stroke="#374151" stroke-width="1.5"/>')
            svg_parts.append(f'<text x="{x}" y="95" text-anchor="middle" font-size="12" fill="#111827">{val}</text>')

        for pt in points:
            val = pt.get("value", 0)
            label = pt.get("label", "")
            x = 50 + (val - min_v) * step_px
            svg_parts.append(f'<circle cx="{x}" cy="70" r="5" fill="#0B6E5F"/>')
            if label:
                svg_parts.append(f'<text x="{x}" y="50" text-anchor="middle" font-size="12" font-weight="bold" fill="#0B6E5F">{_esc(label)}</text>')

        svg_parts.append('</svg>')
        return "".join(svg_parts)

    # Bar chart default
    data = spec.get("data") or {}
    items = list(data.items()) if isinstance(data, dict) else []
    if not items:
        items = [("A", 10), ("B", 25), ("C", 15), ("D", 30)]

    max_val = max(v for _, v in items) if items else 1
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" style="background:#ffffff;font-family:sans-serif;">',
        f'<text x="{width/2}" y="30" text-anchor="middle" font-size="16" font-weight="bold">{_esc(title)}</text>',
        f'<line x1="60" y1="{height-50}" x2="{width-30}" y2="{height-50}" stroke="#374151" stroke-width="2"/>',
        f'<line x1="60" y1="50" x2="60" y2="{height-50}" stroke="#374151" stroke-width="2"/>',
    ]

    avail_w = width - 110
    bar_w = avail_w / len(items) if items else 30
    chart_h = height - 110

    for i, (lbl, val) in enumerate(items):
        bh = (val / max_val) * chart_h if max_val > 0 else 0
        x = 75 + i * bar_w
        y = (height - 50) - bh
        w = max(10.0, bar_w - 15.0)
        svg_parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{bh}" fill="#0B6E5F" rx="2"/>')
        svg_parts.append(f'<text x="{x + w/2}" y="{y - 6}" text-anchor="middle" font-size="11" font-weight="bold" fill="#0B6E5F">{val}</text>')
        svg_parts.append(f'<text x="{x + w/2}" y="{height - 30}" text-anchor="middle" font-size="12" fill="#374151">{_esc(lbl)}</text>')

    svg_parts.append('</svg>')
    return "".join(svg_parts)


def render_geometry_svg(spec: dict[str, Any]) -> str:
    """Render a triangle or geometric shape as constructible SVG."""
    width = spec.get("width", 400)
    height = spec.get("height", 300)
    kind = spec.get("kind", "triangle")

    if kind == "triangle":
        base_label = spec.get("base_label", "8 cm")
        height_label = spec.get("height_label", "6 cm")
        p_a = (60, 240)
        p_b = (320, 240)
        p_c = (190, 80)
        p_h = (190, 240)

        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" style="background:#ffffff;font-family:sans-serif;">
  <!-- Triangle body -->
  <polygon points="{p_a[0]},{p_a[1]} {p_b[0]},{p_b[1]} {p_c[0]},{p_c[1]}" fill="#f0fdf4" stroke="#0B6E5F" stroke-width="2.5"/>
  <!-- Perpendicular height line -->
  <line x1="{p_c[0]}" y1="{p_c[1]}" x2="{p_h[0]}" y2="{p_h[1]}" stroke="#dc2626" stroke-width="2" stroke-dasharray="4,4"/>
  <!-- Right angle marker -->
  <rect x="{p_h[0]}" y="{p_h[1]-12}" width="12" height="12" fill="none" stroke="#dc2626" stroke-width="1.5"/>
  <!-- Labels -->
  <text x="{p_a[0]-15}" y="{p_a[1]+10}" font-weight="bold" font-size="14">A</text>
  <text x="{p_b[0]+8}" y="{p_b[1]+10}" font-weight="bold" font-size="14">B</text>
  <text x="{p_c[0]-5}" y="{p_c[1]-12}" font-weight="bold" font-size="14">C</text>
  <!-- Base dimension -->
  <text x="{(p_a[0]+p_b[0])/2}" y="{p_a[1]+28}" text-anchor="middle" font-size="13" font-weight="bold" fill="#0B6E5F">{_esc(base_label)}</text>
  <!-- Height dimension -->
  <text x="{p_c[0]+10}" y="{(p_c[1]+p_h[1])/2}" font-size="13" font-weight="bold" fill="#dc2626">{_esc(height_label)}</text>
</svg>"""
        return svg

    # Default fallback circle
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" style="background:#ffffff;font-family:sans-serif;">
  <circle cx="{width/2}" cy="{height/2}" r="70" fill="#f0fdf4" stroke="#0B6E5F" stroke-width="2.5"/>
  <line x1="{width/2}" y1="{height/2}" x2="{width/2+70}" y2="{height/2}" stroke="#dc2626" stroke-width="2"/>
  <text x="{width/2+30}" y="{height/2-8}" font-size="13" font-weight="bold" fill="#dc2626">r = 7 cm</text>
</svg>"""

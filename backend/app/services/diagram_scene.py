"""Structured diagrams: addressable parts, removable layers, croppable regions.

A diagram used to be an opaque SVG string, so "ask a question about part of this
diagram" was not expressible and the learner's paper and the marking scheme had
to be drawn twice.

The scene document is the structured description; the SVG is a render target.
Two capabilities follow:

* **Layer stripping** — render once with the label layer hidden for the question
  paper and once with it shown for the marking scheme, from one source, so they
  cannot disagree.
* **Region cropping** — render a viewBox around a named region so a question can
  test one part of a larger figure.

Diagrams generated before this existed are backfilled by :func:`build_scene_from_svg`,
which reads structure out of the markup rather than requiring regeneration.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger("cbc-diagram-scene")

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

LABEL_LAYER = "labels"
BASE_LAYER = "base"
ANNOTATION_LAYER = "annotations"

_SLUG = re.compile(r"[^a-z0-9]+")
# Rough advance width per character at font-size 1, for estimating text extents.
_CHAR_WIDTH_RATIO = 0.55


def _slug(text: str, fallback: str = "part") -> str:
    out = _SLUG.sub("_", (text or "").strip().lower()).strip("_")
    return out[:40] or fallback


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).strip().rstrip("px%"))
    except (TypeError, ValueError):
        return default


def _parse_viewbox(root: ET.Element) -> list[float]:
    raw = root.get("viewBox") or root.get("viewbox") or ""
    parts = [p for p in re.split(r"[,\s]+", raw.strip()) if p]
    if len(parts) == 4:
        try:
            return [float(p) for p in parts]
        except ValueError:
            pass
    return [0.0, 0.0, _float(root.get("width"), 800.0), _float(root.get("height"), 500.0)]


def _text_bbox(elem: ET.Element) -> list[float]:
    """Approximate the box a text node occupies.

    Approximate on purpose — exact glyph metrics would need a font engine, and a
    region crop only needs to be close enough to frame the part.
    """
    x, y = _float(elem.get("x")), _float(elem.get("y"))
    size = _float(elem.get("font-size"), 14.0)
    text = (elem.text or "").strip()
    width = max(20.0, len(text) * size * _CHAR_WIDTH_RATIO)
    anchor = (elem.get("text-anchor") or "start").lower()

    if anchor == "middle":
        x -= width / 2
    elif anchor == "end":
        x -= width

    return [round(x, 2), round(y - size, 2), round(width, 2), round(size * 1.4, 2)]


def _shape_bbox(elem: ET.Element) -> list[float] | None:
    tag = _local(elem.tag)
    if tag == "rect":
        return [_float(elem.get("x")), _float(elem.get("y")),
                _float(elem.get("width")), _float(elem.get("height"))]
    if tag in {"circle", "ellipse"}:
        cx, cy = _float(elem.get("cx")), _float(elem.get("cy"))
        rx = _float(elem.get("r")) or _float(elem.get("rx"))
        ry = _float(elem.get("r")) or _float(elem.get("ry")) or rx
        return [cx - rx, cy - ry, rx * 2, ry * 2]
    return None


def _union(boxes: list[list[float]]) -> list[float]:
    if not boxes:
        return [0.0, 0.0, 0.0, 0.0]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return [round(x0, 2), round(y0, 2), round(x1 - x0, 2), round(y1 - y0, 2)]


def _pad(box: list[float], viewbox: list[float], ratio: float = 0.12) -> list[float]:
    """Give a cropped region breathing room without leaving the canvas."""
    padding = max(box[2], box[3]) * ratio
    x = max(viewbox[0], box[0] - padding)
    y = max(viewbox[1], box[1] - padding)
    w = min(viewbox[0] + viewbox[2] - x, box[2] + padding * 2)
    h = min(viewbox[1] + viewbox[3] - y, box[3] + padding * 2)
    return [round(x, 2), round(y, 2), round(max(w, 1.0), 2), round(max(h, 1.0), 2)]


# ─────────────────────────────────────────────────────────────────────────────
# Building
# ─────────────────────────────────────────────────────────────────────────────


def build_scene_from_svg(svg_markup: str, title: str = "", model_scene: dict | None = None) -> dict[str, Any]:
    """Derive a scene document from SVG markup.

    When the generator supplied its own scene document, that wins for labels and
    semantics; geometry is still measured from the markup so bounding boxes match
    what will actually be drawn.
    """
    try:
        root = ET.fromstring(svg_markup)
    except ET.ParseError as exc:
        logger.debug("Cannot derive scene document, SVG did not parse: %s", exc)
        return {}

    viewbox = _parse_viewbox(root)
    parts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _unique(base: str) -> str:
        candidate, suffix = base, 2
        while candidate in seen_ids:
            candidate, suffix = f"{base}_{suffix}", suffix + 1
        seen_ids.add(candidate)
        return candidate

    for elem in root.iter():
        tag = _local(elem.tag)

        if tag == "text":
            label = (elem.text or "").strip()
            if not label:
                continue
            part_id = _unique(_slug(label, f"label_{len(parts) + 1}"))
            elem.set("data-part-id", part_id)
            elem.set("data-layer", LABEL_LAYER)
            parts.append({
                "part_id": part_id,
                "label": label,
                "layer": LABEL_LAYER,
                "bbox": _text_bbox(elem),
                "role": "label",
                "assessable": True,
                "alt_text": label,
            })

        elif tag in {"rect", "circle", "ellipse"}:
            bbox = _shape_bbox(elem)
            if not bbox or bbox[2] <= 0 or bbox[3] <= 0:
                continue
            # Skip full-canvas background rectangles; they are not parts.
            if bbox[2] >= viewbox[2] * 0.95 and bbox[3] >= viewbox[3] * 0.95:
                elem.set("data-layer", BASE_LAYER)
                continue
            existing = elem.get("id") or elem.get("data-part-id")
            part_id = _unique(_slug(existing or f"{tag}_{len(parts) + 1}", f"shape_{len(parts) + 1}"))
            elem.set("data-part-id", part_id)
            elem.set("data-layer", BASE_LAYER)
            parts.append({
                "part_id": part_id,
                "label": existing or f"{tag} region",
                "layer": BASE_LAYER,
                "bbox": [round(v, 2) for v in bbox],
                "role": "region",
                "assessable": False,
                "alt_text": "",
            })

        elif tag in {"path", "polygon", "polyline", "line"}:
            elem.set("data-layer", elem.get("data-layer") or ANNOTATION_LAYER)

    # Merge the generator's own semantics over the derived geometry.
    if isinstance(model_scene, dict) and model_scene.get("parts"):
        by_label = {p["label"].strip().lower(): p for p in parts if p.get("label")}
        for supplied in model_scene["parts"]:
            if not isinstance(supplied, dict):
                continue
            key = str(supplied.get("label") or "").strip().lower()
            target = by_label.get(key)
            if target:
                target["alt_text"] = supplied.get("alt_text") or target["alt_text"]
                target["role"] = supplied.get("role") or target["role"]
                target["assessable"] = bool(supplied.get("assessable", target["assessable"]))

    regions = _derive_regions(parts, viewbox)
    if isinstance(model_scene, dict) and model_scene.get("regions"):
        for supplied in model_scene["regions"]:
            if not isinstance(supplied, dict) or not supplied.get("region_id"):
                continue
            part_ids = [p for p in (supplied.get("part_ids") or []) if p in seen_ids]
            if not part_ids:
                continue
            boxes = [p["bbox"] for p in parts if p["part_id"] in part_ids]
            regions.append({
                "region_id": _slug(str(supplied["region_id"]), "region"),
                "label": supplied.get("label", ""),
                "part_ids": part_ids,
                "bbox": _pad(_union(boxes), viewbox),
            })

    used_layers = {p["layer"] for p in parts} | {ANNOTATION_LAYER}
    layers = [
        {"layer_id": BASE_LAYER, "label": "Structure", "removable": False},
        {"layer_id": LABEL_LAYER, "label": "Labels", "removable": True},
        {"layer_id": ANNOTATION_LAYER, "label": "Annotations", "removable": True},
    ]

    return {
        "title": title,
        "viewbox": [round(v, 2) for v in viewbox],
        "layers": [layer for layer in layers if layer["layer_id"] in used_layers or not layer["removable"]],
        "parts": parts,
        "regions": regions,
        "instrumented_svg": ET.tostring(root, encoding="unicode"),
    }


def _derive_regions(parts: list[dict[str, Any]], viewbox: list[float]) -> list[dict[str, Any]]:
    """Group parts into upper/middle/lower bands so a crop target always exists."""
    labelled = [p for p in parts if p.get("assessable") and p.get("bbox")]
    if len(labelled) < 2:
        return []

    height = viewbox[3] or 1.0
    bands: dict[str, list[dict[str, Any]]] = {"upper": [], "middle": [], "lower": []}
    for part in labelled:
        centre = (part["bbox"][1] + part["bbox"][3] / 2 - viewbox[1]) / height
        key = "upper" if centre < 0.34 else ("middle" if centre < 0.67 else "lower")
        bands[key].append(part)

    regions: list[dict[str, Any]] = []
    for name, members in bands.items():
        if len(members) < 2:
            continue
        regions.append({
            "region_id": f"{name}_section",
            "label": f"{name.title()} section",
            "part_ids": [m["part_id"] for m in members],
            "bbox": _pad(_union([m["bbox"] for m in members]), viewbox),
        })
    return regions


# ─────────────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────────────


def render_svg(
    svg_markup: str,
    scene: dict[str, Any] | None = None,
    hide_layers: list[str] | None = None,
    region_id: str | None = None,
    highlight_part_ids: list[str] | None = None,
) -> str:
    """Render a variant of a diagram.

    ``hide_layers=["labels"]`` produces the learner's copy; rendering the same
    diagram without it produces the marking scheme's copy.
    """
    source = (scene or {}).get("instrumented_svg") or svg_markup
    if not source:
        return svg_markup

    hide = {h for h in (hide_layers or []) if h}
    highlight = {h for h in (highlight_part_ids or []) if h}

    if not hide and not region_id and not highlight:
        return source

    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        logger.warning("Could not render diagram variant, SVG did not parse: %s", exc)
        return svg_markup

    if hide:
        # ElementTree has no parent pointers, so walk parents explicitly.
        for parent in list(root.iter()):
            for child in list(parent):
                if child.get("data-layer") in hide:
                    parent.remove(child)

    if highlight:
        for elem in root.iter():
            if elem.get("data-part-id") in highlight:
                elem.set("stroke", "#B45309")
                elem.set("stroke-width", str(max(2.0, _float(elem.get("stroke-width"), 1.0) * 2)))

    if region_id and scene:
        region = next(
            (r for r in (scene.get("regions") or []) if r.get("region_id") == region_id),
            None,
        )
        if region and region.get("bbox"):
            x, y, w, h = region["bbox"]
            root.set("viewBox", f"{x} {y} {w} {h}")
        else:
            logger.info("Region '%s' not found in scene document; rendering full diagram", region_id)

    return ET.tostring(root, encoding="unicode")


def render_for_question(
    diagram: dict[str, Any],
    binding: dict[str, Any] | None,
    with_answers: bool,
) -> str:
    """The diagram as it should appear on a paper.

    With answers, everything is shown. Without, the layers the question expects
    the learner to supply are stripped.
    """
    svg = str(diagram.get("svg_markup") or diagram.get("diagram_svg") or "")
    scene = diagram.get("scene_document") or {}

    if not binding:
        return render_svg(svg, scene)

    return render_svg(
        svg,
        scene,
        hide_layers=[] if with_answers else list(binding.get("hide_layers") or []),
        region_id=binding.get("region_id"),
        highlight_part_ids=list(binding.get("part_ids") or []),
    )

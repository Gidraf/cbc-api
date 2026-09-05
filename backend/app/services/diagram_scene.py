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
                "function": "",
                "occludable": True,
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
                "function": "",
                "occludable": False,
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
                # What the part *does*. Without this an occlusion question can be
                # posed ("name part A") but not marked beyond the bare label, and
                # the generator cannot ask why the part matters.
                target["function"] = str(supplied.get("function") or target.get("function") or "").strip()
                target["occludable"] = bool(supplied.get("occludable", target.get("occludable", True)))

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


def _part_id_of(elem: Any) -> str | None:
    """Which part this element belongs to, however the drawing marked it.

    `data-part-id` is what this engine has always written. A model asked for an
    SVG writes `id="part-stigma"` instead, because that is ordinary SVG — and
    a drawing whose parts cannot be found is a drawing no question can occlude,
    so every diagram question against it silently showed the learner the
    marking copy.
    """
    marked = elem.get("data-part-id")
    if marked:
        return marked
    identifier = elem.get("id") or ""
    return identifier if identifier.startswith("part-") else None


def render_svg(
    svg_markup: str,
    scene: dict[str, Any] | None = None,
    hide_layers: list[str] | None = None,
    region_id: str | None = None,
    highlight_part_ids: list[str] | None = None,
    hide_part_ids: list[str] | None = None,
    blank_slots: dict[str, str] | None = None,
) -> str:
    """Render a variant of a diagram.

    ``hide_layers=["labels"]`` blanks every label at once; ``hide_part_ids``
    blanks named parts only, which is what lets one figure carry several
    different questions.

    ``blank_slots`` maps a hidden ``part_id`` to the marker printed in its place
    ("A", "B", …). Removing a label without leaving a marker produces a paper
    where the learner cannot tell which parts they are being asked to name, so
    an occlusion question should always pass slots.
    """
    source = (scene or {}).get("instrumented_svg") or svg_markup
    if not source:
        return svg_markup

    hide = {h for h in (hide_layers or []) if h}
    highlight = {h for h in (highlight_part_ids or []) if h}
    hide_parts = {h for h in (hide_part_ids or []) if h}
    slots = dict(blank_slots or {})

    if not hide and not region_id and not highlight and not hide_parts:
        return source

    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        logger.warning("Could not render diagram variant, SVG did not parse: %s", exc)
        return svg_markup

    if hide or hide_parts:
        # ElementTree has no parent pointers, so walk parents explicitly.
        for parent in list(root.iter()):
            for child in list(parent):
                if (child.get("data-layer") in hide
                        or _part_id_of(child) in hide_parts):
                    parent.remove(child)

    if slots:
        _draw_blank_slots(root, scene or {}, slots)

    if highlight:
        for elem in root.iter():
            if _part_id_of(elem) in highlight:
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

    hidden = list(binding.get("hide_part_ids") or [])
    slots = dict(binding.get("slots") or {})

    if with_answers:
        # The marking copy shows everything, and highlights whatever the learner
        # had to supply so a marker's eye goes straight to it.
        return render_svg(
            svg,
            scene,
            region_id=binding.get("region_id"),
            highlight_part_ids=hidden or list(binding.get("part_ids") or []),
        )

    return render_svg(
        svg,
        scene,
        hide_layers=list(binding.get("hide_layers") or []),
        region_id=binding.get("region_id"),
        highlight_part_ids=[] if hidden else list(binding.get("part_ids") or []),
        hide_part_ids=hidden,
        blank_slots=slots,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Occlusion variants
# ─────────────────────────────────────────────────────────────────────────────

# Slot markers printed where a label was removed.
_SLOT_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

VARIANT_MODES = ("label_blanks", "hide_parts", "crop_region", "missing_parameters", "full")

# A number, optionally signed/decimal, with a unit — "37 °C", "4.5 cm", "250 ml".
_PARAMETER = re.compile(r"^[^\d]*[-+]?\d+(?:\.\d+)?\s*[^\d]*$")


def _draw_blank_slots(root: ET.Element, scene: dict[str, Any], slots: dict[str, str]) -> None:
    """Print a marker where each removed label used to be.

    A dashed box plus a letter, so the paper reads "name the part labelled A"
    and the learner can see exactly which part is meant.
    """
    by_id = {p.get("part_id"): p for p in (scene.get("parts") or []) if isinstance(p, dict)}

    for part_id, marker in slots.items():
        part = by_id.get(part_id)
        bbox = part.get("bbox") if isinstance(part, dict) else None
        if not bbox or len(bbox) != 4:
            continue

        x, y, w, h = (float(v) for v in bbox)
        w = max(w, 26.0)
        h = max(h, 16.0)

        box = ET.SubElement(root, f"{{{SVG_NS}}}rect")
        box.set("x", f"{round(x, 2)}")
        box.set("y", f"{round(y, 2)}")
        box.set("width", f"{round(w, 2)}")
        box.set("height", f"{round(h, 2)}")
        box.set("fill", "none")
        box.set("stroke", "#111827")
        box.set("stroke-width", "1")
        box.set("stroke-dasharray", "4 3")
        box.set("data-blank-slot", marker)
        box.set("data-part-id", f"{part_id}__slot")

        text = ET.SubElement(root, f"{{{SVG_NS}}}text")
        text.set("x", f"{round(x + w / 2, 2)}")
        text.set("y", f"{round(y + h * 0.78, 2)}")
        text.set("text-anchor", "middle")
        text.set("font-family", "system-ui, sans-serif")
        text.set("font-size", f"{round(min(h * 0.8, 16.0), 1)}")
        text.set("font-weight", "700")
        text.set("fill", "#111827")
        text.set("data-blank-slot", marker)
        text.text = marker


def occludable_parts(scene: dict[str, Any], mode: str = "label_blanks") -> list[dict[str, Any]]:
    """The parts a question may legitimately hide.

    A part is only fair game if it is assessable, not explicitly pinned as
    non-occludable, and has geometry to put a marker on. ``missing_parameters``
    narrows further to labels that are a measured value, since "what reading is
    missing" is a different question from "name this part".
    """
    parts = [
        p for p in (scene.get("parts") or [])
        if isinstance(p, dict)
        and p.get("assessable")
        and p.get("occludable", True)
        and p.get("bbox")
        and p.get("part_id")
    ]

    if mode == "missing_parameters":
        return [p for p in parts if _PARAMETER.match(str(p.get("label") or "").strip())]
    if mode == "hide_parts":
        return parts
    return [p for p in parts if p.get("role") == "label"]


def plan_occlusion(
    scene: dict[str, Any],
    mode: str = "label_blanks",
    max_blanks: int = 3,
    part_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Choose what to remove and record what removing it costs the learner.

    Returns the plan rather than applying it, so a caller can inspect (or an
    operator can approve) the occlusion before any question is written against
    it. ``removed_facts`` is the ground truth the question and the marking
    scheme must both be derived from — generating the answer separately from
    the occlusion is how a paper and its marking scheme drift apart.
    """
    if mode not in VARIANT_MODES:
        mode = "label_blanks"

    candidates = occludable_parts(scene, mode)
    by_id = {p["part_id"]: p for p in candidates}

    if part_ids:
        chosen = [by_id[pid] for pid in part_ids if pid in by_id]
        rejected = [pid for pid in part_ids if pid not in by_id]
    else:
        # Deterministic: reading order down the figure, so the same diagram and
        # mode always yield the same paper.
        ordered = sorted(candidates, key=lambda p: (p["bbox"][1], p["bbox"][0]))
        chosen = ordered[: max(0, max_blanks)]
        rejected = []

    slots: dict[str, str] = {}
    removed_facts: list[dict[str, Any]] = []

    for index, part in enumerate(chosen):
        marker = _SLOT_ALPHABET[index] if index < len(_SLOT_ALPHABET) else f"X{index}"
        slots[part["part_id"]] = marker
        removed_facts.append({
            "slot": marker,
            "part_id": part["part_id"],
            "label": part.get("label", ""),
            "role": part.get("role", ""),
            "function": part.get("function", ""),
            "alt_text": part.get("alt_text", ""),
        })

    # What the learner can still see. A question is only answerable if enough
    # context survives the occlusion, so the caller gets the remainder too.
    hidden = set(slots)
    retained = [
        {"part_id": p["part_id"], "label": p.get("label", ""), "function": p.get("function", "")}
        for p in (scene.get("parts") or [])
        if isinstance(p, dict) and p.get("part_id") not in hidden and p.get("assessable")
    ]

    return {
        "mode": mode,
        "hidden_part_ids": list(slots),
        "slots": slots,
        "removed_facts": removed_facts,
        "retained_parts": retained,
        "rejected_part_ids": rejected,
        "answerable": bool(removed_facts) and bool(retained or mode == "missing_parameters"),
    }


def apply_occlusion(
    diagram: dict[str, Any],
    plan: dict[str, Any],
    region_id: str | None = None,
) -> dict[str, Any]:
    """Render the learner's copy and the marking copy from one occlusion plan.

    Both come from the same source and the same plan, so they cannot disagree
    about which parts were removed.
    """
    svg = str(diagram.get("svg_markup") or diagram.get("diagram_svg") or "")
    scene = diagram.get("scene_document") or {}
    hidden = list(plan.get("hidden_part_ids") or [])
    slots = dict(plan.get("slots") or {})

    paper_svg = render_svg(
        svg, scene,
        hide_part_ids=hidden,
        blank_slots=slots,
        region_id=region_id,
    )
    answer_svg = render_svg(
        svg, scene,
        highlight_part_ids=hidden,
        region_id=region_id,
    )
    return {
        "paper_svg": paper_svg,
        "answer_svg": answer_svg,
        "mode": plan.get("mode", "label_blanks"),
        "slots": slots,
        "removed_facts": list(plan.get("removed_facts") or []),
        "region_id": region_id,
    }


def describe_scene_for_prompt(scene: dict[str, Any], max_parts: int = 40) -> str:
    """A compact catalogue of what a diagram contains, for a model prompt.

    Prompts used to paste a truncated slice of raw SVG markup, from which a model
    cannot reliably name a single ``part_id``. Listing the addressable parts,
    their roles and their functions is both shorter and actually usable.
    """
    if not isinstance(scene, dict) or not scene.get("parts"):
        return "(no structured parts available for this diagram)"

    lines: list[str] = []
    title = str(scene.get("title") or "").strip()
    if title:
        lines.append(f"Diagram: {title}")

    parts = [p for p in scene["parts"] if isinstance(p, dict) and p.get("assessable")]
    lines.append(f"Addressable parts ({len(parts)}):")
    for part in parts[:max_parts]:
        bits = [f"  - part_id={part.get('part_id')}", f'label="{part.get("label", "")}"']
        if part.get("function"):
            bits.append(f'function="{part["function"]}"')
        if not part.get("occludable", True):
            bits.append("occludable=false")
        lines.append(" ".join(bits))
    if len(parts) > max_parts:
        lines.append(f"  … and {len(parts) - max_parts} more")

    regions = [r for r in (scene.get("regions") or []) if isinstance(r, dict)]
    if regions:
        lines.append("Croppable regions:")
        for region in regions:
            lines.append(f"  - region_id={region.get('region_id')} covering {len(region.get('part_ids') or [])} part(s)")

    removable = [
        str(layer.get("layer_id"))
        for layer in (scene.get("layers") or [])
        if isinstance(layer, dict) and layer.get("removable")
    ]
    if removable:
        lines.append(f"Removable layers: {', '.join(removable)}")

    return "\n".join(lines)

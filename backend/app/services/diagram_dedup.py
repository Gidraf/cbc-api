from __future__ import annotations

import hashlib
import html
import logging
import re
import secrets
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from ..infra.db import execute, fetch_one, to_json
from ..infra.storage import object_storage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeduplicatedDiagramResult:
    diagram_id: str
    diagram_title: str
    diagram_svg: str
    diagram_hash: str
    storage_url: str
    dedup_status: str  # "created" | "reused"
    alt_text: str
    tactile_description: str


def extract_and_sanitize_svg(raw_svg: str, default_title: str = "Diagram") -> str:
    """Extracts, cleans, and sanitizes SVG XML, ensuring full standalone visual rendering."""
    if not raw_svg or not isinstance(raw_svg, str):
        return _generate_fallback_svg(default_title)

    clean = raw_svg.strip()

    # 1. Strip markdown fences if present (```xml ... ``` or ```svg ... ```)
    if "```" in clean:
        match = re.search(r"```(?:xml|svg|html)?\s*(<svg[\s\S]*?</svg>)\s*```", clean, re.IGNORECASE)
        if match:
            clean = match.group(1).strip()
        else:
            match_any = re.search(r"<svg[\s\S]*?</svg>", clean, re.IGNORECASE)
            if match_any:
                clean = match_any.group(0).strip()

    # 2. Extract <svg ... </svg>
    svg_match = re.search(r"<svg[\s\S]*?</svg>", clean, re.IGNORECASE)
    if svg_match:
        clean = svg_match.group(0).strip()
    elif not clean.lower().startswith("<svg"):
        return _generate_fallback_svg(default_title)

    # 3. Ensure essential attributes on <svg> root tag
    root_match = re.search(r"<svg([^>]*)>", clean, re.IGNORECASE)
    if root_match:
        attrs = root_match.group(1)
        new_attrs = attrs
        if "xmlns=" not in attrs:
            new_attrs += ' xmlns="http://www.w3.org/2000/svg"'
        if "viewbox=" not in attrs.lower():
            new_attrs += ' viewBox="0 0 800 500"'
        if "width=" not in attrs.lower():
            new_attrs += ' width="100%"'
        if "height=" not in attrs.lower():
            new_attrs += ' height="100%"'
        clean = clean[:root_match.start()] + f"<svg{new_attrs}>" + clean[root_match.end():]

    # 4. Check for CSS rules (.class { ... } or #id { ... }) that are NOT inside <style> tags
    # If found, extract them and place them inside <defs><style type="text/css">...</style></defs>
    has_style_tag = bool(re.search(r"<style[\s\S]*?</style>", clean, re.IGNORECASE))
    if not has_style_tag:
        css_blocks = re.findall(r"(?:^|\n|\s)(\.[a-zA-Z0-9_-]+\s*\{[^}]*\}|#[a-zA-Z0-9_-]+\s*\{[^}]*\})", clean)
        if css_blocks:
            css_combined = "\n".join(css_blocks)
            for block in css_blocks:
                clean = clean.replace(block, "")
            defs_block = (
                f"<defs>\n"
                f"  <style type='text/css'><![CDATA[\n{css_combined}\n]]></style>\n"
                f"  <marker id='arrowhead' markerWidth='10' markerHeight='7' refX='10' refY='3.5' orient='auto'>\n"
                f"    <polygon points='0 0, 10 3.5, 0 7' fill='#0284c7' />\n"
                f"  </marker>\n"
                f"</defs>"
            )
            # Insert right after <svg ...>
            first_gt = clean.find(">")
            if first_gt != -1:
                clean = clean[:first_gt + 1] + "\n" + defs_block + "\n" + clean[first_gt + 1:]

    # 5. Clean any unescaped loose text lines directly in svg body that aren't wrapped in XML tags
    # If the SVG is valid XML, ElementTree can verify it
    try:
        ET.fromstring(clean)
    except Exception as exc:
        logger.debug("SVG XML parse warning, cleaning: %s", exc)
        # Attempt basic XML recovery
        clean = re.sub(r"&(?!(?:amp|lt|gt|quot|apos);)", "&amp;", clean)

    return clean


def _generate_fallback_svg(title: str) -> str:
    escaped_title = html.escape(title)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" width="100%" height="100%">'
        f'<rect width="100%" height="100%" fill="#f8fafc" rx="8" stroke="#cbd5e1" stroke-width="1"/>'
        f'<rect x="250" y="200" width="300" height="100" rx="8" fill="#e0f2fe" stroke="#0284c7" stroke-width="2"/>'
        f'<text x="400" y="255" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="600" text-anchor="middle" fill="#0369a1">{escaped_title}</text>'
        f'</svg>'
    )


class DiagramDeduplicator:
    def canonicalize_svg(self, svg_str: str) -> tuple[str, str]:
        """
        Normalizes SVG XML attributes alphabetically, rounds float precision to 4dp,
        strips whitespace, and normalizes labels to NFC lowercase for deterministic SHA-256 computation ONLY.
        """
        try:
            clean_svg = re.sub(r"<!--.*?-->", "", svg_str, flags=re.DOTALL).strip()
            root = ET.fromstring(clean_svg)
        except Exception:  # noqa: BLE001
            clean_svg = re.sub(r"\s+", " ", svg_str).strip()
            labels = " ".join(re.findall(r">([^<]+)<", clean_svg)).strip()
            norm_labels = unicodedata.normalize("NFC", labels.lower())
            return clean_svg.lower(), norm_labels

        labels_list: list[str] = []

        def _walk_and_normalize(elem: ET.Element) -> None:
            if elem.text and elem.text.strip():
                clean_text = elem.text.strip()
                labels_list.append(clean_text)
                elem.text = clean_text.lower()

            sorted_keys = sorted(elem.attrib.keys())
            new_attribs = {}
            for k in sorted_keys:
                v = elem.attrib[k]
                try:
                    num = round(float(v), 4)
                    new_attribs[k] = f"{int(num)}" if num.is_integer() else f"{num}"
                except ValueError:
                    new_attribs[k] = v.strip()

            elem.attrib.clear()
            elem.attrib.update(new_attribs)

            for child in elem:
                _walk_and_normalize(child)

        _walk_and_normalize(root)
        canonical_xml = ET.tostring(root, encoding="unicode", method="xml")
        canonical_xml = re.sub(r"\s+", " ", canonical_xml).strip()

        combined_labels = " ".join(labels_list)
        norm_labels = unicodedata.normalize("NFC", combined_labels.lower())

        return canonical_xml, norm_labels

    def compute_diagram_hash(self, svg_str: str) -> tuple[str, str]:
        canonical_svg, canonical_labels = self.canonicalize_svg(svg_str)
        hash_input = f"{canonical_svg}:{canonical_labels}".encode("utf-8")
        diagram_hash = hashlib.sha256(hash_input).hexdigest()
        return diagram_hash, canonical_svg

    def deduplicate_and_store(
        self,
        svg_str: str,
        diagram_title: str = "Diagram",
        alt_text: str = "",
        tactile_description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DeduplicatedDiagramResult:
        # Sanitize and ensure valid visual SVG structure
        clean_svg = extract_and_sanitize_svg(svg_str, default_title=diagram_title)
        diagram_hash, canonical_svg = self.compute_diagram_hash(clean_svg)

        existing = fetch_one(
            "SELECT diagram_id, storage_url, alt_text, tactile_description FROM diagram_registry WHERE content_hash = :hash",
            {"hash": diagram_hash},
        )

        if existing:
            return DeduplicatedDiagramResult(
                diagram_id=existing["diagram_id"],
                diagram_title=diagram_title,
                diagram_svg=clean_svg,
                diagram_hash=diagram_hash,
                storage_url=existing["storage_url"],
                dedup_status="reused",
                alt_text=existing.get("alt_text") or alt_text,
                tactile_description=existing.get("tactile_description") or tactile_description,
            )

        diagram_id = f"diag_{secrets.token_hex(6)}"
        object_name = f"diagrams/{diagram_id}.svg"
        storage_url = object_storage.save_svg(object_name, clean_svg)

        execute(
            """
            INSERT INTO diagram_registry (diagram_id, content_hash, storage_url, alt_text, tactile_description, metadata, created_at)
            VALUES (:diagram_id, :content_hash, :storage_url, :alt_text, :tactile_description, CAST(:metadata AS jsonb), NOW())
            ON CONFLICT (content_hash) DO NOTHING
            """,
            {
                "diagram_id": diagram_id,
                "content_hash": diagram_hash,
                "storage_url": storage_url,
                "alt_text": alt_text,
                "tactile_description": tactile_description,
                "metadata": to_json(metadata or {}),
            },
        )

        return DeduplicatedDiagramResult(
            diagram_id=diagram_id,
            diagram_title=diagram_title,
            diagram_svg=clean_svg,
            diagram_hash=diagram_hash,
            storage_url=storage_url,
            dedup_status="created",
            alt_text=alt_text,
            tactile_description=tactile_description,
        )


diagram_deduplicator = DiagramDeduplicator()

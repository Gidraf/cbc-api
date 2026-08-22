from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from ..infra.db import execute, fetch_one, to_json
from ..infra.storage import object_storage


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


class DiagramDeduplicator:
    def canonicalize_svg(self, svg_str: str) -> tuple[str, str]:
        """
        Normalizes SVG XML attributes alphabetically, rounds float precision to 4dp,
        strips whitespace, and normalizes labels to NFC lowercase for deterministic SHA-256 computation.
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
        diagram_hash, canonical_svg = self.compute_diagram_hash(svg_str)

        existing = fetch_one(
            "SELECT diagram_id, storage_url, alt_text, tactile_description FROM diagram_registry WHERE content_hash = :hash",
            {"hash": diagram_hash},
        )

        if existing:
            return DeduplicatedDiagramResult(
                diagram_id=existing["diagram_id"],
                diagram_title=diagram_title,
                diagram_svg=canonical_svg,
                diagram_hash=diagram_hash,
                storage_url=existing["storage_url"],
                dedup_status="reused",
                alt_text=existing.get("alt_text") or alt_text,
                tactile_description=existing.get("tactile_description") or tactile_description,
            )

        diagram_id = f"diag_{secrets.token_hex(6)}"
        object_name = f"diagrams/{diagram_id}.svg"
        storage_url = object_storage.save_svg(object_name, canonical_svg)

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
            diagram_svg=canonical_svg,
            diagram_hash=diagram_hash,
            storage_url=storage_url,
            dedup_status="created",
            alt_text=alt_text,
            tactile_description=tactile_description,
        )


diagram_deduplicator = DiagramDeduplicator()

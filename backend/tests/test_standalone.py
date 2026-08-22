from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET
import hashlib
import re
import unicodedata

def canonicalize_svg(svg_str: str) -> tuple[str, str]:
    clean_svg = re.sub(r"<!--.*?-->", "", svg_str, flags=re.DOTALL).strip()
    root = ET.fromstring(clean_svg)
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

def compute_diagram_hash(svg_str: str) -> str:
    canonical_svg, canonical_labels = canonicalize_svg(svg_str)
    hash_input = f"{canonical_svg}:{canonical_labels}".encode("utf-8")
    return hashlib.sha256(hash_input).hexdigest()

class StandaloneDeduplicationTest(unittest.TestCase):
    def test_canonical_dedup_hashing(self):
        svg1 = '<svg viewBox="0 0 400 200" xmlns="http://www.w3.org/2000/svg"><rect height="200.00001" width="400.0" y="0" x="0"/><text>State of Matter</text></svg>'
        svg2 = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"><rect x="0" y="0" width="400" height="200"/><text>STATE OF MATTER</text></svg>'

        h1 = compute_diagram_hash(svg1)
        h2 = compute_diagram_hash(svg2)
        self.assertEqual(len(h1), 64)
        self.assertEqual(h1, h2)

if __name__ == "__main__":
    unittest.main()

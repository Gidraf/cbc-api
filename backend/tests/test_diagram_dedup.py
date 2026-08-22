from __future__ import annotations

from app.services.diagram_dedup import diagram_deduplicator


def test_svg_canonicalization_deterministic():
    svg1 = '<svg viewBox="0 0 400 200" xmlns="http://www.w3.org/2000/svg"><rect height="200.00001" width="400.0" y="0" x="0"/><text>State of Matter</text></svg>'
    svg2 = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 200"><rect x="0" y="0" width="400" height="200"/><text>STATE OF MATTER</text></svg>'

    hash1, canon1 = diagram_deduplicator.compute_diagram_hash(svg1)
    hash2, canon2 = diagram_deduplicator.compute_diagram_hash(svg2)

    assert len(hash1) == 64
    assert len(hash2) == 64
    assert hash1 == hash2  # Deterministic hash must match normalized attributes and labels

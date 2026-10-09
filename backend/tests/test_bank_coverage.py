"""The planner's view of the bank: one grouped count per subject, joined to
the design's own sub-strand list."""
from __future__ import annotations

from datetime import datetime

from app.services import bank_coverage as coverage


def test_every_design_sub_strand_is_listed_with_its_counts(monkeypatch) -> None:
    from app.services import product_orders

    monkeypatch.setattr(product_orders, "sub_strands_for", lambda g, s: [
        {"strand": "Matter", "sub_strand": "Structure of the atom", "hours": 6},
        {"strand": "Matter", "sub_strand": "Metals and Alloys", "hours": 4},
        {"strand": "Energy", "sub_strand": "Waves", "hours": 5},
    ])
    monkeypatch.setattr(coverage, "_counts", lambda g, s: {
        "structure of the atom": {"total": 60, "usable": 54, "approved": 10, "with_figures": 5,
                                  "last_reviewed": "2026-10-01T03:00:00", "last_written": datetime(2026, 10, 7)},
        "waves": {"total": 3, "usable": 3, "approved": 0, "with_figures": 0},
    })
    monkeypatch.setattr(product_orders, "_has_notes", lambda g, s, ss: ss != "Metals and Alloys")

    out = coverage.for_subject("grade-9", "Integrated Science")
    rows = {r["sub_strand"]: r for r in out["sub_strands"]}

    assert rows["Structure of the atom"]["questions"] == 54 and rows["Structure of the atom"]["held"] == 6
    assert rows["Metals and Alloys"]["questions"] == 0, "a sub-strand with nothing is still listed"
    assert rows["Metals and Alloys"]["has_notes"] is False
    assert rows["Waves"]["last_reviewed"] is None
    assert out["totals"] == {"sub_strands": 3, "questions": 57, "with_figures": 5, "with_notes": 2,
                             "never_reviewed": 1}


def test_without_notes_no_guide_is_looked_up(monkeypatch) -> None:
    from app.services import product_orders

    monkeypatch.setattr(product_orders, "sub_strands_for", lambda g, s: [{"strand": "A", "sub_strand": "B"}])
    monkeypatch.setattr(coverage, "_counts", lambda g, s: {})
    monkeypatch.setattr(product_orders, "_has_notes", lambda *a: (_ for _ in ()).throw(AssertionError("looked up")))
    out = coverage.for_subject("grade-9", "Mathematics", with_notes=False)
    assert out["sub_strands"][0]["has_notes"] is None

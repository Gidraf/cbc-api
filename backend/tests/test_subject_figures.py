"""Figures a science or Social Studies paper actually sets.

62 of the bank's 89 question figures were tables, whichever model wrote
them: the figure menu was a Mathematics paper's, and for an atom, a circuit,
a food chain or a population pyramid a table was the only kind that fitted.
"""
from __future__ import annotations

import re

import pytest

from app.services import figure_sketch as fs
from app.services import question_check as qc


def _electrons_by_shell(svg: str) -> list[int]:
    """Count the electron dots on each drawn shell."""
    shells = sorted({int(float(r)) for r in re.findall(r"r='(\d+)' fill='none'", svg)})
    dots = re.findall(r"<circle cx='([\d.]+)' cy='([\d.]+)' r='5' fill='#1f5fa8'", svg)
    counts = []
    for r in shells:
        counts.append(sum(1 for x, y in dots if abs(((float(x) - 200) ** 2 + (float(y) - 165) ** 2) ** 0.5 - r) < 1))
    return counts


@pytest.mark.parametrize("protons, electrons, shells", [
    (16, 16, [2, 8, 6]), (11, 10, [2, 8]), (20, 20, [2, 8, 8, 2]), (17, 18, [2, 8, 8]), (1, 1, [1]),
])
def test_an_atom_is_drawn_with_the_arrangement_its_electrons_give(protons, electrons, shells) -> None:
    drawn = fs.render({"kind": "atom", "protons": protons, "neutrons": protons, "electrons": electrons})
    assert drawn and _electrons_by_shell(drawn["svg"]) == shells


def test_an_ion_is_named_as_an_ion() -> None:
    assert fs.render({"kind": "atom", "element": "Sodium", "protons": 11, "neutrons": 12,
                      "electrons": 10})["title"] == "Sodium ion, Na+"
    assert "S2−" in fs.render({"kind": "atom", "element": "Sulphur", "protons": 16,
                               "mass_number": 32, "electrons": 18})["title"]


@pytest.mark.parametrize("spec", [
    {"kind": "atom", "protons": 26, "neutrons": 30},            # beyond the level's 1–20
    {"kind": "atom", "protons": 8},                               # no neutrons, no mass number
    {"kind": "circuit", "branches": [[{"kind": "bulb"}]]},       # nothing to drive it
    {"kind": "circuit", "source": [{"kind": "cell"}], "branches": [[{"kind": "bulb", "label": "L"}]],
     "voltmeters": [{"across": "L9"}]},                           # across nothing
    {"kind": "population_pyramid", "age_groups": ["0-14"], "male": [1, 2], "female": [1]},
    {"kind": "flow", "nodes": ["only one"]},
])
def test_an_impossible_figure_is_refused_not_drawn(spec) -> None:
    assert fs.render(spec) is None


def test_a_parallel_circuit_has_its_junctions_and_a_voltmeter_across() -> None:
    svg = fs.render({"kind": "circuit", "source": [{"kind": "cell", "label": "C"}],
                     "branches": [[{"kind": "bulb", "label": "L1"}], [{"kind": "bulb", "label": "L2"}]],
                     "voltmeters": [{"across": "L2", "label": "V"}]})["svg"]
    assert svg.count("r='3.5'") == 2, "one junction dot each side of the second branch"
    assert ">V<" in svg


def test_a_food_chain_points_each_organism_at_the_next() -> None:
    svg = fs.render({"kind": "food_chain", "nodes": ["Grass", "Grasshopper", "Frog", "Hawk"]})["svg"]
    assert svg.count("marker-end='url(#arrow)'") == 3
    cycle = fs.render({"kind": "cycle", "nodes": ["Evaporation", "Condensation", "Precipitation", "Collection"]})["svg"]
    assert cycle.count("marker-end='url(#arrow)'") == 4, "a cycle closes"


def test_a_map_keeps_what_each_feature_is() -> None:
    drawn = fs.render({"kind": "map", "extent": "Kenya", "title": "Lakes",
                       "features": [{"kind": "lake", "name": "Lake Victoria", "note": "largest lake"}]})
    assert drawn and drawn["kind"] == "map"
    assert any("Victoria" in str(p.get("label")) for p in drawn["scene"].get("parts", []))


def _items(kinds: list[str]) -> list[dict]:
    out = []
    for i, kind in enumerate(kinds):
        figure = {"kind": kind, "columns": ["a"], "rows": [["1"]]} if kind else None
        out.append({"question_id": f"q{i}", "question_type": "short_answer",
                    "question_text": f"Question {i} about the figure.", "figure": figure})
    return out


def test_a_batch_of_tables_is_sent_back_for_the_subjects_own_figures() -> None:
    findings: list = []
    qc._too_many_tables(_items(["table"] * 5 + ["atom"]), subject="Integrated Science", findings=findings)
    over = [f for f in findings if f.kind == "table_over_used"]
    assert len(over) == 3, "6 figures allow 2 tables; 3 of 5 go back"
    assert "atom" in over[0].fix and "circuit" in over[0].fix


def test_a_table_or_two_among_other_figures_passes() -> None:
    findings: list = []
    qc._too_many_tables(_items(["table", "atom", "circuit", "flow"]), subject="Integrated Science",
                        findings=findings)
    assert findings == []


def test_an_atom_that_is_not_the_element_in_the_question_is_caught() -> None:
    item = {"question_id": "a1", "question_text": "The figure shows an atom of sulphur. State its electron arrangement.",
            "figure": {"kind": "atom", "protons": 15, "neutrons": 16}}
    findings: list = []
    qc._figure_contradicts_stem([item], findings)
    assert findings and findings[0].kind == "figure_contradicts_stem"

    labelled = {"question_id": "a2", "question_text": "Study the atom below.",
                "figure": {"kind": "atom", "element": "Sulphur", "protons": 15, "neutrons": 16}}
    findings = []
    qc._figure_contradicts_stem([labelled], findings)
    assert findings, "a figure's label and its protons must agree"


def test_an_atom_that_matches_passes_and_a_comparison_is_left_alone() -> None:
    right = {"question_id": "a1", "question_text": "Sulphur has atomic number 16. Study the figure.",
             "figure": {"kind": "atom", "element": "Sulphur", "protons": 16, "neutrons": 16}}
    compare = {"question_id": "a2", "question_text": "Compare sodium and chlorine. The figure shows one of them.",
               "figure": {"kind": "atom", "protons": 17, "neutrons": 18}}
    findings: list = []
    qc._figure_contradicts_stem([right, compare], findings)
    assert findings == []


def test_the_menu_offers_the_new_kinds_and_calls_a_table_the_last_resort() -> None:
    block = fs.prompt_block("Integrated Science")
    for kind in ('"atom"', '"circuit"', '"flow"', '"population_pyramid"', '"map"'):
        assert kind in block, kind
    assert "LAST RESORT" in block
    assert "population pyramid" in fs.prompt_block("Social Studies").split("HOW MANY", 1)[1]

"""How dense a paper prints: presets, knobs, and what they change."""
from __future__ import annotations

from app.services import print_settings as ps


def test_presets_get_tighter_in_order():
    s, c, d = ps.PRESETS["standard"], ps.PRESETS["compact"], ps.PRESETS["dense"]
    assert s.font_pt > c.font_pt > d.font_pt
    assert s.answer_lines > c.answer_lines > d.answer_lines
    assert s.scheme_detail == "full" and c.scheme_detail == "brief" and d.scheme_detail == "key"
    assert not s.split_long_items and c.split_long_items


def test_working_lines_scale_with_the_setting():
    assert ps.PRESETS["standard"].lines_for(5) == 6
    assert ps.PRESETS["compact"].lines_for(5) == 3
    assert ps.PRESETS["dense"].lines_for(5) == 2
    assert ps.PRESETS["compact"].lines_for(1) == 1, "never zero for a written item"


def test_query_params_pick_a_preset_and_move_knobs_within_limits():
    s = ps.from_params({"density": "compact", "font_pt": "9", "columns": "1", "margins_mm": "2",
                        "scheme_detail": "key", "split_long_items": "false", "nonsense": "x"})
    assert s.font_pt == 9.0 and s.columns == 1
    assert s.margins_mm == 5.0, "clamped to the floor"
    assert s.scheme_detail == "key" and s.split_long_items is False
    assert s.density == "compact*", "a moved preset says so"
    assert ps.from_params({}) == ps.PRESETS["standard"]
    assert ps.from_params({"density": "bogus"}).density == "standard"


def test_the_css_carries_every_knob_and_round_trips_through_a_query_string():
    s = ps.from_params({"density": "compact", "font_pt": "8"})
    css = s.css()
    assert "font-size: 8pt" in css and "margin: 9mm 9mm 11mm" in css
    assert ".exam .q.long { break-inside: auto" in css
    assert "column-count: 2" in css
    again = ps.from_params(dict(kv.split("=") for kv in ps.query_string(s).split("&")))
    assert again.font_pt == 8.0 and again.scheme_detail == "brief" and again.split_long_items


def test_the_paper_renders_with_settings_and_the_scheme_detail_changes_what_prints():
    from app.services import paper_builder, question_paper

    q = {"question_id": "q1", "question_type": "multiple_choice", "status": "draft",
         "question_text": "Work out $(-6) \\times (-4) + (-32) \\div 8$.",
         "options": [{"id": "A", "text": "20", "is_correct": True, "distractor_rationale": "Right: 24 - 4."},
                     {"id": "B", "text": "-20", "distractor_rationale": "Sign slip on the product."}],
         "pedagogy": {"max_marks": 1}, "curriculum": {"strand": "Numbers", "sub_strand": "Integers"},
         "marking_scheme": "A1 for 20"}
    w = {"question_id": "q2", "question_type": "structured_scenario", "status": "draft",
         "question_text": "A diver at $-18$ m rises $7$ m. Where is she?",
         "structured_parts": [{"part_id": "(a)", "sub_question": "Write the sum.", "marks": 1, "model_answer": "-18 + 7"},
                              {"part_id": "(b)", "sub_question": "Work it out.", "marks": 3, "model_answer": "-11"}],
         "pedagogy": {"max_marks": 4}, "curriculum": {"strand": "Numbers", "sub_strand": "Integers"},
         "marking_scheme": "M1 sum; A1 -11"}
    paper = paper_builder.compose([q, w], kind="topical", grade="grade-9", subject="Mathematics",
                                  sub_strand="Integers", count=8, allow_drafts=True)
    assert len(paper.items) == 2, paper.shortfall
    full = question_paper.render_paper(paper, with_scheme=True, settings=ps.PRESETS["standard"])
    brief = question_paper.render_paper(paper, with_scheme=True, settings=ps.PRESETS["compact"])
    key = question_paper.render_paper(paper, with_scheme=True, settings=ps.PRESETS["dense"])
    assert "Why not" in full and "Why not" not in brief and "Why not" not in key
    assert "A1 for 20" in brief and "A1 for 20" not in key
    assert "font-size: 8.4pt" in brief
    # The long written item is marked so compact may break it across columns.
    assert "class='q long'" in brief
    # Working lines under the written item shrink with the preset.
    assert full.count("<div></div>") > brief.count("<div></div>") > 0

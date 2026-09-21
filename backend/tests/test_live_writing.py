"""The batch on the screen as it is written, and figures that are not drawn."""
from __future__ import annotations

from app.services import figure_sketch, run_log


def test_previews_track_each_item_through_the_run():
    log = run_log.start("job-1")
    run_log.preview_questions([{"display_label": "Q1", "question_text": "Work out 3 + 4.", "question_type": "multiple_choice",
                                "figure": {"kind": "number_line"}},
                               {"display_label": "Q2", "question_text": "Explain.", "question_type": "short_answer"}], "written")
    run_log.preview("Q2", status="flagged", why="Q2 is Q1 again")
    run_log.preview_questions([{"display_label": "Q2", "question_text": "A better one.", "question_type": "short_answer"}], "rewritten")
    run_log.preview_questions([{"display_label": "Q1", "question_id": "q-abc"}], "saved")
    d = log.to_dict()
    by = {i["key"]: i for i in d["items"]}
    assert by["Q1"]["status"] == "saved" and by["Q1"]["question_id"] == "q-abc" and by["Q1"]["figure"] == "number_line"
    assert by["Q2"]["status"] == "rewritten" and by["Q2"]["stem"] == "A better one." and by["Q2"]["why"] == "Q2 is Q1 again"
    run_log.stop()
    run_log.preview("Q9", status="written")  # no run: a no-op, never an error


def test_emoji_groups_draw_locally():
    out = figure_sketch.render({"kind": "emoji", "items": [{"glyph": "🐔", "count": 9, "label": "hens"}, {"glyph": "🥚", "count": 12, "label": "eggs"}], "per_row": 6})
    assert out and out["svg"].count("🐔") == 9 and out["svg"].count("🥚") == 12
    assert "hens" in out["svg"] and out["kind"] == "emoji"
    assert figure_sketch.render({"kind": "emoji", "items": []}) is None


def test_a_photo_figure_is_fetched_credited_and_filed_or_dropped(monkeypatch):
    from app.services import open_images, platform_settings

    monkeypatch.setattr(platform_settings, "get", lambda key, default=None: default)
    monkeypatch.setattr(open_images, "fetch", lambda query: {
        "svg": f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><image href='data:image/jpeg;base64,AA'/><text>{query} — Someone · CC BY-SA 4.0</text></svg>",
        "title": query, "alt_text": "Photograph", "kind": "image", "credit": f"{query} — Someone · CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:x.jpg", "licence": "CC BY-SA 4.0", "scene": {"title": query, "parts": []}})
    out = figure_sketch.render({"kind": "image", "query": "maize plant Kenya farm"})
    assert out and "CC BY-SA" in out["svg"] and out["title"] == "maize plant Kenya farm"

    monkeypatch.setattr(open_images, "fetch", lambda query: None)
    assert figure_sketch.render({"kind": "photo", "query": "nothing at all"}) is None, "no photo → the item goes on without one"

    monkeypatch.setattr(platform_settings, "get", lambda key, default=None: False if key == "open_images_enabled" else default)
    assert figure_sketch.render({"kind": "image", "query": "maize"}) is None


def test_commons_search_keeps_only_reusable_bitmaps(monkeypatch):
    import io
    import json
    import urllib.request

    from app.services import open_images

    payload = {"query": {"pages": {
        "1": {"title": "File:Maize.jpg", "imageinfo": [{"thumburl": "http://x/1.jpg", "mime": "image/jpeg", "thumbwidth": 720, "thumbheight": 480,
                                                        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a href='#'>Amina</a>"}}}]},
        "2": {"title": "File:Closed.jpg", "imageinfo": [{"thumburl": "http://x/2.jpg", "mime": "image/jpeg",
                                                         "extmetadata": {"LicenseShortName": {"value": "Fair use"}}}]},
        "3": {"title": "File:Map.svg", "imageinfo": [{"thumburl": "http://x/3.png", "mime": "image/svg+xml",
                                                      "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]},
    }}}

    class _R(io.BytesIO):
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: _R(json.dumps(payload).encode()))
    got = open_images.search("maize")
    assert [g["title"] for g in got] == ["Maize.jpg", "Map.svg"], "fair use is out; an SVG bitmap thumb is fine"
    assert got[0]["author"] == "Amina" and got[0]["licence"] == "CC BY-SA 4.0"

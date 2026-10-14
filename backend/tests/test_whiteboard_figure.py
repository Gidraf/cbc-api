"""The item's figure is drawn in its whiteboard video, straight after the question."""
from app.services import question_paper, whiteboard

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 300"><rect x="108" y="20" width="24" height="220"/></svg>'
BINDING = {"diagram_id": "diag-thermo", "diagram_title": "Thermometer", "hide_layers": []}


def _q(binding=BINDING):
    return {"question_id": "q1", "question_text": "What was the noon temperature?", "diagram": binding}


def _walk():
    return {"scenes": [{"scene": "title", "text": "What was the noon temperature?", "say": "x"},
                       {"scene": "working", "text": "-4 + 9 = 5", "say": "y"}]}


def test_the_figure_is_drawn_straight_after_the_question(monkeypatch):
    monkeypatch.setattr(question_paper, "figures_for", lambda qs: {"diag-thermo": {"svg_markup": SVG, "scene_document": {}}})
    data = whiteboard.with_figure(_walk(), _q())
    kinds = [sc["scene"] for sc in data["scenes"]]
    assert kinds == ["title", "figure", "working"]
    fig = data["scenes"][1]
    assert fig["svg"].startswith("<svg") and "Thermometer" in fig["say"]


def test_no_figure_leaves_the_walkthrough_alone(monkeypatch):
    monkeypatch.setattr(question_paper, "figures_for", lambda qs: {})
    assert whiteboard.with_figure(_walk(), _q()) == _walk()
    assert whiteboard.with_figure(_walk(), _q(None)) == _walk()


def test_a_figure_that_cannot_be_loaded_never_stops_the_video(monkeypatch):
    def boom(qs):
        raise RuntimeError("registry down")
    monkeypatch.setattr(question_paper, "figures_for", boom)
    assert whiteboard.with_figure(_walk(), _q()) == _walk()


def test_the_figure_changes_the_video_key(monkeypatch):
    """A video made before the figure was drawn is remade, not reused."""
    monkeypatch.setattr(question_paper, "figures_for", lambda qs: {"diag-thermo": {"svg_markup": SVG, "scene_document": {}}})
    assert whiteboard.cache_key(whiteboard.with_figure(_walk(), _q()), "en-KE") != whiteboard.cache_key(_walk(), "en-KE")


def test_figure_markup_is_the_bare_svg_and_the_paper_still_wraps_it():
    assets = {"diag-thermo": {"svg_markup": SVG, "scene_document": {}}}
    assert question_paper.figure_markup(_q(), assets).startswith("<svg")
    assert question_paper._figure(_q(), assets).startswith("<div class='figure-inline'>")
    assert question_paper.figure_markup(_q(), {}) == ""
    assert "Refer to Thermometer" in question_paper._figure(_q(), {})


def test_the_board_engine_has_a_figure_scene():
    assert "figure(s, at, dur)" in (whiteboard.STATIC / "whiteboard.js").read_text()

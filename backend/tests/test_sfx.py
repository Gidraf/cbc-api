"""Sound effects: the page lists them, the server synthesises the same recipes."""
from __future__ import annotations

import wave

from app.services import sfx


def test_the_track_holds_each_sound_at_its_time(tmp_path) -> None:
    events = [{"t": 0.5, "kind": "whoosh", "gain": 0.8}, {"t": 1.2, "kind": "ding"}, {"t": 2.0, "kind": "pop", "pitch": 1.3},
              {"t": 99, "kind": "pop"}]                         # past the end: left out
    path = sfx.track(events, 3.0, tmp_path / "s.wav")
    with wave.open(str(path)) as w:
        assert w.getframerate() == sfx.RATE and abs(w.getnframes() / sfx.RATE - 4.0) < 0.01
        frames = w.readframes(w.getnframes())
    quiet = frames[: int(0.4 * sfx.RATE) * 2]
    assert not any(quiet) and any(frames[int(0.6 * sfx.RATE) * 2:int(0.9 * sfx.RATE) * 2])


def test_no_sounds_no_track(tmp_path) -> None:
    assert sfx.track([], 5, tmp_path / "s.wav") is None


def test_every_recipe_the_page_can_ask_for_exists() -> None:
    import re
    from pathlib import Path

    js = (Path(__file__).parents[1] / "app/static/sfx.js").read_text()
    kinds = set(re.findall(r"^\s{4}(\w+): \(k", js, re.M))
    assert kinds >= {"whoosh", "pop", "ding", "chime", "zap", "snap", "thud", "fizz", "drip", "sparkle", "flame", "click", "riser", "tick"}
    for k in kinds:
        assert len(sfx.recipe(k)) > 100


def test_a_chemistry_page_carries_its_sounds_and_the_atomic_world() -> None:
    from app.services import play_engine, whiteboard

    w = play_engine.walkthrough({"question_id": "x", "question_text": "?", "chemistry": {"bond": ["Na", "Cl"]},
                                 "curriculum": {"subject": "Chemistry"}})
    page = whiteboard.page(w, title="t", voice="en-GB", durations=[4.0] * len(w["scenes"]))
    assert "window.sfxAt" in page and "window.__sfx3d = sounds" in page and "__sfxTick" in page

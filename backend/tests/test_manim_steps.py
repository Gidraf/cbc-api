"""Manim takes the working: which scenes, how long each, where on the frame."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import manim_steps, play_engine

STEPS = play_engine.structured_steps("18 ÷ (-3) × 2 + (-24) - (-5)")


def _scenes() -> list[dict]:
    return ([{"scene": "title", "text": "q"}, {"scene": "setup", "expression": STEPS[0]["before"]}]
            + [{"scene": "rewrite", "step": s} for s in STEPS]
            + [{"scene": "answer", "text": "-31"}, {"scene": "check"}, {"scene": "outro"}])


def test_the_working_and_its_answer_are_one_run_the_question_stays_on_the_board() -> None:
    sc = _scenes()
    assert manim_steps.runs(sc) == [(1, 7)]
    assert manim_steps.runs([{"scene": "setup", "expression": "1+2"}, {"scene": "answer", "text": "3"}]) == [], \
        "a setup alone is the board's"
    assert manim_steps.runs([{"scene": "rewrite", "step": {"before": "x"}}]) == [], "half a step is never animated"


def test_each_beat_lasts_its_narration_and_the_board_skips_those_scenes(tmp_path: Path, monkeypatch) -> None:
    seen = {}

    def render(scenes, seconds, folder, fps):
        seen.update(scenes=scenes, seconds=seconds)
        return tmp_path / "clip.mp4"

    monkeypatch.setattr(manim_steps, "render_run", render)
    sc = _scenes()
    durations = [3.0, 2.0, 4.0, 4.0, 4.0, 4.0, 2.5, 2.0, 3.0]
    starts = [0.3 + sum(d + 0.4 for d in durations[:k]) for k in range(len(durations))]
    marked, clips = manim_steps.plan(sc, durations, starts, tmp_path, 20)
    assert seen["seconds"] == pytest.approx([d + 0.4 for d in durations[1:7]])
    assert [bool(s.get("manim")) for s in marked] == [False] + [True] * 6 + [False, False]
    (clip, start, end), = clips
    assert start == pytest.approx(starts[1]) and end == pytest.approx(starts[7])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_clip_lands_inside_the_boards_box_only_while_it_plays(tmp_path: Path) -> None:
    ff = shutil.which("ffmpeg")
    board, clip = tmp_path / "board.mp4", tmp_path / "clip.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x101828:s=1080x1920:d=4:r=20",
                    "-pix_fmt", "yuv420p", str(board)], check=True)
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=1280x720:d=1:r=20",
                    "-pix_fmt", "yuv420p", str(clip)], check=True)
    out = tmp_path / "out.mp4"
    assert manim_steps.overlay(ff, board, [(clip, 1.0, 2.0)], manim_steps.BOX_SOCIAL, out)

    def pixel(t: float, x: int, y: int) -> tuple[int, ...]:
        raw = subprocess.run([ff, "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1",
                              "-vf", f"crop=2:2:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, check=True).stdout
        return tuple(raw[:3])

    assert pixel(1.5, 520, 740)[0] > 200, "inside the board's box, while it plays: the clip"
    assert pixel(1.5, 41, 471)[0] < 80, "the board's rounded corner stays the frame's"
    assert pixel(1.5, 520, 300)[0] < 80, "above the board: the frame"
    assert pixel(3.0, 520, 740)[0] < 80, "after the clip: the board again"

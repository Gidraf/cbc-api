"""The working of a question, animated with Manim — from the maths engine's
own steps, never from a model.

    MANIM_SPEC=spec.json manim -r 1280,720 --fps 20 app/manim_board.py Board

The spec (services/manim_steps.py writes it) is a list of beats, each one of
the engine's scenes with how long it must last, so the clip keeps time with
the narration it is laid under:

    rewrite          the expression; the part done next ringed; its sum worked
                     beside it; then that part becomes its result in place
    number_line_*    the line, the start, each jump an arc to where it lands
    balance_*        the equation; the same thing done to both sides; the next
                     line; the unknown alone, boxed
    fraction_bars    two bars, cut to a common size, joined
    answer           the result, boxed

Nothing here decides anything about the maths: the engine already did. This
only moves the symbols the way a teacher would on a board.
"""
from __future__ import annotations

import json
import os
import re
from fractions import Fraction

from manim import (DOWN, LEFT, ORIGIN, RIGHT, UP, Arc, Create, CurvedArrow, Dot, FadeIn, FadeOut, Flash,
                   GrowFromCenter, Indicate, Line, MathTex, MoveAlongPath, NumberLine, Rectangle, ReplacementTransform,
                   Scene, SurroundingRectangle, Tex, TransformMatchingTex, VGroup, Write, config)

INK, BLUE, RED, GREEN, AMBER, GREY = "#1b1f2a", "#1d4ed8", "#c2410c", "#15803d", "#d97706", "#6b7280"
OP_COLOUR = {"\\times": BLUE, "\\div": BLUE, "+": GREEN, "-": RED}
config.background_color = "#fdfdfb"
# A plain article, not Manim's default `standalone` class: the basic LaTeX
# packages are enough (texlive-latex-base + recommended), so the server image
# does without texlive-latex-extra, the biggest of them. dvisvgm crops to the ink.
from manim import TexTemplate  # noqa: E402

config.tex_template = TexTemplate(documentclass=r"\documentclass{article}",
                                  preamble=r"\usepackage{amsmath}\usepackage{amssymb}"
                                           r"\pagestyle{empty}")


import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))     # backend/, run as a script by manim
from app.services.step_tex import mixed_tex, num_tex, op_tex, split_on, tex_of  # noqa: E402


class Board(Scene):
    def construct(self):
        spec = json.loads(open(os.environ["MANIM_SPEC"]).read())
        self.expr = None          # the expression on the board now
        self.line = None          # the number line, while it is up
        for beat in spec["beats"]:
            try:
                used = getattr(self, f"beat_{beat['scene']}", self.beat_hold)(beat, float(beat["seconds"]))
            except Exception as exc:  # noqa: BLE001
                # One step LaTeX cannot set: the board stays as it is for its time.
                print(f"beat {beat.get('scene')} skipped: {exc}")
                used = 0.0
            left = float(beat["seconds"]) - used
            if left > 0.01:
                self.wait(left)

    # ── helpers ──
    def _place(self, mob, y: float = 1.2):
        """A line of working, as big as the board allows: up to 12.5 wide,
        never taller than 1.7 — a phone shows the board small."""
        mob.set_color(INK)
        k = min(12.5 / max(mob.width, 0.01), 1.7 / max(mob.height, 0.01))
        mob.scale(k)
        return mob.move_to(UP * y)

    def _clear(self):
        if self.mobjects:
            self.play(*[FadeOut(m) for m in self.mobjects], run_time=0.3)
            self.expr, self.line = None, None
            return 0.3
        return 0.0

    def beat_hold(self, beat, seconds):
        return 0.0

    # ── the calculation, step by step ──
    def beat_setup(self, beat, seconds):
        used = self._clear()
        tex = tex_of(beat.get("expression") or "")
        self.expr = self._place(MathTex(tex, font_size=72))
        self.expr._tex = tex
        t = min(1.4, seconds * 0.5)
        self.play(Write(self.expr), run_time=t)
        return used + t

    def beat_rewrite(self, beat, seconds):
        step = beat["step"]
        before, after = step["before"], step["after"]
        used = 0.0
        parts = split_on(before, step["left"], step["op"], step["right"])
        if self.expr is None or getattr(self.expr, "_tex", "") != before:
            used += self._clear()
            whole = self._place(MathTex(before, font_size=72))
            whole._tex = before
            self.play(FadeIn(whole), run_time=0.4)
            self.expr, used = whole, used + 0.4
        if not parts:
            nxt = self._place(MathTex(after, font_size=72))
            nxt._tex = after
            self.play(TransformMatchingTex(self.expr, nxt), run_time=min(1.0, seconds * 0.4))
            self.expr = nxt
            return used + min(1.0, seconds * 0.4)
        pre, mid, post = parts
        colour = OP_COLOUR.get(op_tex(step["op"]), AMBER)
        pieces = [p for p in (pre, mid, post) if p.strip()]
        split = self._place(MathTex(*pieces, font_size=72))
        k = pieces.index(mid)
        self.remove(self.expr)
        self.add(split)
        ring = SurroundingRectangle(split[k], color=colour, buff=0.12, corner_radius=0.08)
        right = num_tex(step["right"])
        right = f"({right})" if str(step["right"]).startswith("-") else right
        side = MathTex(num_tex(step["left"]), op_tex(step["op"]), right, "=", num_tex(step["result"]),
                       font_size=52, color=colour).next_to(split, DOWN, buff=0.9)
        a = min(0.5, seconds * 0.12)
        self.play(Create(ring), split[k].animate.set_color(colour), run_time=a)
        b = min(1.2, seconds * 0.28)
        self.play(Write(side), run_time=b)
        hold = max(0.0, seconds - a - b - 1.2 - used)
        if hold > 0.3:
            self.wait(min(hold, 1.2))
            used += min(hold, 1.2)
        # The part becomes its result, where it stood.
        res = num_tex(step["result"])
        if str(step["result"]).startswith("-") and pre.rstrip().endswith(("+", "-", r"\times", r"\div")):
            res = f"({res})"
        new_pieces = [p for p in (pre, res, post) if p.strip()]
        nxt = self._place(MathTex(*new_pieces, font_size=72))
        c = min(0.9, seconds * 0.22)
        moves = [ReplacementTransform(split[i], nxt[i]) for i in range(len(pieces))]
        self.play(*moves, FadeOut(ring), FadeOut(side, shift=UP * 0.3), run_time=c)
        # Only the new line stays: the old one's frame goes with its parts.
        self.remove(split, *split.submobjects)
        self.add(nxt)
        nxt._tex = after
        self.expr = nxt
        return used + a + b + c

    # ── a number line ──
    def beat_number_line_start(self, beat, seconds):
        used = self._clear()
        sp = beat["spec"]
        lo, hi, tick = int(sp["min"]), int(sp["max"]), int(sp.get("tick") or 1)
        line = NumberLine(x_range=[lo, hi, tick], length=12.5, include_numbers=True, font_size=36, color=INK,
                          stroke_width=3,
                          decimal_number_config={"color": INK, "num_decimal_places": 0}).shift(DOWN * 0.6)
        dot = Dot(line.n2p(sp["start"]), color=BLUE, radius=0.13)
        label = MathTex(num_tex(sp["start"]), color=BLUE, font_size=44).next_to(dot, DOWN, buff=0.55)
        a = min(1.2, seconds * 0.4)
        self.play(Create(line), run_time=a)
        self.play(GrowFromCenter(dot), FadeIn(label), run_time=0.5)
        self.line, self.dot, self.dot_label = line, dot, label
        return used + a + 0.5

    def beat_number_line_jump(self, beat, seconds):
        if self.line is None:
            used = self.beat_number_line_start({"spec": beat["spec"]}, 1.7)
        else:
            used = 0.0
        a, b = self.line.n2p(beat["from"]), self.line.n2p(beat["to"])
        colour = GREEN if beat["move"] > 0 else RED
        arc = CurvedArrow(a + UP * 0.2, b + UP * 0.2, color=colour, angle=-1.2 if beat["move"] > 0 else 1.2,
                          stroke_width=6)
        arc.set_fill(opacity=0)
        arc.tip.set_fill(colour, opacity=1)
        tag = MathTex(("+" if beat["move"] > 0 else "") + str(beat["move"]), color=colour, font_size=44)
        tag.next_to(arc, UP, buff=0.15)
        path = Arc(start_angle=0, angle=0)  # placeholder for type
        path = arc.copy()
        t = min(1.4, seconds * 0.45)
        self.play(Create(arc), FadeIn(tag), MoveAlongPath(self.dot, path), run_time=t)
        land = MathTex(num_tex(beat["to"]), color=colour, font_size=44).next_to(self.dot, DOWN, buff=0.55)
        self.play(ReplacementTransform(self.dot_label, land), Indicate(self.dot, color=colour), run_time=0.5)
        self.dot.move_to(b)
        self.dot_label = land
        self.play(arc.animate.set_opacity(0.35), tag.animate.set_opacity(0.5), run_time=0.2)
        return used + t + 0.7

    # ── an equation, balanced ──
    def _equation(self, left: str, right: str, size: int = 64):
        return self._place(MathTex(tex_of(left), "=", tex_of(right), font_size=size), y=0.8)

    def beat_balance_start(self, beat, seconds):
        used = self._clear()
        sp = beat["spec"]
        eq = self._equation(sp["left"], sp["right"])
        beam = Line(LEFT * 4.5, RIGHT * 4.5, color=GREY, stroke_width=6).next_to(eq, DOWN, buff=0.5)
        pivot = MathTex(r"\triangle", color=GREY, font_size=60).next_to(beam, DOWN, buff=0.05)
        t = min(1.3, seconds * 0.45)
        self.play(Write(eq), Create(beam), FadeIn(pivot), run_time=t)
        self.expr, self.beam = eq, VGroup(beam, pivot)
        self.balance_step = 0
        return used + t

    def beat_balance_move(self, beat, seconds):
        sp, move = beat["spec"], beat["move"]
        k = getattr(self, "balance_step", 0)
        if self.expr is None:
            self.beat_balance_start({"spec": sp}, 1.3)
        cur_left, cur_right = (sp["states"][k - 1] if k > 0 else [sp["left"], sp["right"]])
        op = op_tex(move["op"])
        colour = OP_COLOUR.get(op, AMBER)
        both = self._place(MathTex(tex_of(cur_left), f"{op} {tex_of(move['value'])}", "=", tex_of(cur_right),
                                   f"{op} {tex_of(move['value'])}", font_size=60), y=0.8)
        both[1].set_color(colour); both[4].set_color(colour)
        a = min(1.0, seconds * 0.3)
        self.play(TransformMatchingTex(self.expr, both), self.beam.animate.rotate(0.06).rotate(-0.06), run_time=a)
        self.wait(min(0.6, max(0.0, seconds * 0.2)))
        left, right = sp["states"][k]
        nxt = self._equation(left, right)
        b = min(0.9, seconds * 0.25)
        self.play(TransformMatchingTex(both, nxt), run_time=b)
        self.expr, self.balance_step = nxt, k + 1
        return a + min(0.6, max(0.0, seconds * 0.2)) + b

    def beat_balance_done(self, beat, seconds):
        if self.expr is None:
            return 0.0
        box = SurroundingRectangle(self.expr, color=GREEN, buff=0.2, corner_radius=0.1)
        self.play(Create(box), Flash(box.get_corner(UP + RIGHT), color=GREEN), run_time=0.8)
        return 0.8

    # ── fraction bars ──
    def _bar(self, parts: int, shaded: int, colour: str, width: float = 9.0):
        cells = VGroup(*[Rectangle(width=width / parts, height=0.7, stroke_color=INK, stroke_width=2,
                                   fill_color=colour, fill_opacity=0.75 if k < shaded else 0.0)
                         for k in range(parts)]).arrange(RIGHT, buff=0)
        return cells

    def beat_fraction_bars(self, beat, seconds):
        sp, phase = beat["spec"], beat.get("phase")
        (a, b), (c, d) = sp["first"], sp["second"]
        if phase == "start":
            used = self._clear()
            top = self._bar(b, a, BLUE).move_to(UP * 1.2)
            bottom = self._bar(d, c, RED).move_to(DOWN * 0.4)
            la = MathTex(rf"\frac{{{a}}}{{{b}}}", color=BLUE, font_size=52).next_to(top, LEFT)
            lc = MathTex(rf"\frac{{{c}}}{{{d}}}", color=RED, font_size=52).next_to(bottom, LEFT)
            t = min(1.5, seconds * 0.45)
            self.play(Create(top), Create(bottom), Write(la), Write(lc), run_time=t)
            self.bars = (top, bottom, la, lc)
            return used + t
        if not getattr(self, "bars", None):
            self.beat_fraction_bars({**beat, "phase": "start"}, 1.6)
        top, bottom, la, lc = self.bars
        n = sp["common"]
        if phase == "common":
            ta, tc = sp["first_as"][0], sp["second_as"][0]
            top2 = self._bar(n, ta, BLUE).move_to(top)
            bottom2 = self._bar(n, tc, RED).move_to(bottom)
            la2 = MathTex(rf"\frac{{{ta}}}{{{n}}}", color=BLUE, font_size=52).next_to(top2, LEFT)
            lc2 = MathTex(rf"\frac{{{tc}}}{{{n}}}", color=RED, font_size=52).next_to(bottom2, LEFT)
            t = min(1.6, seconds * 0.45)
            self.play(ReplacementTransform(top, top2), ReplacementTransform(bottom, bottom2),
                      ReplacementTransform(la, la2), ReplacementTransform(lc, lc2), run_time=t)
            self.bars = (top2, bottom2, la2, lc2)
            return t
        # The result: one bar.
        rn, rd = sp["result"]
        width_parts = max(n, rd)
        joined = self._bar(n, min(n, sp["first_as"][0] + (sp["second_as"][0] if sp["op"] == "+" else -sp["second_as"][0])),
                           GREEN).move_to(DOWN * 2.0)
        lr = MathTex(rf"= \frac{{{rn}}}{{{rd}}}" if rd != 1 else f"= {rn}", color=GREEN, font_size=56).next_to(joined, RIGHT)
        t = min(1.5, seconds * 0.45)
        self.play(FadeIn(joined, shift=DOWN * 0.3), Write(lr), run_time=t)
        self.play(Indicate(lr, color=GREEN), run_time=0.6)
        return t + 0.6 + 0 * width_parts

    # ── the answer ──
    def beat_answer(self, beat, seconds):
        text = beat.get("text") or ""
        plain = str(text).strip()
        tex = (num_tex(plain) if re.fullmatch(r"-?\d+(/\d+)?", plain)
               else mixed_tex(plain) if "$" in plain or re.search(r"[A-Za-z]{2,}", plain) else tex_of(plain))
        if beat.get("option"):
            tex = rf"\text{{{beat['option']}}}:\ " + tex
        ans = MathTex(tex, font_size=72, color=GREEN)
        ans.scale(min(10.5 / max(ans.width, 0.01), 1.6 / max(ans.height, 0.01)))
        if self.expr is not None and self.line is None:
            ans.move_to(self.expr)
            self.play(ReplacementTransform(self.expr, ans), run_time=0.7)
            self.remove(*[m for m in self.mobjects if m is not ans])
            self.add(ans)
        else:
            ans.move_to(DOWN * 2.3 if self.line is not None else UP * 0.6)
            self.play(Write(ans), run_time=0.7)
        box = SurroundingRectangle(ans, color=GREEN, buff=0.25, corner_radius=0.12)
        self.play(Create(box), Flash(box.get_corner(UP + RIGHT), color=GREEN, flash_radius=0.4), run_time=0.7)
        self.expr = ans
        return 1.4


__all__ = ["Board", "ORIGIN", "Tex"]

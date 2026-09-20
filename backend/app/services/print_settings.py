"""How dense a paper prints.

The national design is generous — 9.6 pt, two or three lines a mark for
working, wide margins — and a Grade 9 term paper with its scheme ran to
fifteen pages. Sold as printouts, that is fifteen sheets a copy. The same
paper at 8.4 pt with the working space halved is seven, and reads fine.

Every knob is a number the builder can move and see; the presets are only
starting points. Everything here is CSS: the paper's HTML does not change.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True)
class PrintSettings:
    density: str = "standard"      # the preset this started from; informational
    font_pt: float = 9.6           # body text
    line_height: float = 1.32
    margins_mm: float = 12.0
    columns: int = 2               # 1 or 2, Section A and the scheme
    answer_lines: float = 1.0      # multiplier on the working lines under a written item
    line_mm: float = 5.2           # height of one working line
    question_gap_px: float = 7.0   # space between items
    figure_max_mm: float = 64.0    # tallest a question figure prints
    masthead_scale: float = 1.0    # the head of the paper, relative
    scheme_font_pt: float = 0.0    # 0 = 0.9 × font_pt
    # full: engine steps, rationale, why-not (a learner marks their own);
    # brief: the scheme's own lines; key: the answer alone.
    scheme_detail: str = "full"
    # A long Section B item may continue in the next column rather than
    # leave the rest of a page blank to stay whole.
    split_long_items: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def scheme_pt(self) -> float:
        return self.scheme_font_pt or round(self.font_pt * 0.9, 1)

    def lines_for(self, marks: float) -> int:
        """Working lines under a written item worth `marks`."""
        base = 2 if marks <= 2 else min(6, int(marks) + 1)
        return max(1, int(round(base * self.answer_lines)))

    def css(self) -> str:
        m = self.masthead_scale
        return f"""
@page {{ margin: {self.margins_mm:g}mm {self.margins_mm:g}mm {self.margins_mm + 2:g}mm; }}
.exam body, .exam {{ font-size: {self.font_pt:g}pt; line-height: {self.line_height:g}; }}
.exam .cols {{ column-count: {max(1, min(2, self.columns))}; }}
.exam .q {{ margin: 0 0 {self.question_gap_px:g}px; }}
.exam .lines div {{ height: {self.line_mm:g}mm; }}
.exam .fig svg {{ max-height: {self.figure_max_mm:g}mm; }}
.exam .scheme {{ font-size: {self.scheme_pt:g}pt; }}
.exam .mast .assessment {{ font-size: {14 * m:g}pt; }}
.exam .mast .gradeline {{ font-size: {12 * m:g}pt; }}
.exam .mast .subject {{ font-size: {13 * m:g}pt; }}
.exam .mast .kindline {{ font-size: {9.5 * m:g}pt; }}
.exam .rules {{ font-size: {8.4 * min(1.0, m):g}pt; }}
.exam .qno {{ font-size: {self.font_pt * 1.1:g}pt; }}
{".exam .q.long { break-inside: auto; page-break-inside: auto; -webkit-column-break-inside: auto; }" if self.split_long_items else ""}
"""


PRESETS: dict[str, PrintSettings] = {
    "standard": PrintSettings(),
    # About half the pages of standard: smaller type, working space halved,
    # narrower margins, figures a little shorter. Still a paper a learner
    # can write on.
    "compact": PrintSettings(density="compact", font_pt=8.4, line_height=1.22, margins_mm=9.0,
                             answer_lines=0.5, line_mm=4.4, question_gap_px=4.0, figure_max_mm=50.0,
                             masthead_scale=0.85, scheme_detail="brief", split_long_items=True),
    # For a marking scheme or a revision sheet, not for a learner to write on.
    "dense": PrintSettings(density="dense", font_pt=7.8, line_height=1.18, margins_mm=8.0,
                           answer_lines=0.34, line_mm=4.0, question_gap_px=3.0, figure_max_mm=42.0,
                           masthead_scale=0.75, scheme_detail="key", split_long_items=True),
}

_LIMITS: dict[str, tuple[float, float]] = {
    "font_pt": (6.5, 13.0), "line_height": (1.0, 1.8), "margins_mm": (5.0, 25.0), "columns": (1, 2),
    "answer_lines": (0.0, 2.0), "line_mm": (3.0, 9.0), "question_gap_px": (0.0, 20.0),
    "figure_max_mm": (25.0, 120.0), "masthead_scale": (0.5, 1.2), "scheme_font_pt": (0.0, 13.0),
}


def from_params(params: Any) -> PrintSettings:
    """Settings from a query string or a dict: a preset, then any knob by
    name over it. Unknown keys are ignored; out-of-range values clamped."""
    get = params.get if hasattr(params, "get") else (lambda k, d=None: d)
    preset = str(get("density") or get("preset") or "standard").lower()
    settings = PRESETS.get(preset, PRESETS["standard"])
    changes: dict[str, Any] = {}
    for key, (lo, hi) in _LIMITS.items():
        raw = get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        value = max(lo, min(hi, value))
        changes[key] = int(value) if key == "columns" else value
    detail = str(get("scheme_detail") or "").lower()
    if detail in ("full", "brief", "key"):
        changes["scheme_detail"] = detail
    split = get("split_long_items")
    if split not in (None, ""):
        changes["split_long_items"] = str(split).lower() in ("1", "true", "yes", "on")
    if changes:
        settings = replace(settings, **changes)
        if preset not in PRESETS:
            settings = replace(settings, density="custom")
        elif changes:
            settings = replace(settings, density=f"{preset}*")
    return settings


def query_string(settings: PrintSettings) -> str:
    """The settings as query parameters, for a print link."""
    from urllib.parse import urlencode

    base = PRESETS.get(settings.density.rstrip("*"), PRESETS["standard"])
    out: dict[str, Any] = {"density": settings.density.rstrip("*") if settings.density.rstrip("*") in PRESETS else "standard"}
    for key in list(_LIMITS) + ["scheme_detail", "split_long_items"]:
        if getattr(settings, key) != getattr(base, key):
            out[key] = getattr(settings, key)
    return urlencode(out)

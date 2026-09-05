"""A drawing has to READ in the 85mm column, and that is measurable.

The first drawing this station produced looked plausible in a browser tab and
was unusable on the page: 4:3 against a plate reserving 1.85:1, four of its
eight labels lying across the line-work, and a smallest font-size that resolves
to 2.1mm once the figure is scaled into the column — smaller than the caption
printed beside it.

None of that is visible in a thumbnail, and all of it is arithmetic.
"""
from __future__ import annotations

from app.services import diagram_layout

# Verbatim, as the model returned it.
BAD = """
<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg" width="100%">
  <g data-part-id="part-addition" id="addition">
    <text x="50" y="50" font-size="24" font-weight="bold">5 + 3</text>
    <text x="50" y="90" font-size="20">Addition - combines two integers</text>
    <line x1="100" y1="60" x2="150" y2="60" stroke="black" stroke-width="2"/>
    <circle cx="100" cy="60" r="10" fill="none" stroke="black"/>
  </g>
  <g data-part-id="part-division" id="division">
    <text x="50" y="350" font-size="24" font-weight="bold">12 / 3</text>
    <text x="50" y="390" font-size="20">Division - how many times one fits another</text>
    <line x1="100" y1="360" x2="150" y2="360" stroke="black" stroke-width="2"/>
    <circle cx="100" cy="360" r="10" fill="none" stroke="black"/>
  </g>
</svg>
"""

GOOD = """
<svg viewBox="0 0 340 200" xmlns="http://www.w3.org/2000/svg">
  <g data-part-id="part-numerator" id="numerator">
    <rect x="20" y="20" width="130" height="70" fill="#d9e8f5" stroke="#111"/>
    <text x="20" y="110" font-size="14" font-family="Helvetica">Numerator</text>
  </g>
  <g data-part-id="part-denominator" id="denominator">
    <rect x="190" y="20" width="130" height="70" fill="#fff" stroke="#111"/>
    <text x="190" y="110" font-size="14" font-family="Helvetica">Denominator</text>
  </g>
  <g data-part-id="part-bar" id="bar">
    <line x1="20" y1="150" x2="320" y2="150" stroke="#111" stroke-width="2"/>
    <text x="20" y="185" font-size="14" font-family="Helvetica">Dividing bar</text>
  </g>
</svg>
"""


def test_the_drawing_that_shipped_is_caught_on_every_count() -> None:
    fit = diagram_layout.measure(BAD)

    assert not fit.ok
    faults = " ".join(fit.findings)
    assert "1.33:1" in faults, "the shape it renders at is named, not just wrong"
    assert "reflows" in faults
    assert "font-size 20" in faults and "2.1mm" in faults
    assert "sit on top of" in faults
    # And the numbers an operator sees on the panel.
    assert fit.collisions == 2 and fit.texts == 4


def test_a_drawing_built_to_the_brief_passes() -> None:
    fit = diagram_layout.measure(GOOD)

    assert fit.ok, fit.findings
    assert 1.4 <= fit.aspect <= 2.4
    assert fit.collisions == 0


def test_a_label_is_measured_from_its_baseline_not_its_top() -> None:
    """`y` on a <text> is the baseline; the glyphs sit ABOVE it. Measuring the
    box downwards reported every caption under a shape as colliding with it,
    and a check that cries wolf on correct drawings gets turned off."""
    below = """<svg viewBox="0 0 340 200">
      <circle cx="60" cy="40" r="20" stroke="#111"/>
      <text x="30" y="90" font-size="14">Below it</text>
    </svg>"""
    assert diagram_layout.measure(below).collisions == 0


def test_text_anchored_middle_is_measured_around_its_point() -> None:
    centred = """<svg viewBox="0 0 340 200">
      <rect x="0" y="120" width="340" height="60" fill="none" stroke="#111"/>
      <text x="170" y="40" font-size="14" text-anchor="middle">Centred title</text>
    </svg>"""
    fit = diagram_layout.measure(centred)
    assert fit.collisions == 0


def test_a_label_smaller_than_the_caption_beside_it_is_rejected() -> None:
    """8.5pt is 3mm, and 3mm of the 85mm column is 3.5% of the viewBox."""
    tiny = """<svg viewBox="0 0 340 200">
      <rect x="12" y="12" width="316" height="120" fill="none" stroke="#111"/>
      <text x="12" y="180" font-size="8">Unreadable</text>
    </svg>"""
    faults = " ".join(diagram_layout.measure(tiny).findings)
    assert "font-size 12" in faults, "it says the size to use, not just 'bigger'"


def test_a_drawing_crowded_into_a_corner_is_rejected() -> None:
    """Empty canvas is not empty page: the figure is scaled to 85mm either
    way, so the blank margin only makes the drawing itself smaller."""
    corner = """<svg viewBox="0 0 340 200">
      <rect x="5" y="5" width="60" height="40" fill="none" stroke="#111"/>
      <text x="5" y="60" font-size="14">Small</text>
    </svg>"""
    assert "blank" in " ".join(diagram_layout.measure(corner).findings)


def test_a_fixed_width_overrides_the_column() -> None:
    fixed = '<svg viewBox="0 0 340 200" width="800"><text x="12" y="100" font-size="14">A</text></svg>'
    assert "fixed width" in " ".join(diagram_layout.measure(fixed).findings)


def test_a_transform_it_cannot_measure_is_reported_rather_than_guessed() -> None:
    """A wrong overlap report is worse than none."""
    rotated = """<svg viewBox="0 0 340 200">
      <g transform="rotate(30 100 100)"><rect x="12" y="12" width="300" height="170"
         fill="none" stroke="#111"/></g>
      <text x="12" y="190" font-size="14">Turned</text>
    </svg>"""
    assert "cannot measure" in " ".join(diagram_layout.measure(rotated).findings)


def test_nonsense_fails_closed() -> None:
    assert not diagram_layout.measure("not an svg").ok
    assert not diagram_layout.measure("<svg><circle r='5'/></svg>").ok


def test_the_corrections_are_addressed_to_the_model_that_drew_it() -> None:
    fit = diagram_layout.measure(BAD)
    text = diagram_layout.corrections(fit)

    assert "REJECTED" in text
    assert text.count("\n  ") >= len(fit.findings)
    assert diagram_layout.corrections(diagram_layout.measure(GOOD)) == ""


def test_a_label_inside_a_panel_is_how_a_textbook_sets_a_label() -> None:
    """The first version of this check called every intersection a collision,
    and rejected a correctly panelled drawing along with the broken one. A
    check that fails good work is a check somebody turns off."""
    panelled = """<svg viewBox="0 0 340 200">
      <g data-part-id="part-addition" id="addition">
        <rect x="12" y="12" width="150" height="80" fill="#d9e8f5" stroke="#111"/>
        <text x="87" y="40" font-size="15" text-anchor="middle">5 + 3 = 8</text>
        <text x="87" y="84" font-size="13" text-anchor="middle">Addition</text>
      </g>
      <g data-part-id="part-groups" id="groups">
        <rect x="178" y="12" width="150" height="176" fill="#fff" stroke="#111"/>
        <text x="253" y="40" font-size="15" text-anchor="middle">12 / 3 = 4</text>
      </g>
      <rect x="12" y="106" width="150" height="82" fill="none" stroke="#111"/>
      <text x="87" y="150" font-size="13" text-anchor="middle">Array</text>
    </svg>"""
    fit = diagram_layout.measure(panelled)

    assert fit.collisions == 0, fit.findings
    assert fit.ok, fit.findings


def test_a_panel_does_not_licence_lying_across_the_line_work_inside_it() -> None:
    """Being in the box is not being in the clear."""
    crossed = """<svg viewBox="0 0 340 200">
      <rect x="12" y="12" width="316" height="176" fill="#fff" stroke="#111"/>
      <line x1="20" y1="100" x2="320" y2="100" stroke="#111" stroke-width="2"/>
      <text x="40" y="104" font-size="14">On the rule</text>
    </svg>"""
    assert diagram_layout.measure(crossed).collisions == 1


def test_a_background_rectangle_cannot_absolve_the_whole_drawing() -> None:
    """Wrap everything in one full-canvas rect and every label is "inside a
    panel". The brief forbids that rectangle; this makes forbidding it stick.

    The label here runs across a small circle's EDGE — half on the line, half
    off it — which is the unreadable case, and the background rect must not
    excuse it. (A label sitting wholly inside a large circle is a labelled
    node, and is left alone.)
    """
    hidden = """<svg viewBox="0 0 340 200">
      <rect x="0" y="0" width="340" height="200" fill="#eee"/>
      <circle cx="100" cy="100" r="15" fill="none" stroke="#111"/>
      <text x="70" y="105" font-size="14">Across it</text>
    </svg>"""
    assert diagram_layout.measure(hidden).collisions == 1


# ── wrapped labels ──────────────────────────────────────────────────────────


def test_each_tspan_line_is_measured_where_it_actually_lands() -> None:
    """The brief asks for <tspan> wrapping, and the first version of this check
    read x/y off the parent <text> only — so a three-line label collapsed to
    one box at the parent's own coordinates, and a drawing whose later lines
    ran off the canvas passed. The check has to measure the thing it asked
    for."""
    wrapped = """<svg viewBox="0 0 340 200">
      <rect x="12" y="12" width="316" height="140" fill="none" stroke="#111"/>
      <text x="20" y="170" font-size="14">
        <tspan x="20" dy="0">First line here</tspan>
        <tspan x="20" dy="16">Second line runs off</tspan>
        <tspan x="20" dy="16">Third line is gone</tspan>
      </text>
    </svg>"""
    faults = " ".join(diagram_layout.measure(wrapped).findings)

    assert "outside the 340×200 viewBox" in faults
    assert "205" in faults, "it names where the last line actually ended up"


def test_a_tspan_inherits_x_from_the_line_above_it() -> None:
    """A <tspan> with only `dy` keeps the previous x. Resetting it to zero
    reported every wrapped label as running off the left edge."""
    wrapped = """<svg viewBox="0 0 340 200">
      <text x="120" y="30" font-size="14">
        <tspan x="120" dy="0">Line one</tspan>
        <tspan dy="18">Line two</tspan>
      </text>
      <rect x="12" y="70" width="316" height="118" fill="none" stroke="#111"/>
    </svg>"""
    fit = diagram_layout.measure(wrapped)

    assert fit.texts == 2, "two lines, measured as two"
    assert not any("outside" in f for f in fit.findings), fit.findings
    assert fit.ok, fit.findings


def test_a_tspan_with_absolute_coordinates_is_placed_there() -> None:
    over = """<svg viewBox="0 0 340 200">
      <line x1="20" y1="100" x2="320" y2="100" stroke="#111" stroke-width="2"/>
      <text x="20" y="40" font-size="14">
        <tspan x="20" y="40">Clear of it</tspan>
        <tspan x="20" y="104">Lying on it</tspan>
      </text>
    </svg>"""
    fit = diagram_layout.measure(over)

    assert fit.collisions == 1
    assert '"Lying on it"' in " ".join(fit.findings)

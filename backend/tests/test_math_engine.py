from __future__ import annotations

import math
from fractions import Fraction
import pytest

from app.services.math_engine.ast import (
    BinaryOp,
    Circle,
    Constant,
    Dataset,
    Equation,
    InterestModel,
    Money,
    Point,
    Polynomial,
    Sector,
    Term,
    Triangle,
    Variable,
)
from app.services.math_engine.assessment_validator import (
    AssessmentAuditReport,
    AssessmentValidator,
    QuestionValidationResult,
)
from app.services.math_engine.context import CurriculumContext
from app.services.math_engine.document_renderer import render_educational_document_html
from app.services.math_engine.document_schema import DocumentBlock, EducationalDocument
from app.services.math_engine.formula_registry import (
    FORMULA_REGISTRY,
    get_formulas_for_context,
    search_formulas,
)
from app.services.math_engine.question_generator import generate_math_question
from app.services.math_engine.solver import (
    prime_factorization,
    solve_circle_properties,
    solve_complementary_probability,
    solve_compound_interest,
    solve_coordinate_distance_midpoint,
    solve_cuboid_volume_and_surface_area,
    solve_cylinder_volume_and_surface_area,
    solve_dataset_summary,
    solve_density_mass_volume,
    solve_elevation_depression,
    solve_fraction_addition,
    solve_fraction_operation,
    solve_frequency_table_mean,
    solve_gcd_lcm,
    solve_independent_events_probability,
    solve_linear_equation,
    solve_math_problem,
    solve_percentage_change,
    solve_percentage_of_quantity,
    solve_profit_loss,
    solve_pythagoras,
    solve_quadratic_equation,
    solve_rectangle_perimeter_and_area,
    solve_right_triangle_angle,
    solve_right_triangle_side,
    solve_rounding,
    solve_share_in_ratio,
    solve_simple_interest,
    solve_simple_probability,
    solve_simplify_ratio,
    solve_simultaneous_linear,
    solve_speed_distance_time,
    solve_statistics_summary,
    solve_trapezium_area,
    solve_triangle_area,
    solve_unit_conversion,
)
from app.services.math_engine.units import (
    Dimension,
    DimensionalError,
    Quantity,
    UnitRegistry,
    get_unit,
)
from app.services.math_engine.verifier import MathVerifier, verify_solution
from app.services.math_engine.visualization import render_geometry_svg, render_graph_svg


# ══════════════════════════════════════════════════════════════════════
# 1. Physical Quantities and Units Subsystem Tests
# ══════════════════════════════════════════════════════════════════════
def test_unit_registry_and_dimensions():
    m = UnitRegistry.get("m")
    assert m.dimension == Dimension.LENGTH
    assert m.scale_to_base == 1.0

    km = UnitRegistry.get("km")
    assert km.scale_to_base == 1000.0

    kes = UnitRegistry.get("KES")
    assert kes.dimension == Dimension.MONEY


def test_quantity_addition_and_conversion():
    q1 = Quantity(5, "m")
    q2 = Quantity(20, "cm")
    res = q1 + q2
    assert res.unit.symbol == "m"
    assert math.isclose(res.value, 5.2, rel_tol=1e-5)

    # Conversion
    in_cm = res.to_unit("cm")
    assert math.isclose(in_cm.value, 520.0, rel_tol=1e-5)
    assert in_cm.unit.symbol == "cm"


def test_quantity_multiplication_division_dimensions():
    # Area = Length * Length
    length = Quantity(10, "m")
    width = Quantity(5, "m")
    area = length * width
    assert area.dimension == Dimension.AREA
    assert math.isclose(area.value, 50.0)

    # Speed = Length / Time
    dist = Quantity(100, "m")
    t = Quantity(10, "s")
    speed = dist / t
    assert speed.dimension == Dimension.SPEED
    assert math.isclose(speed.value, 10.0)


def test_dimensional_error_on_incompatible_quantities():
    mass = Quantity(5, "kg")
    length = Quantity(10, "m")
    with pytest.raises(DimensionalError):
        _ = mass + length


# ══════════════════════════════════════════════════════════════════════
# 2. Canonical AST Tests
# ══════════════════════════════════════════════════════════════════════
def test_ast_polynomial_and_evaluation():
    # 2x^2 + 3x - 5
    poly = Polynomial(
        terms=[
            Term(coeff=2, variable="x", power=2),
            Term(coeff=3, variable="x", power=1),
            Term(coeff=-5, variable="x", power=0),
        ],
        variable="x",
    )
    assert poly.degree == 2
    # At x = 2: 2(4) + 3(2) - 5 = 8 + 6 - 5 = 9
    val = poly.evaluate({"x": 2})
    assert val == 9.0
    assert "x^{2}" in poly.to_latex()


def test_ast_binary_op_evaluation():
    # (15 + 5) * 2 = 40
    c15 = Constant(15)
    c5 = Constant(5)
    add_op = BinaryOp("+", c15, c5)
    c2 = Constant(2)
    mult_op = BinaryOp("*", add_op, c2)
    assert mult_op.evaluate() == 40.0


def test_ast_geometry_circle_and_sector():
    center = Point("O", 0, 0)
    circ = Circle(center=center, radius=7.0)
    assert math.isclose(circ.diameter(), 14.0)
    assert math.isclose(circ.circumference(), 2 * math.pi * 7, rel_tol=1e-3)

    sector = Sector(circle=circ, angle_degrees=90.0)
    # 90 degrees is 1/4 of circle area
    assert math.isclose(sector.area(), (1 / 4) * circ.area(), rel_tol=1e-3)


def test_ast_financial_and_interest():
    m = Money(amount=10000.0, currency="KES")
    im = InterestModel(principal=m, rate_percent=5.0, time_years=2.0)
    assert im.interest().amount == 1000.0
    assert im.total_amount().amount == 11000.0


# ══════════════════════════════════════════════════════════════════════
# 3. Domain Solvers Tests
# ══════════════════════════════════════════════════════════════════════
def test_arithmetic_prime_factorization_and_gcd_lcm():
    pf = prime_factorization(60)
    assert pf == [(2, 2), (3, 1), (5, 1)]

    trace = solve_gcd_lcm(24, 36)
    assert "\\text{GCD} = 12" in trace.final_answer
    assert "\\text{LCM} = 72" in trace.final_answer
    assert trace.verified is True

    round_tr = solve_rounding(3.14159, 2)
    assert "3.14" in round_tr.final_answer


def test_fraction_solvers():
    # Addition
    tr_add = solve_fraction_addition(2, 3, 3, 4)
    assert "\\frac{17}{12}" in tr_add.final_answer
    assert tr_add.verified is True

    # Multiplication
    tr_mult = solve_fraction_operation(3, 4, 2, 3, op="*")
    assert "\\frac{1}{2}" in tr_mult.final_answer
    assert tr_mult.verified is True


def test_percentage_solvers():
    tr_pct = solve_percentage_of_quantity(20.0, 150.0)
    assert "30" in tr_pct.final_answer
    assert tr_pct.verified is True

    tr_chg = solve_percentage_change(50.0, 65.0)
    assert "30%" in tr_chg.final_answer
    assert "increase" in tr_chg.final_answer


def test_ratio_solvers():
    tr_simp = solve_simplify_ratio([12, 18, 24])
    assert "2 : 3 : 4" in tr_simp.final_answer

    tr_share = solve_share_in_ratio(1200.0, [2, 3, 5])
    assert tr_share.verified is True
    assert "240" in tr_share.final_answer
    assert "600" in tr_share.final_answer


def test_algebra_solvers():
    # Linear
    tr_lin = solve_linear_equation("3*(2*x - 1) = 15")
    assert "x = 3" in tr_lin.final_answer
    assert tr_lin.verified is True

    # Simultaneous
    tr_simul = solve_simultaneous_linear("x + y = 10", "x - y = 2")
    assert "x = 6" in tr_simul.final_answer
    assert "y = 4" in tr_simul.final_answer
    assert tr_simul.verified is True

    # Quadratic
    tr_quad = solve_quadratic_equation(1, -5, 6)
    assert "3.0" in tr_quad.final_answer
    assert "2.0" in tr_quad.final_answer


def test_geometry_solvers():
    # Triangle Area
    tr_tri = solve_triangle_area(8.0, 6.0)
    assert "24" in tr_tri.final_answer
    assert tr_tri.verified is True

    # Rectangle
    tr_rect = solve_rectangle_perimeter_and_area(10.0, 5.0)
    assert "P = 30" in tr_rect.final_answer
    assert "A = 50" in tr_rect.final_answer

    # Circle
    tr_circ = solve_circle_properties(7.0)
    assert "44" in tr_circ.final_answer  # 2 * 22/7 * 7 = 44
    assert "154" in tr_circ.final_answer  # 22/7 * 49 = 154

    # Trapezium
    tr_trap = solve_trapezium_area(6.0, 10.0, 4.0)
    assert "32" in tr_trap.final_answer  # 0.5 * 16 * 4 = 32

    # Pythagoras
    tr_pyth = solve_pythagoras(a=3.0, b=4.0)
    assert "c = 5" in tr_pyth.final_answer

    # Cylinder
    tr_cyl = solve_cylinder_volume_and_surface_area(7.0, 10.0)
    assert "1540" in tr_cyl.final_answer  # 154 * 10 = 1540

    # Coordinate geometry
    tr_coord = solve_coordinate_distance_midpoint(0.0, 0.0, 3.0, 4.0)
    assert "d = 5" in tr_coord.final_answer


def test_trigonometry_solvers():
    # Right triangle side: opposite = hypotenuse * sin(30) = 10 * 0.5 = 5
    tr_side = solve_right_triangle_side(30.0, 10.0, ratio="sin", find_part="numerator")
    assert "5" in tr_side.final_answer

    # Right triangle angle: opp=4, adj=4 -> 45 deg
    tr_ang = solve_right_triangle_angle(4.0, 4.0)
    assert "45.0" in tr_ang.final_answer

    # Angle of elevation
    tr_elev = solve_elevation_depression(height=20.0, distance=20.0, is_elevation=True)
    assert "45.0" in tr_elev.final_answer


def test_measurement_solvers():
    # Unit conversion: 5.5 km -> 5500 m
    tr_conv = solve_unit_conversion(5.5, "km", "m")
    assert "5500" in tr_conv.final_answer

    # Speed = Distance / Time
    tr_sdt = solve_speed_distance_time(distance=150.0, time=3.0)
    assert "50" in tr_sdt.final_answer

    # Density = Mass / Volume
    tr_dmv = solve_density_mass_volume(mass=500.0, volume=50.0)
    assert "10" in tr_dmv.final_answer


def test_statistics_solvers():
    tr_stat = solve_statistics_summary([10, 15, 15, 20])
    assert "15" in tr_stat.final_answer
    assert tr_stat.verified is True

    # Frequency table mean
    table = [{"value": 10.0, "freq": 2.0}, {"value": 20.0, "freq": 3.0}]
    tr_freq = solve_frequency_table_mean(table)
    # (20 + 60) / 5 = 16.0
    assert "16" in tr_freq.final_answer


def test_probability_solvers():
    # P(A) = 3/6 = 1/2 = 50%
    tr_prob = solve_simple_probability(3, 6)
    assert "\\frac{1}{2}" in tr_prob.final_answer
    assert "50\\%" in tr_prob.final_answer or "50%" in tr_prob.final_answer

    # Complement
    tr_comp = solve_complementary_probability(Fraction(1, 4))
    assert "\\frac{3}{4}" in tr_comp.final_answer

    # Independent events: 1/2 * 1/3 = 1/6
    tr_ind = solve_independent_events_probability(Fraction(1, 2), Fraction(1, 3))
    assert "\\frac{1}{6}" in tr_ind.final_answer


def test_financial_solvers():
    # Profit
    tr_pl = solve_profit_loss(cost_price=1000.0, selling_price=1250.0)
    assert "250" in tr_pl.final_answer
    assert "25\\%" in tr_pl.final_answer or "25%" in tr_pl.final_answer

    # Simple Interest: I = (10000 * 5 * 2) / 100 = 1000
    tr_si = solve_simple_interest(10000.0, 5.0, 2.0)
    assert "1000" in tr_si.final_answer
    assert "11000" in tr_si.final_answer

    # Compound Interest: 1000 * (1.1)^2 = 1210
    tr_ci = solve_compound_interest(1000.0, 10.0, 2.0)
    assert "1210.00" in tr_ci.final_answer
    assert "210.00" in tr_ci.final_answer


def test_unified_dispatcher():
    # Math problem string parsing
    tr1 = solve_math_problem("Solve: 2*x + 4 = 10")
    assert "x = 3" in tr1.final_answer

    tr2 = solve_math_problem("Find area of triangle with base of 8 and height of 6")
    assert "24" in tr2.final_answer

    tr3 = solve_math_problem("1/2 + 1/4")
    assert "\\frac{3}{4}" in tr3.final_answer


# ══════════════════════════════════════════════════════════════════════
# 4. Verifier Tests
# ══════════════════════════════════════════════════════════════════════
def test_verifier_symbolic_numeric_and_quantities():
    # Exact symbolic
    v1 = MathVerifier.verify_exact_symbolic("(x - 1)*(x + 1)", "x^2 - 1")
    assert v1["verified"] is True

    # Numeric tolerance
    v2 = MathVerifier.verify_numeric_tolerance(3.14159, 3.142, abs_tol=1e-3)
    assert v2["verified"] is True

    # Equation substitution
    ok = verify_solution("2*x + 5 = 15", "x = 5")
    assert ok["verified"] is True

    bad = verify_solution("2*x + 5 = 15", "x = 6")
    assert bad["verified"] is False

    # Physical quantity verification
    q_match = MathVerifier.verify_quantity("500 cm", "5 m")
    assert q_match["verified"] is True

    q_mismatch = MathVerifier.verify_quantity("500 cm", "5 kg")
    assert q_mismatch["verified"] is False
    assert "Dimensional mismatch" in q_mismatch["message"]


# ══════════════════════════════════════════════════════════════════════
# 5. Formula Registry Tests (50+ Formulas)
# ══════════════════════════════════════════════════════════════════════
def test_formula_registry_comprehensive():
    assert len(FORMULA_REGISTRY) >= 50

    # Test domain filtering
    geo_formulas = search_formulas(domain="geometry")
    assert len(geo_formulas) >= 10

    trig_formulas = search_formulas(domain="trigonometry")
    assert len(trig_formulas) >= 5

    stat_formulas = search_formulas(domain="statistics")
    assert len(stat_formulas) >= 4

    fin_formulas = search_formulas(domain="financial")
    assert len(fin_formulas) >= 4

    # Search keyword
    pyth = search_formulas(query="pythagoras")
    assert len(pyth) >= 1

    # Context query
    g8_formulas = get_formulas_for_context(grade="grade-8")
    assert len(g8_formulas) > 0


# ══════════════════════════════════════════════════════════════════════
# 6. Assessment Validator Tests
# ══════════════════════════════════════════════════════════════════════
def test_assessment_validator():
    # Question with matched marks
    valid_q = {
        "question_number": 1,
        "question_text": "Solve: $2x + 4 = 10$",
        "marks": 2,
        "marking_scheme": "M1 for subtraction, A1 for division",
        "solution_trace": {"verified": True, "steps": [{"step_number": 1}]},
    }
    res = AssessmentValidator.validate_question(valid_q)
    assert res.is_mark_consistent is True
    assert res.trace_verified is True
    assert len(res.discrepancies) == 0

    # Question with mark mismatch: stated 3 marks, but scheme has 2 marks
    mismatched_q = {
        "question_number": 2,
        "question_text": "Find hypotenuse",
        "marks": 3,
        "marking_scheme": "M1 A1",
        "solution_trace": {"verified": True, "steps": [{"step_number": 1}]},
    }
    res2 = AssessmentValidator.validate_question(mismatched_q)
    assert res2.is_mark_consistent is False
    assert len(res2.discrepancies) > 0

    # Full assessment document audit
    doc = {
        "document_id": "test_exam_01",
        "total_marks": 5,
        "questions": [valid_q, mismatched_q],
    }
    audit = AssessmentValidator.validate_assessment_document(doc)
    assert audit.question_count == 2
    assert audit.is_valid is False  # due to mismatch in question 2
    assert len(audit.discrepancies) >= 1


# ══════════════════════════════════════════════════════════════════════
# 7. Document Rendering, SVGs, and Question Generator Tests
# ══════════════════════════════════════════════════════════════════════
def test_question_generator():
    ctx = CurriculumContext(
        grade="grade-8",
        subject="Mathematics",
        strand_name="2. Algebra",
        sub_strand_name="2.1 Linear Equations",
    )
    q = generate_math_question(ctx, template_id="linear_equation", enable_simulation=False)
    assert q["question_text"]
    assert q["solution_trace"]
    assert q["verified"] is True
    assert "marks" in q


def test_svg_rendering():
    bar_svg = render_graph_svg({"type": "bar", "data": {"Term 1": 45, "Term 2": 60}})
    assert "<svg" in bar_svg
    assert "</svg>" in bar_svg

    geo_svg = render_geometry_svg({"kind": "triangle", "base_label": "8 cm", "height_label": "6 cm"})
    assert "<svg" in geo_svg
    assert "polygon" in geo_svg


def test_document_rendering():
    doc = EducationalDocument(
        document_id="doc_test_01",
        title="Grade 8 End-Term Mathematics Test",
        curriculum={"grade": "Grade 8", "subject": "Mathematics"},
        blocks=[
            DocumentBlock("heading", {"text": "Section A: Algebra", "level": 2}),
            DocumentBlock(
                "question",
                {
                    "question_number": 1,
                    "question_text": "Solve: $2x + 5 = 15$",
                    "marks": 3,
                    "solution_trace": {
                        "steps": [{"step_number": 1, "latex": "2x = 10", "explanation": "Subtract 5"}]
                    },
                    "marking_scheme": "1 mark for subtraction; 2 marks for division",
                },
            ),
        ],
    )
    html_student = render_educational_document_html(doc, audience="student")
    assert "Solve: $2x + 5 = 15$" in html_student
    assert "answer-line" in html_student
    assert "Subtract 5" not in html_student  # hidden from student

    html_teacher = render_educational_document_html(doc, audience="teacher")
    assert "Subtract 5" in html_teacher
    assert "TEACHER COPY" in html_teacher

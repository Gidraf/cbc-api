

# --- Orders is the O in BODMAS ------------------------------------------------
#
# `8 + (3 \times 4) - 2^2` is worth 16. The engine answered 18, because the run
# extractor stopped at the `^` and quietly worked `8 + (3 \times 4) - 2`. It
# then published 18 on the page against working that correctly reached 16,
# under a badge saying the engine had checked it. An engine that answers from
# part of an expression is worse than one that declines.

def test_an_exponent_is_worked_not_dropped() -> None:
    from app.services.math_engine.solver import solve_math_problem

    for written in ("8 + (3 \\times 4) - 2^2", "8 + (3 * 4) - 2**2",
                    "8 + (3 × 4) - 2²", "8 + (3 \\times 4) - 2^{2}"):
        assert solve_math_problem(written).final_answer == "16", written


def test_orders_bind_tighter_than_multiplication() -> None:
    from app.services.math_engine.solver import solve_math_problem

    assert solve_math_problem("2 \\times 3^2").final_answer == "18"
    assert solve_math_problem("(2 \\times 3)^2").final_answer == "36"


def test_powers_associate_to_the_right() -> None:
    from app.services.math_engine.solver import solve_math_problem

    # 2^(3^2) = 2^9 = 512, not (2^3)^2 = 64.
    assert solve_math_problem("2^3^2").final_answer == "512"


def test_an_even_power_of_a_negative_is_positive() -> None:
    from app.services.math_engine.solver import solve_math_problem

    assert solve_math_problem("(-3)^2 + 1").final_answer == "10"
    assert solve_math_problem("(-2)^3 + 1").final_answer == "-7"


def test_a_fragment_of_an_expression_is_refused_not_answered() -> None:
    from app.services.math_engine.solvers.integers import arithmetic_in

    assert arithmetic_in("Work out \\sqrt{16} + 2 \\times 3") == ""
    assert arithmetic_in("Find 50% of 40 + 10") == ""
    assert arithmetic_in("Calculate 3x + 4 - 2") == ""
    assert arithmetic_in("What is 5! + 2") == ""


def test_the_ordinary_sentence_still_reads() -> None:
    """The guard must not cost coverage on what it was always able to work."""
    from app.services.math_engine.solvers.integers import arithmetic_in

    assert arithmetic_in("Determine (-3) × (-4) + 10.") == "(-3) × (-4) + 10"
    assert arithmetic_in("Work out 300 - 120 + 80 shillings") == "300 - 120 + 80"
    assert arithmetic_in("Calculate 8 + (3 × 4) - 2^2") == "8 + (3 × 4) - 2^2"

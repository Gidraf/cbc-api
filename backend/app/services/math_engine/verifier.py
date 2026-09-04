"""Mathematical Verification Subsystem.

Provides deterministic verification for:
1. Exact symbolic equivalence (via SymPy)
2. Numerical approximations within configurable tolerance
3. Equation solution verification via algebraic substitution
4. Physical quantities, units, and dimensional validation
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

import sympy as sp

from .units import Dimension, DimensionalError, Quantity, UnitRegistry


def _clean_math_str(s: str) -> str:
    """Normalize LaTeX and mathematical tokens for SymPy parsing."""
    out = s.replace(r"\left", "").replace(r"\right", "")
    out = out.replace(r"\cdot", "*").replace(r"\times", "*")
    out = out.replace(r"\%", "").replace("%", "")
    out = out.replace(r"^\circ", "").replace(r"°", "")
    out = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", out)
    out = re.sub(r"\\sqrt\{([^{}]+)\}", r"sqrt(\1)", out)
    out = re.sub(r"(\d)\s+([a-zA-Z])", r"\1*\2", out)
    out = re.sub(r"(\d)([a-zA-Z])", r"\1*\2", out)
    out = re.sub(r"(\d)\(", r"\1*(", out)
    out = re.sub(r"\)([a-zA-Z0-9])", r")*\1", out)
    out = out.replace(r"\pi", "pi")
    return out.strip()


class MathVerifier:
    """Production-grade mathematical verifier with symbolic, numeric, and dimensional checks."""

    @staticmethod
    def verify_exact_symbolic(expr1: str, expr2: str) -> Dict[str, Any]:
        """Verify that two algebraic expressions are symbolically identical (difference is 0)."""
        c1 = _clean_math_str(expr1)
        c2 = _clean_math_str(expr2)

        try:
            s1 = sp.sympify(c1)
            s2 = sp.sympify(c2)
            diff = sp.simplify(s1 - s2)
            is_zero = diff == 0 or diff.is_zero
            return {
                "verified": bool(is_zero),
                "method": "symbolic_exact",
                "diff": str(diff),
                "check_latex": f"{sp.latex(s1)} - ({sp.latex(s2)}) = {sp.latex(diff)} "
                               f"{'\\checkmark' if is_zero else '\\times'}",
                "message": "Symbolically equivalent" if is_zero else f"Expressions differ by {diff}",
            }
        except Exception as exc:
            return {
                "verified": False,
                "method": "symbolic_exact",
                "check_latex": "",
                "message": f"Symbolic parsing failed: {exc}",
            }

    @staticmethod
    def verify_numeric_tolerance(
        val1: float,
        val2: float,
        rel_tol: float = 1e-2,
        abs_tol: float = 1e-3,
    ) -> Dict[str, Any]:
        """Verify two numeric values match within relative or absolute tolerance."""
        is_close = math.isclose(val1, val2, rel_tol=rel_tol, abs_tol=abs_tol)
        diff = abs(val1 - val2)
        return {
            "verified": is_close,
            "method": "numeric_tolerance",
            "diff": round(diff, 6),
            "check_latex": f"|{val1} - {val2}| = {diff:.4g} "
                           f"{'\\le' if is_close else '>'} \\text{{tolerance}} "
                           f"{'\\checkmark' if is_close else '\\times'}",
            "message": "Values within tolerance" if is_close else f"Difference {diff:.4g} exceeds tolerance",
        }

    @staticmethod
    def verify_equation_solution(
        equation_str: str,
        candidate_solution: str,
    ) -> Dict[str, Any]:
        """Verify candidate solution satisfies an equation f(x) = g(x) via substitution."""
        clean_eq = equation_str.replace("Solve:", "").replace("solve", "").strip()
        parts = clean_eq.split("=")
        if len(parts) != 2:
            return {
                "verified": False,
                "method": "substitution",
                "message": "Equation must have exactly one '=' sign",
            }

        lhs_str = _clean_math_str(parts[0])
        rhs_str = _clean_math_str(parts[1])

        # Extract variable name and value from candidate e.g. "x = 3" or "3"
        clean_cand = candidate_solution.strip()
        var_match = re.search(r"([a-zA-Z])\s*=\s*([-+]?\d+(?:\.\d+)?(?:/\d+)?)", clean_cand)
        if var_match:
            var_name = var_match.group(1)
            val_raw = var_match.group(2)
        else:
            # Detect variable in equation
            vars_found = re.findall(r"[a-zA-Z]", lhs_str + rhs_str)
            var_name = vars_found[0] if vars_found else "x"
            # Remove prefix like "ans =" or similar
            num_match = re.search(r"[-+]?\d+(?:\.\d+)?(?:/\d+)?", clean_cand)
            val_raw = num_match.group(0) if num_match else clean_cand

        val_cleaned = _clean_math_str(val_raw)

        try:
            var_sym = sp.Symbol(var_name)
            val_sym = sp.sympify(val_cleaned)
            lhs_sym = sp.sympify(lhs_str)
            rhs_sym = sp.sympify(rhs_str)

            lhs_sub = lhs_sym.subs(var_sym, val_sym)
            rhs_sub = rhs_sym.subs(var_sym, val_sym)

            diff = sp.simplify(lhs_sub - rhs_sub)
            is_verified = (diff == 0 or diff.is_zero)

            # Check numerical tolerance if symbolic simplification didn't yield 0
            if not is_verified:
                try:
                    diff_float = float(sp.N(diff))
                    if math.isclose(diff_float, 0.0, abs_tol=1e-3):
                        is_verified = True
                except Exception:
                    pass

            check_latex = (
                f"{sp.latex(lhs_sym.subs(var_sym, sp.Symbol(f'({val_sym})')))} = "
                f"{sp.latex(lhs_sub)} = {sp.latex(rhs_sub)} "
                f"{'\\checkmark' if is_verified else '\\times'}"
            )
            return {
                "verified": is_verified,
                "method": "substitution",
                "check_latex": check_latex,
                "message": f"Substitution {var_name} = {val_sym} satisfies equation"
                           if is_verified
                           else f"Substitution does not balance equation (diff = {diff})",
            }
        except Exception as exc:
            return {
                "verified": False,
                "method": "substitution",
                "message": f"Substitution failed: {exc}",
            }

    @staticmethod
    def verify_quantity(candidate_str: str, expected_str: str) -> Dict[str, Any]:
        """Verify two physical quantities (value + unit) for dimensional consistency and value."""
        # Parse candidate e.g. "5.2 m" or "520 cm" or "24 cm^2"
        cand_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*([a-zA-Z^/0-9]+)?", candidate_str.strip())
        exp_match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*([a-zA-Z^/0-9]+)?", expected_str.strip())

        if not cand_match or not exp_match:
            return {
                "verified": False,
                "method": "quantity_unit",
                "message": "Could not parse quantity patterns",
            }

        val_cand = float(cand_match.group(1))
        unit_cand = (cand_match.group(2) or "").strip()
        val_exp = float(exp_match.group(1))
        unit_exp = (exp_match.group(2) or "").strip()

        try:
            q_cand = Quantity(val_cand, unit_cand)
            q_exp = Quantity(val_exp, unit_exp)

            if q_cand.dimension != q_exp.dimension:
                return {
                    "verified": False,
                    "method": "quantity_unit",
                    "message": (
                        f"Dimensional mismatch: candidate is {q_cand.dimension.value} ({unit_cand}), "
                        f"expected {q_exp.dimension.value} ({unit_exp})"
                    ),
                    "check_latex": f"\\text{{Dimension mismatch: }} {q_cand.dimension.value} \\neq {q_exp.dimension.value} \\times",
                }

            # Convert candidate to expected unit and check value
            converted_cand = q_cand.to_unit(unit_exp)
            is_equal = math.isclose(converted_cand.value, q_exp.value, rel_tol=1e-2, abs_tol=1e-3)
            check_latex = (
                f"{q_cand.to_latex()} = {converted_cand.to_latex()} "
                f"\\equiv {q_exp.to_latex()} {'\\checkmark' if is_equal else '\\times'}"
            )
            return {
                "verified": is_equal,
                "method": "quantity_unit",
                "check_latex": check_latex,
                "message": f"Quantities match ({q_cand.to_plain()} == {q_exp.to_plain()})"
                           if is_equal
                           else f"Values do not match ({converted_cand.value} vs {q_exp.value})",
            }
        except Exception as exc:
            return {
                "verified": False,
                "method": "quantity_unit",
                "message": f"Quantity verification error: {exc}",
            }

    @classmethod
    def verify(
        cls,
        problem: str,
        candidate_answer: str,
        expected_answer: Optional[str] = None,
        tolerance: float = 1e-3,
    ) -> Dict[str, Any]:
        """Comprehensive verification router."""
        clean_prob = problem.strip()
        clean_cand = candidate_answer.strip()

        # 1. If equation solving problem: f(x) = g(x)
        if "=" in clean_prob:
            return cls.verify_equation_solution(clean_prob, clean_cand)

        # 2. If expected answer provided, check exact or quantity
        if expected_answer:
            clean_exp = expected_answer.strip()
            # If units detected
            if any(u in clean_cand for u in ["cm", "m", "km", "kg", "g", "s", "h", "L", "mL", "KES"]):
                q_res = cls.verify_quantity(clean_cand, clean_exp)
                if q_res.get("method") == "quantity_unit":
                    return q_res

            # Try exact symbolic
            sym_res = cls.verify_exact_symbolic(clean_cand, clean_exp)
            if sym_res["verified"]:
                return sym_res

            # Try numeric comparison
            try:
                c_num = float(_clean_math_str(clean_cand))
                e_num = float(_clean_math_str(clean_exp))
                return cls.verify_numeric_tolerance(c_num, e_num, abs_tol=tolerance)
            except Exception:
                pass

        # 3. Direct expression evaluation check: problem == candidate
        try:
            c_prob = _clean_math_str(clean_prob)
            c_cand = _clean_math_str(clean_cand)
            sym_res = cls.verify_exact_symbolic(c_prob, c_cand)
            if sym_res["verified"]:
                return sym_res
        except Exception:
            pass

        # 4. Nothing could check it. That is not a pass.
        #
        # This branch used to return verified=True with "Verified by inspection",
        # which meant every answer the parser could not read was certified
        # correct — including answers that were simply wrong, and strings that
        # were not mathematics at all. An engine that cannot check something
        # must say so; a false "verified" is worse than no verifier, because it
        # is printed on the teacher's marking scheme.
        return {
            "verified": False,
            "method": "unverified",
            "check_latex": "",
            "message": (
                "Could not verify this answer automatically — it needs a human check. "
                "Verification works on equations (by substitution), on quantities with "
                "units, and on expressions that parse symbolically."
            ),
        }


def verify_solution(problem: str, candidate_answer: str) -> Dict[str, Any]:
    """Backward-compatible entry point for solution verification."""
    return MathVerifier.verify(problem=problem, candidate_answer=candidate_answer)

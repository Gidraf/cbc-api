"""The Chemistry API: the chemistry engine for developers' apps, metered like
the content API (the same keys, free calls, wallet and per-minute limit).

Everything is worked out by rules, not a model: reactions by the rules of
school chemistry (balanced exactly, with observations, gas tests and
applications), equations balanced, electron arrangements, bonds and the
formulas they give, and how to separate mixtures — and, for any of them, the
animated whiteboard walkthrough (scenes to render yourself, or a
self-contained animated page to embed).

Pricing: a data call (react, balance, atom, bond, separate) is charged as one
text question past the free calls; an animation (walkthrough, animation.html)
as one figure question.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext
from .content import DEVELOPER, _charge, _usage_headers

router = APIRouter(prefix="/api/v1/chemistry", tags=["Chemistry API"])

TEXT = [{"has_figure": False}]
ANIMATION = [{"has_figure": True}]


def _ok(auth: AuthContext, body: dict[str, Any], ref: str, priced: list[dict[str, Any]] = TEXT) -> JSONResponse:
    bill = _charge(auth, priced, ref=ref)
    return JSONResponse({**body, "charged_ksh": bill.get("charged_ksh", 0)}, headers=_usage_headers(auth.subject))


def _engine(call: Any) -> Any:
    try:
        return call()
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
    return None


@router.get("/react", summary="What happens when two substances meet (or one is heated)")
def chem_react(a: str = Query(..., max_length=40, description="A formula: Zn, CuSO4, HCl, Ca(OH)2, CH4, O2 …"),
               b: str = Query("", max_length=40, description="The second formula; leave empty to heat `a` alone"),
               condition: Literal["", "heat", "steam", "molten", "boil"] = Query(""),
               auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """The reaction by the rules of school chemistry: its kind, the balanced
    equation (with state symbols), the word equation, what is observed, the
    test for any gas, where it is used, and the steps of the explanation —
    or `reacts: false` with the reason, or `covered: false` when the rules do
    not decide it (never guessed)."""
    from ..services import chem_engine as C

    r = _engine(lambda: C.react(a, b, condition=condition))
    return _ok(auth, r, ref=f"chemistry/react {a}+{b} {condition}")


class Equation(BaseModel):
    equation: str = Field(..., max_length=200, examples=["KMnO4 + HCl -> KCl + MnCl2 + H2O + Cl2"])


@router.post("/balance", summary="Balance an equation exactly")
def chem_balance(body: Equation, auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """Smallest whole-number coefficients (exact, not by trial), with the atom
    counts of each side before and after."""
    from ..services import chem_engine as C

    r = _engine(lambda: C.balance_given(body.equation))
    return _ok(auth, r, ref="chemistry/balance")


@router.get("/atom/{symbol}", summary="An element's electron arrangement and its ion")
def chem_atom(symbol: str, auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """Protons, neutrons, electrons, shells (2.8.8.2 model), group, period, the
    ion it forms and why — the first twenty elements."""
    from ..services import chem_engine as C

    return _ok(auth, _engine(lambda: C.atom(symbol)), ref=f"chemistry/atom {symbol}")


@router.get("/bond", summary="How two elements bond, and the formula it gives")
def chem_bond(a: str = Query(..., max_length=3), b: str = Query(..., max_length=3),
              auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """Ionic (the electrons moved, the ions and their charges) or covalent (the
    shared pairs) — the formula from the electron arrangements."""
    from ..services import chem_engine as C

    return _ok(auth, _engine(lambda: C.bond(a, b)), ref=f"chemistry/bond {a}{b}")


@router.get("/separate", summary="How to separate a mixture")
def chem_separate(parts: str = Query(..., max_length=120, description="Comma-separated: sand,salt · ethanol,water · ink"),
                  keep: str = Query("", max_length=40, description="The part to keep, when it changes the method (water)"),
                  auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """The method(s), the steps and where they are used."""
    from ..services import chem_engine as C

    return _ok(auth, C.separate(parts.split(","), keep), ref=f"chemistry/separate {parts}")


class Walk(BaseModel):
    chemistry: dict[str, Any] = Field(..., examples=[{"reactants": ["Zn", "CuSO4"], "condition": "", "focus": "observations"}])
    question_text: str = Field("", max_length=600, examples=["What is seen when zinc is placed in copper(II) sulphate solution?"])


def _walk(body: Walk) -> dict[str, Any]:
    from ..services import play_engine

    if not any(body.chemistry.get(k) for k in ("reactants", "equation", "atom", "bond", "separate")):
        raise_api_error("VALIDATION_FAILED", "Give chemistry.reactants, .equation, .atom, .bond or .separate.")
    q = {"question_id": "api", "question_text": body.question_text or "Chemistry", "chemistry": body.chemistry,
         "curriculum": {"subject": "Chemistry"}}
    w = _engine(lambda: play_engine.walkthrough(q))
    if not w or len(w["scenes"]) < 2:
        raise_api_error("VALIDATION_FAILED", "The engine could not read that chemistry block.")
    return w


@router.post("/walkthrough", summary="The animated walkthrough's scenes (render them yourself)")
def chem_walkthrough(body: Walk, auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """Scenes in order — the hook, the lab bench, the reactivity series, the
    equation, the particles, the electrons, the observations, the uses —
    each with its narration (`say`) and the data to draw it."""
    w = _walk(body)
    return _ok(auth, {"scenes": w["scenes"], "words": w["words"]}, ref="chemistry/walkthrough", priced=ANIMATION)


@router.post("/animation.html", summary="A self-contained animated whiteboard page to embed", response_class=HTMLResponse)
def chem_animation(body: Walk, voiced: bool = Query(False, description="Narrate it in a British/American voice (slower)"),
                   auth: AuthContext = Depends(DEVELOPER)) -> HTMLResponse:
    """The walkthrough as one HTML page: the marker draws, the lab bubbles, the
    electrons move. Put it in an `<iframe srcdoc>`; nothing else is fetched."""
    from ..services import whiteboard
    from ..services.math_engine.tts_service import science_voice

    w = _walk(body)
    bill = _charge(auth, ANIMATION, ref="chemistry/animation")
    if voiced:
        html = whiteboard.live_page(w, title=body.question_text[:80] or "Chemistry", voice=science_voice("female", body.question_text))
    else:
        durations = [max(3.5, len(s["say"].split()) / 2.6) for s in w["scenes"]]
        html = whiteboard.page(w, title=body.question_text[:80] or "Chemistry", voice="en-GB", durations=durations)
    return HTMLResponse(html, headers={**_usage_headers(auth.subject), "X-Charged-KSh": str(bill.get("charged_ksh", 0))})

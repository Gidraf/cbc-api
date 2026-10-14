"""The wallet: balance, M-Pesa top-ups, and Safaricom's callback."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])

SIGNED_IN = require_roles("admin", "operator", "reviewer", "developer", "user", "api")
ADMIN = require_roles("admin")


class TopUp(BaseModel):
    phone: str = Field(description="The Safaricom number to charge, e.g. 0712345678")
    amount: int = Field(description="Shillings, whole")


class Credit(BaseModel):
    owner: str
    amount_ksh: float = Field(gt=0, le=1_000_000)
    note: str = ""


@router.get("/wallet")
def wallet(auth: AuthContext = Depends(SIGNED_IN)) -> dict[str, Any]:
    """Balance, free questions left, the content API's usage, the prices, and
    the latest movements."""
    from ..services import billing, mpesa

    p = billing.prices()
    ok, why = mpesa.ready()
    return {"owner": auth.subject, "exempt": billing.exempt(auth.role),
            "balance_ksh": billing.ksh(billing.balance(auth.subject)),
            "free_questions_left": max(0, p.free_questions - billing.free_used(auth.subject)),
            "api": billing.api_usage(auth.subject), "prices": p.public(),
            "topups_ready": ok, "topups_note": why, "entries": billing.entries(auth.subject, 30)}


@router.post("/topup")
def topup(payload: TopUp, request: Request, auth: AuthContext = Depends(SIGNED_IN)) -> dict[str, Any]:
    """Send an M-Pesa PIN prompt to the phone. Poll /topup/{id} for the result."""
    from ..services import billing, mpesa, platform_settings

    from ..services import rate_limit

    p = billing.prices()
    if not p.min_topup <= payload.amount <= p.max_topup:
        raise_api_error("VALIDATION_FAILED", f"Top up between KSh {p.min_topup} and KSh {p.max_topup}.")
    # A prompt lands on someone's phone: never a flood, from one account or to one number.
    rate_limit.hit("topup_owner", auth.subject)
    rate_limit.hit("topup_phone", mpesa.phone(payload.phone) or payload.phone[:20])
    try:
        return mpesa.stk_push(owner=auth.subject, phone_number=payload.phone, amount=payload.amount,
                              callback_base=platform_settings.public_base_url(request))
    except mpesa.MpesaError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))


@router.get("/topup/{checkout_request_id}")
def topup_status(checkout_request_id: str, auth: AuthContext = Depends(SIGNED_IN)) -> dict[str, Any]:
    from ..services import billing, mpesa

    row = mpesa.refresh(checkout_request_id, auth.subject)
    if not row:
        raise_api_error("NOT_FOUND", "No such top-up on this account.")
    return {"checkout_request_id": checkout_request_id, "status": row["status"], "amount_ksh": row["amount"],
            "receipt": row.get("receipt") or "", "message": row.get("result_desc") or "",
            "balance_ksh": billing.ksh(billing.balance(auth.subject))}


@router.post("/mpesa/callback/{token}", include_in_schema=False)
async def mpesa_callback(token: str, request: Request) -> dict[str, Any]:
    """Safaricom's result for an STK push. The path carries a secret only
    Safaricom was given; anything else is ignored."""
    from ..services import mpesa

    if not mpesa.callback_token_ok(token):
        return {"ResultCode": 1, "ResultDesc": "Rejected"}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    mpesa.handle_callback(body if isinstance(body, dict) else {})
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/admin/credit")
def admin_credit(payload: Credit, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """Add to an account's wallet by hand: a refund, a gift, a cash payment."""
    from ..services import billing

    cents = int(round(payload.amount_ksh * 100))
    new = billing.credit(payload.owner.strip(), cents, kind="admin", ref=auth.subject,
                         note=payload.note or f"Added by {auth.subject}")
    return {"owner": payload.owner, "balance_ksh": billing.ksh(new)}


@router.get("/admin/payments")
def admin_payments(limit: int = Query(100, ge=1, le=500), auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT checkout_request_id, owner, phone, amount, status, result_desc, receipt, created_at
                        FROM mpesa_payments ORDER BY created_at DESC LIMIT :n""", {"n": limit}) or []
    return {"payments": rows}

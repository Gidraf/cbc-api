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


@router.get("/admin/accounts")
def admin_accounts(days: int = Query(30, ge=1, le=365), auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """Who signed up, when, and who pays: every account with its wallet and
    payments, and the totals for today, seven days and `days` days."""
    from datetime import datetime, timedelta, timezone

    from ..infra.db import fetch_all, fetch_one
    from ..services import mpesa

    now = datetime.now(timezone.utc)
    day = now.astimezone(mpesa.EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = fetch_all("""
        SELECT u.username, u.role, COALESCE(u.email, '') AS email, u.email_verified_at IS NOT NULL AS email_verified,
               u.is_active, u.created_at,
               COALESCE(w.balance_cents, 0) AS balance_cents,
               COALESCE(p.paid_ksh, 0) AS paid_ksh, COALESCE(p.payments, 0) AS payments, p.last_paid_at,
               COALESCE(s.spent_cents, 0) AS spent_cents
        FROM app_users u
        LEFT JOIN wallets w ON w.owner = u.username
        LEFT JOIN (SELECT owner, SUM(amount) AS paid_ksh, COUNT(*) AS payments, MAX(updated_at) AS last_paid_at
                   FROM mpesa_payments WHERE status = 'paid' GROUP BY owner) p ON p.owner = u.username
        LEFT JOIN (SELECT owner, -SUM(amount_cents) AS spent_cents FROM wallet_entries WHERE amount_cents < 0
                   GROUP BY owner) s ON s.owner = u.username
        WHERE u.role IN ('user', 'api')
        ORDER BY u.created_at DESC NULLS LAST LIMIT 1000""") or []
    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()

    def count(sql: str, since: datetime) -> int:
        return int((fetch_one(sql, {"t": since}) or {}).get("n") or 0)

    signups = "SELECT COUNT(*) AS n FROM app_users WHERE role IN ('user', 'api') AND created_at >= :t"
    revenue = "SELECT COALESCE(SUM(amount), 0) AS n FROM mpesa_payments WHERE status = 'paid' AND updated_at >= :t"
    payers = "SELECT COUNT(DISTINCT owner) AS n FROM mpesa_payments WHERE status = 'paid' AND updated_at >= :t"
    windows = {"today": day, "week": now - timedelta(days=7), "period": now - timedelta(days=days)}
    ready, why = mpesa.ready()
    return {"accounts": rows, "mpesa_ready": ready, "mpesa_note": why,
            "totals": {w: {"signups": count(signups, t), "revenue_ksh": count(revenue, t), "payers": count(payers, t)}
                       for w, t in windows.items()},
            "all": {"accounts": len(rows), "paying": sum(1 for r in rows if int(r["payments"] or 0) > 0),
                    "revenue_ksh": sum(int(r["paid_ksh"] or 0) for r in rows)}}


@router.get("/admin/payments")
def admin_payments(limit: int = Query(100, ge=1, le=500), auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT checkout_request_id, owner, phone, amount, status, result_desc, receipt, created_at
                        FROM mpesa_payments ORDER BY created_at DESC LIMIT :n""", {"n": limit}) or []
    return {"payments": rows}

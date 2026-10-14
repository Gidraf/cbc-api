"""M-Pesa top-ups: Lipa na M-Pesa Online (STK push) on Safaricom's Daraja API.

The customer types their number, their phone asks for their M-Pesa PIN, and
Safaricom calls us back with the result. The callback is what credits the
wallet; if it never arrives, `refresh` asks Daraja for the result, so a
payment is never lost to a dropped callback. A payment is credited exactly
once: the row moves from pending to paid in one UPDATE, and only the call
that moved it adds the money.

Configuration is the environment only — none of it is ever logged:

    MPESA_ENV              sandbox | production
    MPESA_CONSUMER_KEY     the Daraja app's key and secret
    MPESA_CONSUMER_SECRET
    MPESA_SHORTCODE        the Paybill number, or a Till's store (head office) number
    MPESA_PASSKEY          the Lipa na M-Pesa Online passkey
    MPESA_TYPE             paybill | till
    MPESA_TILL_NUMBER      the Till number customers pay (Till only)
    MPESA_CALLBACK_TOKEN   a long random string: Safaricom calls
                           /api/v1/billing/mpesa/callback/<token>
"""
from __future__ import annotations

import base64
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("cbc-mpesa")

EAT = timezone(timedelta(hours=3))
_token: dict[str, Any] = {"value": "", "until": 0.0}


class MpesaError(Exception):
    pass


def config() -> dict[str, str]:
    env = os.getenv("MPESA_ENV", "sandbox").strip().lower()
    return {"env": "production" if env == "production" else "sandbox",
            "key": os.getenv("MPESA_CONSUMER_KEY", "").strip(),
            "secret": os.getenv("MPESA_CONSUMER_SECRET", "").strip(),
            "shortcode": os.getenv("MPESA_SHORTCODE", "").strip(),
            "passkey": os.getenv("MPESA_PASSKEY", "").strip(),
            "type": "till" if os.getenv("MPESA_TYPE", "paybill").strip().lower() == "till" else "paybill",
            "till": os.getenv("MPESA_TILL_NUMBER", "").strip(),
            "callback_token": os.getenv("MPESA_CALLBACK_TOKEN", "").strip()}


def ready() -> tuple[bool, str]:
    """Whether top-ups can work here, and if not what is missing (names only)."""
    c = config()
    missing = [name for name, key in (("MPESA_CONSUMER_KEY", "key"), ("MPESA_CONSUMER_SECRET", "secret"),
                                      ("MPESA_SHORTCODE", "shortcode"), ("MPESA_PASSKEY", "passkey"),
                                      ("MPESA_CALLBACK_TOKEN", "callback_token")) if not c[key]]
    if c["type"] == "till" and not c["till"]:
        missing.append("MPESA_TILL_NUMBER")
    return (not missing, "" if not missing else "M-Pesa is not set up on the server: " + ", ".join(missing) + " missing.")


def _base(c: dict[str, str]) -> str:
    return "https://api.safaricom.co.ke" if c["env"] == "production" else "https://sandbox.safaricom.co.ke"


def phone(raw: str) -> str:
    """07XX…, 01XX…, +2547…, 2547… → 2547XXXXXXXX / 2541XXXXXXXX, or ""."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "71":
        digits = "254" + digits
    return digits if re.fullmatch(r"254[71]\d{8}", digits) else ""


def masked(number: str) -> str:
    return number[:6] + "***" + number[-3:] if len(number) >= 9 else "***"


def _access_token(c: dict[str, str]) -> str:
    import httpx

    if _token["value"] and time.time() < _token["until"]:
        return str(_token["value"])
    try:
        r = httpx.get(f"{_base(c)}/oauth/v1/generate", params={"grant_type": "client_credentials"},
                      auth=(c["key"], c["secret"]), timeout=20)
    except httpx.HTTPError as exc:
        raise MpesaError(f"Could not reach Safaricom: {type(exc).__name__}") from exc
    if r.status_code != 200 or not r.json().get("access_token"):
        raise MpesaError(f"Safaricom refused the app's key and secret (HTTP {r.status_code}).")
    body = r.json()
    _token.update(value=body["access_token"], until=time.time() + max(60, int(body.get("expires_in") or 3599) - 120))
    return str(body["access_token"])


def _password(c: dict[str, str], stamp: str) -> str:
    return base64.b64encode(f"{c['shortcode']}{c['passkey']}{stamp}".encode()).decode()


def stk_push(*, owner: str, phone_number: str, amount: int, callback_base: str) -> dict[str, Any]:
    """Ask the customer's phone for the PIN. The pending payment is stored
    before Safaricom answers, so its callback always finds it."""
    import httpx

    from ..infra.db import execute

    ok, why = ready()
    if not ok:
        raise MpesaError(why)
    number = phone(phone_number)
    if not number:
        raise MpesaError("Use a Safaricom number like 0712 345 678.")
    c = config()
    stamp = datetime.now(EAT).strftime("%Y%m%d%H%M%S")
    payload = {
        "BusinessShortCode": c["shortcode"], "Password": _password(c, stamp), "Timestamp": stamp,
        "TransactionType": "CustomerBuyGoodsOnline" if c["type"] == "till" else "CustomerPayBillOnline",
        "Amount": int(amount), "PartyA": number,
        "PartyB": c["till"] if c["type"] == "till" else c["shortcode"], "PhoneNumber": number,
        "CallBackURL": f"{callback_base.rstrip('/')}/api/v1/billing/mpesa/callback/{c['callback_token']}",
        "AccountReference": "CBC" + re.sub(r"[^A-Za-z0-9]", "", owner)[:9].upper(),
        "TransactionDesc": "CBC wallet top-up",
    }
    try:
        r = httpx.post(f"{_base(c)}/mpesa/stkpush/v1/processrequest", json=payload,
                       headers={"Authorization": f"Bearer {_access_token(c)}"}, timeout=30)
        body = r.json() if r.content else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise MpesaError(f"Could not reach Safaricom: {type(exc).__name__}") from exc
    if r.status_code != 200 or str(body.get("ResponseCode")) != "0":
        raise MpesaError(str(body.get("errorMessage") or body.get("ResponseDescription")
                             or f"Safaricom did not take the request (HTTP {r.status_code})."))
    checkout = str(body.get("CheckoutRequestID") or "")
    execute("""INSERT INTO mpesa_payments (checkout_request_id, merchant_request_id, owner, phone, amount, status)
               VALUES (:c, :m, :o, :p, :a, 'pending')""",
            {"c": checkout, "m": str(body.get("MerchantRequestID") or ""), "o": owner, "p": masked(number),
             "a": int(amount)})
    logger.info("STK push %s for %s: KSh %s", checkout, owner, amount)
    return {"checkout_request_id": checkout, "status": "pending",
            "message": str(body.get("CustomerMessage") or "Check your phone and enter your M-Pesa PIN.")}


def _settle(checkout: str, *, paid: bool, code: str, desc: str, receipt: str = "",
            amount: int | None = None, raw: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Close a pending payment; credit the wallet only if this call closed it."""
    from sqlalchemy import text

    from ..infra.db import get_engine, to_json
    from . import billing

    status = "paid" if paid else ("cancelled" if code == "1032" else "failed")
    with get_engine().begin() as c:
        row = c.execute(text("""UPDATE mpesa_payments SET status = :s, result_code = :rc, result_desc = :rd,
                                       receipt = :r, raw = CAST(:raw AS jsonb), updated_at = NOW()
                                WHERE checkout_request_id = :c AND status = 'pending'
                                RETURNING owner, amount"""),
                        {"s": status, "rc": code, "rd": desc[:300], "r": receipt[:40], "raw": to_json(raw or {}),
                         "c": checkout}).mappings().first()
        if row is None:
            return None                    # unknown, or settled already: never credit twice
        if paid:
            got = int(amount if amount is not None else row["amount"])
            if got != int(row["amount"]):
                logger.warning("Payment %s: asked KSh %s, Safaricom says KSh %s — crediting what was paid",
                               checkout, row["amount"], got)
            billing.credit(str(row["owner"]), got * 100, kind="topup", ref=receipt or checkout,
                           note=f"M-Pesa {receipt}".strip(), conn=c)
    return {"owner": row["owner"], "status": status}


def handle_callback(body: dict[str, Any]) -> dict[str, Any]:
    """Safaricom's result for one STK push."""
    cb = ((body or {}).get("Body") or {}).get("stkCallback") or {}
    checkout = str(cb.get("CheckoutRequestID") or "")
    code = str(cb.get("ResultCode", ""))
    items = {str(i.get("Name")): i.get("Value") for i in ((cb.get("CallbackMetadata") or {}).get("Item") or [])
             if isinstance(i, dict)}
    if not checkout:
        return {"ok": False}
    amount = None
    try:
        amount = int(float(items["Amount"])) if "Amount" in items else None
    except (TypeError, ValueError):
        amount = None
    out = _settle(checkout, paid=code == "0", code=code, desc=str(cb.get("ResultDesc") or ""),
                  receipt=str(items.get("MpesaReceiptNumber") or ""), amount=amount,
                  raw={"ResultCode": code, "ResultDesc": cb.get("ResultDesc"),
                       "Receipt": items.get("MpesaReceiptNumber"), "Amount": items.get("Amount")})
    return {"ok": True, "settled": bool(out)}


def status(checkout: str, owner: str) -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    row = fetch_one("""SELECT checkout_request_id, owner, amount, status, result_desc, receipt, created_at
                       FROM mpesa_payments WHERE checkout_request_id = :c AND owner = :o""", {"c": checkout, "o": owner})
    return dict(row) if row else None


def refresh(checkout: str, owner: str) -> dict[str, Any] | None:
    """The payment as it stands; still pending after 20 s, ask Daraja."""
    import httpx

    row = status(checkout, owner)
    if not row or row["status"] != "pending":
        return row
    created = row.get("created_at")
    if isinstance(created, datetime) and datetime.now(created.tzinfo or timezone.utc) - created < timedelta(seconds=20):
        return row
    ok, _ = ready()
    if not ok:
        return row
    c = config()
    stamp = datetime.now(EAT).strftime("%Y%m%d%H%M%S")
    try:
        r = httpx.post(f"{_base(c)}/mpesa/stkpushquery/v1/query",
                       json={"BusinessShortCode": c["shortcode"], "Password": _password(c, stamp),
                             "Timestamp": stamp, "CheckoutRequestID": checkout},
                       headers={"Authorization": f"Bearer {_access_token(c)}"}, timeout=20)
        body = r.json() if r.content else {}
    except (httpx.HTTPError, ValueError, MpesaError):
        return row
    code = str(body.get("ResultCode", ""))
    if code == "":
        return row                         # still being processed
    if code == "0":
        # The query has no receipt or amount: credit what was asked; the
        # callback, if it comes, finds the row settled and does nothing.
        _settle(checkout, paid=True, code=code, desc=str(body.get("ResultDesc") or ""))
    else:
        _settle(checkout, paid=False, code=code, desc=str(body.get("ResultDesc") or ""))
    return status(checkout, owner)


def callback_token_ok(token: str) -> bool:
    expected = config()["callback_token"]
    return bool(expected) and secrets.compare_digest(token, expected)

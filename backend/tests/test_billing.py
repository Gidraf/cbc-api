"""The wallet, paper pricing, the content API's meter, and M-Pesa top-ups.

The money paths run against a real Postgres (transactions, the balance that
never goes below zero, one purchase at a time): set CBC_TEST_DATABASE_URL to
an empty database to run them. The rest needs no database.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.services import billing, mpesa

DB = os.getenv("CBC_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_DATABASE_URL to an empty Postgres database")

TEXT = {"question_id": "q-text-{}", "diagram": None}
FIG = {"question_id": "q-fig-{}", "diagram": {"diagram_id": "d1"}}


def _qs(n_text: int, n_fig: int, start: int = 0) -> list[dict]:
    return ([{**TEXT, "question_id": f"q-text-{start + i}"} for i in range(n_text)]
            + [{**FIG, "question_id": f"q-fig-{start + i}"} for i in range(n_fig)])


@pytest.fixture()
def db(monkeypatch):
    """The billing tables on a clean database, with the default prices."""
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    sql = dict(infra.MIGRATIONS)["049_billing"]
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS wallets, wallet_entries, mpesa_payments, question_purchases, api_usage"))
        c.execute(text(sql))
    yield engine
    engine.dispose()


# ── papers ───────────────────────────────────────────────────────────────────

@needs_db
def test_ten_free_questions_then_five_and_eight_shillings(db):
    q = billing.quote_paper("mama", "user", _qs(8, 6))
    assert q["free"] == 10 and q["unpaid"] == 14
    # Diagram questions take the free places first: 6 figures + 4 text free, 4 text paid.
    assert q["total_ksh"] == 20 and q["text"] == 4 and q["diagram"] == 0
    with pytest.raises(billing.PaymentRequired) as short:
        billing.buy_paper("mama", "user", _qs(8, 6), ref="d1")
    assert short.value.needed == 2000
    assert billing.free_used("mama") == 0                 # nothing happened: not even the free ones
    billing.credit("mama", 100_00, kind="topup", ref="R1")
    out = billing.buy_paper("mama", "user", _qs(8, 6), ref="d1")
    assert out["charged_ksh"] == 20 and out["paid"] and billing.balance("mama") == 80_00
    # Paid once: the same questions never cost again, on this paper or another.
    assert billing.buy_paper("mama", "user", _qs(8, 6), ref="d2")["charged_ksh"] == 0
    # New questions are priced at full: 2 text (KSh 10) and 1 figure (KSh 8).
    more = _qs(8, 6) + _qs(2, 1, start=100)
    assert billing.quote_paper("mama", "user", more)["total_ksh"] == 18
    assert billing.buy_paper("mama", "user", more, ref="d3")["charged_ksh"] == 18
    assert billing.balance("mama") == 62_00


@needs_db
def test_staff_are_never_charged(db):
    q = billing.quote_paper("gidraf", "admin", _qs(50, 50))
    assert q["exempt"] and q["paid"] and q["total_ksh"] == 0
    assert billing.buy_paper("gidraf", "operator", _qs(5, 5), ref="x")["charged_ksh"] == 0


@needs_db
def test_the_balance_never_goes_below_zero_and_every_shilling_has_an_entry(db):
    billing.credit("t", 7_00, kind="topup")
    with pytest.raises(billing.PaymentRequired):
        billing.buy_paper("t", "user", _qs(12, 0), ref="p")      # 2 paid text = KSh 10 > KSh 7
    assert billing.balance("t") == 7_00
    entries = billing.entries("t")
    assert [e["kind"] for e in entries] == ["topup"] and entries[0]["amount_ksh"] == 7


# ── the content API ──────────────────────────────────────────────────────────

@needs_db
def test_free_calls_then_per_question_then_402(db, monkeypatch):
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "_load", lambda: {"billing_api_free_daily": 2, "billing_api_free_monthly": 3})
    now = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
    page = [{"has_figure": False}] * 4 + [{"has_figure": True}] * 2
    assert billing.meter_api("dev", "api", page, ref="a", now=now)["free"]
    assert billing.meter_api("dev", "api", page, ref="b", now=now)["free"]
    with pytest.raises(billing.PaymentRequired):                          # day's 2 free used, wallet empty
        billing.meter_api("dev", "api", page, ref="c", now=now)
    assert billing.api_usage("dev", now)["calls_today"] == 2              # the refused call is not counted
    billing.credit("dev", 20_00, kind="topup")
    out = billing.meter_api("dev", "api", page, ref="d", now=now)
    assert not out["free"] and out["charged_ksh"] == 11                   # 4 × 1.50 + 2 × 2.50
    tomorrow = now + timedelta(days=1)
    # A new day, but the month's 3 free calls are gone: still charged.
    assert billing.meter_api("dev", "api", [{"has_figure": False}], ref="e", now=tomorrow)["charged_ksh"] == 1.5
    assert billing.api_usage("dev", tomorrow)["free_left_today"] == 0
    assert billing.balance("dev") == 20_00 - 11_00 - 1_50


# ── M-Pesa ───────────────────────────────────────────────────────────────────

def _callback(checkout: str, code: int = 0, amount: int = 100, receipt: str = "SJK1ABC2DE") -> dict:
    cb = {"MerchantRequestID": "m", "CheckoutRequestID": checkout, "ResultCode": code, "ResultDesc": "ok"}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": [{"Name": "Amount", "Value": amount}, {"Name": "MpesaReceiptNumber", "Value": receipt},
                                           {"Name": "PhoneNumber", "Value": 254712345678}]}
    return {"Body": {"stkCallback": cb}}


@needs_db
def test_a_payment_is_credited_once_however_many_times_safaricom_calls(db):
    from sqlalchemy import text

    with db.begin() as c:
        c.execute(text("INSERT INTO mpesa_payments (checkout_request_id, owner, amount) VALUES ('ws_1', 'mama', 100)"))
    assert mpesa.handle_callback(_callback("ws_1"))["settled"]
    assert not mpesa.handle_callback(_callback("ws_1"))["settled"]
    assert billing.balance("mama") == 100_00
    assert billing.entries("mama")[0]["ref"] == "SJK1ABC2DE"
    assert mpesa.status("ws_1", "mama")["status"] == "paid"
    assert mpesa.status("ws_1", "someone-else") is None                  # a payment is its owner's only


@needs_db
def test_a_cancelled_prompt_credits_nothing(db):
    from sqlalchemy import text

    with db.begin() as c:
        c.execute(text("INSERT INTO mpesa_payments (checkout_request_id, owner, amount) VALUES ('ws_2', 'mama', 50)"))
    mpesa.handle_callback(_callback("ws_2", code=1032))
    assert mpesa.status("ws_2", "mama")["status"] == "cancelled" and billing.balance("mama") == 0
    mpesa.handle_callback(_callback("ws_2", code=0))                      # a late "paid" after a cancel: ignored
    assert billing.balance("mama") == 0


def test_phone_numbers():
    assert mpesa.phone("0712 345 678") == "254712345678"
    assert mpesa.phone("+254 110 123456") == "254110123456"
    assert mpesa.phone("712345678") == "254712345678"
    assert mpesa.phone("0812345678") == "" and mpesa.phone("12345") == ""
    assert mpesa.masked("254712345678") == "254712***678"


def test_top_ups_say_which_settings_are_missing_by_name_only(monkeypatch):
    for name in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY",
                 "MPESA_CALLBACK_TOKEN", "MPESA_TILL_NUMBER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MPESA_CONSUMER_SECRET", "s3cret-value")
    ok, why = mpesa.ready()
    assert not ok and "MPESA_PASSKEY" in why and "s3cret-value" not in why and "MPESA_CONSUMER_SECRET" not in why


def test_till_and_paybill_send_the_right_request(monkeypatch):
    import httpx

    from app.infra import db as infra

    sent = {}

    class R:
        status_code = 200
        content = b"{}"

        def __init__(self, body):
            self._b = body

        def json(self):
            return self._b

    monkeypatch.setattr(httpx, "get", lambda *a, **k: R({"access_token": "tok", "expires_in": 3599}))
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None:
                        sent.update(url=url, body=json) or R({"ResponseCode": "0", "CheckoutRequestID": "ws_9",
                                                              "MerchantRequestID": "m9", "CustomerMessage": "Enter PIN"}))
    monkeypatch.setattr(infra, "execute", lambda sql, p=None: sent.update(row=p))
    mpesa._token.update(value="", until=0)
    env = {"MPESA_CONSUMER_KEY": "k", "MPESA_CONSUMER_SECRET": "s", "MPESA_SHORTCODE": "600000",
           "MPESA_PASSKEY": "pk", "MPESA_CALLBACK_TOKEN": "cbtoken", "MPESA_TYPE": "till", "MPESA_TILL_NUMBER": "5123456"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    out = mpesa.stk_push(owner="mama", phone_number="0712345678", amount=100, callback_base="https://cbc.gidraf.dev")
    assert out["checkout_request_id"] == "ws_9"
    b = sent["body"]
    assert b["TransactionType"] == "CustomerBuyGoodsOnline" and b["PartyB"] == "5123456" and b["BusinessShortCode"] == "600000"
    assert b["CallBackURL"] == "https://cbc.gidraf.dev/api/v1/billing/mpesa/callback/cbtoken"
    assert sent["url"].startswith("https://sandbox.safaricom.co.ke") and sent["row"]["p"] == "254712***678"
    monkeypatch.setenv("MPESA_TYPE", "paybill")
    monkeypatch.setenv("MPESA_ENV", "production")
    mpesa.stk_push(owner="mama", phone_number="0712345678", amount=100, callback_base="https://cbc.gidraf.dev")
    assert sent["body"]["TransactionType"] == "CustomerPayBillOnline" and sent["body"]["PartyB"] == "600000"
    assert sent["url"].startswith("https://api.safaricom.co.ke")


def test_the_callback_needs_the_secret_in_its_path(monkeypatch):
    monkeypatch.setenv("MPESA_CALLBACK_TOKEN", "the-right-one")
    assert mpesa.callback_token_ok("the-right-one")
    assert not mpesa.callback_token_ok("guess")
    monkeypatch.setenv("MPESA_CALLBACK_TOKEN", "")
    assert not mpesa.callback_token_ok("")                                # unset: nothing is accepted


# ── who signs up as what ─────────────────────────────────────────────────────

def test_nobody_signs_up_into_the_factory(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import auth as auth_routes

    from app.services import platform_settings, rate_limit

    rate_limit.reset_all()
    made = []
    monkeypatch.setattr(auth_routes, "fetch_one", lambda sql, p=None: None)
    monkeypatch.setattr(auth_routes, "execute", lambda sql, p=None: made.append(p["role"]))
    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: ["gidraf"] if k == "video_makers" else d)
    c = TestClient(app)
    for asked in ("reviewer", "developer", "admin", "operator", "user", "api", ""):
        rate_limit.reset_all()                 # five sign-ups an hour from one address
        c.post("/api/v1/auth/register", json={"username": f"person-{asked or 'none'}", "password": "a long passphrase",
                                              "role": asked})
    assert made == ["user", "api", "user", "user", "user", "api", "user"]


# ── the paper the owner prints ───────────────────────────────────────────────

def test_their_own_lines_the_name_and_the_version_print_and_unpaid_previews_are_marked():
    from app.services import question_paper
    from app.services.paper_builder import thaw

    snapshot = {"kind": "topical", "title": "Integers", "grade": "grade-9", "subject": "Mathematics",
                "masthead": {"header_lines": ["Moi Avenue Primary", "Grade 9 Blue — Term 3"],
                             "candidate": "Achieng Otieno", "version": "B"},
                "sections": [{"letter": "", "heading": "", "instructions": "", "question_ids": ["q1"]}]}
    paper = thaw(snapshot, [{"question_id": "q1", "question_text": "What is -5 + 8?", "options": []}])
    html = question_paper.render_paper(paper, preview_mark=True)
    assert "Moi Avenue Primary" in html and "Grade 9 Blue — Term 3" in html
    assert "Achieng Otieno" in html and "VERSION B" in html and "previewmark" in html
    assert "previewmark'" not in question_paper.render_paper(paper)


# ── the routes ───────────────────────────────────────────────────────────────

@pytest.fixture()
def as_role():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import AuthContext, get_auth_context

    who = {"subject": "dev1", "role": "api"}
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(subject=who["subject"], role=who["role"], auth_type="api_key")
    try:
        yield TestClient(app), who
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


def test_the_content_api_charges_or_answers_402_and_says_what_is_left(as_role, monkeypatch):
    from app.services import content_api

    c, who = as_role
    row = {"question_id": "q1", "content": {"question_text": "What is -5 + 8?", "correct_answer": "3",
                                            "marking_scheme": "B1", "options": []},
           "curriculum_link": {"grade": "grade-9", "subject": "Mathematics"}, "pedagogical_dna": {"max_marks": 1}}
    monkeypatch.setattr(content_api, "search", lambda f, limit=20, offset=0: ([row], 1))
    monkeypatch.setattr(billing, "api_usage", lambda owner, now=None: {"free_left_today": 7, "balance_ksh": 12.5})
    monkeypatch.setattr(billing, "meter_api", lambda *a, **k: {"free": False, "charged_ksh": 1.5})
    r = c.get("/api/v1/content/questions", params={"grade": "Grade 9"})
    assert r.status_code == 200 and r.json()["items"][0]["question"] == "What is -5 + 8?"
    assert r.json()["items"][0]["answer"] == "3" and r.json()["charged_ksh"] == 1.5
    assert r.headers["X-Free-Calls-Left-Today"] == "7" and r.headers["X-Wallet-Balance-KSh"] == "12.5"

    def broke(*a, **k):
        raise billing.PaymentRequired("Costs KSh 1.5, wallet KSh 0.", needed=150, price=150, balance=0)
    monkeypatch.setattr(billing, "meter_api", broke)
    r = c.get("/api/v1/content/questions")
    err = r.json()["errors"][0]
    assert r.status_code == 402 and err["code"] == "PAYMENT_REQUIRED" and err["detail"]["needed_ksh"] == 1.5
    who["role"] = "user"                                   # a parent's account is not a developer's
    assert c.get("/api/v1/content/questions").status_code == 403


def test_the_docs_are_public_and_cover_only_the_content_api(as_role):
    from app.main import app
    from app.services.auth import get_auth_context

    c, _ = as_role
    app.dependency_overrides.pop(get_auth_context, None)    # signed out
    spec = c.get("/api/v1/content/openapi.json").json()
    paths = set(spec["paths"])
    assert "/api/v1/content/questions" in paths and "/api/v1/billing/topup" in paths
    assert not any(p.startswith(("/api/v1/questions", "/api/v1/play", "/api/v1/builder")) for p in paths)
    assert "/api/v1/billing/mpesa/callback/{token}" not in paths
    assert "import requests" in spec["info"]["description"] and "KSh 1.50" in spec["info"]["description"]
    assert spec["components"]["securitySchemes"]["ApiKey"]["name"] == "X-API-Key"
    html = c.get("/api/v1/content/docs").text
    assert "redoc@2.1.5" in html and "/api/v1/content/openapi.json" in html


def test_an_unpaid_paper_previews_marked_and_will_not_download(as_role, monkeypatch):
    from app.services import exam_drafts, pdf

    c, who = as_role
    who.update(subject="mama", role="user")
    row = {"draft_id": "d1", "title": "Integers", "grade": "grade-9", "subject": "Mathematics", "settings": {},
           "items": [{"question_id": "q1"}], "snapshot": {}}
    monkeypatch.setattr(exam_drafts, "get", lambda draft_id, owner="": row)
    seen = {}
    monkeypatch.setattr(exam_drafts, "render", lambda r, **k: seen.update(k) or "<html>paper</html>")
    monkeypatch.setattr(exam_drafts, "paper_for", lambda r: type("P", (), {"items": [{"question_id": "q1"}]})())
    monkeypatch.setattr(billing, "quote_paper", lambda o, role, qs: {"paid": False, "total_ksh": 5, "unpaid": 1, "free": 0,
                                                                     "balance_ksh": 0, "lines": []})
    r = c.get("/api/v1/builder/drafts/d1/preview.html", params={"answers": "true", "with_scheme": "true"})
    assert r.status_code == 200 and seen["preview_mark"] and not seen["answers"] and not seen["with_scheme"]
    monkeypatch.setattr(pdf, "from_html", lambda html: b"%PDF")
    assert c.get("/api/v1/builder/drafts/d1/preview.pdf").status_code == 402
    assert c.post("/api/v1/builder/drafts/d1/freeze").status_code == 403
    monkeypatch.setattr(billing, "quote_paper", lambda o, role, qs: {"paid": True, "lines": []})
    r = c.get("/api/v1/builder/drafts/d1/preview.html", params={"answers": "true"})
    assert not seen["preview_mark"] and seen["answers"]


def test_a_developer_who_signed_up_can_actually_sign_in():
    """A real token, not an override: the role has to be one the API accepts."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.auth import create_access_token

    from app.services import auth as auth_service

    token = create_access_token("devtest", "api")
    auth_service._ACCOUNT_CACHE["devtest"] = (10**12, {"username": "devtest", "role": "api", "is_active": True})
    r = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    auth_service._ACCOUNT_CACHE.pop("devtest", None)
    assert r.status_code == 200 and r.json()["role"] == "api"

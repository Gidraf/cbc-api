"""The platform's defences: passwords, tokens, keys, limits, headers, secrets."""
from __future__ import annotations

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth as auth_service
from app.services import rate_limit, secrets_guard


@pytest.fixture(autouse=True)
def _fresh():
    rate_limit.reset_all()
    auth_service._ACCOUNT_CACHE.clear()
    yield
    rate_limit.reset_all()
    auth_service._ACCOUNT_CACHE.clear()


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode()


# ── passwords ────────────────────────────────────────────────────────────────

def test_plain_text_passwords_are_never_accepted():
    assert not auth_service.verify_password("admin123", "admin123")
    assert auth_service.verify_password("a long passphrase", _hash("a long passphrase"))
    assert not auth_service.verify_password("wrong", _hash("a long passphrase"))


def test_a_wrong_name_and_a_switched_off_account_get_the_same_answer(monkeypatch):
    rows = {"amina": {"username": "amina", "password_hash": _hash("a long passphrase"), "role": "user", "is_active": False}}
    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: rows.get(p["uname"]))
    for name, pw in (("nobody", "x"), ("amina", "a long passphrase"), ("amina", "wrong")):
        with pytest.raises(Exception) as err:
            auth_service.authenticate_login(name, pw)
        assert "Invalid username or password" in str(err.value)
    rows["amina"]["is_active"] = True
    assert auth_service.authenticate_login("amina", "a long passphrase").role == "user"


def test_startup_hashes_plain_passwords_and_switches_off_default_ones(monkeypatch):
    from app import state

    users = {"old": {"username": "old", "password_plain": "their-own-password", "password_hash": "", "role": "user", "is_active": True},
             "admin": {"username": "admin", "password_plain": "", "password_hash": _hash("admin123"), "role": "admin", "is_active": True},
             "boss": {"username": "boss", "password_plain": "", "password_hash": _hash("a strong one here"), "role": "admin", "is_active": True}}

    def fetch_all(sql, p=None):
        if "password_plain, '') <> ''" in sql:
            return [dict(u) for u in users.values() if u["password_plain"]]
        return [dict(u) for u in users.values() if u["is_active"] and u["role"] in ("admin", "operator", "reviewer", "developer")]

    def execute(sql, p=None):
        u = users.setdefault(p["u"], {"username": p["u"], "password_plain": "", "password_hash": "", "role": "user", "is_active": True})
        if "password_hash = :h" in sql:
            u.update(password_hash=p["h"], password_plain="")
        elif "password_plain = ''" in sql and "is_active = FALSE" not in sql:
            u["password_plain"] = ""
        if "is_active = FALSE" in sql:
            u["is_active"] = False

    import app.infra.db as db
    monkeypatch.setattr(db, "fetch_all", fetch_all)
    monkeypatch.setattr(db, "execute", execute)
    for name in ("ADMIN_PASSWORD", "OPERATOR_PASSWORD", "REVIEWER_PASSWORD", "DEVELOPER_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPERATOR_PASSWORD", "operator123")          # a default in .env: ignored
    done = state.harden_users()
    assert users["old"]["password_plain"] == "" and users["old"]["password_hash"].startswith("$2")
    assert auth_service.verify_password("their-own-password", users["old"]["password_hash"])
    assert done["switched_off"] == ["admin"] and not users["admin"]["is_active"]
    assert users["boss"]["is_active"] and "OPERATOR_PASSWORD" in done["weak_env"]
    assert "operator" not in users                                    # no account is made with a default


def test_sign_ups_need_a_real_password_and_cannot_take_a_trusted_name(monkeypatch):
    from app.routes import auth as auth_routes
    from app.services import platform_settings

    made = []
    monkeypatch.setattr(auth_routes, "fetch_one", lambda sql, p=None: None)
    monkeypatch.setattr(auth_routes, "execute", lambda sql, p=None: made.append(p["uname"]))
    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: ["gidraf"] if k == "video_makers" else d)
    c = TestClient(app)

    def signup(name, pw):
        rate_limit.reset_all()
        return c.post("/api/v1/auth/register", json={"username": name, "password": pw, "email": "someone@example.org"}).status_code

    assert signup("gidraf", "a long passphrase") == 400          # a video maker's name
    assert signup("Admin", "a long passphrase") == 400           # a built-in, any case
    assert signup("amina", "short") == 400
    assert signup("amina", "password123") == 400                 # a known default
    assert signup("amina", "amina") == 400
    assert signup("a b", "a long passphrase") == 400              # not a username
    assert signup("Amina.W", "a long passphrase") == 200
    assert made == ["amina.w"]


# ── tokens and keys ──────────────────────────────────────────────────────────

def test_a_token_stops_working_when_its_account_is_switched_off_or_changes_role(monkeypatch):
    token = auth_service.create_access_token("amina", "admin")
    c = TestClient(app)
    me = lambda: c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})  # noqa: E731
    auth_service._ACCOUNT_CACHE["amina"] = (10**12, {"username": "amina", "role": "user", "is_active": True})
    assert me().json()["role"] == "user"                          # the role it has now, not the token's
    auth_service._ACCOUNT_CACHE["amina"] = (10**12, {"username": "amina", "role": "user", "is_active": False})
    assert me().status_code == 401
    auth_service._ACCOUNT_CACHE["amina"] = (10**12, None)          # deleted
    assert me().status_code == 401


def test_an_expired_refresh_token_is_refused(monkeypatch):
    from datetime import datetime, timedelta, timezone

    gone = []
    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: {"user_id": "amina",
                        "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    monkeypatch.setattr(auth_service, "execute", lambda sql, p=None: gone.append(sql))
    with pytest.raises(Exception):
        auth_service.verify_and_consume_refresh_token("old")
    assert gone, "the used token is deleted even when refused"


def test_an_unknown_key_is_refused_and_the_example_fixed_key_never_works(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: None)
    c = TestClient(app)
    assert c.get("/api/v1/auth/me", headers={"X-API-Key": "cbc_live_guess"}).status_code == 401
    monkeypatch.setattr(settings, "developer_api_key", "cbc_live_dev_key_example")
    assert c.get("/api/v1/auth/me", headers={"X-API-Key": "cbc_live_dev_key_example"}).status_code == 401
    strong = "k" * 40
    monkeypatch.setattr(settings, "developer_api_key", strong)
    assert c.get("/api/v1/auth/me", headers={"X-API-Key": strong}).json()["role"] == "developer"


def test_a_key_dies_with_its_account(monkeypatch):
    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: {"user_id": "amina", "role": "api", "is_active": True}
                        if "api_keys" in sql else {"username": "amina", "role": "api", "is_active": False})
    monkeypatch.setattr(auth_service, "execute", lambda sql, p=None: None)
    assert TestClient(app).get("/api/v1/auth/me", headers={"X-API-Key": "cbc_live_x"}).status_code == 401


# ── limits ───────────────────────────────────────────────────────────────────

def test_password_guessing_is_stopped(monkeypatch):
    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: None)
    c = TestClient(app)
    codes = [c.post("/api/v1/auth/login", json={"username": "admin", "password": f"guess{i}"}).status_code for i in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]


def test_a_stranger_cannot_flood_a_phone_with_m_pesa_prompts(monkeypatch):
    from app.services import mpesa
    from app.services.auth import AuthContext, get_auth_context

    monkeypatch.setattr(mpesa, "stk_push", lambda **k: {"checkout_request_id": "ws", "status": "pending", "message": ""})
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(subject="mama", role="user", auth_type="bearer")
    try:
        c = TestClient(app)
        codes = [c.post("/api/v1/billing/topup", json={"phone": "0712345678", "amount": 50}).status_code for _ in range(4)]
    finally:
        app.dependency_overrides.pop(get_auth_context, None)
    assert codes == [200, 200, 200, 429]


def test_the_client_address_is_the_one_our_proxies_saw():
    class Req:
        def __init__(self, peer, xff):
            self.client = type("C", (), {"host": peer})()
            self.headers = {"x-forwarded-for": xff}

    # The caller wrote "1.2.3.4" themselves; nginx appended the real address.
    assert rate_limit.client_ip(Req("172.18.0.5", "1.2.3.4, 41.90.10.20, 127.0.0.1")) == "41.90.10.20"
    assert rate_limit.client_ip(Req("41.90.10.20", "1.2.3.4")) == "41.90.10.20"      # not via our proxy: ignored


# ── headers, CORS, secrets ───────────────────────────────────────────────────

def test_every_response_carries_the_protective_headers_and_cors_never_sends_cookies(monkeypatch):
    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: None)
    r = TestClient(app).get("/api/v1/content/docs", headers={"Origin": "https://evil.example"})
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "strict-origin" in r.headers["Referrer-Policy"]
    assert r.headers.get("access-control-allow-credentials") != "true"
    r = TestClient(app).post("/api/v1/auth/login", json={"username": "x", "password": "y"},
                             headers={"x-forwarded-proto": "https"})
    assert r.headers["Cache-Control"] == "no-store" and "max-age" in r.headers["Strict-Transport-Security"]


def test_weak_secrets_are_recognised():
    assert secrets_guard.jwt_weak("change-me-jwt-secret") and secrets_guard.jwt_weak("change-this-jwt-secret")
    assert secrets_guard.jwt_weak("short") and not secrets_guard.jwt_weak("x" * 48)
    assert secrets_guard.master_key_weak(None) and secrets_guard.master_key_weak(secrets_guard.PUBLISHED_MASTER_KEY)
    assert not secrets_guard.master_key_weak("another-key")


def test_the_repository_ships_no_usable_secret():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text()
    example = (root / ".env.example").read_text()
    for text in (compose, example):
        for bad in ("admin123", "operator123", "reviewer123", "developer123", secrets_guard.PUBLISHED_MASTER_KEY,
                    "change-this-jwt-secret", "cbc_live_dev_key_example"):
            assert bad not in text, bad
    for port in ('"5173:5173"', '"8000:8000"', '"3001:3000"'):
        assert port not in compose, f"{port} would be open to the internet"


def test_the_master_key_moves_all_saved_keys_or_none(monkeypatch):
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, text

    from app import admin_tools

    engine = create_engine("sqlite://")
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    with engine.begin() as c:
        c.execute(text("CREATE TABLE provider_configs (provider TEXT PRIMARY KEY, encrypted_api_key TEXT)"))
        c.execute(text("INSERT INTO provider_configs VALUES ('openai', :v), ('gemini', :w), ('ollama', '')"),
                  {"v": Fernet(old.encode()).encrypt(b"sk-1").decode(), "w": Fernet(old.encode()).encrypt(b"g-2").decode()})
    monkeypatch.setattr(admin_tools, "get_engine", lambda: engine)
    monkeypatch.setenv("OLD_MASTER_KEY", old)
    monkeypatch.setenv("NEW_MASTER_KEY", new)
    assert admin_tools.main(["rotate-master-key", "--dry-run"]) == 0
    with engine.begin() as c:
        still = c.execute(text("SELECT encrypted_api_key FROM provider_configs WHERE provider='openai'")).scalar()
    assert Fernet(old.encode()).decrypt(still.encode()) == b"sk-1"          # a dry run writes nothing
    assert admin_tools.main(["rotate-master-key"]) == 0
    with engine.begin() as c:
        rows = dict(c.execute(text("SELECT provider, encrypted_api_key FROM provider_configs")).all())
    assert Fernet(new.encode()).decrypt(rows["openai"].encode()) == b"sk-1"
    assert Fernet(new.encode()).decrypt(rows["gemini"].encode()) == b"g-2"
    assert admin_tools.main(["rotate-master-key"]) == 0                     # run twice: already moved, still fine


def test_you_set_your_own_password_with_the_current_one(monkeypatch):
    from app.routes import auth as auth_routes
    from app.services.auth import AuthContext, get_auth_context

    stored = {"hash": _hash("the one I was shown"), "tokens_cleared": False, "set": None}
    monkeypatch.setattr(auth_service, "fetch_one", lambda sql, p=None: {"username": "gidraf", "password_hash": stored["hash"],
                                                                       "role": "admin", "is_active": True})

    def execute(sql, p=None):
        if "password_hash = :h" in sql:
            stored["set"] = p["h"]
        if "DELETE FROM refresh_tokens" in sql:
            stored["tokens_cleared"] = True
    monkeypatch.setattr(auth_routes, "execute", execute)
    who = {"auth": AuthContext("gidraf", "admin", "bearer")}
    app.dependency_overrides[get_auth_context] = lambda: who["auth"]
    try:
        c = TestClient(app)
        say = lambda cur, new: c.post("/api/v1/auth/password", json={"current_password": cur, "new_password": new}).status_code  # noqa: E731
        assert say("wrong", "a brand new passphrase") == 401
        assert say("the one I was shown", "short") == 400
        assert say("the one I was shown", "password123") == 400
        assert say("the one I was shown", "a brand new passphrase") == 200
        assert auth_service.verify_password("a brand new passphrase", stored["set"]) and stored["tokens_cleared"]
        who["auth"] = AuthContext("gidraf", "admin", "api_key")
        assert say("the one I was shown", "another new passphrase") == 403        # a key cannot
    finally:
        app.dependency_overrides.pop(get_auth_context, None)

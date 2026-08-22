from __future__ import annotations

from app.services.auth import create_access_token, hash_password, verify_password


def test_password_hashing():
    pwd = "secret_password_123"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_jwt_token_creation():
    token = create_access_token("admin_user", "admin")
    assert isinstance(token, str)
    assert len(token.split(".")) == 3  # Valid JWT format

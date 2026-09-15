"""Tests for security utilities."""
import jwt
from fastapi import Response

from app.core import security
from app.core.security import (
    _ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_COOKIE,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    set_refresh_cookie,
    verify_password,
)
from app.db.database import hash_token


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = hash_password("mysecret")
        assert hashed != "mysecret"

    def test_verify_correct_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("correct_password", hashed) is True

    def test_reject_wrong_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_same_password_different_hashes(self):
        # bcrypt uses random salt — same password produces different hashes
        h1 = hash_password("password")
        h2 = hash_password("password")
        assert h1 != h2

    def test_verify_works_across_salted_hashes(self):
        hashed = hash_password("shared_secret")
        assert verify_password("shared_secret", hashed) is True


class TestJWT:
    def test_token_roundtrip(self):
        token = create_access_token("alice")
        recovered = decode_token(token)
        assert recovered == "alice"

    def test_tampered_token_returns_none(self):
        token = create_access_token("bob")
        tampered = token[:-4] + "XXXX"
        assert decode_token(tampered) is None

    def test_garbage_token_returns_none(self):
        assert decode_token("not.a.valid.jwt.at.all") is None

    def test_empty_token_returns_none(self):
        assert decode_token("") is None


class TestSessionHelpers:
    """HttpOnly-cookie refresh-session helpers (no DB needed)."""

    def test_hash_token_is_sha256_hex_and_deterministic(self):
        assert len(hash_token("abc")) == 64
        assert hash_token("abc") == hash_token("abc")
        assert hash_token("abc") != hash_token("abd")

    def test_hash_never_stores_plaintext(self):
        raw = "a-long-unguessable-refresh-token"
        assert hash_token(raw) != raw

    def test_refresh_token_is_urlsafe_and_unique(self):
        a, b = create_refresh_token(), create_refresh_token()
        assert a != b
        assert len(a) >= 43
        # token_urlsafe alphabet has no '+/', '=', but may contain '-' or '_'
        assert all(c.isalnum() or c in "-_" for c in a)

    def test_access_token_expires_in_configured_minutes(self):
        token = create_access_token("carol")
        payload = jwt.decode(token, security.SECRET_KEY, algorithms=["HS256"])
        ttl = payload["exp"] - payload["iat"]
        assert abs(ttl - _ACCESS_TOKEN_EXPIRE_MINUTES * 60) <= 60

    def test_set_refresh_cookie_is_httponly_lax_root(self):
        resp = Response()
        set_refresh_cookie(resp, "tok123")
        h = resp.headers.get("set-cookie", "").lower()
        assert REFRESH_COOKIE in h and "tok123" in h
        assert "httponly" in h
        assert "samesite=lax" in h
        assert "path=/" in h

    def test_secure_flag_sets_in_production(self):
        prev = security._is_production
        security._is_production = lambda: True
        try:
            resp = Response()
            set_refresh_cookie(resp, "tok123")
            assert "secure" in resp.headers.get("set-cookie", "").lower()
        finally:
            security._is_production = prev

    def test_clear_refresh_cookie_expires_it(self):
        resp = Response()
        clear_refresh_cookie(resp)
        h = resp.headers.get("set-cookie", "").lower()
        assert REFRESH_COOKIE in h
        # deletion marks max-age=0 / expires in the past
        assert "max-age=0" in h or "expires=thu, 01 jan 1970" in h

"""Tests for security utilities."""
import pytest

from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


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

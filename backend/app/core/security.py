"""Security utilities — password hashing and JWT."""
from __future__ import annotations

import logging
import os
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt as _bcrypt_lib
import jwt
from fastapi import HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError as JWTError

logger = logging.getLogger(__name__)

_PLACEHOLDER_SECRETS = frozenset({
    "your-secret-key-change-in-production",
    "replace_with_generated_key",
    "changeme",
    "secret",
    "secret_key",
    "atom_secret",
})


def is_insecure_secret(key: str) -> bool:
    stripped = key.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    if lowered in _PLACEHOLDER_SECRETS:
        return True
    if "replace_with" in lowered or lowered.startswith("your-secret"):
        return True
    return False


def _generate_dev_secret() -> str:
    import secrets
    generated = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY is missing or is a known placeholder — generated a random key. "
        "JWTs will be invalidated on every restart. Set a 32+ byte SECRET_KEY in .env."
    )
    return generated


SECRET_KEY: str = os.getenv("SECRET_KEY", "")
_ENV = os.getenv("ATOM_ENV", "development").lower()

if is_insecure_secret(SECRET_KEY):
    if _ENV == "production":
        raise RuntimeError(
            "SECRET_KEY is missing or is a documented placeholder. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    SECRET_KEY = _generate_dev_secret()

if _ENV == "production" and len(SECRET_KEY.encode()) < 32:
    raise RuntimeError("Production SECRET_KEY must contain at least 32 bytes")

_ALGORITHM = "HS256"
# Short-lived access token (kept only in front-end memory, never localStorage).
_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
# Long-lived opaque refresh token, carried in an HttpOnly cookie and rotated on use.
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "45"))
REFRESH_COOKIE = "atom_refresh"

_bearer = HTTPBearer(auto_error=False)


def _is_production() -> bool:
    return os.getenv("ATOM_ENV", "development").lower() == "production"


def hash_password(password: str) -> str:
    return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt_lib.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(username: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=_ALGORITHM)


def create_refresh_token() -> str:
    """Generates an opaque, unguessable refresh token (stored only as a hash)."""
    return secrets.token_urlsafe(48)


def set_refresh_cookie(response: Response, token: str) -> None:
    """Marks the refresh token as an HttpOnly cookie so it is not JS-readable."""
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_is_production(),
        path="/",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_production(),
    )


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[_ALGORITHM], options={"require": ["exp", "iat", "sub"]})
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str:
    """FastAPI dependency — returns the authenticated username."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = decode_token(credentials.credentials)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    from app.db.database import get_user_by_username
    user = await get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="Account unavailable")
    return user["username"]

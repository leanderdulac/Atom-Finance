"""Security utilities — password hashing and JWT."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt_lib
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

SECRET_KEY: str = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets
    SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "SECRET_KEY env var is not set — generated a random key. "
        "Set SECRET_KEY in your .env file for a stable key."
    )

_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt_lib.checkpw(plain.encode(), hashed.encode())


def create_access_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + timedelta(hours=_ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer),
) -> str:
    """FastAPI dependency — returns the authenticated username."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = decode_token(credentials.credentials)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username

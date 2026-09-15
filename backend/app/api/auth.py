"""
Authentication API — JWT with bcrypt password hashing, backed by Postgres.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.core.limiter import limiter
from app.core.security import (
    _ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_COOKIE,
    REFRESH_TOKEN_EXPIRE_DAYS,
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    set_refresh_cookie,
    verify_password,
)
from app.db.database import (
    create_refresh_token as db_create_refresh,
)
from app.db.database import (
    create_user,
    get_user_by_id,
    get_user_by_username,
    hash_token,
    list_users,
    revoke_refresh_token,
    rotate_refresh_token,
    user_exists,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_DUMMY_PASSWORD_HASH = hash_password("atom-timing-dummy-not-a-real-user")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value):
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must fit within 72 UTF-8 bytes")
        return value


class RegisterRequest(LoginRequest):
    password: str = Field(min_length=12, max_length=72)
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
@limiter.limit("3/hour")
async def register(request: Request, req: RegisterRequest):
    allowed = os.getenv("ATOM_ALLOW_REGISTRATION", "false" if os.getenv("ATOM_ENV") == "production" else "true")
    if allowed.lower() != "true":
        raise HTTPException(status_code=403, detail="Registration is disabled; contact the operator.")
    already_taken = await user_exists(req.username)
    if already_taken:
        raise HTTPException(status_code=400, detail="Unable to register with these credentials.")

    pw_hash = await asyncio.to_thread(hash_password, req.password)
    uid = await create_user(req.username, req.email, pw_hash)

    if uid is None:
        raise HTTPException(
            status_code=400,
            detail="Unable to register with these credentials.",
        )

    logger.info("New user registered: %s (id=%d)", req.username, uid)
    return {"message": "User registered successfully.", "username": req.username.lower()}


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, response: Response):
    user = await get_user_by_username(req.username)
    stored = user["password_hash"] if user else _DUMMY_PASSWORD_HASH
    pwd_ok = await asyncio.to_thread(verify_password, req.password, stored)
    if not user or not pwd_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    # Short-lived access token (front-end keeps it only in memory) + a long-lived
    # opaque refresh token carried in an HttpOnly, SameSite=Lax cookie.
    access_token = create_access_token(user["username"])
    refresh_token = create_refresh_token()
    await db_create_refresh(
        user["id"],
        hash_token(refresh_token),
        datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )
    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
        "expires_in": _ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "refresh_cookie_set": True,
    }


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    """Rotates the HttpOnly refresh cookie and returns a fresh short access token."""
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="No active session.")
    new_refresh = create_refresh_token()
    new_expires = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    user_id = await rotate_refresh_token(hash_token(token), hash_token(new_refresh), new_expires)
    if user_id is None:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Session expired or revoked.")
    user = await get_user_by_id(user_id)
    if not user:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Account unavailable.")
    set_refresh_cookie(response, new_refresh)
    return {
        "access_token": create_access_token(user["username"]),
        "token_type": "bearer",
        "expires_in": _ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/logout")
@limiter.limit("30/minute")
async def logout(request: Request, response: Response):
    """Revokes the refresh token and clears the cookie."""
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await revoke_refresh_token(hash_token(token))
    clear_refresh_cookie(response)
    return {"message": "Logged out."}


@router.get("/me")
async def get_me(username: str = Depends(get_current_user)):
    user = await get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "created_at": user["created_at"],
    }


@router.get("/users")
async def admin_list_users(current_user: str = Depends(get_current_user)):
    """Admin-only: list all registered users (no password hashes)."""
    me = await get_user_by_username(current_user)
    if not me or me.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await list_users()

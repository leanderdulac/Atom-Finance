"""
Authentication API — JWT with bcrypt password hashing, backed by SQLite.
Users persist across restarts via the shared ATOM database.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.db.database import (
    create_user,
    get_user_by_username,
    user_exists,
    list_users,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class LoginRequest(BaseModel):
    username: str
    password: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    already_taken = await asyncio.to_thread(user_exists, req.username)
    if already_taken:
        raise HTTPException(status_code=400, detail="Username already exists.")

    pw_hash = await asyncio.to_thread(hash_password, req.password)
    uid = await asyncio.to_thread(create_user, req.username, req.email, pw_hash)

    if uid is None:
        raise HTTPException(
            status_code=400,
            detail="Username or e-mail already registered.",
        )

    logger.info("New user registered: %s (id=%d)", req.username, uid)
    return {"message": "User registered successfully.", "username": req.username.lower()}


@router.post("/login")
async def login(req: LoginRequest):
    user = await asyncio.to_thread(get_user_by_username, req.username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    pwd_ok = await asyncio.to_thread(verify_password, req.password, user["password_hash"])
    if not pwd_ok:
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    token = create_access_token(user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
    }


@router.get("/me")
async def get_me(username: str = Depends(get_current_user)):
    user = await asyncio.to_thread(get_user_by_username, username)
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
    me = await asyncio.to_thread(get_user_by_username, current_user)
    if not me or me.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await asyncio.to_thread(list_users)

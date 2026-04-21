"""Authentication API — JWT with bcrypt password hashing."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory user store.
# Production: replace with SQLAlchemy + PostgreSQL (models ready in app/db/).
_users_db: dict[str, dict] = {}


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register", status_code=201)
async def register(req: RegisterRequest):
    if req.username in _users_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    _users_db[req.username] = {
        "password": hash_password(req.password),
        "email": req.email,
        "role": "analyst",
        "created": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("New user registered: %s", req.username)
    return {"message": "User registered successfully", "username": req.username}


@router.post("/login")
async def login(req: LoginRequest):
    user = _users_db.get(req.username)
    if not user or not verify_password(req.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(req.username)
    return {"access_token": token, "token_type": "bearer", "username": req.username}


@router.get("/me")
async def get_me(username: str = Depends(get_current_user)):
    user = _users_db.get(username, {})
    return {
        "username": username,
        "email": user.get("email"),
        "role": user.get("role", "analyst"),
    }

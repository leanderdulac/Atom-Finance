"""Public client lock: hide and block the operator surface.

ATOM_CLIENT_MODE=true on the Mac that faces the internet. Analysts then only
reach /api/client, auth, health and the GBM scenario used by «Meu plano».
Users with role admin or operator keep the full desk.
"""
from __future__ import annotations

import os

OPERATOR_ROLES = frozenset({"admin", "operator"})

# Prefixes a client may hit when the lock is on. Everything else is 403.
CLIENT_ALLOWED_PREFIXES = (
    "/api/auth",
    "/api/health",
    "/api/live",
    "/api/client",
    "/api/capm/gbm-multi",
)


def client_mode_enabled() -> bool:
    return os.getenv("ATOM_CLIENT_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def is_operator_role(role: str | None) -> bool:
    return (role or "").strip().lower() in OPERATOR_ROLES


def client_may_access(path: str) -> bool:
    for prefix in CLIENT_ALLOWED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False

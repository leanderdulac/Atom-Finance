"""ATOM_CLIENT_MODE blocks desk APIs for analysts; operators keep them."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.client_mode import client_may_access, is_operator_role
from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password
from app.db import database


def test_allowlist_and_roles():
    assert client_may_access("/api/client/config")
    assert client_may_access("/api/client/ready-operation")
    assert client_may_access("/api/capm/gbm-multi")
    assert client_may_access("/api/auth/login")
    assert not client_may_access("/api/pricing/black-scholes")
    assert not client_may_access("/api/paper-trades/operations")
    assert is_operator_role("admin")
    assert is_operator_role("operator")
    assert not is_operator_role("analyst")


@pytest.mark.asyncio
async def test_analyst_is_blocked_operator_is_not(monkeypatch):
    await database.create_user("ana", "ana@example.test", hash_password("a-secure-test-password"), role="analyst")
    await database.create_user("mesa", "mesa@example.test", hash_password("a-secure-test-password"), role="admin")
    monkeypatch.setenv("ATOM_CLIENT_MODE", "true")

    from main import app
    limiter.reset()
    client = TestClient(app)

    public = client.get("/api/client/config")
    assert public.status_code == 200
    assert public.json()["client_mode"] is True

    ana = create_access_token("ana")
    mesa = create_access_token("mesa")
    blocked = client.get("/api/pricing/black-scholes", headers={"Authorization": f"Bearer {ana}"})
    # Some pricing routes are POST-only; 403 or 405 after the guard is fine as long as not 200 with data.
    assert blocked.status_code in {403, 405, 422}
    if blocked.status_code == 403:
        assert "cliente" in blocked.json()["detail"].lower()

    desk = client.get("/api/desk/doctrine", headers={"Authorization": f"Bearer {ana}"})
    assert desk.status_code == 403

    allowed = client.get("/api/client/me", headers={"Authorization": f"Bearer {ana}"})
    assert allowed.status_code == 200
    assert allowed.json()["is_operator"] is False

    op_desk = client.get("/api/desk/doctrine", headers={"Authorization": f"Bearer {mesa}"})
    assert op_desk.status_code == 200

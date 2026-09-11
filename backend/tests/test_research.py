"""Research gateway identity and upstream failure contract."""

import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.research import router
from app.core.security import create_access_token


class ResearchGatewayTests(unittest.TestCase):
    def setUp(self):
        active = patch("app.db.database.get_user_by_username", return_value={"username": "alice", "is_active": 1})
        active.start()
        self.addCleanup(active.stop)
        app = FastAPI()
        app.include_router(router, prefix="/api/research")
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer " + create_access_token("alice")}

    def test_auth_required(self):
        self.assertEqual(self.client.get("/api/research/papers").status_code, 401)

    def test_owner_comes_from_token(self):
        with patch(
            "app.api.research.call_worker", new=AsyncMock(return_value={"id": "paper"})
        ) as worker:
            response = self.client.post(
                "/api/research/papers",
                headers=self.headers,
                json={"kind": "text", "content": "paper"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(worker.call_args.kwargs["json"]["owner"], "alice")
        self.assertEqual(
            self.client.post(
                "/api/research/papers",
                headers=self.headers,
                json={"kind": "text", "content": "paper", "owner": "bob"},
            ).status_code,
            422,
        )

    def test_unconfigured_worker(self):
        with patch.dict(os.environ, {"QUANTMIND_SERVICE_TOKEN": ""}):
            self.assertEqual(
                self.client.get(
                    "/api/research/papers", headers=self.headers
                ).status_code,
                503,
            )

    def test_worker_unavailable(self):
        with (
            patch.dict(os.environ, {"QUANTMIND_SERVICE_TOKEN": "test"}),
            patch(
                "httpx.AsyncClient.request",
                new=AsyncMock(side_effect=httpx.ConnectError("offline")),
            ),
        ):
            self.assertEqual(
                self.client.get(
                    "/api/research/papers", headers=self.headers
                ).status_code,
                503,
            )

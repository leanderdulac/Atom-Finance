"""Offline extraction, persistence, validation and access-control tests."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from quantmind.knowledge import Paper, TreeNode
from quantmind.knowledge._base import SourceRef
from service import app


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(
            os.environ,
            {
                "QUANTMIND_DB_PATH": self.temp.name + "/papers.db",
                "QUANTMIND_SERVICE_TOKEN": "test-token",
                "OPENAI_API_KEY": "test-only",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(app, headers={"Authorization": "Bearer test-token"})
        node = TreeNode(title="Momentum study", summary="Evidence and limitations")
        self.paper = Paper(
            root_node_id=node.node_id,
            nodes={node.node_id: node},
            as_of=datetime.now(timezone.utc),
            source=SourceRef(kind="manual"),
        )

    def test_extract_persist_and_isolate_users(self):
        with patch(
            "service.paper_flow", new=AsyncMock(return_value=self.paper)
        ) as flow:
            response = self.client.post(
                "/papers",
                json={"owner": "alice", "kind": "text", "content": "Research article"},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(flow.call_args.kwargs["cfg"].tracing_disabled)
        self.assertIn("not reported", flow.call_args.kwargs["extra_instructions"])
        self.assertIn("Deflated Sharpe", flow.call_args.kwargs["extra_instructions"])
        self.assertIn("range(len(df))", flow.call_args.kwargs["extra_instructions"])
        self.assertEqual(
            len(self.client.get("/papers", params={"owner": "alice"}).json()), 1
        )
        self.assertEqual(self.client.get("/papers", params={"owner": "bob"}).json(), [])
        path = "/papers/" + response.json()["id"]
        self.assertEqual(
            self.client.get(path, params={"owner": "alice"}).json(), response.json()
        )
        self.assertEqual(
            self.client.get(path, params={"owner": "bob"}).status_code, 404
        )

    def test_credentials_and_missing_configuration(self):
        self.assertEqual(TestClient(app).get("/health").status_code, 401)
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            self.assertFalse(self.client.get("/health").json()["configured"])
            self.assertEqual(
                self.client.post(
                    "/papers", json={"owner": "a", "kind": "text", "content": "paper"}
                ).status_code,
                503,
            )

    def test_reject_arbitrary_urls_paths_and_empty_text(self):
        for kind, content in [
            ("arxiv", "http://127.0.0.1/private"),
            ("local", "/etc/passwd"),
            ("text", "   "),
        ]:
            self.assertEqual(
                self.client.post(
                    "/papers", json={"owner": "a", "kind": kind, "content": content}
                ).status_code,
                422,
            )

    def test_provider_failure_does_not_save(self):
        for exception, status in [
            (RuntimeError("provider secret"), 502),
            (TimeoutError(), 504),
        ]:
            with patch("service.paper_flow", new=AsyncMock(side_effect=exception)):
                response = self.client.post(
                    "/papers", json={"owner": "a", "kind": "text", "content": "paper"}
                )
            self.assertEqual(response.status_code, status)
            self.assertNotIn("provider secret", response.text)
        self.assertEqual(self.client.get("/papers", params={"owner": "a"}).json(), [])

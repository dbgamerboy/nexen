"""The read-only Everything page and API are reachable through their registrar."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from everything_runtime import register


class EmptyDB:
    def scalar(self, sql, params=()):
        return 0

    def rows(self, sql, params=()):
        return []


class EverythingRegistrationTests(unittest.TestCase):
    def test_read_only_page_and_snapshot_routes_register(self):
        app = FastAPI()
        app.state.workflow_workspace = SimpleNamespace(catalog=lambda compact=False: {
            "cards": [], "summary": {"states": {}, "families": {}},
            "coverage": {"errors": []},
        })
        app.state.benefits = SimpleNamespace(_catalog=lambda: [])
        app.state.readiness = SimpleNamespace(packet=lambda: {
            "checked_at": "fixture", "verified_count": 0, "blocker_count": 0,
            "execution_counts": {}, "coverage": "fixture", "items": [],
        })
        with patch("pc_control.validate_request") as validate:
            service = register(app, EmptyDB())
            self.assertEqual(service.snapshot()["coverage"]["active_app"], "H:/NEXEN/v1/app")
            with TestClient(app) as client:
                page = client.get("/everything")
                api = client.get("/api/everything?offset=0&limit=2")
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(page.status_code, 200)
        self.assertIn("NEXEN Everything", page.text)
        marvin = Path(__file__).with_name("marvin.html").read_text(encoding="utf-8")
        self.assertIn('href="/everything"', marvin)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["schema"], "nexen.everything.v1")
        self.assertFalse(api.json()["benefits"]["applications_submitted_by_nexen"])


if __name__ == "__main__":
    unittest.main()

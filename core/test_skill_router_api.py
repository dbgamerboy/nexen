"""Read-only API/CLI coverage for the shared skill router."""
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

import nexen_cli
from skill_router import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_SOURCE_LEDGER_PATH,
    SkillRouter,
    load_router,
)
from skill_router_api import register, search_response, source_response
from test_support import fixture_root


def _skill(name, description, *, tool_name=""):
    stable_id = "sha256:" + hashlib.sha256((name + description).encode("utf-8")).hexdigest()
    return {
        "stable_id": stable_id,
        "title": name,
        "title_aliases": [name],
        "description_purpose": description,
        "source_provenance": {
            "repos": ["fixture__repo"],
            "repository_urls": ["https://example.invalid/fixture/repo"],
            "repository_commits": ["0123456789abcdef"],
            "paths": [r"H:\private\skills\SKILL.md"],
            "status": "fixture receipt",
        },
        "license_provenance_status": {
            "skill_license": None,
            "repo_license_labels": ["unknown"],
            "status": "repo-level or unknown",
        },
        "availability_status": "local reference only",
        "dependencies_tools_model_interface": {
            "dependencies": "unknown",
            "tools": [tool_name] if tool_name else [],
            "model": "unknown",
            "interface": "unknown",
        },
        "applicable_workstream_tasks": [],
        "risk_approval_constraints": {
            "status": "unreviewed",
            "constraints": "Review before use.",
            "paid_service_status": "unknown",
        },
        "identity": {"content_sha256": stable_id.removeprefix("sha256:")},
        "source_copies": [],
    }


class SkillRouterApiCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skill-router-api-", dir=fixture_root())
        self.root = Path(self.temp.name)
        catalog = {
            "records": [
                _skill(
                    "Video Content Draft",
                    "Create original short video content and a source-backed workflow. API_KEY=sk-proj-supersecret987654 🚀",
                    tool_name="render video",
                ),
                _skill("cli-anything-n8n", "Mutate n8n workflows and credentials for video content."),
            ]
        }
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps(catalog), encoding="utf-8")
        self.ledger = self.root / "source-ledger.csv"
        fields = [
            "source_id", "shortcode", "method", "classification", "evidence_status",
            "evidence_artifact_exists", "visual_review_required", "valid_export_count",
            "source_faithful_export_present", "nexen_adaptation_export_present",
            "primary_state", "installed_names", "staged_only_names", "exported_only_names",
            "exact_next_piece", "account_or_rights_gates",
        ]
        row = {
            "source_id": "1",
            "shortcode": "fixture01",
            "method": "Create original short video content with a source-backed workflow",
            "classification": "actionable_method",
            "evidence_status": "fixture evidence",
            "evidence_artifact_exists": "true",
            "visual_review_required": "false",
            "valid_export_count": "1",
            "source_faithful_export_present": "false",
            "nexen_adaptation_export_present": "false",
            "primary_state": "fixture",
            "installed_names": "",
            "staged_only_names": "",
            "exported_only_names": "",
            "exact_next_piece": "Review the original source before any adaptation.",
            "account_or_rights_gates": "Owner must confirm source rights.",
        }
        with self.ledger.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerow(row)
        self.router = SkillRouter(self.catalog, self.ledger, review_manifest_root=None)
        self.app = FastAPI()
        register(self.app, router=self.router)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.temp.cleanup)

    def test_api_status_search_and_source_routes_are_read_only(self):
        status = self.client.get("/api/workflow-skills/status")
        search = self.client.get("/api/workflow-skills/search", params={"q": "video content"})
        source = self.client.get("/api/workflow-skills/source/1")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(search.status_code, 200)
        self.assertEqual(source.status_code, 200)
        self.assertEqual(status.json()["catalog"]["skill_count"], 2)
        self.assertEqual(search.json()["result_count"], 1)
        self.assertEqual(search.json()["results"][0]["name"], "Video Content Draft")
        self.assertNotIn("score", search.json()["results"][0])
        self.assertEqual(source.json()["source"]["source_id"], "1")
        self.assertTrue(source.json()["suggestion_only"])
        self.assertFalse(source.json()["execution_allowed"])
        self.assertFalse(source.json()["candidates"][0]["execution_allowed"])

    def test_public_search_redacts_secrets_and_local_paths(self):
        response = self.client.get("/api/workflow-skills/search", params={"q": "video"})
        body = response.text
        self.assertNotIn("sk-proj-supersecret987654", body)
        self.assertNotIn(r"H:\private\skills", body)
        self.assertIn("[REDACTED]", body)
        self.assertNotIn("cli-anything-n8n", body)

    def test_api_rejects_bad_limits_and_unknown_source_ids(self):
        self.assertEqual(self.client.get("/api/workflow-skills/search", params={"q": "x" * 201}).status_code, 422)
        self.assertEqual(self.client.get("/api/workflow-skills/search", params={"q": "video", "limit": 21}).status_code, 422)
        self.assertEqual(self.client.get("/api/workflow-skills/source/0").status_code, 422)
        self.assertEqual(self.client.get("/api/workflow-skills/source/2").status_code, 404)
        with self.assertRaises(ValueError):
            search_response(self.router, "video", limit=0)
        with self.assertRaises(ValueError):
            source_response(self.router, 1, limit=11)

    def test_cli_commands_use_the_same_safe_responses(self):
        for argv in (
            ["skills", "status"],
            ["skills", "search", "video content"],
            ["skills", "source", "1"],
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(argv=argv):
                result = nexen_cli.main(argv, router_factory=lambda: self.router, stdout=stdout, stderr=stderr)
                self.assertEqual(result, 0)
                self.assertEqual(stderr.getvalue(), "")
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload.get("execution_allowed", False))

    def test_cli_rejects_unknown_source_and_never_runs_commands(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        result = nexen_cli.main(
            ["skills", "source", "999"],
            router_factory=lambda: self.router,
            stdout=stdout,
            stderr=stderr,
        )
        self.assertEqual(result, 2)
        self.assertIn("not found", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        with self.assertRaises(SystemExit):
            nexen_cli.main(["skills", "execute", "video"], router_factory=lambda: self.router)

    def test_cli_json_is_safe_for_legacy_windows_code_pages(self):
        raw = io.BytesIO()
        stdout = io.TextIOWrapper(raw, encoding="cp1252")
        result = nexen_cli.main(
            ["skills", "search", "video"],
            router_factory=lambda: self.router,
            stdout=stdout,
            stderr=io.StringIO(),
        )
        stdout.flush()
        self.assertEqual(result, 0)
        payload = json.loads(raw.getvalue().decode("cp1252"))
        self.assertIn("🚀", payload["results"][0]["description"])


class LiveSkillRouterApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DEFAULT_CATALOG_PATH.is_file() or not DEFAULT_SOURCE_LEDGER_PATH.is_file():
            raise unittest.SkipTest("The H: skill catalog and 82-source ledger are unavailable")

    def test_real_catalog_and_source_ledger_through_api(self):
        router = load_router()
        app = FastAPI()
        register(app, router=router)
        with TestClient(app) as client:
            status = client.get("/api/workflow-skills/status")
            search = client.get("/api/workflow-skills/search", params={"q": "content-engine", "limit": 3})
            source = client.get("/api/workflow-skills/source/1", params={"limit": 3})
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["catalog"]["sha256"], router.receipt()["catalog_sha256"])
        self.assertEqual(status.json()["source_ledger"]["method_count"], 82)
        self.assertEqual(search.status_code, 200)
        self.assertIn("content-engine", [item["name"] for item in search.json()["results"]])
        self.assertEqual(source.status_code, 200)
        self.assertEqual(source.json()["source"]["source_id"], "1")
        self.assertTrue(source.json()["suggestion_only"])
        self.assertFalse(source.json()["execution_allowed"])
        self.assertNotIn(str(router.catalog_path), search.text + source.text)


if __name__ == "__main__":
    unittest.main()

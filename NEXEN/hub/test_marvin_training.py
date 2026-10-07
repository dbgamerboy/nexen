"""Focused safety and behavior checks for MARVIN's practice console."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import marvin_training as training
from fastapi import HTTPException
from pydantic import ValidationError


class TrainingDatabase:
    def __init__(self, path):
        import sqlite3
        self.path = Path(path)
        self.sqlite3 = sqlite3
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
            CREATE TABLE hub_requests(id INTEGER PRIMARY KEY,text TEXT,status TEXT,created_at TEXT);
            CREATE TABLE task_details(request_id INTEGER PRIMARY KEY,seed_key TEXT UNIQUE,priority TEXT,
              due_date TEXT,next_step TEXT,reminder_date TEXT,updated_at TEXT,completed_at TEXT,pinned INTEGER);
            CREATE TABLE task_history(id INTEGER PRIMARY KEY,request_id INTEGER,old_status TEXT,new_status TEXT,
              outcome TEXT,reminder_date TEXT,created_at TEXT);
            """)

    from contextlib import contextmanager

    @contextmanager
    def connect(self):
        connection = self.sqlite3.connect(self.path)
        connection.row_factory = self.sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def rows(self, query, params=()):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]


class MarvinTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="H:/NEXEN/temp", prefix="marvin-training-")
        self.addCleanup(self.temp.cleanup)
        self.db = TrainingDatabase(Path(self.temp.name) / "training.sqlite3")
        training._ensure_schema(self.db)

    def test_full_round_covers_every_pool_business_and_engine_track(self):
        def fake_retrieval(track_id, query, task_type, pool):
            return {"track_id": track_id, "status": "pass", "citation_count": 1,
                    "citation_kinds": ["knowledge"], "source_ids": ["safe-id"], "warnings": []}
        with patch.object(training, "_retrieval_drill", side_effect=fake_retrieval), \
             patch.object(training, "_memory_base_coverage_drill", return_value={"track_id": "memory_base_coverage", "status": "pass"}), \
             patch.object(training, "_orchestration_drill", return_value={"track_id": "orchestration", "status": "pass"}), \
             patch.object(training, "_vector_drill", return_value={"track_id": "vector_rag", "status": "pass"}):
            run = training._run_practice(self.db, "full")
        self.assertEqual(run["drill_count"], 18)
        self.assertEqual(run["pass_count"], 18)
        self.assertEqual({item["track_id"] for item in run["drills"]},
                         set(training.MEMORY_DRILLS) | {item["id"] for item in training.BUSINESS_TRACKS} |
                         {"memory_base_coverage", "orchestration", "vector_rag"})

    def test_retrieval_records_citation_metadata_not_private_excerpt(self):
        packet = {"citations": [{"kind": "knowledge", "source_id": "chunk-1", "text": "private body"}],
                  "warnings": ["budget limit"]}
        with patch("memory_runtime.context_for", return_value=packet) as context_for:
            result = training._retrieval_drill("commerce", "query", "workflow", "commerce")
        context_for.assert_called_once_with("query", task_type="workflow", pool="commerce",
                                            max_chars=16000, limit=8)
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("text", json.dumps(result))
        self.assertEqual(result["source_ids"], ["chunk-1"])

    def test_pool_failure_does_not_crash_full_round(self):
        with patch("memory_runtime.context_for", side_effect=RuntimeError("private details")):
            result = training._retrieval_drill("voice", "query", "automation", "voice")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["warnings"], ["Retrieval failed: RuntimeError"])

    def test_orchestration_drill_checks_catalog_gates_without_executing(self):
        catalog = {"cards": [
            {"launch_ready": False, "actions": [{"id": "run", "enabled": False, "reason": "blocked by setup"}]},
            {"launch_ready": True, "actions": [{"id": "run", "enabled": True, "reason": ""}]},
        ], "coverage": {"errors": []}, "executed": False}
        with patch.object(training, "_retrieval_drill", return_value={
                "track_id": "orchestration", "status": "pass", "citation_count": 1,
                "citation_kinds": ["knowledge"], "source_ids": ["safe-id"], "warnings": []}), \
             patch("workflow_workspace.WorkflowWorkspace") as workspace:
            workspace.return_value.catalog.return_value = catalog
            result = training._orchestration_drill(self.db)
        workspace.return_value.catalog.assert_called_once_with(compact=True)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["catalog_card_count"], 2)
        self.assertEqual(result["run_blocked"], 1)
        self.assertEqual(result["run_enabled"], 1)
        self.assertFalse(result["execution_performed"])

    def test_orchestration_gate_mismatch_fails_the_drill(self):
        catalog = {"cards": [{"launch_ready": False,
                               "actions": [{"id": "run", "enabled": True, "reason": ""}]}],
                   "coverage": {"errors": []}, "executed": False}
        with patch.object(training, "_retrieval_drill", return_value={
                "track_id": "orchestration", "status": "pass", "citation_count": 1,
                "citation_kinds": ["knowledge"], "source_ids": ["safe-id"], "warnings": []}), \
             patch("workflow_workspace.WorkflowWorkspace") as workspace:
            workspace.return_value.catalog.return_value = catalog
            result = training._orchestration_drill(self.db)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["gate_mismatches"], 1)
        self.assertFalse(result["execution_performed"])

    def test_memory_base_drill_reports_disconnected_and_practice_only_stores(self):
        bases = [
            {"id": "files", "available": True, "connected_to_shared_retrieval": True},
            {"id": "chunks", "available": True, "connected_to_shared_retrieval": True},
            {"id": "completion_memory", "available": True, "connected_to_shared_retrieval": True},
            {"id": "knowledge_items", "available": True, "connected_to_shared_retrieval": False},
        ]
        vector = {"installed": True, "records": 15, "adapter_available": True,
                  "connected_to_marvin_chat": False}
        with patch.object(training, "_memory_bases", return_value=bases), \
             patch.object(training, "_vector_inventory", return_value=vector):
            result = training._memory_base_coverage_drill(self.db)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["disconnected_bases"], ["knowledge_items"])
        self.assertEqual(result["vector_db"]["records"], 15)
        self.assertTrue(any("practice-only" in warning for warning in result["warnings"]))

    def test_vector_timeout_fails_closed(self):
        with tempfile.TemporaryDirectory(dir="H:/NEXEN/temp", prefix="marvin-vector-") as root:
            python = Path(root) / "python.exe"
            adapter = Path(root) / "adapter.py"
            python.touch()
            adapter.touch()
            with patch.object(training, "MEMSEARCH_PYTHON", python), \
                 patch.object(training, "MEMSEARCH_ADAPTER", adapter), \
                 patch("marvin_training.subprocess.run", side_effect=subprocess.TimeoutExpired("fixed", 90)):
                result = training._vector_drill()
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["local_only"])

    def test_vector_crash_and_bad_output_do_not_leak_adapter_text(self):
        with tempfile.TemporaryDirectory(dir="H:/NEXEN/temp", prefix="marvin-vector-") as root:
            python = Path(root) / "python.exe"
            adapter = Path(root) / "adapter.py"
            python.touch()
            adapter.touch()
            with patch.object(training, "MEMSEARCH_PYTHON", python), patch.object(training, "MEMSEARCH_ADAPTER", adapter):
                with patch("marvin_training.subprocess.run", return_value=subprocess.CompletedProcess([], 2, "", "secret error")):
                    crashed = training._vector_drill()
                with patch("marvin_training.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "not json", "")):
                    malformed = training._vector_drill()
        self.assertEqual(crashed["status"], "error")
        self.assertNotIn("secret", json.dumps(crashed))
        self.assertEqual(malformed["status"], "error")

    def test_vector_result_is_source_allowlisted_and_metadata_only(self):
        payload = {"local_only": True, "results": [
            {"source": "H:/private/other.md", "content": "must not escape"},
            {"source": "F:/NEXEN_MEMORY/Plans/NEXEN-stem-export-plan-2026-09-09.md", "content": "secret"},
        ]}
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with tempfile.TemporaryDirectory(dir="H:/NEXEN/temp", prefix="marvin-vector-") as root:
            python = Path(root) / "python.exe"
            adapter = Path(root) / "adapter.py"
            python.touch()
            adapter.touch()
            with patch.object(training, "MEMSEARCH_PYTHON", python), \
                 patch.object(training, "MEMSEARCH_ADAPTER", adapter), \
                 patch("marvin_training.subprocess.run", return_value=completed):
                result = training._vector_drill()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["sources"], [training.VECTOR_EXPECTED_SOURCE])
        self.assertNotIn("secret", json.dumps(result))

    def test_research_action_is_idempotent_and_persistent(self):
        selected = training._research_selection("all_businesses", None)
        self.assertEqual(len(selected), 8)
        track = selected[0]
        title = f"MARVIN research and practice: {track['name']}"
        first = training._create_linked_task(self.db, "research", track["id"], title, "Save cited research.")
        second = training._create_linked_task(self.db, "research", track["id"], title, "Save cited research.")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(training._recent_tasks(self.db)), 1)

    def test_unknown_business_and_bad_scope_are_rejected(self):
        with self.assertRaises(HTTPException):
            training._research_selection("one_business", "unknown")
        with self.assertRaises(ValidationError):
            training.PracticeRequest(scope="execute_imported_workflow")
        with self.assertRaises(ValidationError):
            training.ResearchRequest(scope="one_business", business_id="unknown", extra="shell")

    def test_marvin_labels_and_practice_routes_are_registered(self):
        from fastapi import FastAPI
        import marvin_brain
        from memory_pools import POOLS
        from marvin_training import register
        self.assertIn("You are MARVIN,", marvin_brain.PERSONA)
        self.assertNotIn("formerly MARVIN", marvin_brain.PERSONA)
        self.assertEqual(POOLS["voice"]["label"], "MARVIN and voice")
        app = FastAPI()
        with patch("pc_control.validate_request", return_value=None):
            register(app, self.db)
        paths = {route.path for route in app.routes}
        self.assertTrue({"/marvin/training", "/api/marvin/training/state",
                         "/api/marvin/training/practice", "/api/marvin/training/research",
                         "/api/marvin/training/code-practice"}.issubset(paths))
        page = Path("marvin-training.html").read_text(encoding="utf-8")
        home = Path("marvin.html").read_text(encoding="utf-8")
        self.assertIn("Queue research for all businesses", page)
        self.assertIn("Run full practice", page)
        self.assertIn("Ingestion coverage", page)
        self.assertIn("gate mismatches", page)
        self.assertIn("disconnected_bases", page)
        self.assertIn("/marvin/training", home)

    def test_active_marvin_identity_uses_canonical_labels_and_keeps_safe_legacy_hooks(self):
        import agentic_os
        self.assertIn("Use MARVIN as the assistant's product identity", agentic_os.templates()['SOUL.md'])
        self.assertIn("You are MARVIN", Path("life_runtime.py").read_text(encoding="utf-8"))
        self.assertIn("class Marvin:", Path("nexen.py").read_text(encoding="utf-8"))
        self.assertIn("Marvin = Marvin", Path("nexen.py").read_text(encoding="utf-8"))
        self.assertIn("/api/marvin", Path("nexen.py").read_text(encoding="utf-8"))
        self.assertIn("nexen:marvin-state", Path("problems.html").read_text(encoding="utf-8"))
        self.assertIn("ask_marvin", Path("world-assets/voice-control.js").read_text(encoding="utf-8"))
        self.assertNotIn("MARVIN as the assistant's product identity", agentic_os.templates()['SOUL.md'])
        self.assertNotIn("NEXEN MARVIN", Path("problem_cases.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import memory_runtime
from recursive_learning import (
    evaluate_candidate,
    load_feedback,
    record_feedback,
    run_recursive_learning,
)

FIXTURE_ROOT = Path(r"H:\NEXEN\temp\tests\recursive-learning")


class RecursiveLearningTests(unittest.TestCase):
    def setUp(self):
        self.scope = ["a distinct concept owned by novel learning"]

    def candidate(self, text="A sourced candidate about dependable local indexing.", **extra):
        item = {"candidate_id": "candidate-1", "text": text,
                "source_ids": ["source-1"]}
        item.update(extra)
        return item

    def test_declared_novel_owner_and_scope_overlap_are_excluded(self):
        owned = evaluate_candidate(self.candidate(owner="Novel Learning"),
                                   novel_learning_scope=self.scope,
                                   scope_configured=True)
        self.assertEqual(owned["status"], "excluded_novel_overlap")
        self.assertFalse(owned["can_add"])

        overlap = evaluate_candidate(
            self.candidate("This candidate supports a distinct concept owned by novel learning."),
            novel_learning_scope=self.scope, scope_configured=True)
        self.assertEqual(overlap["status"], "excluded_novel_overlap")
        self.assertFalse(overlap["can_add"])

    def test_missing_scope_or_provenance_fails_closed(self):
        no_scope = evaluate_candidate(self.candidate(), scope_configured=False)
        self.assertEqual(no_scope["status"], "needs_review_scope")
        self.assertIsNone(no_scope["can_add"])

        no_source = evaluate_candidate(self.candidate(source_ids=[]),
                                       novel_learning_scope=["unrelated boundary"],
                                       scope_configured=True)
        self.assertEqual(no_source["status"], "needs_review_provenance")
        self.assertIsNone(no_source["can_add"])

    def test_existing_exact_duplicate_is_excluded_and_near_match_is_held(self):
        original = "alpha beta gamma delta"
        exact = evaluate_candidate(self.candidate(original),
                                   existing_items=[{"source_id": "mem-1", "text": original}],
                                   novel_learning_scope=["unrelated boundary"],
                                   scope_configured=True)
        self.assertEqual(exact["status"], "excluded_duplicate")
        self.assertEqual(exact["related_source_ids"], ["mem-1"])

        similar = evaluate_candidate(
            self.candidate("alpha beta gamma delta epsilon"),
            existing_items=[{"source_id": "mem-2", "text": original}],
            novel_learning_scope=["unrelated boundary"], scope_configured=True)
        self.assertEqual(similar["status"], "needs_review_similarity")
        self.assertIsNone(similar["can_add"])

    def test_novel_reference_overlap_is_excluded_conservatively(self):
        reference = {"source_id": "novel-1",
                     "text": "astronomy notes combine short exposure stacking and raw color calibration"}
        high = evaluate_candidate(
            self.candidate("astronomy notes combine short exposure stacking and raw color calibration guide"),
            novel_learning_items=[reference], scope_configured=True)
        self.assertEqual(high["status"], "excluded_novel_overlap")
        self.assertEqual(high["related_source_ids"], ["novel-1"])

        possible = evaluate_candidate(
            self.candidate("astronomy notes compare raw color settings for wide field photos"),
            novel_learning_items=[reference], scope_configured=True)
        self.assertEqual(possible["status"], "excluded_novel_overlap")
        self.assertFalse(possible["can_add"])

    def test_recursion_expands_only_eligible_candidates_and_stops_at_overlap(self):
        calls = []
        root = self.candidate("A local index keeps verified task receipts searchable.")
        root["candidate_id"] = "root"
        child = self.candidate("This analyzes a distinct concept owned by novel learning.")
        child.update(candidate_id="child", parent_id="root")
        grandchild = self.candidate("A child beneath the overlapping concept.")
        grandchild.update(candidate_id="grandchild", parent_id="child")
        tree = {"root": [child], "child": [grandchild], "grandchild": []}

        def expand(item):
            calls.append(item["candidate_id"])
            return tree[item["candidate_id"]]

        result = run_recursive_learning(
            [root], expand=expand, novel_learning_scope=self.scope,
            scope_configured=True, max_depth=3)
        self.assertEqual([item["status"] for item in result["candidates"]],
                         ["proposal_ready", "excluded_novel_overlap"])
        self.assertEqual(calls, ["root"])
        self.assertFalse(result["summary"]["automatic_ingestion"])

    def test_recursion_depth_and_candidate_limits_are_enforced(self):
        def expand(item):
            depth = int(item["candidate_id"].split("-")[1])
            if depth >= 8:
                return []
            return [self.candidate(f"Evidence node {depth + 1} about blue widgets.",
                                   candidate_id=f"node-{depth + 1}",
                                   parent_id=item["candidate_id"])]

        root = self.candidate("Evidence node 0 about blue widgets.", candidate_id="node-0")
        result = run_recursive_learning([root], expand=expand,
                                        novel_learning_scope=["unrelated term"],
                                        scope_configured=True, max_depth=3,
                                        max_candidates=3)
        self.assertEqual(len(result["candidates"]), 3)
        self.assertTrue(result["summary"]["truncated"])
        self.assertLessEqual(max(item["depth"] for item in result["candidates"]), 3)

    def test_recursive_ancestor_cycle_is_held(self):
        root = self.candidate("Evidence about bird migration tracking.", candidate_id="root")
        cycle = self.candidate("Different sourced follow-up on migration data.", candidate_id="root")
        result = run_recursive_learning([root], expand=lambda _: [cycle],
                                        novel_learning_scope=["unrelated term"],
                                        scope_configured=True)
        self.assertEqual(result["candidates"][1]["status"], "needs_review_cycle")
        self.assertIsNone(result["candidates"][1]["can_add"])

    def test_feedback_persists_latest_decision_without_candidate_text(self):
        FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=FIXTURE_ROOT) as directory:
            database = Path(directory) / "feedback.sqlite3"
            sqlite3.connect(database).close()
            text = "A special candidate string that must not be stored verbatim."
            approve = record_feedback(database, text, "approve",
                                      reason_code="owner_approved")
            self.assertFalse(approve["candidate_text_stored"])
            record_feedback(database, text, "exclude", reason_code="conflict")
            feedback = load_feedback(database)
            latest = feedback[approve["fingerprint"]]
            self.assertEqual(latest["decision"], "exclude")
            with closing(sqlite3.connect(database)) as connection:
                stored = " ".join(str(row) for row in connection.execute(
                    "SELECT * FROM recursive_learning_feedback"))
            self.assertNotIn(text, stored)

            assessed = evaluate_candidate(
                self.candidate(text), novel_learning_scope=["unrelated scope"],
                scope_configured=True, feedback=feedback)
            self.assertEqual(assessed["status"], "excluded_by_owner_feedback")


class RecursiveLearningRouteTests(unittest.TestCase):
    class MemoryStub:
        def build_context(self, query, **kwargs):
            return {"citations": [{"source_id": "memory-1",
                                   "text": "Older notes cover local indexing for archived tasks."}],
                    "warnings": []}

    def setUp(self):
        FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=FIXTURE_ROOT)
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        sqlite3.connect(self.base / "data" / "nexen.db").close()
        self.app = FastAPI()
        self.base_patch = patch.object(memory_runtime, "BASE", self.base)
        self.memory_patch = patch.object(memory_runtime, "shared_memory", return_value=self.MemoryStub())
        self.base_patch.start()
        self.memory_patch.start()
        memory_runtime.register(self.app)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.memory_patch.stop()
        self.base_patch.stop()
        self.temp.cleanup()

    def request_body(self, **overrides):
        body = {
            "candidates": [{"candidate_id": "root", "text": "Fresh blue lantern protocol details.",
                            "source_ids": ["owner-note-143"]}],
            "novel_learning_scope": ["Adaptive visual pattern discovery"],
            "max_depth": 2,
        }
        body.update(overrides)
        return body

    def test_preview_uses_shared_citations_and_fails_closed_without_scope(self):
        ok = self.client.post("/api/memory/recursive-learning/preview", json=self.request_body())
        self.assertEqual(ok.status_code, 200)
        payload = ok.json()
        self.assertEqual(payload["candidates"][0]["status"], "proposal_ready")
        self.assertEqual(payload["retrieved_source_ids"], ["memory-1"])
        self.assertFalse(payload["summary"]["automatic_ingestion"])

        held = self.client.post("/api/memory/recursive-learning/preview", json=self.request_body(novel_learning_scope=[]))
        self.assertEqual(held.status_code, 200)
        self.assertEqual(held.json()["scope_status"], "unavailable_fails_closed")
        self.assertEqual(held.json()["candidates"][0]["status"], "needs_review_scope")

    def test_feedback_route_is_idempotently_read_by_later_preview(self):
        text = "Fresh blue lantern protocol details."
        saved = self.client.post("/api/memory/recursive-learning/feedback", json={
            "candidate_text": text, "decision": "approve", "reason_code": "owner_approved",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(saved.json()["candidate_text_stored"])
        preview = self.client.post("/api/memory/recursive-learning/preview", json=self.request_body())
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["candidates"][0]["status"], "approved_for_staging")

    def test_preview_rejects_orphan_parent_and_duplicate_ids(self):
        orphan = self.client.post("/api/memory/recursive-learning/preview", json=self.request_body(
            candidates=[{"candidate_id": "child", "parent_id": "missing", "text": "candidate",
                         "source_ids": ["s1"]}]))
        self.assertEqual(orphan.status_code, 422)
        duplicate = self.client.post("/api/memory/recursive-learning/preview", json=self.request_body(
            candidates=[{"candidate_id": "root", "text": "one", "source_ids": ["s1"]},
                        {"candidate_id": "root", "text": "two", "source_ids": ["s2"]}]))
        self.assertEqual(duplicate.status_code, 422)


if __name__ == "__main__":
    unittest.main()

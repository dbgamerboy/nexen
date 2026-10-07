import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nexen import paths
from nexen.marvin.agent import Agent
from nexen.marvin.orchestrator import Orchestrator
from nexen.marvin.traces import OUTCOME_SCHEMA, TraceStore, episode_outcome, validate_local_artifact, verified_success


class FakeLedger:
    def __init__(self):
        self.skills = []
    def upsert_skill(self, *args):
        self.skills.append(args)


class FakePacks:
    def __init__(self, script):
        self.script, self.calls = iter(script), 0
    def ask(self, *args, **kwargs):
        self.calls += 1
        item = next(self.script)
        if isinstance(item, Exception):
            raise item
        return item


def response(text, **extra):
    return {"ok": True, "candidate": "local:scripted-fixture", "text": text, **extra}


def brain(script=()):
    facts, ledger = [], FakeLedger()
    app = SimpleNamespace(novel=SimpleNamespace(ingest=lambda item: facts.append(item) or {"op": "ADD"}), ledger=ledger)
    spine = SimpleNamespace(resolve=lambda goal: {"kind": "known", "solution": {"problem": "FIXTURE", "title": "Useful retained plan", "steps": ["Inspect the actual evidence"], "verify": ["Check the artifact hash"]}, "premortem": {"go": "proceed"}})
    return SimpleNamespace(app=app, spine=spine, packs=FakePacks(script), traces=TraceStore(":memory:"), facts=facts)


class Outcomes(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / "scratch"
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.tmp.name)
        self.patch_data = patch.object(paths, "DATA", self.root)
        self.patch_data.start()
        self.patch_audit = patch.object(paths, "AUDIT_LOG", self.root / "audit.jsonl")
        self.patch_audit.start()
        self.brains = []
    def tearDown(self):
        for b in self.brains:
            b.traces.db.close()
        self.patch_data.stop()
        self.patch_audit.stop()
        self.tmp.cleanup()
    def b(self, script=()):
        b = brain(script)
        self.brains.append(b)
        return b
    def packet_script(self, goal):
        return [response(json.dumps({"tool": "ticket", "args": {"objective": goal, "files": ["engine/nexen/marvin/agent.py"], "checks": ["Verify outcome evidence"]}})), response('{"final":"Prepared the bounded work packet; no worker dispatched."}')]
    def checker(self, goal, observations, answer):
        p = Path(observations[-1]["result"]["packet"])
        data = p.read_bytes()
        packet = json.loads(data)
        return {"path": str(p), "sha256": hashlib.sha256(data).hexdigest(), "job_id": packet["job_id"], "job_kind": "prepare_packet", "checks": [{"name": "packet objective matches admitted goal", "passed": packet["objective"] == goal}, {"name": "bounded packet schema", "passed": packet["packet_version"] == 1 and packet["resource_budget"]["max_external_spend"] == 0}]}
    def verify_not_learned(self, b, out):
        self.assertFalse(out["ok"])
        self.assertFalse(b.traces.rows()[0]["ok"])
        self.assertEqual(b.facts, [])
        self.assertEqual(b.traces.mine()["sft"], [])
        self.assertEqual(Orchestrator(b.app, b).discover_skills(min_successes=1), [])

    def test_useful_deterministic_plan_is_not_job_success(self):
        b = self.b()
        out = Agent(b).run("Plan the next internal coding packet", use_model=False)
        self.assertIn("Useful retained plan", out["answer"])
        self.assertEqual(out["outcome"]["status"], "planning_only")
        self.assertEqual(b.packs.calls, 0)
        self.verify_not_learned(b, out)
        self.assertEqual(b.traces.analyze()["unverified_traces"], 1)

    def test_model_timeout_preserves_plan_but_cannot_be_success(self):
        b = self.b([TimeoutError("synthetic model timeout")])
        out = Agent(b).run("Prepare the next coding packet")
        self.assertTrue(out["deterministic"])
        self.assertEqual(out["outcome"]["status"], "model_failed")
        self.assertIsNone(out["outcome"]["provider_success"])
        self.verify_not_learned(b, out)
        self.assertEqual(b.traces.mine()["routing"][0]["success"], 0)
        self.assertEqual(b.traces.mine()["failure"], [])  # useful fallback is not a bad model answer

    def test_explicit_provider_failure_cannot_be_hidden_by_fallback(self):
        b = self.b([{"ok": False, "errors": [{"candidate": "local:fixture-failed", "error": "timeout"}]}])
        out = Agent(b).run("Prepare the revenue research packet")
        self.assertEqual(out["model"], "local:fixture-failed")
        self.verify_not_learned(b, out)
        self.assertEqual(b.traces.analyze(min_n=1)["models"]["local:fixture-failed"]["success"], 0)

    def test_tool_exception_is_recorded_without_losing_trace(self):
        b = self.b([response('{"tool":"search","args":{"topic":"receipt"}}')])
        agent = Agent(b)
        agent.tool = lambda *args: (_ for _ in ()).throw(RuntimeError("synthetic tool crash"))
        out = agent.run("Find a grounded revenue source")
        self.assertEqual(out["outcome"]["status"], "tool_failed")
        self.assertEqual(len(b.traces.rows()), 1)
        self.verify_not_learned(b, out)

    def test_tool_error_and_refusal_are_not_successful_actions(self):
        for result in ({"ok": False, "error": "failed"}, {"refused": "held by the source gate"}):
            with self.subTest(result=result):
                b = self.b([response('{"tool":"search","args":{}}')])
                agent = Agent(b)
                agent.tool = lambda *args: result
                out = agent.run("Inspect an internal source")
                self.assertEqual(out["outcome"]["tool_succeeded"], 0)
                self.verify_not_learned(b, out)

    def test_malformed_tool_arguments_do_not_crash_or_promote(self):
        b = self.b([response('{"tool":"search","args":["not an object"]}')])
        out = Agent(b).run("Search this project")
        self.assertEqual(out["outcome"]["status"], "tool_failed")
        self.verify_not_learned(b, out)

    def test_unknown_tool_is_failed_and_not_dispatched(self):
        b = self.b([response('{"tool":"publish_everything","args":{}}')])
        out = Agent(b).run("Review draft copy")
        self.assertEqual(out["outcome"]["status"], "tool_failed")
        self.verify_not_learned(b, out)

    def test_partial_packet_then_model_failure_retains_artifact_without_success(self):
        goal = "Prepare an internal coding packet"
        script = self.packet_script(goal)
        script[1] = TimeoutError("synthetic final-answer timeout")
        b = self.b(script)
        out = Agent(b).run(goal, verify_job=lambda *a: self.fail("partial run must not invoke acceptance"), proof_root=self.root)
        self.assertEqual(out["outcome"]["status"], "partial_actions")
        self.assertEqual(len(list((self.root / "tickets").glob("*.json"))), 1)
        self.verify_not_learned(b, out)

    def test_real_bounded_packet_requires_actual_hash_and_goal_checks(self):
        goal = "Prepare the NEXEN trace-outcome repair packet"
        b = self.b(self.packet_script(goal))
        out = Agent(b, "coder").run(goal, verify_job=self.checker, proof_root=self.root)
        self.assertTrue(out["ok"])
        self.assertTrue(verified_success(b.traces.rows()[0]))
        proof = out["outcome"]["proof"]
        artifact = Path(proof["path"])
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), proof["sha256"])
        self.assertEqual(json.loads(artifact.read_text())["objective"], goal)
        self.assertEqual(proof["job_kind"], "prepare_packet")
        self.assertEqual(out["outcome"]["tool_succeeded"], 1)
        self.assertIsNone(out["outcome"]["provider_success"])
        self.assertEqual(len(b.facts), 1)
        self.assertEqual(b.traces.mine()["sft"], [])  # unscored even though artifact verified
        b.traces.feedback(out["trace"], True, "actual accepted packet")
        self.assertEqual(len(b.traces.mine()["sft"]), 1)

    def test_plain_answer_and_model_claimed_proof_remain_unverified(self):
        b = self.b([response(json.dumps({"final": "Everything is complete", "outcome": {"verified": True}, "proof": {"validated": True}}))])
        out = Agent(b).run("Explain the internal coding plan")
        self.assertEqual(out["answer"], "Everything is complete")
        self.assertEqual(out["outcome"]["status"], "response_unverified")
        b.traces.feedback(out["trace"], True)
        self.verify_not_learned(b, out)

    def test_adapter_fallback_text_is_not_provider_or_job_success(self):
        b = self.b([response('{"final":"A useful fallback response"}', fallback=True)])
        out = Agent(b).run("Suggest a coding plan")
        self.assertEqual(out["outcome"]["model_status"], "fallback_response")
        self.assertIsNone(out["outcome"]["provider_success"])
        self.verify_not_learned(b, out)

    def test_verifier_failure_preserves_packet_but_excludes_success(self):
        goal = "Prepare a scoped packet"
        b = self.b(self.packet_script(goal))
        def wrong_hash(*args):
            proof = self.checker(*args)
            proof["sha256"] = "0" * 64
            return proof
        out = Agent(b).run(goal, verify_job=wrong_hash, proof_root=self.root)
        self.assertEqual(out["outcome"]["status"], "verification_failed")
        self.verify_not_learned(b, out)

    def test_evidence_missing_from_actual_tool_is_rejected(self):
        artifact = self.root / "unrelated.md"
        artifact.write_text("An unrelated existing report")
        proof = {"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "job_id": "unrelated", "job_kind": "report", "checks": [{"name": "exists", "passed": True}]}
        with self.assertRaises(ValueError):
            validate_local_artifact(proof, self.root, [])

    def test_path_traversal_and_failed_acceptance_are_rejected(self):
        artifact = self.root / "proof.txt"
        artifact.write_text("bounded evidence")
        proof = {"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "job_id": "fixture", "job_kind": "report", "checks": [{"name": "goal met", "passed": False}]}
        with self.assertRaises(ValueError):
            validate_local_artifact(proof, self.root, [str(artifact)])
        proof["checks"][0]["passed"] = True
        proof["path"] = str(self.root / ".." / "outside.txt")
        with self.assertRaises(ValueError):
            validate_local_artifact(proof, self.root, [proof["path"]])

    def test_legacy_success_rows_and_feedback_are_visible_not_verified(self):
        b = self.b()
        for i in range(4):
            b.traces.record("coder", "legacy successful-looking coding plan", "Helpful plan text", "legacy-model", True, score=0.99)
        b.traces.feedback(b.traces.rows()[0]["id"], True)
        self.assertEqual(len(b.traces.rows()), 4)
        self.assertTrue(all(r["ok"] for r in b.traces.rows()))  # history was not silently rewritten
        self.assertEqual(b.traces.analyze()["unverified_traces"], 4)
        self.assertEqual(b.traces.mine(), {"sft": [], "failure": [], "routing": []})
        self.assertEqual(Orchestrator(b.app, b).discover_skills(), [])

    def test_malformed_new_receipt_is_not_legacy_promotion(self):
        b = self.b()
        b.traces.record("coder", "review", "done", "fixture", True, score=1, receipt={"outcome": {"schema": OUTCOME_SCHEMA}})
        self.assertEqual(episode_outcome(b.traces.rows()[0])["status"], "legacy_unverified")
        self.assertEqual(b.traces.mine()["sft"], [])

    def test_only_three_verified_goal_artifacts_create_a_skill(self):
        b = self.b()
        for i in range(3):
            artifact = self.root / ("accepted-%d.md" % i)
            artifact.write_text("Accepted internal report %d" % i)
            proof = validate_local_artifact({"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "job_id": "fixture-%d" % i, "job_kind": "write_report", "checks": [{"name": "actual accepted local report", "passed": True}]}, self.root, [str(artifact)])
            receipt = {"outcome": {"schema": OUTCOME_SCHEMA, "status": "verified_success", "verified": True, "response_origin": "model", "proof": proof}}
            b.traces.record("coder", "write a bounded internal coding report", "Accepted report produced", "scripted-fixture", True, score=0.9, receipt=receipt)
        found = Orchestrator(b.app, b).discover_skills()
        self.assertEqual(found[0]["successes"], 3)
        self.assertEqual(len(b.traces.mine()["sft"]), 3)
        self.assertEqual(b.traces.mine()["routing"][0]["success"], 1)

    def test_step_budget_rejects_bad_inputs_and_stops_partial_loop(self):
        for limit in (0, -1, 7, True, "6"):
            b = self.b()
            with self.assertRaises(ValueError):
                Agent(b).run("plan", max_steps=limit)
            self.assertEqual(b.packs.calls, 0)
        b = self.b([response('{"tool":"search","args":{"topic":"evidence"}}')] * 2)
        b.app.context_pack = lambda *a, **k: {"counts": {"sources": 0}}
        out = Agent(b).run("look for evidence", max_steps=2)
        self.assertEqual(b.packs.calls, 2)
        self.assertEqual(out["outcome"]["status"], "partial_actions")
        self.verify_not_learned(b, out)


if __name__ == "__main__":
    unittest.main()

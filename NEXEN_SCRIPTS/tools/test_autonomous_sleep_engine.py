import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("sleep_candidate", HERE / "autonomous_sleep_engine.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TruthTests(unittest.TestCase):
    def setUp(self):
        fixtures=Path('H:/NEXEN/handoffs/ticket-reconciliation-20261003/work/sleep-fix/fixtures')
        fixtures.mkdir(parents=True,exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=fixtures)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / "data.jsonl"
        self.dataset.write_text('{"instruction":"fixture","output":"fixture"}\n{}\n', encoding="utf-8")

    def engine(self, **kw):
        return module.AutonomousSleepEngine(state_dir=self.root / "state", dataset_path=self.dataset, **kw)

    def receipts(self, engine):
        return [json.loads(line) for line in engine.receipts_file.read_text(encoding="utf-8").splitlines()]

    def test_default_cycle_never_runs_subprocess_or_sleeps(self):
        e = self.engine()
        with patch.object(module.subprocess, "run", side_effect=AssertionError("Dispatch forbidden")), patch.object(module.time, "sleep", side_effect=AssertionError("Simulated progress forbidden")):
            self.assertEqual(e.execute_all(), 2)
        state = json.loads(e.status_file.read_text())
        self.assertEqual(state["phase"], "BLOCKED")
        self.assertEqual(state["progress_percent"], 0)
        self.assertFalse(state["active"])
        self.assertFalse(state["cloud_training_verified"])
        self.assertFalse(state["model_registration_verified"])
        self.assertFalse(state["provider_shutdown_verified"])
        self.assertNotIn("success", [r["status"] for r in self.receipts(e)])
    def test_atomic_status_failure_preserves_previous_generation(self):
        e=self.engine()
        e.update_status('BLOCKED',0,'previous valid status')
        before=e.status_file.read_bytes()
        with patch.object(module.os,'replace',side_effect=PermissionError('reader denies replacement')):
            with self.assertRaises(PermissionError):e.update_status('FAILED',0,'new status')
        self.assertEqual(e.status_file.read_bytes(),before)
        self.assertEqual(list(e.state_dir.glob('.sleep-status-*.tmp')),[])

    def test_real_count_and_hash_are_inspection_only(self):
        e = self.engine()
        e.orchestrate_cloud_finetuning()
        inspected = self.receipts(e)[0]
        self.assertEqual(inspected["status"], "inspected")
        self.assertEqual(inspected["details"]["records"], 2)
        self.assertEqual(len(inspected["details"]["sha256"]), 64)
        self.assertFalse(inspected["details"]["rights_reviewed"])

    def test_bad_datasets_never_train(self):
        for raw in ("", "not-json\n", "[]\n", "{}\nmalformed\n"):
            with self.subTest(raw=raw):
                self.dataset.write_text(raw, encoding="utf-8")
                e = self.engine()
                e.orchestrate_cloud_finetuning()
                self.assertEqual(e.outcomes["dataset_verification"], "blocked")
                self.assertEqual(e.outcomes["cloud_qlora_training"], "blocked")

    def test_missing_dataset(self):
        self.dataset.unlink()
        e = self.engine()
        e.orchestrate_cloud_finetuning()
        self.assertEqual(e.outcomes["dataset_verification"], "blocked")

    def test_registration_does_not_create_modelfile_or_call_ollama(self):
        e = self.engine()
        with patch.object(module.subprocess, "run", side_effect=AssertionError("Registration forbidden")):
            e.register_local_model()
        self.assertEqual(e.outcomes["ollama_registration"], "blocked")
        self.assertFalse((self.root / "Modelfile.master").exists())

    def admitted_engine(self):
        runner = self.root / "fake_ticket.py"
        runner.write_text("raise SystemExit(0)\n")
        e = self.engine(allow_local_tickets=True, python_exe=sys.executable, ticket_engine=runner)
        e.tickets_to_run = ["test-ticket"]
        return e

    def test_zero_exit_is_unverified_and_uses_argument_list(self):
        e = self.admitted_engine()
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "secret-like output", "")) as run:
            e.run_local_revenue_tickets()
        self.assertEqual(e.outcomes["test-ticket"], "executed_unverified")
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertNotIn("secret-like", e.receipts_file.read_text())

    def test_nonzero_exit_propagates_failure(self):
        e = self.admitted_engine()
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 7, "", "")):
            e.run_local_revenue_tickets()
        self.assertEqual(e.outcomes["test-ticket"], "failed")
        self.assertEqual(e.safe_shutdown_and_serve(), 1)
        self.assertEqual(json.loads(e.status_file.read_text())["phase"], "FAILED")

    def test_timeout_and_launch_crash(self):
        for exc in (subprocess.TimeoutExpired("fixture", 1), OSError("sensitive exception text")):
            with self.subTest(kind=type(exc).__name__):
                e = self.admitted_engine()
                with patch.object(module.subprocess, "run", side_effect=exc):
                    e.run_local_revenue_tickets()
                self.assertEqual(e.outcomes["test-ticket"], "failed")
                self.assertNotIn("sensitive exception text", e.receipts_file.read_text())

    def test_expired_deadline_prevents_dispatch(self):
        e = self.admitted_engine()
        e.deadline_time = 0
        with patch.object(module.subprocess, "run", side_effect=AssertionError("Expired dispatch")):
            e.run_local_revenue_tickets()
        self.assertEqual(e.outcomes["test-ticket"], "skipped_time_limit")

    def test_missing_runner_blocks_dispatch(self):
        e = self.engine(allow_local_tickets=True, ticket_engine=self.root / "missing.py")
        e.run_local_revenue_tickets()
        self.assertEqual(e.outcomes["local_ticket_dispatch"], "blocked")

    def test_invalid_time_rejected_before_writes(self):
        for value in (0, -1, float("nan"), float("inf"), True, "bad"):
            with self.subTest(value=str(value)):
                with self.assertRaises((ValueError, OverflowError)):
                    self.engine(rental_hours=value)

    def test_interruption_not_completion(self):
        e = self.engine()
        with patch.object(e, "run_local_revenue_tickets", side_effect=KeyboardInterrupt):
            self.assertEqual(e.execute_all(), 130)
        self.assertEqual(json.loads(e.status_file.read_text())["phase"], "CANCELLED")

    def test_plain_host_string_is_not_provider_proof(self):
        e = self.engine(cloud_host="configured-private-host")
        e.safe_shutdown_and_serve()
        state = json.loads(e.status_file.read_text())
        self.assertFalse(state["provider_shutdown_verified"])
        self.assertTrue(state["cloud_host_configured"])
        self.assertNotIn("configured-private-host", e.status_file.read_text())

    def test_old_success_journal_is_preserved_but_not_reused(self):
        e = self.engine()
        e.receipts_file.write_text('{"task":"cloud_qlora_training","status":"success"}\n')
        e.execute_all()
        self.assertEqual(self.receipts(e)[0]["status"], "success")
        self.assertEqual(e.outcomes["cloud_qlora_training"], "blocked")
        self.assertEqual(json.loads(e.status_file.read_text())["phase"], "BLOCKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Regression cases taken from real NEXEN and MARVIN logs (2026-10-06). Each real failure line must diagnose to its class."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from nexen import paths  # noqa: E402
from nexen.spine import failures, indicators  # noqa: E402
from nexen.spine.engine import Spine  # noqa: E402

REAL = {
    "OPS-001": ["Error: Cannot find module 'C:\\Users\\exampleuser' code: 'MODULE_NOT_FOUND'",
                "python.exe: can't open file 'C:\\\\Users\\\\exampleuser': [Errno 2] No such file or directory"],
    "OPS-002": ["[05:30:28] BOOT REPORT 8788=False 5678=True 5680=True", "[07:13:33] BOOT REPORT 8788=True 5678=False 5680=False"],
    "OPS-003": ["UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-1 marvin_swarm_worker.py start_worker_loop",
                "ModuleNotFoundError: No module named 'requests' marvin_swarm_orchestrator.py swarm-orchestrator-boot.stderr.log"],
    "OPS-004": ["Error: ENOENT: no such file or directory, mkdir 'F:\\NEXEN_GAME\\NEXEN_Autonomy_v0.1\\data\\n8n\\.n8n'"],
    "OPS-005": ["marvin.show-work: handler showWork missing"],
    "OPS-006": ["content.daily: Daily content worker failed or reached its deadline; inspect its local receipt.",
                "whop.campaigns: subprocess.py line 571, in run raise CalledProcessError"],
    "OPS-008": ["Task142 controller heartbeat is stale at Sep 30 05:23 PDT and PID 27808 is absent.",
                "TRACKER-pc1.json remains Sep 30 01:43 PDT and .tmp Sep 30 05:07 PDT. Tracker publication remains stale."],
}


class RealLogCases(unittest.TestCase):
    def test_every_real_line_diagnoses_to_its_class(self):
        s = Spine(":memory:")
        for pid, lines in REAL.items():
            for text in lines:
                d = s.diagnose(text, k=3)
                self.assertIn(pid, [m["id"] for m in d["matches"]], "%s missed: %s" % (pid, text))

    def test_new_classes_have_playbook_and_verify(self):
        s = Spine(":memory:")
        for pid in ["OPS-%03d" % i for i in range(1, 11)]:
            p = s.problems[pid]
            self.assertTrue(p["playbooks"][0]["steps"] and p["playbooks"][0]["verify"])
            self.assertEqual(p["area"], "ops")


class MinerFilters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_last_error_line_reads_the_exception_not_the_stack(self):
        p = self.write("a.stderr.log", "Traceback (most recent call last):\n  File \"x.py\", line 5, in <module>\n    import requests\nModuleNotFoundError: No module named 'requests'\n")
        self.assertEqual(failures.last_error_line(p), "ModuleNotFoundError: No module named 'requests'")

    def test_empty_and_noise_only_logs_give_nothing(self):
        self.assertIsNone(failures.last_error_line(self.write("e.stderr.log", "")))
        noise = "2026-10-04T06:32:49Z [Rudder] error: Response error code: ECONNRESET\n(node:1) [DEP0060] DeprecationWarning: x\n"
        self.assertIsNone(failures.last_error_line(self.write("n.stderr.log", noise)))

    def test_missing_file_is_not_a_crash(self):
        self.assertIsNone(failures.last_error_line(self.dir / "absent.log"))

    def test_noise_and_owner_gates_are_recognised(self):
        self.assertTrue(failures.is_noise("[Rudder] error: Response error code: ECONNRESET"))
        self.assertFalse(failures.is_noise("ModuleNotFoundError: No module named 'requests'"))
        self.assertTrue(failures.OWNER_GATE.search("Upwork personal-profile4of5 and Fiverr human verification/editor access"))
        self.assertFalse(failures.OWNER_GATE.search("handler showWork missing"))


class PreflightIndicators(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.H_NEXEN
        paths.H_NEXEN = Path(self.tmp.name)
        (paths.H_NEXEN / "logs").mkdir()
        (paths.H_NEXEN / "marvin" / "bus").mkdir(parents=True)

    def tearDown(self):
        paths.H_NEXEN = self.saved
        self.tmp.cleanup()

    def log(self, name, text):
        (paths.H_NEXEN / "logs" / name).write_text(text, encoding="utf-8")

    def test_boot_stderr_classification(self):
        self.assertEqual(indicators.classify_boot_error("Error: Cannot find module 'C:\\Users\\exampleuser'"), "OPS-001")
        self.assertEqual(indicators.classify_boot_error("ENOENT: no such file or directory, mkdir 'F:\\NEXEN_GAME\\x'"), "OPS-004")
        self.assertEqual(indicators.classify_boot_error("ModuleNotFoundError: No module named 'requests'"), "OPS-003")

    def test_boot_stderr_ok_when_empty_or_missing_folder(self):
        self.log("w-boot.stderr.log", "")
        self.assertEqual(indicators._boot_stderr()["state"], "ok")
        paths.H_NEXEN = Path(self.tmp.name) / "nowhere"
        self.assertIn(indicators._boot_stderr()["state"], {"ok", "warn"})

    def test_boot_stderr_flags_fresh_traceback_and_ignores_old(self):
        self.log("n8n-5680-boot.stderr.log", "Error: Cannot find module 'C:\\Users\\exampleuser'\n")
        r = indicators._boot_stderr()
        self.assertEqual((r["state"], r["problem"]), ("bad", "OPS-001"))
        old = paths.H_NEXEN / "logs" / "n8n-5680-boot.stderr.log"
        t = time.time() - 10 * 86400
        import os
        os.utime(old, (t, t))
        self.assertEqual(indicators._boot_stderr()["state"], "ok")

    def test_bus_handler_missing_detected(self):
        rows = [{"action": "marvin.show-work", "status": "failed", "summary": "handler showWork missing"},
                {"action": "money.plan", "status": "done", "summary": "ok"}]
        (paths.H_NEXEN / "marvin" / "bus" / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        r = indicators._bus_handlers()
        self.assertEqual((r["state"], r["problem"]), ("bad", "OPS-005"))
        self.assertIn("marvin.show-work", r["detail"])

    def test_bus_clean_when_no_file(self):
        self.assertEqual(indicators._bus_handlers()["state"], "ok")

    def test_log_size_warns_over_limit(self):
        self.log("big.log", "x" * 2_000_000)
        self.assertEqual(indicators._log_size(limit_mb=1)["state"], "warn")
        self.assertEqual(indicators._log_size(limit_mb=5)["state"], "ok")


if __name__ == "__main__":
    unittest.main()

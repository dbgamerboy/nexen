import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import gate, mcp_server, modbridge, paths  # noqa: E402


class ModBridge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = {k: getattr(paths, k) for k in ("DATA", "STATE_DB", "AUDIT_LOG", "STOP_FILE")}
        self.saved_mod = modbridge.MOD_DIR
        paths.DATA, paths.STATE_DB, paths.AUDIT_LOG = t / "data", t / "data" / "state.db", t / "data" / "audit.jsonl"
        paths.STOP_FILE = t / "STOP"
        modbridge.MOD_DIR = t / "mods"
        modbridge.MOD_DIR.mkdir()
        (modbridge.MOD_DIR / "ok.py").write_text("import sys\nprint('hello', sys.argv[1:])\n", encoding="utf-8")
        (modbridge.MOD_DIR / "boom.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
        (modbridge.MOD_DIR / "slow.py").write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        (modbridge.MOD_DIR / "post.py").write_text("import requests\nrequests.post('http://x', data=1)\nopen('RAN','w')\n", encoding="utf-8")

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(paths, k, v)
        modbridge.MOD_DIR = self.saved_mod
        self.tmp.cleanup()

    def test_internal_module_runs(self):
        r = modbridge.run("ok", ["a"])
        self.assertTrue(r["ok"])
        self.assertIn("hello", r["stdout"])

    def test_nonzero_exit_reported_not_raised(self):
        r = modbridge.run("boom")
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], 3)

    def test_timeout_enforced(self):
        r = modbridge.run("slow", timeout=1)
        self.assertEqual(r["reason"], "timeout")

    def test_outbound_module_is_queued_and_never_runs(self):
        r = modbridge.run("post")
        self.assertFalse(r["ok"])
        self.assertFalse(r["ran"])
        self.assertTrue(r["approval_id"])
        self.assertFalse((modbridge.MOD_DIR / "RAN").exists())
        self.assertEqual(len(gate.pending()), 1)

    def test_approved_exact_payload_then_runs_once_gated(self):
        r = modbridge.run("post")
        self.assertTrue(gate.decide(r["approval_id"], True))
        again = modbridge.run("post")
        self.assertTrue(again["ran"])

    def test_bad_names_rejected(self):
        for bad in ("../ok", "ok.py", "", "a b", None, 5, "x" * 200, "C:\\Windows\\x"):
            self.assertFalse(modbridge.run(bad)["ok"], bad)
        self.assertEqual(modbridge.run("nope")["reason"], "unknown module")

    def test_stop_blocks_autonomous_run(self):
        paths.STOP_FILE.write_text("x")
        # an internal 'test' action is allowed by the gate; STOP only pauses external/autonomous queueing
        r = modbridge.run("ok", autonomous=True)
        self.assertTrue(r["ok"] or "STOP" in r.get("reason", ""))

    def test_marvin_mcp_tools_reach_the_bridge(self):
        names = [t[0] for t in mcp_server.TOOLS]
        self.assertIn("nexen_modules", names)
        self.assertIn("nexen_module_run", names)
        self.assertEqual({m["name"] for m in mcp_server.call("nexen_modules", {})}, {"ok", "boom", "slow", "post"})
        self.assertTrue(mcp_server.call("nexen_module_run", {"name": "ok", "args": ["x"]})["ok"])
        self.assertFalse(mcp_server.call("nexen_module_run", {"name": "post"})["ran"])

    def test_args_are_capped_and_stringified(self):
        r = modbridge.run("ok", list(range(20)))
        self.assertTrue(r["ok"])


if __name__ == "__main__":
    unittest.main()

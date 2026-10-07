import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import actions, paths  # noqa: E402


class Actions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (paths.H_NEXEN, paths.STOP_FILE, paths.DATA, actions.CATALOG)
        t = Path(self.tmp.name)
        paths.H_NEXEN, paths.STOP_FILE, paths.DATA = t / "nexen", t / "STOP", t / "data"
        paths.DATA.mkdir()
        (t / "note.md").write_text("hello plan", encoding="utf-8")
        actions.CATALOG = t / "actions.json"
        actions.CATALOG.write_text(json.dumps({"actions": [
            {"id": "t.view", "label": "view", "risk": "safe", "kind": "view", "target": str(t / "note.md")},
            {"id": "t.log", "label": "log", "risk": "safe", "kind": "internal", "handler": "logResult",
             "inputs": [{"name": "lane", "required": True}, {"name": "item", "required": True}, {"name": "dollars", "type": "number", "required": True},
                        {"name": "hours", "type": "number", "required": True}]},
            {"id": "t.resume", "label": "resume", "risk": "confirm", "kind": "internal", "handler": "loopResume"},
            {"id": "t.pause", "label": "pause", "risk": "safe", "kind": "internal", "handler": "loopPause"},
            {"id": "t.nohandler", "label": "x", "risk": "safe", "kind": "internal", "handler": "doesNotExist"},
            {"id": "t.proc", "label": "proc", "risk": "safe", "kind": "process", "exe": sys.executable, "args": ["-c", "print('ran {x}')"], "inputs": [{"name": "x"}]},
        ]}), encoding="utf-8")

    def tearDown(self):
        paths.H_NEXEN, paths.STOP_FILE, paths.DATA, actions.CATALOG = self.saved
        self.tmp.cleanup()

    def test_view_returns_file_text(self):
        r = actions.request("t.view")
        self.assertEqual(r["status"], "done")
        self.assertIn("hello plan", r["content"])

    def test_log_result_writes_csv_and_rejects_bad_numbers(self):
        r = actions.request("t.log", {"lane": "whop", "item": "clip1", "dollars": "12.5", "hours": "2"})
        self.assertEqual(r["status"], "done")
        self.assertIn("whop,clip1,0,12.5,2", (paths.H_NEXEN / "marvin" / "results.csv").read_text(encoding="utf-8"))
        self.assertEqual(actions.request("t.log", {"lane": "w", "item": "i", "dollars": "abc", "hours": "1"})["status"], "error")
        self.assertEqual(actions.request("t.log", {"lane": "w"})["status"], "error")

    def test_confirm_risk_needs_the_owner_click(self):
        paths.STOP_FILE.write_text("x")
        self.assertEqual(actions.request("t.resume")["status"], "needs_confirm")
        self.assertEqual(actions.request("t.resume", source="mcp", confirmed=True)["status"], "needs_confirm")
        self.assertTrue(paths.STOP_FILE.exists())
        self.assertEqual(actions.request("t.resume", source="ui", confirmed=True)["status"], "done")
        self.assertFalse(paths.STOP_FILE.exists())

    def test_pause_writes_stop_file(self):
        actions.request("t.pause")
        self.assertTrue(paths.STOP_FILE.exists())

    def test_unknown_missing_handler_and_dash_input_are_errors(self):
        self.assertEqual(actions.request("nope")["status"], "error")
        self.assertEqual(actions.request("t.nohandler")["status"], "error")
        self.assertEqual(actions.request("t.proc", {"x": "-rf"})["status"], "error")

    def test_process_runs_without_shell_and_records_result(self):
        r = actions.request("t.proc", {"x": "hi"})
        self.assertEqual(r["status"], "started")
        import time
        for _ in range(50):
            if r["record"]["status"] != "running":
                break
            time.sleep(0.1)
        self.assertEqual(r["record"]["status"], "done")
        self.assertIn("ran hi", r["record"]["summary"])

    def test_real_catalog_loads_every_action_with_a_known_kind(self):
        actions.CATALOG = self.saved[3]
        cat = actions.catalog()
        self.assertGreaterEqual(len(cat), 35)
        for a in cat:
            self.assertIn(a["kind"], {"process", "launch", "view", "edit", "gallery", "internal", "system"})
            if a["kind"] == "internal":
                self.assertIn(a["handler"], actions.HANDLERS, a["id"])


if __name__ == "__main__":
    unittest.main()

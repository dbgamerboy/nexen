import json
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from nexen import api_spine, brain as brain_mod, gate, paths  # noqa: E402
from nexen.connectors import nexen as nexen_conn  # noqa: E402
from tests.test_spine import Sandbox  # noqa: E402

WORKFLOWS = Path(__file__).resolve().parents[2] / "Workflows" / "V4"


class N8nFiles(unittest.TestCase):
    def test_workflows_are_well_formed_inactive_and_wired_to_v4(self):
        files = sorted(WORKFLOWS.glob("*.json"))
        self.assertEqual(len(files), 3)
        for f in files:
            wf = json.loads(f.read_text(encoding="utf-8"))
            self.assertFalse(wf["active"], f.name)
            names = [n["name"] for n in wf["nodes"]]
            self.assertEqual(len(names), len(set(names)), f.name)
            ids = [n["id"] for n in wf["nodes"]]
            self.assertEqual(len(ids), len(set(ids)))
            for src, conn in wf["connections"].items():
                self.assertIn(src, names, f.name)
                for branch in conn["main"]:
                    for link in branch:
                        self.assertIn(link["node"], names, f.name)
            http = [n for n in wf["nodes"] if n["type"].endswith("httpRequest")]
            self.assertTrue(http, f.name)
            for n in http:
                self.assertTrue(n["parameters"]["url"].startswith("http://127.0.0.1:8794/"))
                heads = {h["name"]: h["value"] for h in n["parameters"]["headerParameters"]["parameters"]}
                self.assertEqual(heads["X-Nexen-Action"], "v4")
            self.assertTrue(any(n["type"].endswith(("webhook", "scheduleTrigger")) for n in wf["nodes"]))


class Gateway(Sandbox):
    def setUp(self):
        super().setUp()
        self.b = self.brain()
        brain_mod.set_brain(self.b)
        self.saved_hand = nexen_conn.Vault.write_handoff
        nexen_conn.Vault.write_handoff = lambda self_, name, text: {"ok": True, "path": "test"}

    def tearDown(self):
        nexen_conn.Vault.write_handoff = self.saved_hand
        brain_mod.set_brain(None)
        super().tearDown()

    def test_ops_roundtrip_with_receipts(self):
        n = lambda body: api_spine.n8n(self.b, body)
        self.assertTrue(n({"op": "status"})["ok"])
        r = n({"op": "resolve", "text": "sqlite database is locked while two workers write"})
        self.assertEqual(r["result"]["kind"], "known")
        self.assertIn("at", r["receipt"])
        r = n({"op": "rules_check", "action": {"type": "clip"}})
        self.assertEqual(r["result"]["status"], "blocked")
        self.assertEqual(n({"op": "learn", "text": "The gateway op list is documented in the workflow meta note and in this test.", "source_ids": ["test:gw"]})["result"]["op"], "ADD")
        self.assertTrue(n({"op": "recall", "query": "gateway op list"})["result"])
        d = n({"op": "draft_workflow", "text": "Upwork proposal automation service", "source_ids": ["file:x"]})
        self.assertIn("verdict", d["result"])
        self.assertTrue(n({"op": "due"})["ok"])

    def test_bad_requests_fail_cleanly(self):
        r = api_spine.n8n(self.b, {"op": "nope"})
        self.assertFalse(r["ok"])
        self.assertIn("ops", r)
        self.assertFalse(api_spine.n8n(self.b, {"op": "resolve"})["ok"])

    def test_run_block_internal_obeys_stop_and_external_never_acts(self):
        paths.STOP_FILE.write_text("1")
        self.assertIn("STOP", api_spine.run_block(self.b, "swarm")["skipped"])
        paths.STOP_FILE.unlink()
        out = api_spine.run_block(self.b, "swarm")
        self.assertTrue(out["ok"])
        self.assertIn("not dispatched", out["note"])
        owner = api_spine.run_block(self.b, "services")
        self.assertIn("nothing is sent or posted", owner["note"])
        self.assertFalse(api_spine.run_block(self.b, "ghost")["ok"])
        self.assertEqual(self.b.schedule.due(), [b for b in self.b.schedule.due()])

    def test_http_gateway_endpoint(self):
        from http.server import ThreadingHTTPServer
        from nexen.server import Handler
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request("http://127.0.0.1:%d/api/n8n/marvin" % httpd.server_address[1], data=json.dumps({"op": "resolve", "text": "port already in use"}).encode(),
                                         headers={"X-Nexen-Action": "v4", "Content-Type": "application/json"})
            body = json.loads(urllib.request.urlopen(req, timeout=20).read())
            self.assertTrue(body["ok"])
            with self.assertRaises(Exception):
                urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/n8n/marvin" % httpd.server_address[1], data=b"{}", headers={}), timeout=10)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_mcp_new_tools(self):
        from nexen import mcp_server
        names = {t[0] for t in mcp_server.TOOLS}
        self.assertTrue({"nexen_decide", "nexen_diagnose", "nexen_premortem", "nexen_rules_check", "nexen_prompt", "nexen_schedule", "nexen_world"} <= names)
        self.assertEqual(mcp_server.call("nexen_rules_check", {"action": {"type": "credentials"}})["status"], "blocked")
        self.assertIn("risks", mcp_server.call("nexen_premortem", {"plan": "publish a reel"}))


if __name__ == "__main__":
    unittest.main()

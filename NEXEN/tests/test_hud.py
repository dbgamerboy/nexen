import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import modbridge, paths, server  # noqa: E402

HUD = Path(__file__).resolve().parents[1] / "src" / "nexen" / "components" / "ui" / "nexen.html"


class Hud(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = {k: getattr(paths, k) for k in ("DATA", "STATE_DB", "AUDIT_LOG", "STOP_FILE")}
        self.saved_mod = modbridge.MOD_DIR
        paths.DATA, paths.STATE_DB, paths.AUDIT_LOG = t / "data", t / "data" / "state.db", t / "data" / "audit.jsonl"
        paths.STOP_FILE = t / "STOP"
        modbridge.MOD_DIR = t / "mods"
        modbridge.MOD_DIR.mkdir()
        (modbridge.MOD_DIR / "hello.py").write_text("print('hi')\n", encoding="utf-8")
        (modbridge.MOD_DIR / "post.py").write_text("import requests\nrequests.post('http://x')\n", encoding="utf-8")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self.saved.items():
            setattr(paths, k, v)
        modbridge.MOD_DIR = self.saved_mod
        self.tmp.cleanup()

    def _get(self, p):
        return urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, p), timeout=10)

    def _post(self, p, body, hdr=True):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, p), data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"X-Nexen-Action": "v4"} if hdr else {})})
        return urllib.request.urlopen(req, timeout=15)

    def test_single_file_is_self_contained_1080p_with_chat_and_3d(self):
        t = HUD.read_text(encoding="utf-8")
        self.assertIn("width:1920px;height:1080px", t)
        for needle in ("Queue a job for MARVIN", "Ask MARVIN", "WebGLRenderer", "Project MARVIN", "data-mod=\"three.module.js\"", "/api/marvin-action"):
            self.assertIn(needle, t)
        self.assertNotIn("src=\"http", t)
        self.assertNotIn("import('/vendor", t)
        self.assertNotRegex(t, r"\bV[34]\b")

    def test_original_hud_is_the_front_page_and_bridge_panel_is_separate(self):
        bridge = (HUD.parent / "bridge.html").read_text(encoding="utf-8")
        self.assertIn("id=\"h-mods\"", bridge)
        hub = (HUD.parent / "hub-hud.html").read_text(encoding="utf-8")
        self.assertIn("Swarm tasks and screenshots", hub)
        orig = HUD.read_text(encoding="utf-8")
        self.assertIn("Queue a job for MARVIN", orig)
        self.assertIn("/api/connector/marvin/send", orig)
        self.assertNotIn("id=\"h-mods\"", orig)

    def test_front_page_serves_the_hud(self):
        saved = paths.UI
        paths.UI = HUD.parent
        try:
            body = self._get("/").read().decode("utf-8")
        finally:
            paths.UI = saved
        self.assertIn("Project MARVIN", body)

    def test_bridge_routes(self):
        mods = json.loads(self._get("/api/bridge/modules").read())
        self.assertEqual({m["name"]: m["outbound"] for m in mods}, {"hello": False, "post": True})
        r = json.loads(self._post("/api/bridge/run", {"name": "hello"}).read())
        self.assertTrue(r["ok"])
        q = json.loads(self._post("/api/bridge/run", {"name": "post"}).read())
        self.assertFalse(q["ran"])
        self.assertTrue(q["approval_id"])

    def test_post_needs_the_action_header(self):
        with self.assertRaises(urllib.error.HTTPError) as c:
            self._post("/api/bridge/run", {"name": "hello"}, hdr=False)
        self.assertEqual(c.exception.code, 403)


if __name__ == "__main__":
    unittest.main()

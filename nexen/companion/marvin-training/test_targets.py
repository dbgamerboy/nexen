"""Tests the live-MARVIN and Ollama clients against a fake local server, including failures. No real password, no real MARVIN."""
import http.server, json, os, sys, threading, unittest, argparse, tempfile, importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import marvin_train as mt

PW = "test-only-pw"          # fake server only
STATE = {"mode": "ok", "calls": 0}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj, cookie=None):
        b = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(code); self.send_header("Content-Type", "application/json")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/auth/login":
            if body.get("password") != PW: return self._send(401, {"detail": "bad password"})
            return self._send(200, {"authenticated": True}, "nexen_session=abc; Path=/; HttpOnly")
        if self.path == "/api/marvin/chat":
            if "nexen_session=abc" not in (self.headers.get("Cookie") or ""): return self._send(401, {"detail": "no session"})
            if self.headers.get("X-NEXEN-Action") != "launch" or not (self.headers.get("Origin") or "").startswith("http://127.0.0.1"):
                return self._send(403, {"detail": "headers"})
            STATE["calls"] += 1
            if STATE["mode"] == "500": return self._send(500, {"detail": "boom"})
            if STATE["mode"] == "garbage": return self._send(200, b"<html>not json")
            if STATE["mode"] == "fallback": return self._send(200, {"reply": "", "model": "fallback", "fallback": True, "ms": 1})
            return self._send(200, {"reply": "No. The 229 receipt gate and STOP apply, handlers report fake success.", "model": "x", "fallback": False, "ms": 5})
        if self.path == "/api/chat":
            return self._send(200, {"message": {"content": "ollama says 229 receipt"}})
        self._send(404, {})


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.item = mt.load_bank()[0]
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self): STATE.update(mode="ok", calls=0)

    def test_login_and_chat(self):
        m = mt.Marvin(self.base, password=PW)
        ans, meta = m.ask(self.item)
        self.assertIn("229", ans); self.assertFalse(meta["fallback"])
    def test_wrong_password_raises(self):
        with self.assertRaises(Exception): mt.Marvin(self.base, password="nope")
    def test_http_500_raises(self):
        m = mt.Marvin(self.base, password=PW); STATE["mode"] = "500"
        with self.assertRaises(Exception): m.ask(self.item)
    def test_garbage_json_raises(self):
        m = mt.Marvin(self.base, password=PW); STATE["mode"] = "garbage"
        with self.assertRaises(Exception): m.ask(self.item)
    def test_fallback_flagged(self):
        m = mt.Marvin(self.base, password=PW); STATE["mode"] = "fallback"
        ans, meta = m.ask(self.item); self.assertTrue(meta["fallback"]); self.assertFalse(mt.grade(self.item, ans)["passed"])
    def test_dead_server_raises(self):
        with self.assertRaises(Exception): mt.Marvin("http://127.0.0.1:1", password=PW)
    def test_ollama_client(self):
        ans, meta = mt.Ollama("m", self.base).ask(self.item); self.assertIn("229", ans)

    def test_run_survives_errors_and_resumes(self):
        tmp = tempfile.mkdtemp(); mt.RDIR = tmp
        orig = mt.make_target
        mt.make_target = lambda a: mt.Marvin(self.base, password=PW)
        try:
            a = argparse.Namespace(cat="POL", min_diff=None, ids=None, ids_file=None, limit=4, target="marvin", model=None, base=None,
                                   key_env=None, resume=None, stop_after_errors=0)
            STATE["mode"] = "500"
            out = mt.cmd_run(a)
            rows = [json.loads(l) for l in open(out, encoding="utf-8")]
            self.assertEqual(len(rows), 4); self.assertTrue(all(r["error"] and not r["passed"] for r in rows))
            self.assertNotIn(PW, open(out, encoding="utf-8").read())      # password never lands in results
            STATE["mode"] = "ok"; a.resume = out
            mt.cmd_run(a)                                                   # nothing left to ask, must not duplicate rows
            self.assertEqual(len(open(out, encoding="utf-8").read().splitlines()), 4)
        finally:
            mt.make_target = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)

import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nexen import core, gate, paths, registry, updater  # noqa: E402
from nexen.connectors import agents, base  # noqa: E402
from nexen.learning.ledger import Ledger  # noqa: E402


class Sandbox(unittest.TestCase):
    """Point every V4 path at a temp folder so tests never touch real data."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = {k: getattr(paths, k) for k in ("DATA", "STATE_DB", "AUDIT_LOG", "STOP_FILE", "APP", "UI", "MODULES", "LEARNING_DB")}
        paths.DATA, paths.STATE_DB, paths.AUDIT_LOG = t / "data", t / "data" / "state.db", t / "data" / "audit.jsonl"
        paths.STOP_FILE = t / "STOP"
        paths.APP, paths.UI, paths.MODULES = t / "app", t / "app" / "ui", t / "app" / "modules"
        for d in (paths.DATA, paths.UI, paths.MODULES, paths.APP / "engine"):
            d.mkdir(parents=True, exist_ok=True)
        (paths.UI / "index.html").write_text("<html>ui</html>", encoding="utf-8")
        core._app = core.App(Ledger())

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(paths, k, v)
        core._app = None
        self.tmp.cleanup()


class Redaction(unittest.TestCase):
    def test_secrets_and_lan_removed(self):
        text = "key sk-abcdefghijklmnop1234 and password: hunter2222 and Bearer abcdefghijklmnopqrstuvwxyz1234 at 192.168.77.5"
        out = base.redact(text)
        for leak in ("abcdefghijklmnop1234", "hunter2222", "abcdefghijklmnopqrstuvwxyz1234", "192.168.77.5"):
            self.assertNotIn(leak, out)
        self.assertIn("[LAN-ADDR]", out)

    def test_non_string(self):
        self.assertEqual(base.redact(None), "")


class Gate(Sandbox):
    def test_internal_allowed_external_queued_then_exact_approval(self):
        self.assertTrue(gate.check("learn")["allowed"])
        r = gate.check("publish", "post reel", {"url": "x"})
        self.assertFalse(r["allowed"])
        self.assertEqual(len(gate.pending()), 1)
        self.assertFalse(gate.check("publish", "post reel", {"url": "x"})["allowed"])
        self.assertTrue(gate.decide(r["approval_id"], True))
        self.assertTrue(gate.check("publish", "post reel", {"url": "x"})["allowed"])
        self.assertFalse(gate.check("publish", "post reel", {"url": "different"})["allowed"])  # exact payload only

    def test_unknown_kind_is_treated_as_external(self):
        self.assertFalse(gate.check("wire_money", "x")["allowed"])

    def test_stop_blocks_autonomous_only(self):
        paths.STOP_FILE.write_text("1")
        self.assertFalse(gate.check("learn", autonomous=True)["allowed"])
        self.assertTrue(gate.check("learn", autonomous=False)["allowed"])

    def test_denied_stays_denied(self):
        r = gate.check("spend", "ads", {"usd": 50})
        gate.decide(r["approval_id"], False)
        self.assertFalse(gate.check("spend", "ads", {"usd": 50})["allowed"])


class Connectors(Sandbox):
    def test_codex_read_and_redact(self):
        root = Path(self.tmp.name) / "codex"
        f = root / "sessions" / "2026" / "10" / "05" / "rollout-2026-10-05T00-00-00-abc12345-0000-0000-0000-000000000001.jsonl"
        f.parent.mkdir(parents=True)
        rows = [{"type": "response_item", "timestamp": "t1", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello novel learning"}]}},
                {"type": "response_item", "timestamp": "t2", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "token: abcdef1234567890 done at 192.168.77.5"}]}},
                {"type": "response_item", "timestamp": "t3", "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "<hidden>"}]}}]
        f.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
        saved = agents.CODEX
        agents.CODEX = root
        try:
            c = agents.Codex()
            data = c.read("abc12345-0000-0000-0000-000000000001")
            self.assertTrue(data["ok"])
            self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
            self.assertNotIn("abcdef1234567890", data["messages"][1]["text"])
            self.assertEqual(len(c.search("novel")), 1)
        finally:
            agents.CODEX = saved

    def test_hermes_read_only_query(self):
        db = Path(self.tmp.name) / "state.db"
        con = sqlite3.connect(db)
        con.executescript("CREATE TABLE sessions(id TEXT, source TEXT, display_name TEXT, started_at REAL);"
                          "CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL);"
                          "INSERT INTO sessions VALUES('s1','cli','demo',1790000000);"
                          "INSERT INTO messages(session_id,role,content,timestamp) VALUES('s1','user','what about recursive learning',1790000001);")
        con.commit()
        con.close()
        saved = agents.HERMES_DB
        agents.HERMES_DB = db
        try:
            h = agents.Hermes()
            self.assertEqual(h.recent(5)[0]["id"], "s1")
            self.assertEqual(len(h.search("recursive")), 1)
            self.assertTrue(h.read("s1")["ok"])
            con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("INSERT INTO sessions VALUES('x','y','z',1)")
            con.close()
        finally:
            agents.HERMES_DB = saved

    def test_chatgpt_packet_is_never_marked_sent(self):
        saved = agents.OUTBOX
        agents.OUTBOX = Path(self.tmp.name) / "outbox"
        try:
            r = agents.ChatGPT().packet("score this draft sk-abcdefghijklmnop1234", "score")
            self.assertIn("not sent", r["status"])
            text = Path(r["path"]).read_text(encoding="utf-8")
            self.assertIn("NOT SENT", text)
            self.assertNotIn("abcdefghijklmnop1234", text)
        finally:
            agents.OUTBOX = saved

    def test_missing_sources_do_not_crash(self):
        saved = agents.GEMINI, agents.CODEX
        agents.GEMINI, agents.CODEX = Path(self.tmp.name) / "nope", Path(self.tmp.name) / "nope2"
        try:
            self.assertEqual(agents.Antigravity().recent(3), [])
            self.assertEqual(agents.Codex().recent(3), [])
            self.assertFalse(agents.Codex().read("x")["ok"])
        finally:
            agents.GEMINI, agents.CODEX = saved


class Updater(Sandbox):
    def make(self, name, rel, content, tamper=False):
        d = paths.APP / "updates" / name
        (d / Path(rel).parent).mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(content.encode())  # bytes, so Windows newline translation cannot change the hash
        sha = hashlib.sha256(content.encode()).hexdigest()
        if tamper:
            sha = "0" * 64
        (d / "manifest.json").write_text(json.dumps({"version": "4.0.1", "files": [{"path": rel.replace("\\", "/"), "sha256": sha}]}), encoding="utf-8")

    def test_apply_backup_and_restart_flag(self):
        (paths.MODULES / "a.json").write_text("{}", encoding="utf-8")
        self.make("u1", "modules/a.json", '{"id":"x","name":"X"}')
        r = updater.apply("u1", run_tests=False)
        self.assertTrue(r["ok"], r)
        self.assertEqual(json.loads((paths.MODULES / "a.json").read_text())["id"], "x")
        self.assertFalse((paths.DATA / "restart.flag").exists())
        self.make("u2", "engine/nexen/new.py", "X = 1\n")
        self.assertTrue(updater.apply("u2", run_tests=False)["restart_requested"])
        self.assertTrue((paths.DATA / "restart.flag").exists())
        self.assertEqual(updater.pending(), [])

    def test_hash_mismatch_and_traversal_rejected(self):
        self.make("bad", "modules/a.json", "{}", tamper=True)
        r = updater.apply("bad", run_tests=False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["stage"], "verify")
        d = paths.APP / "updates" / "evil"
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"files": [{"path": "../outside.txt", "sha256": "0" * 64},
                                                              {"path": "engine/../../x.py", "sha256": "0" * 64},
                                                              {"path": "tests/test_x.py", "sha256": "0" * 64}]}))
        self.assertEqual(len(updater.apply("evil", run_tests=False)["problems"]), 3)

    def test_failing_tests_roll_back(self):
        tests = paths.APP / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / "test_gate.py").write_text("import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.fail('boom')\n", encoding="utf-8")
        (paths.MODULES / "keep.json").write_text('{"v":1}', encoding="utf-8")
        self.make("u3", "modules/keep.json", '{"v":2}')
        r = updater.apply("u3", run_tests=True)
        self.assertFalse(r["ok"])
        self.assertEqual(json.loads((paths.MODULES / "keep.json").read_text())["v"], 1)


class Registry(Sandbox):
    def test_hot_module_loaded_and_bad_json_ignored(self):
        (paths.MODULES / "ok.json").write_text(json.dumps({"id": "hot1", "name": "Hot", "buttons": [{"id": "b", "label": "B", "kind": "view", "target": "learning:gaps"}]}))
        (paths.MODULES / "bad.json").write_text("{nope")
        ids = [m["id"] for m in registry.hot_modules()]
        self.assertEqual(ids, ["hot1"])

    def test_launch_only_trusted(self):
        self.assertFalse(registry.launch("script", r"C:\Windows\System32\cmd.exe")["ok"])
        self.assertFalse(registry.launch("url", "https://example.com")["ok"])
        self.assertFalse(registry.launch("folder", r"C:\Windows")["ok"])
        self.assertFalse(registry.launch("nonsense", "x")["ok"])


class Server(Sandbox):
    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        from nexen.server import Handler
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def call(self, path, body=None, headers=None, method=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_health_static_and_traversal(self):
        code, body = self.call("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["version"], "4.0.0")
        self.assertEqual(self.call("/")[0], 200)
        self.assertEqual(self.call("/..%2f..%2fsecret")[0], 404)

    def test_post_requires_header_and_bad_host_blocked(self):
        self.assertEqual(self.call("/api/learning/recall", {"query": "x"})[0], 403)
        code, _ = self.call("/api/learning/recall", {"query": "x"}, {"X-Nexen-Action": "v4"})
        self.assertEqual(code, 200)
        self.assertEqual(self.call("/api/health", headers={"Host": "evil.example"})[0], 403)

    def test_learning_roundtrip_and_launch_guard(self):
        h = {"X-Nexen-Action": "v4", "Content-Type": "application/json"}
        code, body = self.call("/api/learning/novel", {"text": "The V4 server binds only to loopback and rejects posts without the action header.",
                                                     "source_ids": ["test:server"]}, h)
        self.assertEqual(json.loads(body)["op"], "ADD")
        code, body = self.call("/api/learning/recall", {"query": "V4 server loopback"}, h)
        self.assertEqual(len(json.loads(body)), 1)
        code, body = self.call("/api/launch", {"kind": "script", "target": r"C:\Windows\notepad.exe"}, h)
        self.assertFalse(json.loads(body)["ok"])


class Mcp(Sandbox):
    def test_tools_call_roundtrip(self):
        from nexen import mcp_server
        r = mcp_server.call("nexen_learn", {"text": "The MCP server exposes ten tools and reads only local sources for context.", "source_ids": ["test:mcp"]})
        self.assertEqual(r["op"], "ADD")
        hits = mcp_server.call("nexen_recall", {"query": "MCP server tools"})
        self.assertEqual(len(hits), 1)
        r = mcp_server.call("nexen_ask", {"connector": "chatgpt", "prompt": "x"})
        self.assertIn("not sent", r["status"])
        with self.assertRaises(KeyError):
            mcp_server.call("nope", {})


if __name__ == "__main__":
    unittest.main()

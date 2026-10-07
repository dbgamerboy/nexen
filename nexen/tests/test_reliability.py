import io
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from nexen import api_spine, autonomy, cli, core, mcp_server, paths, reliability  # noqa: E402
from nexen.connectors import nexen as nexen_conn  # noqa: E402
from nexen.learning.ledger import Ledger  # noqa: E402
from tests.test_spine import Sandbox  # noqa: E402


class Guard(Sandbox):
    def setUp(self):
        super().setUp()
        reliability._spine = None  # a fresh spine database inside the sandbox

    def test_transient_fault_is_retried_then_succeeds(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise sqlite3_locked()
            return "fine"
        r = reliability.run_guarded("t", flaky, retries=3, backoff=0.01)
        self.assertTrue(r["ok"])
        self.assertEqual(r["result"], "fine")
        self.assertEqual(r["attempts"], 3)

    def test_permanent_fault_returns_diagnosis_not_a_crash(self):
        r = reliability.run_guarded("t", lambda: {}["missing"], retries=2, backoff=0.01)
        self.assertFalse(r["ok"])
        self.assertEqual(r["attempts"], 1)  # not transient, so no retries
        self.assertTrue(r["next_action"])
        self.assertTrue(r["degraded"])
        r2 = reliability.run_guarded("t", lambda: (_ for _ in ()).throw(RuntimeError("sqlite database is locked while two workers write")), retries=1, backoff=0.01)
        self.assertEqual(r2["attempts"], 2)  # locked database is transient: retried once
        self.assertEqual(r2["problem"], "COD-007")

    def test_keyboard_interrupt_is_not_swallowed(self):
        with self.assertRaises(KeyboardInterrupt):
            reliability.run_guarded("t", lambda: (_ for _ in ()).throw(KeyboardInterrupt()))

    def test_resilient_decorator_default_and_structure(self):
        @reliability.resilient("x", default=[])
        def boom():
            raise ValueError("bad")

        @reliability.resilient("y")
        def boom2():
            raise ValueError("bad")
        self.assertEqual(boom(), [])
        out = boom2()
        self.assertFalse(out["ok"])
        self.assertIn("next_action", out)

    def test_faults_are_recorded_for_learning(self):
        reliability.run_guarded("recorder", lambda: 1 / 0, retries=0)
        sp = reliability._get_spine()
        n = sp.db.execute("SELECT COUNT(*) c FROM occurrences WHERE source='runtime:recorder'").fetchone()["c"]
        self.assertEqual(n, 1)
        self.assertTrue(paths.AUDIT_LOG.exists())


def sqlite3_locked():
    import sqlite3
    return sqlite3.OperationalError("database is locked")


class ChaosEntryPoints(Sandbox):
    def setUp(self):
        super().setUp()
        reliability._spine = None
        self.b = self.brain()
        from nexen import brain as bm
        bm.set_brain(self.b)

    def tearDown(self):
        from nexen import brain as bm
        bm.set_brain(None)
        super().tearDown()

    def test_app_methods_degrade_instead_of_raising(self):
        app = core.App(Ledger())
        saved = nexen_conn.NexenCore.tasks
        nexen_conn.NexenCore.tasks = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone"))
        try:
            self.assertEqual(app.timeline(5), [])  # list default
            self.assertIsInstance(app.board(), dict)
        finally:
            nexen_conn.NexenCore.tasks = saved
        app.harvest_vault = reliability.resilient("hv")(lambda: (_ for _ in ()).throw(OSError("F: unreadable")))
        self.assertFalse(app.harvest_vault()["ok"])

    def test_n8n_op_fault_is_structured_and_retried(self):
        n = {"calls": 0}

        def boom(*a, **k):
            n["calls"] += 1
            raise ConnectionError("connection reset")
        self.b.rules.check = boom
        r = api_spine.n8n(self.b, {"op": "rules_check", "action": {"type": "post"}})
        self.assertFalse(r["ok"])
        self.assertTrue(r["degraded"])
        self.assertTrue(r["next_action"])
        self.assertEqual(n["calls"], 2)  # one retry for a transient fault

    def test_server_fault_returns_json_and_stays_up(self):
        from http.server import ThreadingHTTPServer
        from nexen.server import Handler
        saved = Handler.api_get
        Handler.api_get = lambda self, path, q: (_ for _ in ()).throw(RuntimeError("sqlite database is locked while two workers write the ledger"))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            try:
                urllib.request.urlopen(base + "/api/status", timeout=10)
                self.fail("expected 500")
            except urllib.error.HTTPError as e:
                body = json.loads(e.read())
                self.assertEqual(e.code, 500)
                self.assertEqual(body["problem"], "COD-007")
                self.assertTrue(body["next_action"])
            Handler.api_get = saved
            self.assertEqual(urllib.request.urlopen(base + "/api/health", timeout=10).status, 200)  # still serving
        finally:
            Handler.api_get = saved
            httpd.shutdown()
            httpd.server_close()

    def test_mcp_error_path_says_what_to_do(self):
        saved = mcp_server.call
        mcp_server.call = lambda name, a: (_ for _ in ()).throw(RuntimeError("sqlite database is locked"))
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nexen_status", "arguments": {}}})]
        old_in, buf = sys.stdin, io.StringIO()
        sys.stdin = io.StringIO("\n".join(lines) + "\n")
        try:
            with redirect_stdout(buf):
                mcp_server.run()
        finally:
            sys.stdin = old_in
            mcp_server.call = saved
        msg = json.loads(buf.getvalue().splitlines()[-1])["result"]
        self.assertTrue(msg["isError"])
        self.assertIn("next action", msg["content"][0]["text"])

    def test_cli_never_prints_a_traceback(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = cli.main(["learn", "undo"])  # missing argument
        self.assertEqual(code, 1)
        self.assertIn("next action", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_loop_tick_survives_a_crashing_cycle(self):
        saved = autonomy.cycle
        autonomy.cycle = lambda app, deep=False: (_ for _ in ()).throw(RuntimeError("boom in cycle"))
        try:
            autonomy.tick(self.b.app)  # must not raise
            self.assertTrue(any("loop:" in e for e in autonomy.status()["errors"]))
        finally:
            autonomy.cycle = saved

    def test_ensure_alive_restarts_a_dead_loop(self):
        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join()
        autonomy._thread = dead
        autonomy._stop.clear()
        self.assertTrue(autonomy.ensure_alive(self.b.app))
        self.assertTrue(autonomy._thread.is_alive())
        autonomy.stop()
        autonomy._thread.join(25)
        autonomy._stop.clear()


class Doctor(Sandbox):
    def test_doctor_repairs_search_index_and_corrupt_config(self):
        led = Ledger(paths.DATA / "learning.db")
        app = core.App(led)
        app.novel.ingest({"text": "The recovery python runs the whole V4 suite of tests and reports 99 passes today.", "source_ids": ["test:doc"]})
        with led.lock:
            led.db.execute("DELETE FROM items_fts")
            led.db.commit()
        (paths.DATA / "rules.json").write_text("{not json", encoding="utf-8")
        r = reliability.doctor(fix=True)
        names = {c["name"]: c for c in r["checks"]}
        self.assertTrue(names["learning search index matches items"]["fixed"])
        self.assertTrue(names["rules.json parses"]["fixed"])
        self.assertTrue(any(p.name.startswith("rules.json.corrupt-") for p in paths.DATA.iterdir()))
        self.assertTrue(names["identity JARVIS = MARVIN"]["ok"])
        self.assertEqual(len(app.novel.recall("recovery python suite", k=2)), 1)  # recall works again after the repair
        r2 = reliability.doctor(fix=False)
        self.assertTrue({c["name"]: c for c in r2["checks"]}["learning search index matches items"]["ok"])
        led.close()  # release the file so Windows can delete the sandbox


if __name__ == "__main__":
    unittest.main()

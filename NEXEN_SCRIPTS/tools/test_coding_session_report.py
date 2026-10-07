import argparse
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import coding_session_report as csr

class CodingSessionReportTests(unittest.TestCase):
    def make_db(self, root: Path, lease=None) -> Path:
        db = root / "nexen.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE hub_requests(id INTEGER PRIMARY KEY, text TEXT, status TEXT)")
        con.execute("""CREATE TABLE task_history(
            id INTEGER PRIMARY KEY, request_id INTEGER, old_status TEXT, new_status TEXT,
            outcome TEXT, reminder_date TEXT, created_at TEXT)""")
        con.execute("""CREATE TABLE coding_implementation_lease(
            singleton INTEGER PRIMARY KEY, token TEXT, owner TEXT, task_id INTEGER,
            scope TEXT, expires_at REAL)""")
        con.execute("INSERT INTO hub_requests VALUES(142,'V3 core','in_progress')")
        con.execute("INSERT INTO hub_requests VALUES(152,'MARVIN training','in_progress')")
        con.execute(
            "INSERT INTO task_history VALUES(1,142,'in_progress','in_progress','fixture history',NULL,'2026-09-30T00:00:00Z')"
        )
        if lease:
            con.execute(
                "INSERT INTO coding_implementation_lease VALUES(1,'x',?,?,?,?)",
                (lease["owner"], 142, lease["scope"], lease["expires_at"]),
            )
        con.commit()
        con.close()
        return db

    def args(self, root: Path, db: Path, **overrides):
        desktop = root / "Desktop" / "MARVIN" / "Reports"
        values = dict(
            mode="session", agent="Codex", topic="nexen-ops", title="fixture session",
            next_step="continue task 142", db=str(db), session_log=str(root / "SESSION-LOG.md"),
            worktree=str(root / "worktree"), pc2_root=str(root / "pc2"),
            desktop_dir=str(desktop), h_report_root=str(root / "h-reports"), hourly_dir="",
        )
        values.update(overrides)
        return argparse.Namespace(**values)
    def test_free_lease_writes_latest_daily_archive_and_h_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self.make_db(root)
            (root / "SESSION-LOG.md").write_text("## session\n- Did: fixture\n", encoding="utf-8")
            result = csr.generate_report(self.args(root, db))
            latest = Path(result["latest"])
            self.assertTrue(latest.exists())
            self.assertTrue(Path(result["daily"]).exists())
            self.assertTrue(Path(result["archive"]).exists())
            self.assertTrue(Path(result["h_receipt"]).exists())
            text = latest.read_text(encoding="utf-8")
            self.assertIn("IMPLEMENTATION LEASE | FREE", text)
            self.assertIn("#142 [in_progress] V3 core", text)
            self.assertIn("SESSION LOG TAIL", text)

    def test_active_lease_is_a_collision_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self.make_db(
                root,
                lease={"owner": "other-worker", "scope": "owned-files", "expires_at": time.time() + 300},
            )
            result = csr.generate_report(self.args(root, db))
            text = Path(result["latest"]).read_text(encoding="utf-8")
            self.assertIn("IMPLEMENTATION LEASE | ACTIVE", text)
            self.assertIn("owner=other-worker", text)
            self.assertIn("do not start overlapping implementation", text)

    def test_hourly_operational_snapshot_redacts_connection_details(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self.make_db(root)
            desktop = root / "Desktop" / "MARVIN" / "Reports"
            desktop.mkdir(parents=True)
            (desktop / "NEXEN-V3-HOURLY-20260930-2000.txt").write_text(
                "PROOF PASS | PC2 DESKTOP-ABC123 at 192.168.77.5 via \\\\DESKTOP-ABC123\\NEXENPC2\\results\n"
                "NEXT | verify PC2 receipt\n",
                encoding="utf-8",
            )
            result = csr.generate_report(self.args(root, db))
            text = Path(result["latest"]).read_text(encoding="utf-8")
            self.assertNotIn("192.168.77.5", text)
            self.assertNotIn("DESKTOP-ABC123", text)
            self.assertNotIn("\\\\DESKTOP-ABC123", text)
            self.assertIn("[network address redacted]", text)
            self.assertIn("PC2/worker host", text)
    def test_missing_sources_still_produce_status_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing_db = root / "missing.db"
            result = csr.generate_report(self.args(root, missing_db))
            text = Path(result["latest"]).read_text(encoding="utf-8")
            self.assertIn("IMPLEMENTATION LEASE | UNAVAILABLE", text)
            self.assertIn("PC2 STATUS", text)
            self.assertIn("LATEST NEXEN/MARVIN OPS SNAPSHOT | UNAVAILABLE", text)

    def test_session_log_uses_actual_file_tail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self.make_db(root)
            log = root / "SESSION-LOG.md"
            log.write_text(("old line\n" * 20000) + "TAIL-MARKER\n", encoding="utf-8")
            result = csr.generate_report(self.args(root, db))
            text = Path(result["latest"]).read_text(encoding="utf-8")
            self.assertIn("TAIL-MARKER", text)

    def test_daily_mode_does_not_create_session_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self.make_db(root)
            result = csr.generate_report(self.args(root, db, mode="daily", agent="MARVIN", title="daily guard"))
            self.assertEqual(result["archive"], "")
            self.assertTrue(Path(result["daily"]).exists())
            self.assertTrue(Path(result["latest"]).exists())

if __name__ == "__main__":
    unittest.main()

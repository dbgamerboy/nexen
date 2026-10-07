"""Reads must not queue behind a writer; handlers share one threadpool."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_support import fixture_root, load_core_definitions

DB = load_core_definitions().DB


class ReadUnderWriteLockTests(unittest.TestCase):
    """A blocked read holds a worker thread and starves every other route."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=fixture_root())
        self.addCleanup(self.temporary.cleanup)
        self.db = DB(str(Path(self.temporary.name) / 'nexen.db'))
        with self.db.connect() as c:
            c.execute("INSERT INTO events(level,event_type,message,data_json,created_at)"
                      " VALUES('INFO','fixture','probe','{}','2026-09-10T00:00:00+00:00')")

    def test_journal_mode_is_wal(self):
        with self.db.reading() as c:
            self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')

    def test_read_returns_while_a_writer_holds_the_database(self):
        held, release = threading.Event(), threading.Event()

        def writer():
            w = sqlite3.connect(self.db.path, timeout=30, isolation_level=None)
            try:
                w.execute('BEGIN IMMEDIATE')
                w.execute("INSERT INTO events(level,event_type,message,data_json,created_at)"
                          " VALUES('INFO','fixture','held','{}','2026-09-10T00:00:00+00:00')")
                held.set()
                release.wait(20)
                w.execute('ROLLBACK')
            finally:
                w.close()

        thread = threading.Thread(target=writer, daemon=True, name='fixture-writer')
        thread.start()
        self.addCleanup(thread.join, 25)
        self.addCleanup(release.set)
        self.assertTrue(held.wait(10), 'fixture writer never took its lock')

        started = time.monotonic()
        count = self.db.scalar('SELECT count(*) FROM events')
        waited = time.monotonic() - started
        release.set()

        self.assertIsNotNone(count)
        # The previous read path opened a read-write connection with a 30s busy
        # timeout, so this waited for the writer instead of returning.
        self.assertLess(waited, 2.0, 'read queued behind the writer: %.2fs' % waited)

    def test_reads_cannot_write(self):
        with self.db.reading() as c:
            with self.assertRaises(sqlite3.OperationalError):
                c.execute("INSERT INTO events(level,event_type,message,data_json,created_at)"
                          " VALUES('INFO','x','y','{}','2026-09-10T00:00:00+00:00')")


if __name__ == '__main__':
    unittest.main()

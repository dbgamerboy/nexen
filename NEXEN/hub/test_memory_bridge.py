"""Retrieval must wait for the live knowledge writer, not drop file excerpts."""
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import memory_bridge as m
from test_support import fixture_root


class ReadOnlyIndexTests(unittest.TestCase):
    """The knowledge index is written continuously while retrieval reads it."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=fixture_root())
        self.addCleanup(self.temporary.cleanup)
        self.db = Path(self.temporary.name) / 'index.sqlite3'
        # sqlite3's context manager ends the transaction but keeps the handle
        # open, and Windows will not delete a file that still has one.
        setup = sqlite3.connect(self.db)
        try:
            setup.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY, text TEXT)')
            setup.execute("INSERT INTO chunks(text) VALUES ('indexed excerpt')")
            setup.commit()
        finally:
            setup.close()

    def test_busy_timeout_outlives_the_window_that_reported_the_index_unavailable(self):
        with m.readonly(self.db) as c:
            self.assertGreaterEqual(c.execute('PRAGMA busy_timeout').fetchone()[0],
                                    m.READ_TIMEOUT_SECONDS * 1000)

    def test_read_waits_for_a_holding_writer_rather_than_raising(self):
        held, release = threading.Event(), threading.Event()

        def writer():
            w = sqlite3.connect(self.db, timeout=30, isolation_level=None)
            try:
                w.execute('BEGIN EXCLUSIVE')
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

        # Hold past the previous three-second window, well inside the new one.
        threading.Timer(4.0, release.set).start()
        started = time.monotonic()
        with m.readonly(self.db) as c:
            rows = c.execute('SELECT text FROM chunks').fetchall()
        waited = time.monotonic() - started

        self.assertEqual([r['text'] for r in rows], ['indexed excerpt'])
        self.assertGreater(waited, 3.0, 'the read did not actually wait behind the writer')

    def test_a_missing_index_is_still_reported_rather_than_waited_on(self):
        with self.assertRaises(FileNotFoundError):
            with m.readonly(Path(self.temporary.name) / 'absent.sqlite3'):
                pass


def _row(kind, source_id, text):
    return {'kind': kind, 'source_id': source_id, 'title': source_id, 'role': 'source',
            'text': text, 'ts': '2026-09-09T00:00:00+00:00', 'provenance': []}


class ExcerptBudgetTests(unittest.TestCase):
    """A matched source dropped for space must not read as a source that does not exist."""

    def setUp(self):
        self.memory = m.SharedMemory(context_policy=None)

    def _packet(self, **kwargs):
        with patch.object(m.SharedMemory, '_search_exports', return_value=[]), \
             patch.object(m.SharedMemory, '_search_notes',
                          return_value=[_row('manual_note', 'note-' + 'a' * 24, 'rent ' * 4000)]), \
             patch.object(m.SharedMemory, '_search_knowledge',
                          return_value=[_row('knowledge', 'chunk-1', 'rent assistance ' * 400)]), \
             patch.object(m.SharedMemory, '_search_completions', return_value=[]):
            return self.memory.build_context('rent', **kwargs)

    def test_budget_omission_is_named_instead_of_silently_dropped(self):
        packet = self._packet(max_chars=2000, limit=5)
        self.assertTrue(any('excerpt budget ended' in w for w in packet['warnings']),
                        'a dropped source was not reported: ' + repr(packet['warnings']))
        self.assertIn('knowledge', ' '.join(packet['warnings']))
        self.assertEqual(packet['status'], 'degraded')

    def test_a_sufficient_budget_reports_no_omission(self):
        packet = self._packet(max_chars=20000, limit=5)
        self.assertEqual([w for w in packet['warnings'] if 'excerpt budget' in w], [])
        self.assertIn('knowledge', [c['kind'] for c in packet['citations']])


if __name__ == '__main__':
    unittest.main()

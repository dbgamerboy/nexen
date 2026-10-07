"""Deadline regressions use real SQLite work, all fixture writes stay on H:."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import memory_bridge as memory
from probe_deadline import SQL

ROOT = Path(__file__).resolve().parent


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT, prefix='fixture-')
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'index.sqlite3'
        connection = sqlite3.connect(self.path)
        connection.execute('CREATE TABLE marker(id INTEGER)')
        connection.close()

    def test_real_expensive_read_is_cancelled_in_a_bounded_subprocess(self):
        try:
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'probe_deadline.py'),
                                     '--child', str(self.path)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=0.8)
        except subprocess.TimeoutExpired:
            self.fail('SQLite execution ignored the 0.05-second read budget')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        event = json.loads(result.stdout)
        self.assertEqual(event['result'], 'ReadDeadlineExceeded')
        self.assertLess(event['seconds'], 0.5)

    def test_each_expensive_pool_warns_while_healthy_note_is_retained(self):
        try:
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()),
                                     '--pools', str(self.path)], cwd=ROOT,
                                    capture_output=True, text=True, timeout=1.5)
        except subprocess.TimeoutExpired:
            self.fail('build_context failed to return after a database pool exceeded its budget')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet['status'], 'degraded')
        self.assertEqual(len(packet['warnings']), 3)
        for pool in ('Conversation index', 'Knowledge chunk index', 'Local completion history'):
            self.assertTrue(any(pool in warning and 'read time budget' in warning
                                for warning in packet['warnings']), packet['warnings'])
        self.assertEqual([item['source_id'] for item in packet['citations']], ['note-' + 'a' * 24])

    def test_normal_read_stays_read_only_and_connection_closes(self):
        with memory.readonly(self.path) as connection:
            self.assertEqual(connection.execute('SELECT 42').fetchone()[0], 42)
            with self.assertRaises(sqlite3.OperationalError) as raised:
                connection.execute('INSERT INTO marker VALUES (1)')
            self.assertNotIsInstance(raised.exception, memory.ReadDeadlineExceeded)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')
        check = sqlite3.connect(self.path)
        try:
            self.assertEqual(check.execute('SELECT count(*) FROM marker').fetchone()[0], 0)
        finally:
            check.close()

    def test_missing_index_keeps_unavailable_warning(self):
        instance = memory.SharedMemory(context_policy=None)
        with patch.object(instance, '_search_exports', side_effect=FileNotFoundError), \
             patch.object(instance, '_search_knowledge', return_value=[]), \
             patch.object(instance, '_search_notes', return_value=[]), \
             patch.object(instance, '_search_completions', return_value=[]):
            packet = instance.build_context('deadline')
        self.assertEqual(packet['warnings'], [
            'Conversation index is unavailable; no export excerpts were loaded.'])


def pool_child(path):
    class ExpensivePools(memory.SharedMemory):
        def expensive(self, terms, limit):
            with memory.readonly(path, max_seconds=memory.CONTEXT_READ_TIMEOUT_SECONDS) as connection:
                connection.execute(SQL).fetchone()
            return []

        _search_exports = expensive
        _search_knowledge = expensive
        _search_completions = expensive

        def _search_notes(self, terms, limit):
            return [{'kind': 'manual_note', 'source_id': 'note-' + 'a' * 24,
                     'title': 'deadline fixture', 'role': 'source', 'text': 'deadline evidence',
                     'ts': '2026-09-13', 'provenance': []}]

    memory.READ_TIMEOUT_SECONDS = 0.05
    memory.CONTEXT_READ_TIMEOUT_SECONDS = 0.05
    packet = ExpensivePools(context_policy=None).build_context('deadline', max_chars=16000)
    print(json.dumps({key: packet[key] for key in ('warnings', 'status', 'citations')}))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--pools':
        pool_child(sys.argv[2])
    else:
        unittest.main()

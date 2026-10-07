import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_support import fixture_root
import v2_runtime as v2


class V2RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=fixture_root())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_stale_and_future_heartbeats_cannot_pass(self):
        path = self.write('receipt.json', {'checked_at': '2026-09-13T00:00:00+00:00'})
        now = 1789257600
        self.assertTrue(v2.receipt(path, 90, now)['_fresh'])
        self.assertFalse(v2.receipt(path, 90, now + 91)['_fresh'])
        self.assertFalse(v2.receipt(path, 90, now - 20)['_fresh'])

    def test_missing_database_is_not_created(self):
        path = self.root / 'missing.db'
        self.assertEqual(v2.automation_state(path), {})
        self.assertFalse(path.exists())

    def test_missing_or_oversized_receipt_is_unavailable(self):
        self.assertEqual(v2.receipt(self.root / 'missing.json'), {})
        path = self.write('oversized.json', {'detail': 'x' * 65537})
        self.assertEqual(v2.receipt(path), {})

    def test_branding_cannot_mark_incomplete_release_operational(self):
        self.write('startup-v2.json', {'installed': True})
        with patch.object(v2, 'automation_state', return_value={'enabled': 1, 'ticks_completed': 200, 'last_finished': 100}):
            status = v2.snapshot(state=self.root, base=self.root, now=101)
        self.assertEqual(status['version'], 'V2')
        self.assertEqual(status['status'], 'needs_attention')
        self.assertFalse(next(x for x in status['checks'] if x['id'] == 'automations')['ready'])

    def test_operational_requires_live_worker_and_voice(self):
        now = 1789257600
        stamp = '2026-09-13T00:00:00+00:00'
        self.write('startup-v2.json', {'installed': True})
        self.write('discord-v2.json', {'checked_at': stamp, 'connected': True, 'voice_connected': True, 'secret': 'never-return',
                                     'self_muted': False, 'self_deafened': False, 'server_muted': False, 'server_deafened': False})
        self.write('discord-client-v2.json', {'checked_at': stamp, 'connected': True, 'auto_join_verified': True})
        mode = SimpleNamespace(running=lambda: True, gate_from_state=lambda enabled: 'ready')
        app = SimpleNamespace(state=SimpleNamespace(automatic_mode=mode))
        automatic = {'enabled': 1, 'ticks_completed': 2, 'last_finished': now,
                     'last_succeeded': now, 'last_outcome': 'success'}
        with patch.object(v2, 'automation_state', return_value=automatic):
            for hub in ('healthy_owned', 'healthy_attached'):
                self.write('data/watchdog/status.json', {'heartbeat_at': stamp, 'hub': hub})
                status = v2.snapshot(app, self.root, self.root, now)
                self.assertEqual(status['status'], 'operational')
                self.assertNotIn('never-return', json.dumps(status))
                stale = v2.snapshot(app, self.root, self.root, now + 121)
                self.assertEqual(stale['status'], 'needs_attention')

    def test_bot_connection_cannot_verify_the_desktop_user(self):
        self.write('discord-v2.json', {'checked_at': '2026-09-13T00:00:00+00:00',
                   'connected': True, 'voice_connected': True, 'self_muted': False,
                   'self_deafened': False, 'server_muted': False, 'server_deafened': False})
        status = v2.snapshot(state=self.root, base=self.root, now=1789257600)
        checks = {x['id']: x['ready'] for x in status['checks']}
        self.assertTrue(checks['discord'])
        self.assertFalse(checks['desktop_voice'])

    def test_failed_or_unverified_pass_cannot_inherit_historical_success(self):
        mode = SimpleNamespace(running=lambda: True, gate_from_state=lambda enabled: 'ready')
        app = SimpleNamespace(state=SimpleNamespace(automatic_mode=mode))
        for outcome, succeeded in [('failed', 100), (None, None), ('success', 100)]:
            automatic = {'enabled': 1, 'ticks_completed': 42, 'ticks_failed': 3,
                         'last_finished': 110, 'last_succeeded': succeeded, 'last_outcome': outcome}
            with patch.object(v2, 'automation_state', return_value=automatic):
                status = v2.snapshot(app, self.root, self.root, now=111)
            ready = next(x['ready'] for x in status['checks'] if x['id'] == 'automations')
            self.assertEqual(ready, outcome == 'success')

    def test_muted_or_unverified_voice_is_not_ready(self):
        flags = ('self_muted', 'self_deafened', 'server_muted', 'server_deafened')
        base = {'checked_at': '2026-09-13T00:00:00+00:00', 'connected': True,
                'voice_connected': True, **dict.fromkeys(flags, False)}
        for flag in flags:
            for value in (True, None):
                self.write('discord-v2.json', {**base, flag: value})
                status = v2.snapshot(state=self.root, base=self.root, now=1789257600)
                self.assertFalse(next(x['ready'] for x in status['checks'] if x['id'] == 'discord'))

    def test_snapshot_passes_bounded_state_to_gate_without_second_database_read(self):
        observed = []
        mode = SimpleNamespace(running=lambda: True,
                               gate_from_state=lambda enabled: observed.append(enabled) or 'ready')
        app = SimpleNamespace(state=SimpleNamespace(automatic_mode=mode))
        with patch.object(v2, 'automation_state', return_value={'enabled': 0}):
            v2.snapshot(app, self.root, self.root, now=100)
        self.assertEqual(observed, [0])

    def test_busy_database_returns_unavailable_within_short_deadline(self):
        path = self.root / 'busy.sqlite'
        with closing(sqlite3.connect(path)) as writer:
            writer.execute('''CREATE TABLE automatic_mode_state(id INTEGER,enabled INTEGER,
                ticks_completed INTEGER,ticks_failed INTEGER,last_finished REAL,
                last_succeeded REAL,last_outcome TEXT)''')
            writer.commit()
            writer.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            self.assertEqual(v2.automation_state(path), {})
            self.assertLess(time.monotonic() - started, 2)


if __name__ == '__main__':
    unittest.main()

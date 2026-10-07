"""Native game boundary checks. Every game process launch is mocked."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import FastAPI, HTTPException
import app_auth
import game_native as game
from test_support import fixture_root


class NativeGameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='game-native-', dir=fixture_root())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / 'Dolphin.exe'
        self.exe.write_bytes(b'fixture only; never executed')
        self.games = tuple(game.NativeGame(x.id, x.name, self.exe, x.setup_url) for x in game.GAMES)
        for key, value in [('GAMES', self.games), ('GAME_BY_ID', {x.id: x for x in self.games}), ('DOLPHIN_ROOT', self.root / 'dolphin')]:
            item = patch.object(game, key, value)
            item.start()
            self.addCleanup(item.stop)
        self.db = SimpleNamespace(event=Mock(), rows=Mock(return_value=[]))
        self.process = SimpleNamespace(pid=4242, poll=Mock(return_value=None))
        self.spawn = Mock(return_value=self.process)
        self.running = Mock(return_value=False)
        self.clock = 100.
        self.controller = game.NativeGames(self.db, spawn=self.spawn, clock=lambda: self.clock, running=self.running)

    def error(self, status, call):
        with self.assertRaises(HTTPException) as caught:
            call()
        self.assertEqual(caught.exception.status_code, status)
        return caught.exception

    def test_setup_blockers_override_existing_executables(self):
        for ident in ('halo', 'playnite'):
            state = game.game_status(game.GAME_BY_ID[ident])
            self.assertTrue(state['installed'])
            self.assertFalse(state['launch_ready'])
            self.assertTrue(any('H/F' in x for x in state['blockers']))
            self.error(409, lambda: self.controller.launch(ident))
        self.spawn.assert_not_called()
        self.db.event.assert_not_called()

    def test_dolphin_fixed_args_hf_storage_and_log_before_spawn(self):
        order = []
        self.db.event.side_effect = lambda name, *args, **kwargs: order.append(name)
        self.spawn.side_effect = lambda *args, **kwargs: (order.append('spawn') or self.process)
        result = self.controller.launch('dolphin')
        self.assertEqual(result['status'], 'launch_requested')
        self.assertEqual(order, ['game_launch_requested', 'spawn', 'game_launch_started'])
        self.assertEqual(self.spawn.call_args.args[0], [str(self.exe), '-u', str(self.root / 'dolphin/user')])
        options = self.spawn.call_args.kwargs
        self.assertFalse(options['shell'])
        for name in ('TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'XDG_CACHE_HOME'):
            self.assertTrue(Path(options['env'][name]).is_relative_to(self.root / 'dolphin'))
        self.assertFalse(result['storage']['third_party_write_confinement'])

    def test_status_is_read_only_and_missing_executable_disables_launch(self):
        self.assertTrue(game.game_status(game.GAME_BY_ID['dolphin'])['launch_ready'])
        self.assertFalse((self.root / 'dolphin').exists())
        self.exe.unlink()
        self.assertFalse(game.game_status(game.GAME_BY_ID['dolphin'])['installed'])
        self.error(409, lambda: self.controller.launch('dolphin'))
        self.spawn.assert_not_called()

    def test_offdrive_profile_fails_closed(self):
        with patch.object(game, 'DOLPHIN_ROOT', Path('C:/must-not-create-game-profile')):
            self.assertFalse(game.game_status(game.GAME_BY_ID['dolphin'])['launch_ready'])
            self.error(409, lambda: self.controller.launch('dolphin'))
        self.spawn.assert_not_called()

    def test_audit_failure_precedes_environment_writes(self):
        self.db.event.side_effect = sqlite3.OperationalError('fixture only')
        with patch.object(game, 'tool_environment') as environment:
            self.error(503, lambda: self.controller.launch('dolphin'))
            environment.assert_not_called()
        self.spawn.assert_not_called()
        self.assertFalse((self.root / 'dolphin').exists())

    def test_external_process_and_unavailable_probe_block_launch(self):
        self.running.return_value = True
        self.error(409, lambda: self.controller.launch('dolphin'))
        self.running.side_effect = OSError('fixture process check')
        self.error(409, lambda: self.controller.launch('dolphin'))
        self.spawn.assert_not_called()
        self.assertIsNone(self.controller.last_launch)

    def test_owned_process_then_cooldown_then_reopen(self):
        self.controller.launch('dolphin')
        self.error(409, lambda: self.controller.launch('dolphin'))
        self.process.poll.return_value = 0
        self.assertIn('Retry-After', self.error(429, lambda: self.controller.launch('dolphin')).headers)
        self.clock += 31
        self.controller.launch('dolphin')
        self.assertEqual(self.spawn.call_count, 2)

    def test_environment_failure_and_spawn_failure_are_recorded(self):
        with patch.object(game, 'tool_environment', side_effect=OSError('fixture')):
            self.error(409, lambda: self.controller.launch('dolphin'))
        self.spawn.assert_not_called()
        self.assertEqual(self.db.event.call_args.args[0], 'game_launch_blocked')
        self.spawn.side_effect = OSError('fixture')
        self.error(502, lambda: self.controller.launch('dolphin'))
        self.assertEqual(self.db.event.call_args.args[0], 'game_launch_failed')

    def test_followup_log_failure_does_not_lose_launch_result(self):
        self.db.event.side_effect = [None, sqlite3.OperationalError('fixture')]
        self.assertIn('audit_warning', self.controller.launch('dolphin'))
        self.assertEqual(self.spawn.call_count, 1)

    def test_routes_require_local_origin_fixed_body_and_action_header(self):
        app = FastAPI()
        controller = game.register(app, self.db)
        controller.spawn, controller.running = self.spawn, self.running

        async def scenario():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 9000)), base_url='http://127.0.0.1:8788') as client:
                for headers in ({}, {'Origin':'https://outside.invalid','X-Nexen-Action':'launch'}, [('Origin','http://127.0.0.1:8788'),('Origin','http://127.0.0.1:8788'),('X-Nexen-Action','launch')]):
                    self.assertEqual((await client.post('/api/game/native/launch', json={'id':'dolphin'}, headers=headers)).status_code, 403)
                headers = {'Origin':'http://127.0.0.1:8788','X-Nexen-Action':'launch'}
                for body in ({'id':'dolphin','args':['unsafe']}, {'id':'arbitrary'}, {'id':'dolphin','executable':'other.exe'}):
                    self.assertEqual((await client.post('/api/game/native/launch', json=body, headers=headers)).status_code, 422)
                self.assertEqual((await client.post('/api/game/native/launch', json={'id':'halo'}, headers=headers)).status_code, 409)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=('192.0.2.1',9000)), base_url='http://127.0.0.1:8788') as client:
                self.assertEqual((await client.get('/api/game/native/status')).status_code,403)
        asyncio.run(scenario())
        self.spawn.assert_not_called()

    def test_actual_password_gate_locks_both_game_routes_and_service_key(self):
        from starlette.requests import Request
        with patch.object(app_auth, 'AuthStore') as factory:
            factory.return_value.valid.return_value = False
            factory.return_value.service_key = 'x' * 64
            gate = app_auth.register(FastAPI())
        for path, method in [('/api/game/native/status','GET'),('/api/game/native/launch','POST')]:
            request = Request({'type':'http','scheme':'http','server':('127.0.0.1',8788),'path':path,'query_string':b'','method':method,'headers':[(b'x-nexen-service',b'x'*64)]})
            self.assertEqual(gate(request).status_code,401)

    def test_pc2_never_returns_private_configuration_or_truthy_strings(self):
        for value, expected in [(True,'online'),(False,'offline'),('192.0.2.42','unknown'),(None,'unknown')]:
            readiness = SimpleNamespace(connection_snapshot=lambda: {'pc2':value,'hostname':'private-fixture','address':'192.0.2.42','key':'secret-fixture'})
            result = game.pc2_status(readiness)
            self.assertEqual(result['status'],expected)
            for private in ('private-fixture','192.0.2.42','secret-fixture'):
                self.assertNotIn(private,json.dumps(result))

    def test_automation_cards_use_saved_counts_and_fresh_watchdog_only(self):
        now = 1789000000.
        stamp = lambda age: datetime.fromtimestamp(now-age,timezone.utc).isoformat()
        receipt = self.root / 'watchdog.json'
        self.db.rows.return_value = [{'status':'running','count':2,'updated_at':stamp(30)},{'status':'done','count':7,'updated_at':stamp(40)}]
        receipt.write_text(json.dumps({'heartbeat_at':stamp(15),'last_hub_ok_at':stamp(15),'hub':'healthy_owned','private_field':'do not display'}))
        cards = game.automation_cards(self.db,receipt,now)
        self.assertEqual(len(cards),2)
        self.assertEqual([x['status'] for x in cards],['reported_running','running'])
        self.assertIn('7 done',cards[0]['detail'])
        self.assertNotIn('do not display',json.dumps(cards))
        self.db.rows.return_value[0]['updated_at'] = stamp(601)
        receipt.write_text(json.dumps({'heartbeat_at':stamp(91),'last_hub_ok_at':stamp(15),'hub':'healthy_owned'}))
        self.assertEqual([x['status'] for x in game.automation_cards(self.db,receipt,now)],['stale','stale'])
        receipt.write_text('{corrupt')
        self.assertEqual(game.automation_cards(self.db,receipt,now)[1]['status'],'unavailable')

    def test_focus_classifies_only_known_paths_and_never_returns_titles(self):
        native = SimpleNamespace(GetForegroundWindow=Mock(return_value=1), GetWindowThreadProcessId=Mock(return_value=1))
        for path, expected in [(next(p for p, ident in game.FOREGROUND_PATHS.items() if ident=='halo'),'halo'),('F:\\fixture\\HaloInfinite.exe',None)]:
            with patch.object(game,'windows_api',return_value=(None,native,None)), patch.object(game,'process_image',return_value=path):
                result = game.foreground_status()
            self.assertEqual(result,{'supported':True,'game_id':expected,'halo_focused':expected=='halo'})
        with patch.object(game,'windows_api',side_effect=OSError('fixture')):
            self.assertFalse(game.foreground_status()['supported'])


if __name__ == '__main__':
    unittest.main()

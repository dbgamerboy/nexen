import json
import shutil
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from everything_runtime import Everything, format_cli, scan_code_inventory
from nexen_everything import LocalReadiness, ReadOnlyDB
from task_tracking import TaskCreate, Tracker
from test_support import fixture_root, load_core_definitions


class Catalog:
    def __init__(self, cards=None):
        self.cards = cards or []

    def catalog(self, compact=False):
        return {'cards': self.cards, 'summary': {'states': {'draft': len(self.cards)},
                'families': {'source82': len(self.cards)}},
                'coverage': {'expected_source_rows': 82, 'live_n8n_queried': False,
                             'cloud_inventory_verified': False, 'errors': []}}


class BenefitCatalog:
    def __init__(self, resources):
        self.resources = resources

    def _catalog(self):
        return self.resources

    def profile(self):
        raise AssertionError('Everything must not load private benefits profile facts.')


class EverythingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture_root() / ('everything-' + uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.db = load_core_definitions().DB(str(self.root / 'state.sqlite3'))
        self.tracker = Tracker(self.db)
        self.tracker.create(TaskCreate(text='Open task', priority='high', next_step='Inspect CLI'))
        self.tracker.create(TaskCreate(text='Blocked task', priority='urgent', next_step='Owner step'),
                            initial_status='blocked')
        self.tracker.create(TaskCreate(text='Done task'), initial_status='done')

        self.base = self.root / 'app'
        (self.base / 'src').mkdir(parents=True)
        (self.base / 'data').mkdir()
        (self.base / 'vendor').mkdir()
        (self.base / '.git').mkdir()
        (self.base / 'src' / 'worker.py').write_text('value = 1\n', encoding='utf-8')
        (self.base / 'src' / 'test_worker.py').write_text('assert True\n', encoding='utf-8')
        (self.base / 'src' / 'start.cmd').write_text('@echo off\n', encoding='utf-8')
        (self.base / 'data' / 'hidden.py').write_text('secret = True\n', encoding='utf-8')
        (self.base / 'vendor' / 'third_party.py').write_text('third_party = True\n', encoding='utf-8')
        (self.base / '.git' / 'hook.py').write_text('git_data = True\n', encoding='utf-8')

        self.capabilities = self.root / 'capabilities.json'
        self.capabilities.write_text(json.dumps({'built_at': '2026-09-30', 'counts': {'repos': 2},
            'capabilities': [{'kind': 'cli', 'name': 'worker', 'lane': 'coding',
                              'status': 'registered', 'entry': 'H:/NEXEN/worker.cmd',
                              'evidence': 'file present'}]}), encoding='utf-8')
        self.pause = self.root / 'PAUSE_AUTONOMY'
        self.pause.write_text('maintenance', encoding='utf-8')
        self.report = self.root / 'proof.txt'
        self.report.write_text('REMAINING WORK / HONEST LIMITS\nStill open: PC2 execution; provider checks.\n\nOther text.', encoding='utf-8')

        with self.db.connect() as conn:
            conn.execute('CREATE TABLE benefit_resource_state(resource_id TEXT PRIMARY KEY, stage TEXT NOT NULL)')
            conn.execute("INSERT INTO benefit_resource_state(resource_id,stage) VALUES('rent','blocked')")
        self.app = SimpleNamespace(state=SimpleNamespace(
            workflow_workspace=Catalog([{'id': 'draft-1', 'name': 'Draft workflow', 'family': 'source82',
                'status': 'blocked', 'availability': 'Preparation only', 'workspace_url': '/workflows',
                'source_ids': [82], 'prerequisites': ['needs adapter']}]),
            benefits=BenefitCatalog([{'id': 'rent', 'name': 'Rent support', 'tags': ['housing']},
                                    {'id': 'bus', 'name': 'Transit support', 'tags': ['transport']}]),
            readiness=SimpleNamespace(packet=lambda: {'checked_at': '2026-09-30', 'verified_count': 1,
                'blocker_count': 1, 'execution_counts': {'HUMAN': 1}, 'coverage': 'Receipt-based.',
                'items': [{'id': 'nexen', 'title': 'NEXEN', 'status': 'service_reachable',
                          'verified': False, 'evidence': 'Port only.'}]})
        ), routes=[SimpleNamespace(path='/', name='home', methods={'GET'}),
                   SimpleNamespace(path='/api/tasks', name='tasks', methods={'GET'}),
                   SimpleNamespace(path='/workflows/{workflow_id}', name='details', methods={'GET'})])
        self.service = Everything(self.app, self.db, base=self.base,
            capabilities_path=self.capabilities, pause_marker=self.pause, report_path=self.report)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_snapshot_combines_shared_sources_without_private_benefits_facts(self):
        result = self.service.snapshot(offset=0, limit=2)
        self.assertEqual(result['schema'], 'nexen.everything.v1')
        self.assertEqual(result['tasks']['total'], 3)
        self.assertEqual(result['tasks']['counts'], {'blocked': 1, 'done': 1, 'planned': 1})
        self.assertEqual([task['text'] for task in result['tasks']['items']], ['Blocked task', 'Open task'])
        self.assertEqual(result['workflows']['total'], 1)
        self.assertEqual(result['benefits']['resources'], 2)
        self.assertEqual(result['benefits']['stages']['blocked'], 1)
        self.assertEqual(result['benefits']['stages']['ready'], 1)
        self.assertFalse(result['benefits']['applications_submitted_by_nexen'])
        self.assertFalse(result['benefits']['calls_or_emails_sent_by_nexen'])
        self.assertEqual(result['readiness']['verified_count'], 1)
        self.assertEqual(result['capabilities']['total'], 1)
        self.assertEqual(result['routes']['page_count'], 1)
        self.assertEqual(result['routes']['api_route_count'], 1)
        self.assertTrue(result['coverage']['automatic_source_scans_paused'])
        self.assertIn('PC2 execution', result['open_work_report']['text'])
        self.assertNotIn('private benefits profile', json.dumps(result).lower())

    def test_task_paging_clamps_bad_bounds(self):
        low = self.service.snapshot(offset=-10, limit=0)['tasks']
        self.assertEqual(low['offset'], 0)
        self.assertEqual(low['limit'], 1)
        high = self.service.snapshot(offset=0, limit=9000)['tasks']
        self.assertEqual(high['limit'], 500)

    def test_code_inventory_excludes_data_vendor_and_git(self):
        inventory = scan_code_inventory(self.base)
        self.assertEqual(inventory['total'], 3)
        self.assertEqual(inventory['by_extension'], {'.cmd': 1, '.py': 2})
        self.assertEqual(inventory['python_modules'], 1)
        self.assertEqual(inventory['python_tests'], 1)
        self.assertNotIn('data/hidden.py', inventory['files'])
        self.assertNotIn('vendor/third_party.py', inventory['files'])
        self.assertNotIn('.git/hook.py', inventory['files'])

    def test_missing_registries_fail_open_as_unavailable_without_crash(self):
        app = SimpleNamespace(state=SimpleNamespace(), routes=[])
        service = Everything(app, self.db, base=self.base,
            capabilities_path=self.root / 'missing.json', pause_marker=self.root / 'missing-pause',
            report_path=self.root / 'missing-report.txt')
        result = service.snapshot()
        self.assertEqual(result['workflows']['status'], 'unavailable')
        self.assertEqual(result['benefits']['status'], 'unavailable')
        self.assertEqual(result['readiness']['status'], 'unavailable')
        self.assertEqual(result['capabilities']['status'], 'unavailable')
        self.assertEqual(result['open_work_report']['status'], 'not_found')

    def test_cli_formats_human_and_json_snapshots(self):
        result = self.service.snapshot()
        human = format_cli(result)
        machine = json.loads(format_cli(result, as_json=True))
        self.assertIn('NEXEN EVERYTHING - read-only snapshot', human)
        self.assertIn('3 tracked', human)
        self.assertEqual(machine['schema'], 'nexen.everything.v1')
        self.assertNotIn('→', format_cli(result, as_json=True))

    def test_standalone_cli_database_wrapper_is_read_only(self):
        before = self.db.path.read_bytes()
        reader = ReadOnlyDB(self.db.path)
        self.assertEqual(reader.scalar('SELECT count(*) FROM hub_requests'), 3)
        self.assertEqual(len(reader.rows('SELECT id,status FROM hub_requests')), 3)
        self.assertEqual(self.db.path.read_bytes(), before)

    def test_readiness_marks_loopback_reachability_as_unverified(self):
        import socket
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            probe = LocalReadiness()
            probe.SERVICES = (('test', 'Synthetic listener', port),)
            result = probe.packet()
            self.assertTrue(result['items'][0]['endpoint_reachable'])
            self.assertFalse(result['items'][0]['verified'])
            self.assertIn('TCP reachability only', result['items'][0]['evidence'])
        finally:
            listener.close()


if __name__ == '__main__':
    unittest.main()

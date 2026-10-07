"""Read-only NEXEN-wide dashboard snapshot over existing local registries.

Opening this view never runs a workflow, submits a benefits application, contacts
anyone, changes a task, or launches a CLI. Unknown evidence stays unknown.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

BASE = Path(__file__).resolve().parent
CAPABILITIES = BASE / 'config' / 'capabilities.json'
PAUSE_MARKER = BASE / 'data' / 'PAUSE_AUTONOMY'
V3_REPORT = Path('H:/NEXEN/reports/v3-proof-20260930/NEXEN-V3-BUILD-AND-PROOF-20260930.txt')
CODE_EXTENSIONS = {'.py', '.ps1', '.cmd', '.bat', '.js', '.ts'}
SKIP_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'node_modules', 'vendor', 'data', 'fixtures'}


def scan_code_inventory(root=BASE):
    """Count code entry files under the active V1 app, without walking data or vendor trees."""
    root = Path(root)
    counts = Counter()
    files = []
    if not root.is_dir():
        return {'status': 'unavailable', 'by_extension': {}, 'python_tests': 0,
                'python_modules': 0, 'files': [], 'error': 'Active app directory is unavailable.'}
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name.lower() not in SKIP_DIRS and not name.startswith('.')]
        for name in names:
            path = Path(current) / name
            if path.is_symlink() or path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            suffix = path.suffix.lower()
            counts[suffix] += 1
            rel = path.relative_to(root).as_posix()
            files.append(rel)
    files.sort(key=str.lower)
    python_tests = sum(1 for name in files if Path(name).suffix.lower() == '.py' and
                       (Path(name).name.lower().startswith('test_') or Path(name).name.lower().endswith('_test.py')))
    return {'status': 'counted', 'root_scope': 'active_v1_app_only',
            'total': len(files), 'by_extension': dict(sorted(counts.items())),
            'python_tests': python_tests, 'python_modules': counts['.py'] - python_tests,
            'files': files,
            'excluded_directories': sorted(SKIP_DIRS)}


def _status_counts(items, key='status'):
    return dict(sorted(Counter(str(item.get(key) or 'unknown') for item in items).items()))


class Everything:
    """Read-only aggregation for the Everything page and NEXEN CLI."""

    def __init__(self, app, db, base=BASE, capabilities_path=CAPABILITIES,
                 pause_marker=PAUSE_MARKER, report_path=V3_REPORT):
        self.app = app
        self.db = db
        self.base = Path(base)
        self.capabilities_path = Path(capabilities_path)
        self.pause_marker = Path(pause_marker)
        self.report_path = Path(report_path)
        self.code_inventory = scan_code_inventory(self.base)

    def _tasks(self, offset, limit):
        offset = max(0, int(offset))
        limit = max(1, min(500, int(limit)))
        try:
            total = int(self.db.scalar('SELECT count(*) FROM hub_requests') or 0)
            raw_counts = self.db.rows('SELECT coalesce(status,\'planned\') status,count(*) count FROM hub_requests GROUP BY coalesce(status,\'planned\')')
            counts = {row['status']: int(row['count']) for row in raw_counts}
            rows = self.db.rows('''SELECT r.id,r.text,coalesce(r.status,'planned') status,r.created_at,
                coalesce(d.priority,'normal') priority,d.due_date,coalesce(d.next_step,'') next_step,
                d.reminder_date,d.updated_at,d.completed_at
                FROM hub_requests r LEFT JOIN task_details d ON d.request_id=r.id
                ORDER BY (coalesce(r.status,'planned')='done'),coalesce(d.pinned,0) DESC,
                CASE d.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'low' THEN 3 ELSE 2 END,
                coalesce(d.due_date,'9999-12-31'),r.id DESC LIMIT ? OFFSET ?''', (limit, offset))
            return {'status': 'available', 'total': total, 'offset': offset, 'limit': limit,
                    'counts': counts, 'items': rows}
        except Exception as exc:
            return {'status': 'unavailable', 'total': 0, 'offset': offset, 'limit': limit,
                    'counts': {}, 'items': [], 'error': type(exc).__name__}

    def _workflows(self):
        try:
            catalog = self.app.state.workflow_workspace.catalog(compact=True)
            cards = catalog.get('cards', [])
            return {'status': 'available', 'total': len(cards),
                    'states': catalog.get('summary', {}).get('states', _status_counts(cards)),
                    'families': catalog.get('summary', {}).get('families', {}),
                    'coverage': {key: catalog.get('coverage', {}).get(key) for key in
                                 ('expected_source_rows', 'live_n8n_queried', 'cloud_inventory_verified')},
                    'errors': catalog.get('coverage', {}).get('errors', []),
                    'items': [{key: card.get(key) for key in
                               ('id', 'name', 'family', 'status', 'availability', 'workspace_url', 'source_ids', 'prerequisites')}
                              for card in cards]}
        except Exception as exc:
            return {'status': 'unavailable', 'total': 0, 'states': {}, 'families': {},
                    'coverage': {}, 'errors': [], 'items': [], 'error': type(exc).__name__}

    def _benefits(self):
        try:
            service = self.app.state.benefits
            resources = service._catalog()
            states = {row['resource_id']: row['stage'] for row in
                      self.db.rows('SELECT resource_id,stage FROM benefit_resource_state')}
            counts = Counter(states.get(row['id'], 'ready') for row in resources)
            stages = {name: int(counts.get(name, 0)) for name in
                      ('ready', 'contacted', 'applied', 'waiting', 'won', 'blocked', 'ineligible')}
            return {'status': 'available', 'resources': len(resources), 'stages': stages,
                    'applications_submitted_by_nexen': False,
                    'calls_or_emails_sent_by_nexen': False,
                    'scope': 'Local research, draft preparation and owner-reviewed tracking.'}
        except Exception as exc:
            return {'status': 'unavailable', 'resources': 0, 'stages': {},
                    'applications_submitted_by_nexen': False,
                    'calls_or_emails_sent_by_nexen': False, 'error': type(exc).__name__}

    def _readiness(self):
        try:
            packet = self.app.state.readiness.packet()
            items = packet.get('items', [])
            return {'status': 'available', 'checked_at': packet.get('checked_at'),
                    'verified_count': packet.get('verified_count', 0),
                    'blocker_count': packet.get('blocker_count', 0),
                    'execution_counts': packet.get('execution_counts', {}),
                    'coverage': packet.get('coverage'),
                    'items': [{key: item.get(key) for key in
                               ('id', 'title', 'status', 'verified', 'next_step', 'evidence',
                                'evidence_basis', 'verification_scope', 'execution_class', 'endpoint_reachable')}
                              for item in items]}
        except Exception as exc:
            return {'status': 'unavailable', 'verified_count': 0, 'blocker_count': 0,
                    'execution_counts': {}, 'items': [], 'error': type(exc).__name__}

    def _capabilities(self):
        try:
            payload = json.loads(self.capabilities_path.read_text(encoding='utf-8-sig'))
            items = payload.get('capabilities', []) if isinstance(payload, dict) else []
            safe = [{key: item.get(key) for key in ('kind', 'name', 'lane', 'status', 'entry', 'evidence')}
                    for item in items if isinstance(item, dict)]
            return {'status': 'available', 'built_at': payload.get('built_at'),
                    'total': len(safe), 'registry_counts': payload.get('counts', {}),
                    'status_basis': 'Saved registry metadata; a listed executable is not a successful run.',
                    'items': safe}
        except (OSError, ValueError, TypeError) as exc:
            return {'status': 'unavailable', 'total': 0, 'registry_counts': {},
                    'status_basis': 'No current registry could be read.', 'items': [],
                    'error': type(exc).__name__}

    def _tools(self):
        try:
            rows = self.db.rows('SELECT name,status,version,interfaces_json,health,last_checked_at FROM tools ORDER BY name LIMIT 500')
            return {'status': 'available', 'total': len(rows), 'items': rows}
        except Exception as exc:
            return {'status': 'unavailable', 'total': 0, 'items': [], 'error': type(exc).__name__}

    def _routes(self):
        result = []
        for route in getattr(self.app, 'routes', []):
            path = getattr(route, 'path', '')
            methods = sorted(getattr(route, 'methods', set()) or [])
            if not path.startswith('/') or '{' in path or path.startswith(('/api/', '/docs', '/redoc')):
                continue
            if 'GET' not in methods:
                continue
            result.append({'path': path, 'name': str(getattr(route, 'name', '') or path)})
        result.sort(key=lambda item: (item['path'] != '/', item['path']))
        api_count = sum(1 for route in getattr(self.app, 'routes', [])
                        if str(getattr(route, 'path', '')).startswith('/api/'))
        return {'pages': result, 'page_count': len(result), 'api_route_count': api_count}

    def _open_report_items(self):
        try:
            text = self.report_path.read_text(encoding='utf-8-sig')
            heading = 'REMAINING WORK / HONEST LIMITS'
            section = text.split(heading, 1)[1].lstrip() if heading in text else ''
            paragraph = section.split('\n\n', 1)[0].strip()
            if paragraph.startswith('Still open:'):
                paragraph = paragraph[len('Still open:'):].strip()
            return {'status': 'available' if paragraph else 'not_found',
                    'source': str(self.report_path),
                    'source_updated_at': datetime.fromtimestamp(self.report_path.stat().st_mtime, timezone.utc).isoformat(),
                    'text': paragraph[:5000]}
        except OSError:
            return {'status': 'not_found', 'source': str(self.report_path), 'text': ''}

    def snapshot(self, offset=0, limit=200):
        pause_active = self.pause_marker.exists()
        return {'schema': 'nexen.everything.v1',
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'tasks': self._tasks(offset, limit),
                'workflows': self._workflows(),
                'benefits': self._benefits(),
                'readiness': self._readiness(),
                'capabilities': self._capabilities(),
                'tools': self._tools(),
                'routes': self._routes(),
                'code': self.code_inventory,
                'open_work_report': self._open_report_items(),
                'coverage': {'active_app': 'H:/NEXEN/v1/app',
                    'automatic_source_scans_paused': pause_active,
                    'full_census_note': 'This view covers the active V1 app and its connected task, workflow, readiness, benefits and capability registries. It does not claim every file elsewhere on H: or every imported archive was reviewed.',
                    'registry_note': 'Readiness and execution are separate. Registry presence, workflow definitions and route counts are not proof of a successful run.'}}


def format_cli(snapshot, as_json=False):
    if as_json:
        # ASCII escapes keep JSON reliable in Windows consoles with legacy code pages.
        return json.dumps(snapshot, indent=2, ensure_ascii=True, default=str)
    tasks = snapshot.get('tasks', {})
    workflows = snapshot.get('workflows', {})
    benefits = snapshot.get('benefits', {})
    readiness = snapshot.get('readiness', {})
    code = snapshot.get('code', {})
    registry = snapshot.get('capabilities', {})
    route_line = (f"NEXEN pages: {snapshot.get('routes', {}).get('page_count', 0)} · API routes: {snapshot.get('routes', {}).get('api_route_count', 0)}"
                  if snapshot.get('routes', {}).get('page_count') else
                  'NEXEN route list: open the browser Everything view for the live page/API inventory')
    unfinished = [task for task in tasks.get('items', []) if task.get('status') != 'done']
    lines = [
        'NEXEN EVERYTHING - read-only snapshot',
        'Checked: ' + str(snapshot.get('checked_at', 'unknown')),
        f"Tasks: {tasks.get('total', 0)} tracked - " + ', '.join(f'{n} {s}' for s, n in tasks.get('counts', {}).items()),
        f"Workflows: {workflows.get('total', 0)} cataloged - states {workflows.get('states', {})}",
        f"Readiness: {readiness.get('verified_count', 0)} verified - {readiness.get('blocker_count', 0)} need checking",
        f"Benefits: {benefits.get('resources', 0)} resources - no applications or contacts submitted by NEXEN",
        f"CLI/capability registry: {registry.get('total', 0)} entries - saved registry labels are not run proof",
        f"Active V1 code: {code.get('total', 0)} files - {code.get('python_modules', 0)} Python modules - {code.get('python_tests', 0)} test files",
        route_line,
        'Coverage: ' + snapshot.get('coverage', {}).get('full_census_note', '')]
    if unfinished:
        lines.append(f"Tracked unfinished work ({len(unfinished)} items loaded):")
        lines.extend(f"  #{task.get('id')} [{task.get('status')}/{task.get('priority')}] {task.get('text')}"
                     + (f" - Next: {task.get('next_step')}" if task.get('next_step') else '')
                     for task in unfinished)
    report = snapshot.get('open_work_report', {}).get('text')
    if report:
        lines.extend(['Latest V3 report open work (source timestamp shown in JSON):', '  ' + report])
    return '\n'.join(lines)


def register(app, db):
    from pc_control import validate_request
    service = Everything(app, db)

    @app.get('/everything', response_class=HTMLResponse)
    def page(request: Request):
        validate_request(request)
        return HTMLResponse((BASE / 'everything.html').read_text(encoding='utf-8'),
                            headers={'Cache-Control': 'no-store'})

    @app.get('/api/everything')
    def snapshot(request: Request, offset: int = 0, limit: int = 200):
        validate_request(request)
        return JSONResponse(service.snapshot(offset=offset, limit=limit),
                            headers={'Cache-Control': 'no-store'})

    return service

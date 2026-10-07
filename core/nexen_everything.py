"""Read-only NEXEN Everything CLI; does not bootstrap or mutate the live app."""
import argparse
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace

from everything_runtime import Everything, format_cli
from workflow_workspace import WorkflowWorkspace

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / 'data' / 'nexen.db'
BENEFIT_RESOURCES = BASE / 'data' / 'benefit-resources.json'
CLIP_GATE_PATH = Path('H:/NEXEN/clipping/clip_gate.py')
MARVIN_CAPABILITIES_PATH = Path('H:/NEXEN/marvin/brain/capabilities.py')


class ReadOnlyDB:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError('Canonical NEXEN task database is unavailable.')

    def _query(self, sql, params=(), one=False):
        conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            cursor = conn.execute(sql, params)
            row = cursor.fetchone() if one else None
            return (row[0] if row else None) if one else [dict(item) for item in cursor.fetchall()]
        finally:
            conn.close()

    def scalar(self, sql, params=()):
        return self._query(sql, params, one=True)

    def rows(self, sql, params=()):
        return self._query(sql, params)


class BenefitCatalog:
    def _catalog(self):
        data = json.loads(BENEFIT_RESOURCES.read_text(encoding='utf-8-sig'))
        resources = data.get('resources') if isinstance(data, dict) else None
        if not isinstance(resources, list):
            raise ValueError('Benefits resource catalog is invalid.')
        return [dict(item) for item in resources if isinstance(item, dict) and item.get('id')]


class LocalReadiness:
    """Loopback TCP reachability only; never treats it as login or execution proof."""
    SERVICES = (('nexen', 'NEXEN Core', 8788), ('ollama', 'Ollama', 11434),
                ('n8n-live', 'n8n Live', 5678), ('n8n-staging', 'n8n Staging', 5680),
                ('postiz', 'Postiz', 4007))

    def packet(self):
        items = []
        for ident, title, port in self.SERVICES:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.35):
                    reachable = True
            except OSError:
                reachable = False
            items.append({'id': ident, 'title': title,
                'status': 'service_reachable' if reachable else 'not_reachable',
                'verified': False, 'endpoint_reachable': reachable,
                'evidence': 'Loopback TCP reachability only. Authentication, current workflow state and successful execution are not verified.',
                'next_step': 'Open the linked workspace and verify its current login, adapter and execution receipt.'})
        return {'checked_at': None, 'verified_count': 0, 'blocker_count': len(items),
                'execution_counts': {'BLOCKED': len(items)}, 'coverage':
                'The standalone CLI checks loopback TCP only; it does not verify authentication, workflows or execution.',
                'items': items}


def build_snapshot():
    db = ReadOnlyDB(DB_PATH)
    workspace = WorkflowWorkspace(db=db, root=Path('H:/NEXEN'), app_root=BASE)
    app = SimpleNamespace(state=SimpleNamespace(workflow_workspace=workspace,
        benefits=BenefitCatalog(), readiness=LocalReadiness()), routes=[])
    return Everything(app, db).snapshot(limit=500)


def _read_clip_gate_rows():
    """Load only the standalone gate's explicitly read-only status interface."""
    if not CLIP_GATE_PATH.is_file():
        raise FileNotFoundError('The local clipping gate is unavailable.')
    spec = spec_from_file_location('_nexen_clip_gate_status', CLIP_GATE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('The local clipping gate cannot be loaded.')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.status()


def clipping_status(status_reader=None):
    """Return aggregate-only gate status. Never call decide() or expose registry rows."""
    reader = status_reader or _read_clip_gate_rows
    counts = {
        'campaigns': {'total': 0, 'eligible': 0, 'held': 0},
        'client_jobs': {'total': 0, 'eligible': 0, 'held': 0},
    }
    unavailable = set()
    invalid_rows = 0
    try:
        rows = reader()
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return {
            'schema': 'nexen.clipping-status.v1', 'status': 'unavailable',
            'campaigns': counts['campaigns'], 'client_jobs': counts['client_jobs'],
            'unavailable_sources': ['clip_gate'], 'invalid_rows': 0,
            'actions_taken': {'gate_decisions_logged': False, 'clip_jobs_started': False,
                              'downloads_started': False, 'posts_published': False},
            'note': 'Registry eligibility is status only; it does not authorize a clipping run or publication.',
        }
    if not isinstance(rows, (list, tuple)):
        rows = []
        invalid_rows = 1
    for row in rows:
        if not isinstance(row, dict) or row.get('kind') not in ('campaign', 'client_job'):
            invalid_rows += 1
            continue
        kind = row['kind']
        target = counts['campaigns' if kind == 'campaign' else 'client_jobs']
        if 'error' in row:
            unavailable.add(kind)
            continue
        if type(row.get('allowed')) is not bool:
            invalid_rows += 1
            continue
        target['total'] += 1
        target['eligible' if row['allowed'] else 'held'] += 1
    status = 'available' if not unavailable and not invalid_rows else (
        'partial' if any(item['total'] for item in counts.values()) else 'unavailable')
    return {
        'schema': 'nexen.clipping-status.v1', 'status': status,
        'campaigns': counts['campaigns'], 'client_jobs': counts['client_jobs'],
        'unavailable_sources': sorted(unavailable), 'invalid_rows': invalid_rows,
        'actions_taken': {'gate_decisions_logged': False, 'clip_jobs_started': False,
                          'downloads_started': False, 'posts_published': False},
        'note': 'Registry eligibility is status only; it does not authorize a clipping run or publication.',
    }


def _read_marvin_capability_state():
    """Load only MARVIN's pure static descriptor and scoped STOP check."""
    if not MARVIN_CAPABILITIES_PATH.is_file():
        raise FileNotFoundError('The local MARVIN capability adapter is unavailable.')
    spec = spec_from_file_location('_nexen_marvin_capabilities_status', MARVIN_CAPABILITIES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('The local MARVIN capability adapter cannot be loaded.')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.describe(), module.stopped()


def marvin_capability_status(state_reader=None):
    """Summarize static MARVIN declarations without running the adapter CLI or tools."""
    reader = state_reader or _read_marvin_capability_state
    try:
        description, stop_active = reader()
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return {
            'schema': 'nexen.marvin-capabilities.v1', 'status': 'unavailable',
            'capabilities': {}, 'stop_active': True,
            'actions_taken': {'network_requests': False, 'child_processes_started': False,
                              'downloads_started': False, 'stop_marker_changed': False},
            'note': 'Static capability state could not be verified; no MARVIN tool was run.',
        }
    if not isinstance(description, dict) or type(stop_active) is not bool:
        return {
            'schema': 'nexen.marvin-capabilities.v1', 'status': 'unavailable',
            'capabilities': {}, 'stop_active': True,
            'actions_taken': {'network_requests': False, 'child_processes_started': False,
                              'downloads_started': False, 'stop_marker_changed': False},
            'note': 'Static capability state is malformed; no MARVIN tool was run.',
        }
    internet = description.get('internet')
    install = description.get('model_install')
    if not isinstance(internet, dict) or not isinstance(install, dict):
        return {
            'schema': 'nexen.marvin-capabilities.v1', 'status': 'unavailable',
            'capabilities': {}, 'stop_active': True,
            'actions_taken': {'network_requests': False, 'child_processes_started': False,
                              'downloads_started': False, 'stop_marker_changed': False},
            'note': 'Static capability state is malformed; no MARVIN tool was run.',
        }
    max_parameters = install.get('max_parameters')
    quantizations = install.get('quantizations')
    resident_processes = description.get('resident_processes_added')
    cloud_spend = description.get('cloud_spend_enabled')
    if (type(internet.get('available')) is not bool or type(install.get('available')) is not bool or
            type(max_parameters) is not int or not isinstance(quantizations, list) or
            type(resident_processes) is not int or type(cloud_spend) is not bool):
        return {
            'schema': 'nexen.marvin-capabilities.v1', 'status': 'unavailable',
            'capabilities': {}, 'stop_active': True,
            'actions_taken': {'network_requests': False, 'child_processes_started': False,
                              'downloads_started': False, 'stop_marker_changed': False},
            'note': 'Static capability state is malformed; no MARVIN tool was run.',
        }
    return {
        'schema': 'nexen.marvin-capabilities.v1',
        'status': 'paused' if stop_active else 'available',
        'capabilities': {
            'bounded_public_https_text_fetch': internet['available'],
            'model_install': install['available'],
            'model_install_max_parameters': max_parameters,
            'model_install_quantizations': sorted(str(item) for item in quantizations),
            'resident_processes_added': resident_processes,
            'cloud_spend_enabled': cloud_spend,
        },
        'stop_active': stop_active,
        'actions_taken': {'network_requests': False, 'child_processes_started': False,
                          'downloads_started': False, 'stop_marker_changed': False},
        'note': 'Static adapter declarations only; this does not verify a resident MARVIN reload, model compliance, or owner approval.',
    }


def _build_parser():
    parser = argparse.ArgumentParser(description='Show a read-only summary of NEXEN work and connected registries.')
    parser.add_argument('--json', action='store_true', dest='as_json', help='Print machine-readable JSON.')
    commands = parser.add_subparsers(dest='group')
    skills = commands.add_parser('skills', help='Inspect the local read-only skill catalog.')
    skill_commands = skills.add_subparsers(dest='command', required=True)
    skill_commands.add_parser('status', help='Show catalog/ledger receipts and route coverage.')
    search = skill_commands.add_parser('search', help='Search skill metadata; no skill is executed.')
    search.add_argument('query', help='Search terms, up to 200 characters.')
    search.add_argument('--limit', type=int, default=10, help='Maximum results (1-20).')
    source = skill_commands.add_parser('source', help='Suggest skills for a source-ledger ID.')
    source.add_argument('source_id', type=int, help='Source ID from 1 to 82.')
    source.add_argument('--limit', type=int, default=5, help='Maximum suggestions (1-10).')
    clipping = commands.add_parser('clipping', help='Inspect the read-only paid-or-research clipping gate.')
    clipping_commands = clipping.add_subparsers(dest='command', required=True)
    clipping_commands.add_parser('status', help='Show aggregate gate status without starting a clip job.')
    marvin = commands.add_parser('marvin', help='Inspect MARVIN capability declarations without running tools.')
    marvin_commands = marvin.add_subparsers(dest='command', required=True)
    marvin_commands.add_parser('capabilities', help='Show static capabilities and scoped STOP state.')
    return parser


def main(argv=None, *, router_factory=None, clip_status_reader=None, marvin_status_reader=None,
         stdout=None, stderr=None):
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.group == 'skills':
            if router_factory is None:
                from skill_router import load_router
                router_factory = load_router
            from skill_router_api import _status_response, search_response, source_response
            router = router_factory()
            if args.command == 'status':
                result = _status_response(router)
            elif args.command == 'search':
                result = search_response(router, args.query, limit=args.limit)
            else:
                result = source_response(router, args.source_id, limit=args.limit)
            rendered = json.dumps(result, indent=2, ensure_ascii=True)
        elif args.group == 'clipping':
            rendered = json.dumps(clipping_status(clip_status_reader), indent=2, ensure_ascii=True)
        elif args.group == 'marvin':
            rendered = json.dumps(marvin_capability_status(marvin_status_reader), indent=2, ensure_ascii=True)
        else:
            snapshot = build_snapshot()
            rendered = (json.dumps(snapshot, indent=2, ensure_ascii=True, default=str)
                        if args.as_json else format_cli(snapshot))
        encoding = getattr(output_stream, 'encoding', None) or 'utf-8'
        rendered = rendered.encode(encoding, errors='backslashreplace').decode(encoding, errors='replace')
        output_stream.write(rendered + '\n')
    except KeyError:
        error_stream.write('NEXEN Everything: source ID was not found in the local ledger.\n')
        return 2
    except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
        detail = str(exc)[:300] if isinstance(exc, ValueError) else type(exc).__name__
        error_stream.write(f'NEXEN Everything unavailable: {detail}\n')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

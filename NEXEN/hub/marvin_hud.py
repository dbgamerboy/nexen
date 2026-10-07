"""MARVIN V3 HUD: one read-only NEXEN state snapshot plus the chat route.

Everything here reads: vault JSON/Markdown, the task DB (read only), local
service probes (1.5 s each) and PC stats. Nothing is written, launched or
posted. Every section degrades to null/empty plus a note; the state route
never returns a 500.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextlib import contextmanager
import copy
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

from marvin_swarm_feed import read_report as read_swarm_report, read_screenshot

from pydantic import BaseModel, ConfigDict, Field

BASE = Path(__file__).resolve().parent
VAULT = Path('F:/NEXEN_MEMORY')
VERSION = 'V3'
CACHE_SECONDS = 10.0
PROBE_TIMEOUT = 1.5
ARSENAL_TIMEOUT = 3.0
F_WARN_FREE_GB = 50.0
F_WARNING = 'dirty volume, do not write'
DRIVES = ('C:', 'F:', 'H:', 'I:')
TEAMS = ('Bankroll', 'Clipz', 'Studio', 'MARVIN', 'Engine', 'Arsenal', 'Forge')

LOOP_STATE = Path('H:/NEXEN/loop/state')


def _live_or_vault(name, vault_rel):
    """Prefer the autonomous loop's live H: feed (F: is on a repair hold); fall back to the vault copy."""
    live = LOOP_STATE / name
    return live if live.exists() else VAULT / vault_rel


PATHS = {
    'money_lanes': VAULT / '10-Segments/01-money-n8n/MONEY-LANES.json',
    'tonight': _live_or_vault('TONIGHT.json', '00-Control/TONIGHT.json'),  # owner blockers, money first (left screen)
    'pc2': _live_or_vault('PC2-STATUS.json', '00-Control/PC2-STATUS.json'),
    'v3_report': LOOP_STATE / 'V3-REPORT.json',  # owner-facing V3 report written by the NEXEN loop
    'session_log': VAULT / '00-Control/SESSION-LOG.md',
    'posts_root': Path('H:/NEXEN/posts/ai-models'),
    'reels_root': Path('H:/NEXEN/reels-finish'),
    'db': BASE / 'data/nexen.db',
    'page': BASE / 'marvin.html',
    'swarm_report': Path('H:/NEXEN/handoffs/swarm-execution-20261005/marvin-feed/SWARM-REPORT.json'),
}

URLS = {
    'nexen': 'http://127.0.0.1:8788/healthz',
    'n8n_live': 'http://127.0.0.1:5678/healthz',
    'n8n_clean': 'http://127.0.0.1:5680/rest/settings',
    'ollama': 'http://127.0.0.1:11434/api/tags',
    'postiz': 'http://localhost:4007/',
}

LANE_KEYS = ('rank', 'id', 'emoji', 'name', 'status', 'proof', 'next', 'gate', 'link', 'time_to_first_dollar')
ARSENAL_KEYS = ('repos', 'skills_installed', 'skills_indexed', 'cards', 'digests', 'diagrams', 'updated')
POST_SCHEDULED = {'scheduled', 'queued'}
POST_READY = {'', 'ready', 'approved', 'prepared', 'draft', 'drafted', 'rendered', 'pending', 'todo'}
REEL_DONE = {'done', 'finished', 'rendered', 'complete', 'completed', 'ok', 'final', 'exported'}

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_ARSENAL_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='marvin-arsenal')
_ARSENAL_PENDING = {'future': None}


# ---------------------------------------------------------------- helpers

def _now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _read_json(path):
    """Return (data, note). Missing or invalid files never raise."""
    path = Path(path)
    try:
        if not path.is_file():
            return None, f'{path.name} missing ({path})'
        return json.loads(path.read_text(encoding='utf-8-sig')), None
    except (OSError, ValueError) as exc:
        return None, f'{path.name} unreadable: {type(exc).__name__}'


def _read_tail(path, max_bytes=200_000):
    path = Path(path)
    try:
        with path.open('rb') as handle:
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode('utf-8', errors='replace'), None
    except FileNotFoundError:
        return '', f'{path.name} missing ({path})'
    except OSError as exc:
        return '', f'{path.name} unreadable: {type(exc).__name__}'


def _gb(value):
    return round(value / (1024 ** 3), 1)


_REDACT = (
    (re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b'), '[redacted-ip]'),
    (re.compile(r'\\\\[^\s\\]+'), '[redacted-host]'),
    (re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'), '[redacted-account]'),
    (re.compile(r'(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b\s*[:=]\s*\S+'), r'\1=[redacted]'),
)


def redact_private(text):
    """Keep PC2 connection details and secrets out of the HUD payload."""
    text = str(text)
    for pattern, replacement in _REDACT:
        text = pattern.sub(replacement, text)
    return text


def _http_get(url, timeout=PROBE_TIMEOUT):
    """Return (status, body). Raises OSError/URLError when nothing answers."""
    request = urllib.request.Request(url, headers={'Accept': 'application/json, text/html'})
    try:
        with _NO_PROXY.open(request, timeout=timeout) as response:
            return response.status, response.read(1_000_000).decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200_000).decode('utf-8', errors='replace')
        except Exception:
            body = ''
        return exc.code, body


# ---------------------------------------------------------------- probes

def probe_nexen():
    try:
        status, _ = _http_get(URLS['nexen'])
        return {'up': status == 200}
    except Exception as exc:
        return {'up': False, 'note': f'no answer on 8788 ({type(exc).__name__})'}


def probe_n8n_live():
    result = {'up': False, 'port': 5678, 'note': 'Lives on the dirty F: drive: read-only, never write or import there.'}
    try:
        status, body = _http_get(URLS['n8n_live'])
        result['up'] = status == 200 and 'ok' in body.lower()
    except Exception as exc:
        result['note'] += f' Probe failed ({type(exc).__name__}).'
    return result


def probe_n8n_clean():
    result = {'up': False, 'port': 5680, 'setup_needed': None}
    try:
        status, body = _http_get(URLS['n8n_clean'])
        result['up'] = status < 500
        if status == 200:
            flag = ((json.loads(body).get('data') or {}).get('userManagement') or {}).get('showSetupOnFirstLoad')
            result['setup_needed'] = flag if isinstance(flag, bool) else None
        result['note'] = ('Owner login not created yet: open http://127.0.0.1:5680/setup'
                          if result['setup_needed'] else 'Clean n8n on H:.')
    except Exception as exc:
        result['note'] = f'no answer on 5680 ({type(exc).__name__})'
    return result


def probe_ollama():
    result = {'up': False, 'models': []}
    try:
        status, body = _http_get(URLS['ollama'])
        if status == 200:
            models = json.loads(body).get('models') or []
            result['models'] = [m.get('name') for m in models if isinstance(m, dict) and m.get('name')]
            result['up'] = True
        else:
            result['note'] = f'HTTP {status}'
    except Exception as exc:
        result['note'] = f'no answer on 11434 ({type(exc).__name__})'
    return result


def probe_postiz():
    result = {'up': False, 'channels_connected': None,
              'note': 'Channel count needs a Postiz login; not queried. Last vault report: 0 connected channels.'}
    try:
        status, _ = _http_get(URLS['postiz'])
        result['up'] = status < 500
    except Exception as exc:
        result['note'] = f'no answer on 4007 ({type(exc).__name__}). ' + result['note']
    return result


PROBES = {'nexen': probe_nexen, 'n8n_live': probe_n8n_live, 'n8n_clean': probe_n8n_clean,
          'ollama': probe_ollama, 'postiz': probe_postiz}


# ---------------------------------------------------------------- PC1

def _cpu_pct(sample=0.25):
    try:
        import psutil  # optional
        return round(float(psutil.cpu_percent(interval=sample)), 1)
    except ImportError:
        pass
    import ctypes
    idle, kernel, user = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    get = ctypes.windll.kernel32.GetSystemTimes

    def read():
        if not get(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError('GetSystemTimes failed')
        return idle.value, kernel.value + user.value
    idle1, total1 = read()
    time.sleep(sample)
    idle2, total2 = read()
    busy = total2 - total1
    return round(100.0 * (busy - (idle2 - idle1)) / busy, 1) if busy > 0 else None


def _memory():
    try:
        import psutil  # optional
        vm = psutil.virtual_memory()
        return _gb(vm.total - vm.available), _gb(vm.total)
    except ImportError:
        pass
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError('GlobalMemoryStatusEx failed')
    return _gb(status.ullTotalPhys - status.ullAvailPhys), _gb(status.ullTotalPhys)


def _disk_usage(drive):
    root = drive + '\\'
    if not os.path.exists(root):
        return None
    return shutil.disk_usage(root)


def disk_warning(drive, free_gb):
    if free_gb is None:
        return None
    if drive.upper() == 'F:' and free_gb < F_WARN_FREE_GB:
        return F_WARNING
    if free_gb < 10:
        return 'low space'
    return None


def pc1_stats():
    result = {'cpu_pct': None, 'ram_used_gb': None, 'ram_total_gb': None, 'disks': []}
    notes = []
    try:
        result['cpu_pct'] = _cpu_pct()
    except Exception as exc:
        notes.append(f'cpu unavailable ({type(exc).__name__})')
    try:
        result['ram_used_gb'], result['ram_total_gb'] = _memory()
    except Exception as exc:
        notes.append(f'ram unavailable ({type(exc).__name__})')
    for drive in DRIVES:
        try:
            usage = _disk_usage(drive)
        except Exception as exc:
            notes.append(f'{drive} unreadable ({type(exc).__name__})')
            continue
        if usage is None:
            notes.append(f'{drive} not mounted')
            continue
        free = _gb(usage.free)
        result['disks'].append({'drive': drive, 'free_gb': free, 'total_gb': _gb(usage.total),
                                'warning': disk_warning(drive, free)})
    if notes:
        result['note'] = '; '.join(notes)
    return result


# ---------------------------------------------------------------- arsenal

def arsenal_fallback(note):
    data = {key: None for key in ARSENAL_KEYS}
    data['top_money'] = []
    data['note'] = note
    return data


def _load_registry():
    importlib.invalidate_caches()
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))
    return importlib.import_module('arsenal_registry')


def arsenal_summary(timeout=ARSENAL_TIMEOUT):
    """Guarded arsenal_registry.summary(); a slow rebuild is never started twice."""
    try:
        registry = _load_registry()
    except Exception as exc:
        return arsenal_fallback(f'arsenal_registry not available ({type(exc).__name__})')
    pending = _ARSENAL_PENDING['future']
    if pending is None or pending.done():
        pending = _ARSENAL_POOL.submit(registry.summary)
        _ARSENAL_PENDING['future'] = pending
    try:
        data = pending.result(timeout=timeout)
    except FutureTimeout:
        return arsenal_fallback('arsenal registry is rebuilding; counts appear on the next refresh')
    except Exception as exc:
        return arsenal_fallback(f'arsenal_registry.summary failed ({type(exc).__name__})')
    if not isinstance(data, dict):
        return arsenal_fallback('arsenal_registry.summary returned no data')
    data = copy.deepcopy(data)
    for key in ARSENAL_KEYS:
        data.setdefault(key, None)
    if not isinstance(data.get('top_money'), list):
        data['top_money'] = []
    return data


# ---------------------------------------------------------------- vault sections

def money_section(path):
    data, note = _read_json(path)
    if not isinstance(data, dict):
        return {'revenue_verified_usd': None, 'lanes': [],
                'revenue_note': 'Revenue unknown: ' + (note or 'MONEY-LANES.json is not an object') + '. No revenue is claimed.'}
    revenue = data.get('revenue_verified_usd')
    if isinstance(revenue, bool) or not isinstance(revenue, (int, float)):
        revenue = None
    lanes = []
    for index, raw in enumerate(data.get('lanes') or []):
        if not isinstance(raw, dict):
            continue
        lane = {key: raw.get(key) for key in LANE_KEYS}
        if not isinstance(lane['rank'], int) or isinstance(lane['rank'], bool):
            lane['rank'] = index + 1
        for key in LANE_KEYS[1:]:
            lane[key] = '' if lane[key] is None else str(lane[key])
        lanes.append(lane)
    lanes.sort(key=lambda lane: lane['rank'])
    result = {'revenue_verified_usd': revenue,
              'revenue_note': str(data.get('revenue_note') or ('Revenue unknown.' if revenue is None else '')),
              'lanes': lanes, 'updated': data.get('updated')}
    if data.get('source'):
        result['source'] = str(data['source'])
    return result


def tonight_section(path):
    data, note = _read_json(path)
    if data is None:
        return {'note': note}
    return data if isinstance(data, dict) else {'items': data}


def pc2_section(path):
    data, note = _read_json(path)
    if not isinstance(data, dict):
        default = {'state': 'user-reported: model installed', 'note': 'not yet connected to the queue'}
        if note and 'missing' not in note:
            default['note'] += f' ({note})'
        return default
    result = {'state': redact_private(data.get('state') or 'unknown')[:200],
              'note': redact_private(data.get('note') or '')[:400]}
    if data.get('updated'):
        result['updated'] = redact_private(data['updated'])[:60]
    return result


def _clean(value, limit=400):
    """Redacted, length-capped text for anything shown on the page."""
    return redact_private('' if value is None else str(value))[:limit]


def v3_section(path):
    """The loop's V3 report (next action, alerts, loop + memory, goals, agents). Read-only; every string redacted and capped."""
    data, note = _read_json(path)
    if not isinstance(data, dict):
        return {'note': note or 'V3 report not written yet (the NEXEN loop writes it every tick)'}
    nxt = data.get('next_action') if isinstance(data.get('next_action'), dict) else None
    link = _clean((nxt or {}).get('link'), 300)
    loop = data.get('loop') if isinstance(data.get('loop'), dict) else {}
    tickets = loop.get('tickets') if isinstance(loop.get('tickets'), dict) else {}
    return {
        'updated': _clean(data.get('updated'), 40),
        'next_action': {'id': _clean(nxt.get('id'), 20), 'title': _clean(nxt.get('title'), 160), 'step': _clean(nxt.get('step'), 600),
                        'value': _clean(nxt.get('value'), 80), 'link': link if link.startswith(('http://', 'https://')) else ''} if nxt else None,
        'revenue_verified_usd': data.get('revenue_verified_usd') if isinstance(data.get('revenue_verified_usd'), (int, float)) else None,
        'money_count': data.get('money_count') if isinstance(data.get('money_count'), int) else None,
        'alerts': [{'level': a.get('level') if a.get('level') in ('red', 'amber', 'info') else 'info', 'title': _clean(a.get('title'), 160),
                    'fix': _clean(a.get('fix'), 300), 'ticket': _clean(a.get('ticket'), 20)}
                   for a in (data.get('alerts') or [])[:10] if isinstance(a, dict)],
        'loop': {'mode': _clean(loop.get('mode'), 20), 'commit_pct': loop.get('commit_pct') if isinstance(loop.get('commit_pct'), (int, float)) else None,
                 'ram_free_gb': loop.get('ram_free_gb') if isinstance(loop.get('ram_free_gb'), (int, float)) else None,
                 'tickets': {_clean(k, 20): v for k, v in tickets.items() if isinstance(v, int)},
                 'done_this_week': loop.get('done_this_week') if isinstance(loop.get('done_this_week'), int) else None,
                 'pc2': _clean(loop.get('pc2'), 40)},
        'goals': [{'n': g.get('n'), 'goal': _clean(g.get('goal'), 80), 'by': _clean(g.get('by'), 20), 'now': _clean(g.get('now'), 160)}
                  for g in (data.get('goals') or [])[:10] if isinstance(g, dict)],
        'agents': [{'agent': _clean(a.get('agent'), 30), 'open': a.get('open'), 'done': a.get('done')}
                   for a in (data.get('agents') or [])[:10] if isinstance(a, dict)],
    }


def parse_session_log(text, limit=12):
    """Parse '## when · agent · title' entries; newest first."""
    entries, current = [], None
    for line in text.splitlines():
        if line.startswith('## '):
            current = {'heading': line[3:].strip(), 'did': None}
            entries.append(current)
        elif current is not None and current['did'] is None and line.lstrip().startswith('- Did:'):
            current['did'] = line.split('- Did:', 1)[1].strip()
    result = []
    for entry in entries[-limit:][::-1]:
        parts = [part.strip() for part in re.split(r'\s+·\s+', entry['heading'])]
        title = ' · '.join(parts[2:])
        did = entry['did'] or title or entry['heading']
        if len(did) > 240:
            did = did[:237].rstrip() + '...'
        result.append({'when': parts[0], 'agent': parts[1] if len(parts) > 1 else '',
                       'did': did, 'title': title})
    return result


def log_section(path):
    text, note = _read_tail(path)
    if note:
        return [], note
    entries = parse_session_log(text)
    return entries, (None if entries else 'SESSION-LOG.md has no ## entries')


def _list_items(data, keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    return None


def posts_section(root):
    root = Path(root)
    result = {'ready': 0, 'scheduled': 0, 'calendar_path': None}
    try:
        calendars = sorted(root.glob('*/CALENDAR.json'), key=lambda p: p.stat().st_mtime) if root.is_dir() else []
    except OSError as exc:
        result['note'] = f'posts folder unreadable ({type(exc).__name__})'
        return result
    if not calendars:
        result['note'] = f'no CALENDAR.json yet under {root}'
        return result
    result['calendar_path'] = str(calendars[-1])
    result['calendars'] = len(calendars)
    published = 0
    for calendar in calendars:
        data, _ = _read_json(calendar)
        if isinstance(data, dict) and isinstance(data.get('ready'), int) and isinstance(data.get('scheduled'), int):
            result['ready'] += data['ready']
            result['scheduled'] += data['scheduled']
            continue
        for item in _list_items(data, ('posts', 'items', 'entries', 'calendar', 'schedule')) or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get('status') or '').strip().lower()
            if status in POST_SCHEDULED:
                result['scheduled'] += 1
            elif status in POST_READY:
                result['ready'] += 1
            elif status in ('posted', 'published'):
                published += 1
    if published:
        result['published_reported'] = published
    result['note'] = 'Counted from local calendars; entries without a status count as ready. Scheduled means planned, not published.'
    return result


def reels_section(root):
    root = Path(root)
    result = {'done': 0, 'total': 0}
    try:
        indexes = sorted(root.glob('INDEX-*.json')) if root.is_dir() else []
    except OSError as exc:
        result['note'] = f'reels folder unreadable ({type(exc).__name__})'
        return result
    if not indexes:
        result['note'] = f'no INDEX-*.json yet under {root}'
        return result
    for index in indexes:
        data, _ = _read_json(index)
        if isinstance(data, dict) and isinstance(data.get('done'), int) and isinstance(data.get('total'), int):
            result['done'] += data['done']
            result['total'] += data['total']
            continue
        items = _list_items(data, ('reels', 'items', 'clips', 'entries', 'videos')) or []
        result['total'] += len(items)
        for item in items:
            if isinstance(item, dict) and (item.get('done') is True or
                                           str(item.get('status') or '').strip().lower() in REEL_DONE):
                result['done'] += 1
    result['indexes'] = [index.name for index in indexes]
    return result


# ---------------------------------------------------------------- DB (read only)

@contextmanager
def _reader(db, path):
    if db is not None:
        manager = db.reading() if hasattr(db, 'reading') else db.connect()
        with manager as connection:
            yield connection
        return
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'task DB not found ({path})')
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        connection.execute('PRAGMA query_only=ON')
        yield connection
    finally:
        connection.close()


def db_section(db, path):
    """Return (approvals, tasks, counts, notes). Only SELECT statements run."""
    approvals, tasks = [], []
    counts = {'approvals_pending': None, 'tasks_open': None}
    notes = {}
    try:
        with _reader(db, path) as c:
            tables = {row[0] for row in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('approvals','hub_requests')")}
            if 'approvals' in tables:
                counts['approvals_pending'] = c.execute("SELECT count(*) FROM approvals WHERE status='pending'").fetchone()[0]
                for row in c.execute("""SELECT id,title,action_type,created_at FROM approvals
                                        WHERE status='pending' ORDER BY id DESC LIMIT 20"""):
                    approvals.append({'id': row[0], 'title': str(row[1] or '')[:200],
                                      'kind': row[2], 'created_at': row[3]})
            else:
                notes['approvals'] = 'approvals table not found'
            if 'hub_requests' in tables:
                counts['tasks_open'] = c.execute(
                    "SELECT count(*) FROM hub_requests WHERE coalesce(status,'planned')!='done'").fetchone()[0]
                for row in c.execute("""SELECT id,text,status FROM hub_requests
                                        WHERE coalesce(status,'planned')!='done'
                                        ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'blocked' THEN 1 ELSE 2 END,
                                        id DESC LIMIT 20"""):
                    title = ' '.join(str(row[1] or '').split())
                    tasks.append({'id': row[0], 'title': title[:140] + ('...' if len(title) > 140 else ''),
                                  'status': row[2] or 'planned'})
            else:
                notes['tasks'] = 'hub_requests (tasks) table not found'
    except sqlite3.DatabaseError as exc:
        message = f'Task DB unreadable ({exc}). Read-only access only; not repaired here.'
        notes['approvals'] = notes['tasks'] = message
    except Exception as exc:
        message = f'Task DB unavailable ({type(exc).__name__}: {str(exc)[:160]})'
        notes['approvals'] = notes['tasks'] = message
    return approvals, tasks, counts, notes


# ---------------------------------------------------------------- graph + suggestions

_TEAM_WORDS = {
    'Clipz': ('clip', 'viral', 'reel', 'video', 'listing', 'slideshow', 'ugc', 'faceless', 'edit'),
    'Studio': ('music', 'wdr', 'song', 'catalog', 'snippet', 'beat', 'stems'),
    'Bankroll': ('service', 'offer', 'affiliate', 'lumipaw', 'shop', 'digital', 'sale', 'lead', 'product'),
}
_SYSTEM_WORDS = (
    ('n8n_live', ('n8n', ':5678')),
    ('n8n_clean', (':5680',)),
    ('postiz', ('postiz', ':4007', 'posting', 'channel', 'tiktok')),
    ('pc1', ('clip', 'render', 'reel', 'video', 'fl studio', 'music', 'slideshow', 'stems')),
    ('ollama', ('script', 'hook', 'ugc', 'caption', 'local model')),
    ('nexen', ('nexen.db', 'task ')),
)
_TEAM_SYSTEMS = {
    'MARVIN': ('ollama', 'nexen'),
    'Engine': ('n8n_live', 'n8n_clean', 'nexen'),
    'Arsenal': ('nexen', 'ollama'),
    'Forge': ('pc1', 'pc2', 'ollama'),
}
_SYSTEM_LABELS = {'nexen': 'NEXEN core', 'n8n_live': 'n8n live (F:)', 'n8n_clean': 'n8n clean (H:)',
                  'ollama': 'Ollama', 'postiz': 'Postiz', 'pc1': 'PC1', 'pc2': 'PC2'}


def build_graph(lanes, systems, pc2=None):
    nodes, edges, seen = [], [], set()

    def edge(source, target):
        if (source, target) not in seen:
            seen.add((source, target))
            edges.append({'from': source, 'to': target})

    for team in TEAMS:
        nodes.append({'id': 'team:' + team, 'label': team, 'group': 'team'})
    for key, label in _SYSTEM_LABELS.items():
        up = True if key == 'pc1' else (None if key == 'pc2' else (systems.get(key) or {}).get('up'))
        node = {'id': 'sys:' + key, 'label': label, 'group': 'system', 'up': up}
        if key == 'pc2' and pc2:
            node['state'] = pc2.get('state')
        nodes.append(node)
    for lane in lanes:
        lane_id = 'lane:' + (lane.get('id') or str(lane.get('rank')))
        nodes.append({'id': lane_id, 'label': (lane.get('emoji', '') + ' ' + lane.get('name', '')).strip(),
                      'group': 'lane', 'status': lane.get('status'), 'rank': lane.get('rank')})
        who = (lane.get('id', '') + ' ' + lane.get('name', '')).lower()
        teams = [team for team, words in _TEAM_WORDS.items() if any(word in who for word in words)] or ['Bankroll']
        for team in teams:
            edge('team:' + team, lane_id)
        text = ' '.join(str(lane.get(key, '')) for key in ('id', 'name', 'proof', 'next', 'gate', 'link')).lower()
        targets = [key for key, words in _SYSTEM_WORDS if any(word in text for word in words)] or ['nexen']
        for key in targets:
            edge(lane_id, 'sys:' + key)
    if lanes:
        edge('team:MARVIN', 'lane:' + (lanes[0].get('id') or str(lanes[0].get('rank'))))
    for team, keys in _TEAM_SYSTEMS.items():
        for key in keys:
            edge('team:' + team, 'sys:' + key)
    return {'nodes': nodes, 'edges': edges}


def build_suggestions(state):
    out = []
    money = state.get('money') or {}
    lanes = money.get('lanes') or []
    systems = state.get('systems') or {}
    if lanes:
        top = lanes[0]
        out.append(f"Money move #1: {top['name']} [{top['status']}]. Next: {top['next']} (gate: {top['gate']}).")
    if money.get('revenue_verified_usd') in (0, None):
        out.append('Verified revenue is $' + ('0' if money.get('revenue_verified_usd') == 0 else '?') +
                   '. One approved reply to a real lead beats ten more drafts.')
    clean = systems.get('n8n_clean') or {}
    if clean.get('setup_needed'):
        out.append('Create the n8n owner login at http://127.0.0.1:5680/setup (about 1 minute) so the recovered workflows can be imported.')
    postiz = systems.get('postiz') or {}
    if not postiz.get('up'):
        out.append('Postiz is not answering on :4007. Start it before scheduling posts.')
    elif postiz.get('channels_connected') in (None, 0):
        out.append('Connect one TikTok page in Postiz (http://localhost:4007/launches). Nothing auto-posts until a channel is connected.')
    pending = (state.get('counts') or {}).get('approvals_pending')
    if pending:
        out.append(f'{pending} approval(s) waiting in NEXEN. Clear them so work can move.')
    posts = state.get('posts') or {}
    if posts.get('ready') and not posts.get('scheduled'):
        out.append(f"{posts['ready']} posts are ready but none scheduled.")
    for disk in (state.get('pc1') or {}).get('disks') or []:
        if disk.get('warning') == F_WARNING:
            out.append(f"F: is a dirty volume with {disk['free_gb']} GB free. Do not write there; keep new output on H:.")
    if not (systems.get('ollama') or {}).get('up'):
        out.append('Ollama is down, so MARVIN answers from canned state only until it is back.')
    return out[:6]


# ---------------------------------------------------------------- builder

class StateBuilder:
    """Build and cache the MARVIN state for CACHE_SECONDS. Never raises."""

    def __init__(self, db=None, *, paths=None, serving=False, ttl=CACHE_SECONDS, clock=time.monotonic):
        self.db = db
        self.paths = dict(PATHS, **(paths or {}))
        self.serving = serving
        self.ttl = ttl
        self.clock = clock
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = None

    def get(self, force=False):
        with self.lock:
            now = self.clock()
            if force or self.cached is None or now - self.cached_at >= self.ttl:
                self.cached = self.build()
                self.cached_at = self.clock()
            return copy.deepcopy(self.cached)

    def _gather(self):
        """Run probes, PC stats and arsenal concurrently under one deadline."""
        jobs = {name: probe for name, probe in PROBES.items() if not (self.serving and name == 'nexen')}
        pool = ThreadPoolExecutor(max_workers=len(jobs) + 2, thread_name_prefix='marvin-probe')
        try:
            futures = {name: pool.submit(probe) for name, probe in jobs.items()}
            futures['pc1'] = pool.submit(pc1_stats)
            futures['arsenal'] = pool.submit(arsenal_summary)
            deadline = time.monotonic() + max(PROBE_TIMEOUT, ARSENAL_TIMEOUT) + 2.5
            results = {}
            for name, future in futures.items():
                try:
                    results[name] = future.result(timeout=max(0.05, deadline - time.monotonic()))
                except Exception as exc:
                    results[name] = {'note': f'{name} check failed ({type(exc).__name__})'}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if self.serving:
            results['nexen'] = {'up': True, 'note': 'serving this request'}
        return results

    def build(self):
        try:
            return self._build()
        except Exception as exc:  # last-resort guard: the HUD must still render
            return skeleton(f'state build failed ({type(exc).__name__}: {str(exc)[:200]})')

    def _build(self):
        notes = {}
        gathered = self._gather()
        systems = {
            'nexen': dict({'up': False}, **gathered.get('nexen', {})),
            'n8n_live': dict({'up': False, 'port': 5678, 'note': ''}, **gathered.get('n8n_live', {})),
            'n8n_clean': dict({'up': False, 'port': 5680, 'setup_needed': None}, **gathered.get('n8n_clean', {})),
            'ollama': dict({'up': False, 'models': []}, **gathered.get('ollama', {})),
            'postiz': dict({'up': False, 'channels_connected': None}, **gathered.get('postiz', {})),
        }
        pc1 = dict({'cpu_pct': None, 'ram_used_gb': None, 'ram_total_gb': None, 'disks': []}, **gathered.get('pc1', {}))
        arsenal = gathered.get('arsenal')
        if not isinstance(arsenal, dict) or 'top_money' not in arsenal:
            arsenal = arsenal_fallback((arsenal or {}).get('note') or 'arsenal summary unavailable')
        money = money_section(self.paths['money_lanes'])
        pc2 = pc2_section(self.paths['pc2'])
        log, log_note = log_section(self.paths['session_log'])
        if log_note:
            notes['log'] = log_note
        approvals, tasks, counts, db_notes = db_section(self.db, self.paths['db'])
        notes.update(db_notes)
        state = {
            'generated_at': _now_iso(),
            'version': VERSION,
            'money': money,
            'approvals': approvals,
            'tasks': tasks,
            'systems': systems,
            'pc1': pc1,
            'pc2': pc2,
            'arsenal': arsenal,
            'tonight': tonight_section(self.paths['tonight']),
            'v3': v3_section(self.paths['v3_report']),
            'swarm': read_swarm_report(self.paths['swarm_report']),
            'log': log,
            'graph': build_graph(money['lanes'], systems, pc2),
            'suggestions': [],
            'posts': posts_section(self.paths['posts_root']),
            'reels': reels_section(self.paths['reels_root']),
            'counts': counts,
            'notes': notes,
        }
        state['suggestions'] = build_suggestions(state)
        return state


def skeleton(note):
    """Contract-shaped empty state used when everything else fails."""
    return {
        'generated_at': _now_iso(), 'version': VERSION,
        'money': {'revenue_verified_usd': None, 'revenue_note': 'Revenue unknown. No revenue is claimed.', 'lanes': []},
        'approvals': [], 'tasks': [],
        'systems': {'nexen': {'up': None}, 'n8n_live': {'up': None, 'port': 5678, 'note': ''},
                    'n8n_clean': {'up': None, 'port': 5680, 'setup_needed': None},
                    'ollama': {'up': None, 'models': []}, 'postiz': {'up': None, 'channels_connected': None}},
        'pc1': {'cpu_pct': None, 'ram_used_gb': None, 'ram_total_gb': None, 'disks': []},
        'pc2': {'state': 'unknown', 'note': ''},
        'arsenal': arsenal_fallback('unavailable'), 'tonight': {'note': 'unavailable'}, 'v3': {'note': 'unavailable'}, 'log': [],
        'graph': {'nodes': [], 'edges': []}, 'suggestions': [],
        'posts': {'ready': 0, 'scheduled': 0, 'calendar_path': None}, 'reels': {'done': 0, 'total': 0},
        'counts': {'approvals_pending': None, 'tasks_open': None}, 'notes': {'state': note},
        'swarm': read_swarm_report(),
    }


_DEFAULT = {'builder': None}
_DEFAULT_LOCK = threading.Lock()


def get_state(db=None, force=False):
    """Standalone state (used by marvin_brain when no state is passed)."""
    with _DEFAULT_LOCK:
        if _DEFAULT['builder'] is None or _DEFAULT['builder'].db is not db:
            _DEFAULT['builder'] = StateBuilder(db)
        builder = _DEFAULT['builder']
    return builder.get(force=force)


# ---------------------------------------------------------------- routes

class ChatTurn(BaseModel):
    model_config = ConfigDict(extra='ignore')
    role: str = Field(default='user', max_length=20)
    content: str = Field(default='', max_length=8000)


class ChatBody(BaseModel):
    model_config = ConfigDict(extra='ignore')
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] | None = Field(default=None, max_length=40)


PLACEHOLDER_PAGE = ('<!doctype html><meta charset="utf-8"><title>MARVIN</title>'
                    '<body style="background:#07090d;color:#e5eef6;font:16px system-ui;padding:40px">'
                    '<h1>MARVIN HUD</h1><p>The V3 page (marvin.html) is not installed yet. '
                    'State JSON: <a style="color:#7fe3ff" href="/api/marvin/state">/api/marvin/state</a></p>')


def register(app, db):
    from fastapi import HTTPException, Request
    from fastapi.responses import HTMLResponse, Response
    from pc_control import validate_request

    builder = StateBuilder(db, serving=True)
    app.state.marvin = builder

    @app.get('/marvin', response_class=HTMLResponse)
    def marvin_page(request: Request):
        validate_request(request)
        try:
            return HTMLResponse(Path(builder.paths['page']).read_text(encoding='utf-8'))
        except OSError:
            return HTMLResponse(PLACEHOLDER_PAGE)

    @app.get('/api/marvin/state')
    def marvin_state(request: Request):
        validate_request(request)
        try:
            return builder.get()
        except Exception as exc:
            return skeleton(f'state unavailable ({type(exc).__name__})')

    @app.get('/api/marvin/swarm')
    def marvin_swarm(request: Request):
        validate_request(request)
        return read_swarm_report(builder.paths['swarm_report'])

    @app.get('/api/marvin/swarm/image/{image_sha}')
    def marvin_swarm_image(image_sha: str, request: Request):
        validate_request(request)
        try:
            content, mime = read_screenshot(image_sha)
        except (OSError, ValueError):
            raise HTTPException(404, 'Screenshot is missing, changed or outside verified task evidence.')
        return Response(content, media_type=mime, headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': 'inline; filename="task-evidence.png"',
            'Content-Security-Policy': "default-src 'none'; sandbox",
        })

    @app.post('/api/marvin/chat')
    def marvin_chat(body: ChatBody, request: Request):
        validate_request(request, mutation=True)
        message = body.message.strip()
        if not message:
            raise HTTPException(422, 'Say something to MARVIN first.')
        history = [turn.model_dump() for turn in body.history or []]
        try:
            state = builder.get()
        except Exception:
            state = None
        try:
            import marvin_brain
            return marvin_brain.reply(message, state=state, history=history)
        except Exception as exc:
            return {'reply': 'MARVIN hit an internal error before answering. Nothing ran. Try again.',
                    'model': 'error', 'used': {'repos': [], 'skills': []}, 'ms': 0,
                    'fallback': True, 'error': type(exc).__name__}

    return builder

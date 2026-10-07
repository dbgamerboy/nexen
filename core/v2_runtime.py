"""V2 operational status from current local receipts and the live worker."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from fastapi.responses import HTMLResponse

BASE = Path(__file__).resolve().parent
STATE = Path('H:/NEXEN/state')


def receipt(path, max_age=None, now=None):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('Oversized receipt')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('Invalid receipt')
        if max_age is not None:
            stamp = data.get('checked_at') or data.get('heartbeat_at')
            observed = datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).timestamp()
            age = (time.time() if now is None else now) - observed
            data['_fresh'] = -10 <= age <= max_age
        return data
    except (OSError, ValueError, TypeError, OverflowError):
        return {}


def automation_state(path):
    """Read only, with a short deadline independent of the knowledge indexes."""
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)) as con:
            con.row_factory = sqlite3.Row
            until = time.monotonic() + .5
            con.set_progress_handler(lambda: int(time.monotonic() > until), 1000)
            row = con.execute('SELECT enabled,ticks_completed,ticks_failed,last_finished,last_succeeded,last_outcome FROM automatic_mode_state WHERE id=1').fetchone()
            return dict(row) if row else {}
    except (OSError, sqlite3.Error):
        return {}


def snapshot(app=None, state=STATE, base=BASE, now=None):
    now = time.time() if now is None else now
    boot = receipt(state / 'startup-v2.json')
    watchdog = receipt(base / 'data/watchdog/status.json', 120, now)
    discord = receipt(state / 'discord-v2.json', 90, now)
    desktop_voice = receipt(state / 'discord-client-v2.json', 120, now)
    automatic = automation_state(base / 'data/nexen.db')
    mode = getattr(getattr(app, 'state', None), 'automatic_mode', None)
    worker_alive = bool(mode and mode.running())
    gate = mode.gate_from_state(automatic.get('enabled')) if mode else 'unavailable'
    last_succeeded = automatic.get('last_succeeded')
    recent_pass = isinstance(last_succeeded, (int, float)) and -10 <= now - last_succeeded <= 1800
    services_ok = bool(watchdog.get('_fresh') and watchdog.get('hub') in ('healthy_owned', 'healthy_attached'))
    auto_ok = bool(automatic.get('enabled') and worker_alive and gate == 'ready' and recent_pass
                   and automatic.get('last_outcome') == 'success' and automatic.get('ticks_completed', 0) > 0)
    voice_flags = ('self_muted', 'self_deafened', 'server_muted', 'server_deafened')
    voice_ok = bool(discord.get('_fresh') and discord.get('connected') and discord.get('voice_connected')
                    and all(discord.get(flag) is False for flag in voice_flags))
    checks = [
        {'id': 'startup', 'label': 'Windows startup', 'ready': boot.get('installed') is True,
         'detail': str(boot.get('mechanism') or 'Startup registration has not been verified.')[:250]},
        {'id': 'services', 'label': 'App recovery', 'ready': services_ok,
         'detail': 'Watchdog heartbeat is current.' if services_ok else 'Waiting for a current healthy watchdog heartbeat.'},
        {'id': 'discord', 'label': 'JARVIS bot voice', 'ready': voice_ok,
         'detail': str(discord.get('detail') or 'Automatic voice connection has not been verified.')[:400]},
        {'id': 'desktop_voice', 'label': 'Your Discord voice connection',
         'ready': bool(desktop_voice.get('_fresh') and desktop_voice.get('auto_join_verified') is True
                       and desktop_voice.get('connected') is True),
         'detail': str(desktop_voice.get('detail') or 'Startup opens JARVIS in your Discord client. Your account joining voice automatically has not been verified.')[:400]},
        {'id': 'automations', 'label': 'Local automations', 'ready': auto_ok,
         'detail': ('Worker running; %s completed passes.' % automatic.get('ticks_completed', 0)) if auto_ok else ('Worker gate: %s; recent successful pass: %s; latest result: %s.' % (gate, bool(recent_pass), automatic.get('last_outcome') or 'unverified'))},
    ]
    return {'version': 'V2', 'checked_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
            'status': 'operational' if all(x['ready'] for x in checks) else 'needs_attention',
            'checks': checks, 'completed_passes': automatic.get('ticks_completed'), 'last_pass_at': last_succeeded,
            'scope': 'Windows sign-in startup, app recovery, JARVIS bot and personal Discord voice connection, and local background work. External publishing and the wider project backlog have separate task outcomes.',
            'discord': {k: discord.get(k) for k in ('guild_id', 'voice_channel_id', 'text_channel_id', 'user_voice_connected', 'detail', *voice_flags)},
            'census': {'files_counted': watchdog.get('census_files_count'), 'state': watchdog.get('census'),
                       'detail': 'File counts are inventory, not proof that every file was read.'}}


def register(app):
    @app.get('/v2', response_class=HTMLResponse)
    def panel():
        return (BASE / 'v2.html').read_text(encoding='utf-8')

    @app.get('/api/v2/status')
    def status():
        return snapshot(app)

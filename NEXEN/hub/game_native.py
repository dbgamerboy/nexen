"""Fixed native game launches and small, factual WDR TV status summaries.

No input hooks, game injection, recording, arbitrary commands or game downloads.
The host application owns the password gate; both routes also validate locality.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from pc_control import validate_request
from storage_policy import require_output_path, tool_environment

BASE = Path(__file__).resolve().parent
DOLPHIN_ROOT = Path('H:/NEXEN/gaming/dolphin')
WATCHDOG = BASE / 'data/watchdog/status.json'
COOLDOWN_SECONDS = 30


@dataclass(frozen=True)
class NativeGame:
    id: str
    name: str
    executable: Path
    setup_url: str


GAMES = (
    NativeGame('halo', 'Halo Infinite', Path('F:/06_GAMES/FROM_E_DRIVE/SteamLibrary/steamapps/common/Halo Infinite/game/HaloInfinite.exe'),
               'https://store.steampowered.com/app/1240440/Halo_Infinite/'),
    NativeGame('dolphin', 'Dolphin', Path('F:/06_GAMES/Games/Emulators/Dolphin-x64/Dolphin.exe'),
               'https://dolphin-emu.org/'),
    NativeGame('playnite', 'Playnite', Path('F:/Playnite/Playnite.DesktopApp.exe'),
               'https://playnite.link/'),
)
GAME_BY_ID = {game.id: game for game in GAMES}
FOREGROUND_PATHS = {os.path.normcase(str(game.executable)): game.id for game in GAMES}
FOREGROUND_PATHS[os.path.normcase('F:\\Playnite\\Playnite.FullscreenApp.exe')] = 'playnite'


class LaunchBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: Literal['halo', 'dolphin', 'playnite']


def game_status(game):
    try:
        installed = game.executable.is_file()
    except OSError:
        installed = False
    blockers = []
    if not installed:
        blockers.append('The verified Windows executable is unavailable.')
    if game.id == 'halo':
        blockers.extend(['The game library installation has not been verified as complete.',
                         'H/F storage setup is required for Halo settings and its game-store profile.'])
    elif game.id == 'playnite':
        blockers.append('A portable H/F Playnite profile must be verified before launch; the current profile uses C:.')
    elif game.id == 'dolphin':
        try:
            root = require_output_path(DOLPHIN_ROOT)
            require_output_path(root / 'user', within=root)
        except (OSError, ValueError):
            blockers.append('Dolphin user data requires an available, unredirected H/F folder.')
    return {'id': game.id, 'name': game.name, 'installed': installed,
            'launch_ready': installed and not blockers, 'blockers': blockers,
            'setup_url': game.setup_url}


def windows_api():
    """Read process image paths only. Never inspect window titles or inject input."""
    if os.name != 'nt':
        raise OSError('Windows process observation is unavailable.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    psapi.EnumProcesses.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    psapi.EnumProcesses.restype = wintypes.BOOL
    return kernel, user, psapi


def process_image(kernel, pid):
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.normcase(buffer.value)
        return None
    finally:
        kernel.CloseHandle(handle)


def foreground_status():
    result = {'supported': False, 'game_id': None, 'halo_focused': False}
    try:
        kernel, user, _ = windows_api()
        handle = user.GetForegroundWindow()
        if not handle:
            return result
        pid = wintypes.DWORD()
        if not user.GetWindowThreadProcessId(handle, ctypes.byref(pid)):
            return result
        path = process_image(kernel, pid.value)
        if path is None:
            return result
        game_id = FOREGROUND_PATHS.get(path)
        return {'supported': True, 'game_id': game_id, 'halo_focused': game_id == 'halo'}
    except (OSError, AttributeError, ValueError):
        return result


def dolphin_running():
    kernel, _, psapi = windows_api()
    pids = (wintypes.DWORD * 8192)()
    used = wintypes.DWORD()
    if not psapi.EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(used)) or used.value >= ctypes.sizeof(pids):
        raise OSError('Process inventory is unavailable or exceeds the bounded check.')
    expected = os.path.normcase(str(GAME_BY_ID['dolphin'].executable))
    return any(process_image(kernel, pid) == expected for pid in pids[:used.value // ctypes.sizeof(wintypes.DWORD)] if pid)


def fresh(stamp, now, seconds=90):
    if not isinstance(stamp, str) or len(stamp) > 50:
        return False
    try:
        value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if value.tzinfo is None:
            return False
        age = now - value.timestamp()
        return -5 <= age <= seconds
    except (ValueError, OverflowError):
        return False


def read_watchdog(path):
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            return {}
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def automation_cards(db, watchdog=WATCHDOG, now=None):
    now = time.time() if now is None else now
    queue = {'title': 'Local analysis queue', 'status': 'unavailable', 'detail': 'The saved job records could not be read.'}
    try:
        rows = db.rows("SELECT status,count(*) count,MAX(updated_at) updated_at FROM jobs WHERE type='analyze_file' GROUP BY status")
        counts = {row['status']: int(row['count']) for row in rows}
        running = next((row for row in rows if row['status'] == 'running'), {})
        status = 'reported_running' if counts.get('running') and fresh(running.get('updated_at'), now, 600) else 'stale' if counts.get('running') else 'queued' if counts.get('queued') else 'idle'
        queue.update(status=status, detail=f"Saved analysis jobs: {counts.get('running', 0)} running, {counts.get('queued', 0)} queued, {counts.get('done', 0)} done, {counts.get('failed', 0)} failed. Job records are not a live worker heartbeat.")
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError):
        pass
    receipt = read_watchdog(Path(watchdog))
    watchdog_card = {'title': 'Local service watchdog', 'status': 'unavailable', 'detail': 'No recent watchdog receipt is available.'}
    if receipt:
        if not fresh(receipt.get('heartbeat_at'), now):
            watchdog_card.update(status='stale', detail='The watchdog receipt is older than 90 seconds. Current activity is unknown.')
        elif receipt.get('paused') is True:
            watchdog_card.update(status='paused', detail='The recent watchdog receipt reports automation paused.')
        elif receipt.get('hub') in ('healthy_owned', 'healthy_attached') and fresh(receipt.get('last_hub_ok_at'), now):
            watchdog_card.update(status='running', detail='A recent watchdog heartbeat reports the local NEXEN service healthy. It maintains local services while Windows is awake.')
        else:
            watchdog_card.update(status='needs_attention', detail='The watchdog is checking in, but the latest receipt does not verify a healthy NEXEN service.')
    return [queue, watchdog_card]


def pc2_status(readiness):
    try:
        value = readiness.connection_snapshot().get('pc2') if readiness is not None else None
    except Exception:
        value = None
    if value is True:
        return {'status': 'online', 'detail': 'The private peer reports online. Worker task execution is not verified here.'}
    if value is False:
        return {'status': 'offline', 'detail': 'The private peer reports offline.'}
    return {'status': 'unknown', 'detail': 'No current private-peer connection observation is available.'}


class NativeGames:
    def __init__(self, db, *, spawn=None, clock=None, running=None):
        self.db = db
        self.spawn = spawn or subprocess.Popen
        self.clock = clock or time.monotonic
        self.running = running or dolphin_running
        self.lock = threading.Lock()
        self.last_launch = None
        self.process = None

    def status(self, readiness=None):
        return {'games': [game_status(game) for game in GAMES], 'foreground': foreground_status(),
                'automations': automation_cards(self.db), 'pc2': pc2_status(readiness)}

    def event_after(self, kind, message, data):
        try:
            self.db.event(kind, message, data=data)
            return True
        except Exception:
            return False

    def launch(self, game_id):
        game = GAME_BY_ID.get(game_id)
        if game is None:
            raise HTTPException(404, 'Unknown game application.')
        with self.lock:
            status = game_status(game)
            if not status['launch_ready']:
                raise HTTPException(409, ' '.join(status['blockers']))
            # The sole enabled adapter uses Dolphin's documented -u user path.
            if game_id != 'dolphin':
                raise HTTPException(409, 'This game has no verified H/F launch adapter.')
            if self.process is not None and self.process.poll() is None:
                raise HTTPException(409, 'The Dolphin session opened by NEXEN is still running. Use its existing Windows window.')
            now = self.clock()
            if self.last_launch is not None and now - self.last_launch < COOLDOWN_SECONDS:
                raise HTTPException(429, 'Please wait before reopening Dolphin.', headers={'Retry-After': str(max(1, int(COOLDOWN_SECONDS - (now - self.last_launch)) + 1))})
            try:
                root = require_output_path(DOLPHIN_ROOT)
                user = require_output_path(root / 'user', within=root)
                if self.running():
                    raise HTTPException(409, 'Dolphin is already running. Close it before using the verified H/F launcher.')
            except (OSError, ValueError, subprocess.SubprocessError):
                raise HTTPException(409, 'Dolphin storage or existing process state could not be verified; nothing was launched.') from None
            try:
                self.db.event('game_launch_requested', 'Open Dolphin with its H/F user folder', data={'game_id': 'dolphin'})
            except Exception:
                raise HTTPException(503, 'The action log is unavailable; nothing was launched.') from None
            try:
                environment = tool_environment(root)
                user = require_output_path(user, within=root)
                user.mkdir(parents=True, exist_ok=True)
            except (OSError, ValueError):
                self.event_after('game_launch_blocked', 'Dolphin H/F profile preparation failed', {'game_id': 'dolphin'})
                raise HTTPException(409, 'Dolphin H/F profile preparation failed; nothing was launched.') from None
            self.last_launch = now
            try:
                self.process = self.spawn([str(game.executable), '-u', str(user)], shell=False,
                                          cwd=str(game.executable.parent), env=environment, stdin=subprocess.DEVNULL)
            except OSError:
                self.event_after('game_launch_failed', 'Windows could not start Dolphin', {'game_id': 'dolphin'})
                raise HTTPException(502, 'Windows could not start Dolphin.') from None
            recorded = self.event_after('game_launch_started', 'Windows accepted the Dolphin process', {'game_id': 'dolphin', 'pid': self.process.pid})
            result = {'status': 'launch_requested', 'id': 'dolphin', 'name': 'Dolphin',
                      'cooldown_seconds': COOLDOWN_SECONDS,
                      'message': 'Windows accepted the Dolphin launch using its H/F user folder. Confirm the application in its native window.',
                      'storage': {'configured_paths_verified': True, 'allowed_drives': ['H:', 'F:'], 'third_party_write_confinement': False}}
            if not recorded:
                result['audit_warning'] = 'The launch request was recorded, but the follow-up event could not be saved.'
            return result


def register(app, db):
    controller = NativeGames(db)

    @app.get('/api/game/native/status')
    def status(request: Request):
        validate_request(request)
        return controller.status(getattr(app.state, 'readiness', None))

    @app.post('/api/game/native/launch')
    def launch(body: LaunchBody, request: Request):
        validate_request(request, mutation=True)
        return controller.launch(body.id)

    return controller

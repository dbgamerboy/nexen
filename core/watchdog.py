"""NEXEN Watchdog Bot — monitors and auto-restarts all services 24/7.

Monitors: NEXEN core (8788), n8n (5678), Ollama (11434), OpenRouter, Gemini.
Auto-restarts failed services. Logs to H:/NEXEN/state/watchdog/.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent
STATE = Path("H:/NEXEN/state/watchdog")
LOG = STATE / "watchdog.log"
STATE.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG, encoding="utf-8", delay=True),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.watchdog")

# Services to monitor: name -> {check_url, restart_cmd, restart_cooldown_sec}
SERVICES = {
    "nexen-core": {
        "url": "http://127.0.0.1:8788/healthz",
        "check": "http",
        "restart": [
            "H:/NEXEN_RUNTIME/python-recovery/Scripts/python.exe",
            str(BASE / "nexen.py"),
            "--host", "127.0.0.1",
            "--port", "8788",
        ],
        "cooldown": 30,
    },
    "n8n": {
        "url": "http://localhost:5678/healthz",
        "check": "http",
        "restart": ["npx", "n8n", "start", "--tunnel"],
        "cooldown": 30,
    },
    "ollama": {
        "url": "http://127.0.0.1:11434/api/version",
        "check": "http",
        "restart": ["ollama", "serve"],
        "cooldown": 60,
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/models",
        "check": "http",
        "restart": None,  # external — no restart, just alert
        "cooldown": 120,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1/models",
        "check": "http",
        "restart": None,
        "cooldown": 120,
    },
}

FAILED = {}  # name -> last_failed_timestamp
RESTARTS = {}  # name -> count


def check_http(url: str, timeout: float = 10) -> bool:
    try:
        r = httpx.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def restart(name: str, cfg: dict) -> bool:
    cmd = cfg.get("restart")
    if not cmd:
        log.warning("[%s] External service — no restart command. Alert only.", name)
        return False
    if name == "ollama" and port_open("127.0.0.1", 11434):
        log.warning("[ollama] Health probe failed but port 11434 is already listening; skip duplicate restart.")
        return False
    try:
        log.info("[%s] Restarting: %s", name, " ".join(str(c) for c in cmd))
        subprocess.Popen(
            cmd,
            stdout=open(STATE / f"{name}.stdout.log", "a"),
            stderr=open(STATE / f"{name}.stderr.log", "a"),
            start_new_session=True,
        )
        RESTARTS[name] = RESTARTS.get(name, 0) + 1
        return True
    except Exception as e:
        log.error("[%s] Restart failed: %s", name, e)
        return False


async def tick():
    while True:
        for name, cfg in SERVICES.items():
            ok = check_http(cfg["url"])
            if ok:
                if name in FAILED:
                    log.info("[%s] BACK ONLINE (was down %.0fs)", name, time.time() - FAILED[name])
                    del FAILED[name]
            else:
                if name not in FAILED:
                    FAILED[name] = time.time()
                    log.error("[%s] DOWN — first failure", name)
                    restart(name, cfg)
                else:
                    down_for = time.time() - FAILED[name]
                    if down_for >= cfg["cooldown"]:
                        log.warning("[%s] Still down %.0fs — restarting", name, down_for)
                        restart(name, cfg)
                        FAILED[name] = time.time()  # reset cooldown
        await asyncio.sleep(30)


def status() -> dict:
    result = {}
    for name, cfg in SERVICES.items():
        ok = check_http(cfg["url"])
        result[name] = {
            "up": ok,
            "restarts": RESTARTS.get(name, 0),
            "down_since": FAILED.get(name),
        }
    return result


async def main():
    log.info("NEXEN Watchdog starting — monitoring %d services", len(SERVICES))
    await tick()


if __name__ == "__main__":
    asyncio.run(main())

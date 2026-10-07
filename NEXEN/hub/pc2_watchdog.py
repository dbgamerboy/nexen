"""NEXEN PC2 Watchdog — monitors PC2 24/7, keeps status updated, attempts recovery.

PC2 identity: PC2-HOST @ 192.168.77.5
Monitors: Ollama (11434), PAIR cluster (14321), NEXEN core (8788), SMB share.
Tracks state in H:/NEXEN/state/watchdog/pc2_status.json.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

STATE = Path("H:/NEXEN/state/watchdog")
STATE.mkdir(parents=True, exist_ok=True)
STATUS_FILE = STATE / "pc2_status.json"
LOG = STATE / "pc2_watchdog.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG, encoding="utf-8", delay=True),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.pc2watchdog")

PC2 = {
    "host": "192.168.77.5",
    "name": "PC2-HOST",
    "endpoints": {
        "ollama": "http://127.0.0.1:11435/api/tags",  # PAIR proxy on PC1 → PC2 Ollama
        "pair": "http://192.168.77.5:14321/api/health",  # PAIR cluster health
        "nexen": "http://192.168.77.5:8788/healthz",
        "smb": "H$",
    },
    "restart_commands": {
        "ollama": ["ollama", "serve"],
        "nexen": ["H:/NEXEN_RUNTIME/python-recovery/Scripts/python.exe", "H:/NEXEN/v1/app/nexen.py"],
    },
}


def check(url: str, timeout: float = 8) -> tuple[bool, int]:
    """Returns (ok, status_code). status_code=0 means connection refused/timeout."""
    try:
        r = httpx.get(url, timeout=timeout)
        return r.status_code < 500, r.status_code
    except Exception:
        return False, 0


def check_smb() -> bool:
    """Check if PC2's admin share is reachable from PC1."""
    try:
        result = subprocess.run(
            ["net", "use", f"\\\\{PC2['host']}\\H$"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 or "available" in result.stdout.lower()
    except Exception:
        return False


def load_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    return {
        "online": False,
        "last_check": None,
        "endpoints": {},
        "down_since": None,
        "recovery_attempts": 0,
        "total_checks": 0,
        "total_failures": 0,
    }


def save_status(status: dict) -> None:
    STATUS_FILE.write_text(json.dumps(status, indent=2, default=str))


def log_status(status: dict) -> None:
    ep = status.get("endpoints", {})
    parts = [f"{k}={'UP' if v.get('up', False) else 'DOWN'}" for k, v in ep.items()]
    log.info("[PC2] %s — %s | checks=%d failures=%d recovery=%d",
             "ONLINE" if status["online"] else "OFFLINE",
             ", ".join(parts),
             status["total_checks"], status["total_failures"],
             status["recovery_attempts"])


async def tick():
    status = load_status()
    while True:
        status["total_checks"] += 1
        ep_results = {}
        all_up = True

        for name, url in PC2["endpoints"].items():
            if name == "smb":
                ok = check_smb()
                code = 200 if ok else 0
            else:
                ok, code = check(url)
            ep_results[name] = {"up": ok, "status": code}
            if not ok:
                all_up = False

        status["endpoints"] = ep_results
        status["online"] = all_up
        status["last_check"] = datetime.now(timezone.utc).isoformat()

        if all_up:
            if status["down_since"]:
                log.info("[PC2] BACK ONLINE after %.0fs",
                         time.time() - status["down_since"])
                status["down_since"] = None
        else:
            status["total_failures"] += 1
            if not status["down_since"]:
                status["down_since"] = time.time()
                log.error("[PC2] OFFLINE — first failure")
            else:
                down_for = time.time() - status["down_since"]
                if down_for >= 60 and status["recovery_attempts"] < 5:
                    log.warning("[PC2] Down %.0fs — attempting recovery", down_for)
                    for svc, cmd in PC2["restart_commands"].items():
                        if not ep_results.get(svc, {}).get("up", True):
                            log.info("[PC2] Restarting %s", svc)
                            try:
                                subprocess.Popen(
                                    cmd,
                                    stdout=open(STATE / f"pc2-{svc}.log", "a"),
                                    stderr=open(STATE / f"pc2-{svc}.err.log", "a"),
                                    start_new_session=True,
                                )
                                status["recovery_attempts"] += 1
                            except Exception as e:
                                log.error("[PC2] Restart %s failed: %s", svc, e)
                    # Re-check after recovery attempt
                    await asyncio.sleep(5)
                    for name, url in PC2["endpoints"].items():
                        if name == "smb":
                            ok = check_smb()
                        else:
                            ok, _ = check(url)
                        ep_results[name]["up"] = ok
                    status["endpoints"] = ep_results
                    status["online"] = all(v["up"] for v in ep_results.values())

        save_status(status)
        log_status(status)
        await asyncio.sleep(30)


if __name__ == "__main__":
    import asyncio
    asyncio.run(tick())

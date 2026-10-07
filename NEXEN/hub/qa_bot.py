"""NEXEN QA Bot — tests every button, function, and endpoint for bugs.

Checks all NEXEN HTML pages and API endpoints. Logs issues to H:/NEXEN/state/qa/.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent
STATE = Path("H:/NEXEN/state/qa")
STATE.mkdir(parents=True, exist_ok=True)
LOG = STATE / "qa.log"
REPORT = STATE / "qa_report.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.qa")

NEXEN = "http://127.0.0.1:8788"

# All NEXEN routes: (method, path, description)
ROUTES = [
    # HTML pages
    ("GET", "/", "home"),
    ("GET", "/healthz", "health"),
    ("GET", "/desktop", "desktop"),
    ("GET", "/agents", "agents console"),
    ("GET", "/agentic-os", "agentic OS"),
    ("GET", "/automatic-mode", "automatic mode"),
    ("GET", "/benefits", "benefits"),
    ("GET", "/check-in", "daily check-in"),
    ("GET", "/code-review", "code review"),
    ("GET", "/continuity", "continuity"),
    ("GET", "/hub", "hub"),
    ("GET", "/kilo", "kilo"),
    ("GET", "/login", "login"),
    ("GET", "/marvin", "marvin"),
    ("GET", "/next", "next"),
    ("GET", "/intake-desk", "intake desk"),
    ("GET", "/money", "money"),
    ("GET", "/NEXEN-MAP", "NEXEN map"),
    ("GET", "/photos", "photos"),
    ("GET", "/problems", "problems"),
    ("GET", "/problem-cases", "problem cases"),
    ("GET", "/storage", "storage"),
    ("GET", "/v1-readiness", "v1 readiness"),
    ("GET", "/v2", "v2"),
    ("GET", "/voice", "voice"),
    ("GET", "/workflows", "workflows"),
    ("GET", "/youtube-memory", "youtube memory"),
    ("GET", "/lookbook", "lookbook"),
    ("GET", "/memory-pools", "memory pools"),
    ("GET", "/game", "game"),
    ("GET", "/intake-workspace", "intake workspace"),
    # API GETs
    ("GET", "/api/auth/session", "auth session"),
    ("GET", "/api/agents/status", "agents status"),
    ("GET", "/api/agents/handoffs", "agents handoffs"),
    ("GET", "/api/agentic-os/status", "agentic-os status"),
    ("GET", "/api/automatic-mode", "automatic-mode status"),
    ("GET", "/api/benefits", "benefits"),
    ("GET", "/api/check-in", "check-in"),
    ("GET", "/api/check-in/history", "check-in history"),
    ("GET", "/api/code-review/status", "code-review status"),
    ("GET", "/api/continuity/status", "continuity status"),
    ("GET", "/api/day", "daily plan"),
    ("GET", "/api/day/history", "day history"),
    ("GET", "/api/desktop/status", "desktop status"),
    ("GET", "/api/development/status", "development status"),
    ("GET", "/api/discord-voice/status", "discord voice status"),
    ("GET", "/api/handoff/status", "handoff status"),
    ("GET", "/api/handoff/phase-plan", "handoff phase-plan"),
    ("GET", "/api/kilo/status", "kilo status"),
    ("GET", "/api/arsenal/search", "arsenal search"),
    ("GET", "/api/arsenal/summary", "arsenal summary"),
    # API POSTs (body where needed)
    ("POST", "/api/auth/login", "auth login", {"username": "test", "password": "test"}),
    ("POST", "/api/continuity/enable", "continuity enable"),
    ("POST", "/api/continuity/pause", "continuity pause"),
    ("POST", "/api/automatic-mode", "automatic-mode toggle"),
    ("POST", "/api/day/999", "day toggle item"),
    ("POST", "/api/desktop/arm", "desktop arm"),
    ("POST", "/api/desktop/stop", "desktop stop"),
    ("POST", "/api/handoff/checkpoint", "handoff checkpoint"),
]

ISSUES = []
PASS = 0
FAIL = 0


def check(method: str, path: str, desc: str, body: dict | None = None) -> dict:
    global PASS, FAIL
    url = NEXEN + path
    try:
        if method == "GET":
            r = httpx.get(url, timeout=8)
        else:
            r = httpx.post(url, json=body or {}, timeout=8)
        ok = r.status_code < 500
        detail = f"{r.status_code}"
        if r.status_code == 401:
            detail += " (auth required — expected)"
            ok = True  # 401 is fine for unauth endpoints
        if r.status_code == 404 and path.startswith("/api/"):
            detail += " (endpoint missing)"
            ok = False
    except Exception as e:
        ok = False
        detail = f"ERROR: {e}"

    result = {"method": method, "path": path, "desc": desc, "ok": ok, "detail": detail}
    if ok:
        PASS += 1
        log.info("✅ %s %s — %s", method, path, detail)
    else:
        FAIL += 1
        ISSUES.append(result)
        log.error("❌ %s %s — %s", method, path, detail)
    return result


def run():
    global PASS, FAIL
    PASS = 0
    FAIL = 0
    ISSUES.clear()
    log.info("NEXEN QA bot starting — %d routes", len(ROUTES))

    results = []
    for route in ROUTES:
        method, path, desc = route[0], route[1], route[2]
        body = route[3] if len(route) > 3 else None
        results.append(check(method, path, desc, body))

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(ROUTES),
        "pass": PASS,
        "fail": FAIL,
        "issues": ISSUES,
    }
    REPORT.write_text(json.dumps(report, indent=2))
    log.info("QA done — %d/%d pass, %d fail. Report: %s", PASS, len(ROUTES), FAIL, REPORT)
    return report


if __name__ == "__main__":
    run()

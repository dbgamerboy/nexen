"""NEXEN QA bot — recurring health check (background loop)."""

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
LOG = STATE / "qa_recurring.log"
REPORT = STATE / "qa_report_latest.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG, encoding="utf-8", delay=True),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.qa-recur")

NEXEN = "http://127.0.0.1:8788"

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

PASS = 0
FAIL = 0
ISSUES = []


def check(method, path, desc, body=None):
    global PASS, FAIL, ISSUES
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
            ok = True
        if r.status_code == 403:
            detail += " (auth/gate — expected)"
            ok = True
    except Exception as e:
        ok = False
        detail = f"ERROR: {e}"

    result = {"method": method, "path": path, "desc": desc, "ok": ok, "detail": detail}
    if ok:
        PASS += 1
    else:
        FAIL += 1
        ISSUES.append(result)
    return result


def run():
    global PASS, FAIL, ISSUES
    PASS = 0
    FAIL = 0
    ISSUES.clear()
    log.info("NEXEN QA recur starting — %d routes", len(ROUTES))
    for route in ROUTES:
        method, path, desc = route[0], route[1], route[2]
        body = route[3] if len(route) > 3 else None
        check(method, path, desc, body)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(ROUTES),
        "pass": PASS,
        "fail": FAIL,
        "issues": ISSUES,
    }
    (STATE / "qa_report_latest.json").write_text(json.dumps(report, indent=2))
    log.info("QA recur done — %d/%d pass, %d fail", PASS, len(ROUTES), FAIL)
    return report


if __name__ == "__main__":
    while True:
        try:
            run()
        except Exception as e:
            log.error("QA recur error: %s", e)
        time.sleep(60)
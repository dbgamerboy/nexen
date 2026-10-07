#!/usr/bin/env python3
"""NEXEN CLI â€” talk to NEXEN, MARVIN, HERMES, and other bots from the command line.

Usage:
  nexen-cli status
  nexen-cli marvin "hello"
  nexen-cli nexen "do the thing"
  nexen-cli agents
  nexen-cli hub
  nexen-cli qa
  nexen-cli bot <name> "message"
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

NEXEN = "http://127.0.0.1:8788"
STATE = Path("H:/NEXEN/state")

# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get(path, **kw):
    r = httpx.get(f"{NEXEN}{path}", timeout=15, **kw)
    return r

def _post(path, body=None, **kw):
    r = httpx.post(f"{NEXEN}{path}", json=body or {}, timeout=15, **kw)
    return r

def _show(r):
    ct = r.headers.get("content-type", "")
    if "json" in ct:
        print(json.dumps(r.json(), indent=2))
    else:
        print(r.text[:2000])

# â”€â”€ commands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def cmd_status(args):
    """Overall system status."""
    print("=== NEXEN Status ===")
    r = _get("/api/status")
    _show(r)
    print()
    print("=== Health ===")
    r = _get("/healthz")
    _show(r)

def cmd_marvin(args):
    """Send a message to MARVIN."""
    r = _post("/api/marvin", {"message": args.message})
    _show(r)

def cmd_nexen(args):
    """Send a message to NEXEN core."""
    r = _post("/api/marvin", {"message": args.message, "source": "nexen-cli"})
    _show(r)

def cmd_agents(args):
    """List all agents and their status."""
    r = _get("/api/agents/status")
    _show(r)

def cmd_hub(args):
    """NEXEN hub status."""
    r = _get("/api/hub")
    _show(r)

def cmd_qa(args):
    """Run QA bot and show latest report."""
    report = STATE / "qa" / "qa_report_latest.json"
    if report.exists():
        print(report.read_text()[:3000])
    else:
        print("No QA report yet. Run qa_bot.py first.")

def cmd_bot(args):
    """Send a message to any named bot via NEXEN."""
    bot = args.name.lower()
    message = args.message

    # Route to the right endpoint based on bot name
    routes = {
        "nexen": ("/api/marvin", {"message": message, "source": "nexen-cli"}),
        "marvin": ("/api/marvin", {"message": message}),
        "marvin": ("/api/marvin", {"message": message}),
        "kilo": ("/api/kilo/prepare", {"prompt": message}),
        "agents": ("/api/agents/handoffs", {"message": message}),
        "hub": ("/api/hub/request", {"request": message}),
        "life": ("/api/life/analyze", {"input": message}),
        "money": ("/api/money/opportunities", {"query": message}),
        "memory": ("/api/memory/context", {"query": message}),
        "desktop": ("/api/desktop/click", {"x": 0, "y": 0}),
    }

    if bot in routes:
        path, body = routes[bot]
        r = _post(path, body)
        _show(r)
    else:
        print(f"Unknown bot: {bot}")
        print(f"Known bots: {', '.join(routes.keys())}")
        sys.exit(1)

def cmd_routes(args):
    """List all available NEXEN routes."""
    r = _get("/api/links")
    _show(r)

def cmd_send(args):
    """Generic API call: nexen-cli send GET /api/agents/status"""
    method = args.method.upper()
    path = args.path
    body = json.loads(args.body) if args.body else None
    if method == "GET":
        r = _get(path)
    elif method == "POST":
        r = _post(path, body)
    else:
        print(f"Unsupported method: {method}")
        sys.exit(1)
    _show(r)

# â”€â”€ main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    parser = argparse.ArgumentParser(
        description="NEXEN CLI â€” talk to NEXEN, MARVIN, and all bots",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  nexen-cli status
  nexen-cli marvin "what's the plan today?"
  nexen-cli nexen "check the queue"
  nexen-cli agents
  nexen-cli hub
  nexen-cli qa
  nexen-cli bot marvin "hello"
  nexen-cli send GET /api/agents/status
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Overall system status")
    p = sub.add_parser("marvin", help="Talk to MARVIN")
    p.add_argument("message", help="Message to send")
    p = sub.add_parser("nexen", help="Talk to NEXEN core")
    p.add_argument("message", help="Message to send")
    sub.add_parser("agents", help="List all agents")
    sub.add_parser("hub", help="NEXEN hub status")
    sub.add_parser("qa", help="Latest QA report")
    p = sub.add_parser("bot", help="Talk to any named bot")
    p.add_argument("name", help="Bot name (nexen, marvin, marvin, kilo, etc.)")
    p.add_argument("message", help="Message to send")
    sub.add_parser("routes", help="List all NEXEN routes")
    p = sub.add_parser("send", help="Generic API call")
    p.add_argument("method", help="GET or POST")
    p.add_argument("path", help="API path")
    p.add_argument("--body", help="JSON body for POST")

    args = parser.parse_args()
    cmd_map = {
        "status": cmd_status,
        "marvin": cmd_marvin,
        "nexen": cmd_nexen,
        "agents": cmd_agents,
        "hub": cmd_hub,
        "qa": cmd_qa,
        "bot": cmd_bot,
        "routes": cmd_routes,
        "send": cmd_send,
    }
    cmd_map[args.command](args)

if __name__ == "__main__":
    main()

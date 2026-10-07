"""Deterministic tool receipts logger for NEXEN and MARVIN.

Every tool call (video clipping, browser actions, n8n workflows, dropshipping research,
system commands) is appended to H:\\NEXEN\\state\\tool_receipts.jsonl.
When the user asks 'what tools were used', MARVIN answers directly from this log.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RECEIPTS_FILE = Path(r"H:\NEXEN\state\tool_receipts.jsonl")
RECEIPTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def log_tool_receipt(
    tool_name: str,
    arguments: Any,
    result: Any,
    *,
    model: Optional[str] = None,
    status: str = "success",
    duration_sec: float = 0.0,
    lane: str = "general"
) -> Dict[str, Any]:
    """Logs a single tool execution receipt."""
    receipt = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "tool": tool_name,
        "lane": lane,
        "model": model or "local_agent",
        "status": status,
        "duration_sec": round(duration_sec, 3),
        "arguments": arguments,
        "result_summary": str(result)[:300] if result is not None else None,
    }
    try:
        with open(RECEIPTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    except Exception as e:
        pass
    return receipt


def get_recent_tool_receipts(limit: int = 15) -> List[Dict[str, Any]]:
    """Retrieves the most recent tool execution receipts."""
    if not RECEIPTS_FILE.exists():
        return []
    receipts = []
    try:
        with open(RECEIPTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        receipts.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []
    return receipts[-limit:]


def format_tool_receipts_answer(limit: int = 10) -> str:
    """Formats an honest readback of tools used for MARVIN's response."""
    recent = get_recent_tool_receipts(limit=limit)
    if not recent:
        return "🛠️ MARVIN TOOL RECEIPTS: No tools have executed in this session yet. All drafted actions are waiting for execution receipts."
    
    lines = [f"🛠️ MARVIN TOOL AUDIT RECEIPTS (Last {len(recent)} tool calls):"]
    for idx, r in enumerate(reversed(recent), 1):
        ts = r.get("timestamp", "").replace("T", " ")[:19]
        tool = r.get("tool", "unknown_tool")
        status = r.get("status", "unknown")
        model = r.get("model", "agent")
        summary = r.get("result_summary") or "(no summary)"
        lines.append(f"{idx}. [{ts} UTC] Tool: `{tool}` | Status: {status} | Driver: `{model}`")
        lines.append(f"   Summary: {summary}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Self-test receipt log
    log_tool_receipt("audit_probe", {"query": "test"}, {"status": "verified"}, model="marvin-brain-3b:latest", lane="audit")
    print(format_tool_receipts_answer())

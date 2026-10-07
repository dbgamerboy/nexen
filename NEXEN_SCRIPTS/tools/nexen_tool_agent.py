"""Autonomous Tool-Calling Agent Engine for NEXEN / MARVIN / HERMES.

Enables native JSON function calling in local Ollama models (Qwen 2.5 Coder, Llama 3.2),
keeping models warm 24/7 (keep_alive: -1) and automatically executing tools
for multi-agent communication, Arsenal skills search, system status, and web fetching.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Core Paths
NEXEN_ROOT = Path(r"H:\NEXEN")
LOG_DIR = NEXEN_ROOT / "logs" / "tool_agent"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "tool_agent.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.tool_agent")

OLLAMA_ENDPOINT = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("MARVIN_TOOL_MODEL", "marvin-brain-3b:latest")


# --- TOOL IMPLEMENTATIONS ---

def tool_get_system_status() -> Dict[str, Any]:
    """Retrieves live telemetry and state for NEXEN V3, MARVIN, and services."""
    try:
        sys.path.insert(0, str(NEXEN_ROOT / "tools"))
        from nexen_bot_sync import NexenBotSync
        return NexenBotSync().get_status()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tool_search_arsenal_skills(query: Any) -> Dict[str, Any]:
    """Searches across all 3,805 indexed skills in the Arsenal repository."""
    try:
        if isinstance(query, dict):
            query = query.get("query") or query.get("description") or query.get("value") or "viral"
        q_str = str(query)
        sys.path.insert(0, str(NEXEN_ROOT / "tools"))
        from nexen_bot_sync import NexenBotSync
        matches = NexenBotSync().search_skills(q_str)
        return {"query": q_str, "total_found": len(matches), "skills": matches[:10]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tool_search_arsenal_repos(query: Any) -> Dict[str, Any]:
    """Searches across the 255 cloned repositories in the Arsenal."""
    try:
        if isinstance(query, dict):
            query = query.get("query") or query.get("description") or query.get("value") or ""
        q_str = str(query)
        sys.path.insert(0, str(NEXEN_ROOT / "tools"))
        from nexen_bot_sync import NexenBotSync
        matches = NexenBotSync().search_repos(q_str)
        return {"query": q_str, "total_found": len(matches), "repos": matches[:10]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tool_dispatch_bot_message(recipient: str, message: str) -> Dict[str, Any]:
    """Dispatches a task or message to MARVIN bus, Hermes, Codex, or Claude."""
    try:
        sys.path.insert(0, str(NEXEN_ROOT / "tools"))
        from nexen_bot_sync import NexenBotSync
        return NexenBotSync().dispatch_message(recipient, message, sender="tool_agent")
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tool_check_qc_receipts() -> Dict[str, Any]:
    """Inspects latest music renders, audio master files, and content quality scorecards."""
    try:
        sys.path.insert(0, str(NEXEN_ROOT / "tools"))
        from nexen_bot_sync import NexenBotSync
        return NexenBotSync().get_qc_receipts()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def tool_fetch_web_text(url: str) -> Dict[str, Any]:
    """Fetches text content from a public HTTPS URL (read-only, bounded)."""
    try:
        sys.path.insert(0, str(NEXEN_ROOT / "marvin" / "brain"))
        from capabilities import internet_fetch
        return internet_fetch(url)
    except Exception as e:
        return {"status": "error", "message": str(e)}


# TOOL REGISTRY (Schemas & Callable Function Map)
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": "Get real-time operational status, service health, and active money lanes for NEXEN V3 and MARVIN.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_arsenal_skills",
            "description": "Search across the 3,805 indexed skills in the Arsenal catalog by keyword, domain, or tool type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to search for, e.g. 'viral', 'scraper', 'clipping'"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_arsenal_repos",
            "description": "Search across all 255 cloned repositories in the Arsenal by name or capability.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Repository or technology keyword"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dispatch_bot_message",
            "description": "Send a verified instruction, task, or synchronization update to MARVIN, HERMES, CODEX, or CLAUDE.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "enum": ["marvin", "hermes", "codex", "claude", "all"]},
                    "message": {"type": "string", "description": "Verified payload or task text"},
                },
                "required": ["recipient", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_qc_receipts",
            "description": "Inspect latest audio rendering outputs, mastering receipts, and ChatGPT content quality scorecards.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_web_text",
            "description": "Fetch text from a public HTTPS URL (read-only, sanitized).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public HTTPS URL"}
                },
                "required": ["url"],
            },
        },
    },
]

TOOL_DISPATCH: Dict[str, Callable[..., Any]] = {
    "get_system_status": tool_get_system_status,
    "search_arsenal_skills": lambda **kw: tool_search_arsenal_skills(kw.get("query", "")),
    "search_arsenal_repos": lambda **kw: tool_search_arsenal_repos(kw.get("query", "")),
    "dispatch_bot_message": lambda **kw: tool_dispatch_bot_message(kw.get("recipient", "marvin"), kw.get("message", "")),
    "check_qc_receipts": tool_check_qc_receipts,
    "fetch_web_text": lambda **kw: tool_fetch_web_text(kw.get("url", "")),
}


class NexenToolAgent:
    """Autonomous agent loop with native tool calling."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model

    def chat_step(self, messages: List[Dict[str, Any]], timeout: int = 120) -> Dict[str, Any]:
        """Calls Ollama /api/chat with tools and keep_alive=-1 to maintain warm GPU residency."""
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "stream": False,
            "keep_alive": -1,  # Keep permanently warm in VRAM!
            "options": {
                "temperature": 0.2,
                "num_ctx": 8192,
            },
        }

        req = urllib.request.Request(
            f"{OLLAMA_ENDPOINT}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {})

    def run_turn(self, user_prompt: str, max_tool_iterations: int = 5) -> str:
        """Executes a full user turn, resolving tool calls in an iterative loop until completion."""
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are MARVIN, the autonomous tool-calling operator for NEXEN V3. "
                    "You have native tools to inspect system status, search 3,805 Arsenal skills and 255 repos, "
                    "dispatch inter-bot messages, check QC receipts, and fetch web text. "
                    "When a request requires data, invoke the appropriate tool immediately. "
                    "Never hallucinate data or claim a task ran without a tool receipt."
                ),
            },
            {"role": "user", "content": user_prompt},
        ]

        log.info("Agent Turn Started with Model: %s | Prompt: %s", self.model, user_prompt)

        for step in range(max_tool_iterations):
            assistant_msg = self.chat_step(messages)
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls") or []
            if not tool_calls:
                content = assistant_msg.get("content", "").strip()
                # 1. Direct JSON check
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "name" in parsed and parsed["name"] in TOOL_DISPATCH:
                        tool_calls = [{"function": {"name": parsed["name"], "arguments": parsed.get("arguments", {})}}]
                except Exception:
                    pass
                # 2. Markdown codeblock check
                if not tool_calls:
                    m = re.search(r"```(?:json)?\s*(\{[^`]*\"name\"[^`]*\})\s*```", content, re.DOTALL)
                    if m:
                        try:
                            parsed = json.loads(m.group(1))
                            if isinstance(parsed, dict) and "name" in parsed and parsed["name"] in TOOL_DISPATCH:
                                tool_calls = [{"function": {"name": parsed["name"], "arguments": parsed.get("arguments", {})}}]
                        except Exception:
                            pass

            if not tool_calls:
                # No more tools needed, return final answer
                final_content = assistant_msg.get("content", "").strip()
                log.info("Turn completed with final response (%d chars).", len(final_content))
                return final_content

            # Process all emitted tool calls
            for call in tool_calls:
                fn_info = call.get("function", {})
                fn_name = fn_info.get("name")
                fn_args = fn_info.get("arguments", {})

                log.info("TOOL CALL DETECTED: %s(args=%s)", fn_name, fn_args)

                tool_fn = TOOL_DISPATCH.get(fn_name)
                if tool_fn:
                    try:
                        tool_result = tool_fn(**fn_args)
                    except Exception as err:
                        log.error("Tool execution failed: %s", err, exc_info=True)
                        tool_result = {"status": "error", "error": str(err)}
                else:
                    tool_result = {"status": "error", "error": f"Unknown tool: {fn_name}"}

                log.info("TOOL RESULT: %s -> %s", fn_name, str(tool_result)[:120])

                # Feed result back into conversation
                messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

            # After tool execution, get final synthesis from model
            final_step = self.chat_step(messages)
            final_ans = final_step.get("content", "").strip()
            # If model repeated raw json, extract tool result directly into human readable report
            if final_ans.startswith("{") and "name" in final_ans:
                return (
                    f"Tool '{fn_name}' executed successfully.\n"
                    f"Result Summary:\n{json.dumps(tool_result, indent=2)}"
                )
            log.info("Turn completed with final response (%d chars).", len(final_ans))
            return final_ans


def main() -> None:
    parser = argparse.ArgumentParser(description="NEXEN Autonomous Tool-Calling Agent CLI")
    parser.add_argument("prompt", help="User instruction or query")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name in Ollama")
    args = parser.parse_args()

    agent = NexenToolAgent(model=args.model)
    response = agent.run_turn(args.prompt)
    print("\n" + response)


if __name__ == "__main__":
    main()

"""Autonomous Tool-Calling Agent Engine for NEXEN / MARVIN / HERMES (V2).

Enables native JSON function calling in local Ollama models (Qwen 2.5 Coder, Llama 3.2),
keeping models warm 24/7 (keep_alive: -1) and automatically executing tools
for multi-agent communication, Arsenal skills search, system status, web fetching,
and full Computer Use/Browser integration via OpenClaw.
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
from typing import Any, Dict, List, Optional

# Core Paths
NEXEN_ROOT = Path(r"H:\NEXEN")
LOG_DIR = NEXEN_ROOT / "logs" / "tool_agent_v2"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "tool_agent_v2.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.tool_agent_v2")

OLLAMA_ENDPOINT = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("MARVIN_TOOL_MODEL", "marvin-brain-3b:latest")

# Import new Tool Registry
sys.path.insert(0, str(NEXEN_ROOT / "tools"))
from tool_registry import get_tools_for_model, execute_tool

class NexenToolAgentV2:
    """Autonomous agent loop with native tool calling and Computer Use capabilities."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self.tools = get_tools_for_model(self.model)

    def chat_step(self, messages: List[Dict[str, Any]], timeout: int = 120) -> Dict[str, Any]:
        """Calls Ollama /api/chat with tools and keep_alive=-1 to maintain warm GPU residency."""
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": self.tools,
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
                    "You have native tools to inspect system status, search Arsenal skills/repos, "
                    "dispatch inter-bot messages, check QC receipts, fetch web text, and perform full "
                    "Computer Use (screenshots, browser control, file management, CLI, mouse/keyboard). "
                    "When a request requires data or actions, invoke the appropriate tool immediately. "
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
                    if isinstance(parsed, dict) and "name" in parsed:
                        tool_calls = [{"function": {"name": parsed["name"], "arguments": parsed.get("arguments", {})}}]
                except Exception:
                    pass
                # 2. Markdown codeblock check
                if not tool_calls:
                    m = re.search(r"```(?:json)?\s*(\{[^`]*\"name\"[^`]*\})\s*```", content, re.DOTALL)
                    if m:
                        try:
                            parsed = json.loads(m.group(1))
                            if isinstance(parsed, dict) and "name" in parsed:
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

                tool_result = execute_tool(fn_name, fn_args)

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
    parser = argparse.ArgumentParser(description="NEXEN Autonomous Tool-Calling Agent V2 CLI (with Computer Use)")
    parser.add_argument("prompt", help="User instruction or query")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name in Ollama")
    args = parser.parse_args()

    agent = NexenToolAgentV2(model=args.model)
    response = agent.run_turn(args.prompt)
    print("\n" + response)


if __name__ == "__main__":
    main()

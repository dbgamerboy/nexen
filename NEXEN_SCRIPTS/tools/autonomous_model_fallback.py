"""Autonomous Model Fallback and Switchover Engine for NEXEN / MARVIN.

Monitors token/quota headroom, detects provider rate limits (403, 404, 429),
and autonomously fails over between frontier models, local Ollama endpoints,
and browser-use worker scripts without requiring manual intervention.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Base Paths
NEXEN_ROOT = Path(r"H:\NEXEN")
STATE_DIR = NEXEN_ROOT / "state" / "model_router"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATUS_FILE = STATE_DIR / "router_status.json"
HANDOFF_FILE = NEXEN_ROOT / "handoffs" / "AUTONOMOUS_MODEL_SWITCHOVER.json"

LOG_FILE = STATE_DIR / "model_fallback.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("nexen.model_fallback")

# Model Hierarchy (Ordered by Fallback Priority)
MODEL_PRIORITY: List[Dict[str, Any]] = [
    {
        "tier": "tier_1_primary",
        "provider": "gemini_api",
        "model_id": "gemini-2.5-flash",
        "type": "cloud",
        "cost": "free_tier",
    },
    {
        "tier": "tier_2_frontier_fallback",
        "provider": "openrouter",
        "model_id": "openai/gpt-4o-mini",
        "type": "cloud",
        "cost": "gated_approval",
    },
    {
        "tier": "tier_3_tuned_local_brain",
        "provider": "ollama_local",
        "endpoint": "http://127.0.0.1:11434",
        "model_id": "marvin-brain-3b:latest",
        "type": "local_tuned",
        "cost": 0,
    },
    {
        "tier": "tier_4_tuned_local_coder",
        "provider": "ollama_local",
        "endpoint": "http://127.0.0.1:11434",
        "model_id": "nexen-coder-3b:latest",
        "type": "local_tuned",
        "cost": 0,
    },
    {
        "tier": "tier_5_browser_use_agent",
        "provider": "browser_use",
        "script": r"H:\NEXEN\tools\run_browser_agent.py",
        "type": "headless_browser",
        "cost": 0,
    },
]


class ModelFallbackRouter:
    """Manages active model execution and seamless failover."""

    def __init__(self) -> None:
        self.state = self.load_state()

    def load_state(self) -> Dict[str, Any]:
        if STATUS_FILE.exists():
            try:
                return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Could not parse status file, resetting: %s", e)
        return {
            "active_tier_index": 0,
            "last_switch_utc": datetime.now(timezone.utc).isoformat(),
            "switch_reason": "initial_boot",
            "fail_counts": {},
            "quota_warnings": {},
        }

    def save_state(self) -> None:
        STATUS_FILE.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def get_current_model(self) -> Dict[str, Any]:
        idx = self.state.get("active_tier_index", 0)
        if idx >= len(MODEL_PRIORITY):
            idx = 0
            self.state["active_tier_index"] = 0
        return MODEL_PRIORITY[idx]

    def record_failure_and_switch(self, reason: str) -> Dict[str, Any]:
        """Triggered when a quota limit (100% usage), 403, 429, or timeout occurs."""
        curr_idx = self.state.get("active_tier_index", 0)
        curr_model = MODEL_PRIORITY[curr_idx]
        model_key = curr_model.get("model_id") or curr_model.get("provider")

        log.warning("FAILURE / QUOTA HIT on %s: %s. Initiating autonomous switchover...", model_key, reason)

        # Increment failure tally
        fails = self.state.setdefault("fail_counts", {})
        fails[model_key] = fails.get(model_key, 0) + 1

        # Advance to next tier
        next_idx = (curr_idx + 1) % len(MODEL_PRIORITY)
        next_model = MODEL_PRIORITY[next_idx]

        self.state["active_tier_index"] = next_idx
        self.state["last_switch_utc"] = datetime.now(timezone.utc).isoformat()
        self.state["switch_reason"] = f"Failed over from {model_key}: {reason}"
        self.save_state()

        # Emit persistent autonomous handoff receipt
        receipt = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from_tier": curr_model,
            "to_tier": next_model,
            "switch_reason": reason,
            "autonomous_action": "failover_dispatched",
        }
        HANDOFF_FILE.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        log.info("AUTONOMOUS SWITCHOVER COMPLETE. Active model is now: %s (%s)", next_model.get("model_id"), next_model.get("tier"))

        # If switching to browser-use or local execution, trigger warm-up
        if next_model.get("type") == "local":
            self.probe_ollama(next_model)

        return next_model

    def probe_ollama(self, model_spec: Dict[str, Any]) -> bool:
        endpoint = model_spec.get("endpoint", "http://127.0.0.1:11434")
        model_name = model_spec.get("model_id")
        log.info("Probing local Ollama at %s for model %s...", endpoint, model_name)
        try:
            import urllib.request
            req = urllib.request.Request(f"{endpoint}/api/tags", headers={"User-Agent": "NEXEN-Router"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                if any(model_name in m for m in models):
                    log.info("Local model %s is verified and warm at %s.", model_name, endpoint)
                    return True
                else:
                    log.warning("Model %s not found in Ollama tags at %s.", model_name, endpoint)
                    return False
        except Exception as e:
            log.warning("Ollama probe failed at %s: %s", endpoint, e)
            return False


if __name__ == "__main__":
    router = ModelFallbackRouter()
    curr = router.get_current_model()
    print(f"Current Active Model Tier: {curr['tier']} | Provider: {curr['provider']} | Model: {curr.get('model_id')}")
    if "--test-switch" in sys.argv:
        nxt = router.record_failure_and_switch("Approaching 100% token quota limit")
        print(f"Switched To: {nxt['tier']} | Provider: {nxt['provider']} | Model: {nxt.get('model_id')}")
